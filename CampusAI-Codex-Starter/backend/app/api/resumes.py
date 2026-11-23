from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_db
from app.documents.ingest import extract_pages, validate_document
from app.models import ResumeAnalysis, SkillGapAnalysis, User
from app.security import require_roles
from app.upload_scan import MalwareDetected, ScannerUnavailable, scan_upload
from app.core.config import settings
from app.ai.resume import analyze_resume_text, redact_resume_contact_details, review_skill_gap
import re
import tempfile
from pathlib import Path
from hashlib import sha256
import logging

router = APIRouter(prefix="/resumes", tags=["resume intelligence"])
logger = logging.getLogger(__name__)

@router.post("/analyze")
async def analyze_resume(file: UploadFile = File(...), job_title: str = Form(default=""),
                        job_description: str = Form(default=""), role_file: UploadFile | None = File(default=None),
                        user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    if not settings.file_uploads_enabled:
        raise HTTPException(
            status_code=503,
            detail="Resume uploads are disabled on this deployment until malware scanning is configured.",
        )
    data = await file.read(settings.max_upload_size + 1)
    try:
        validate_document(file.filename or "", data, settings.max_upload_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        scan_upload(data)
    except MalwareDetected as exc:
        raise HTTPException(status_code=400, detail="The uploaded resume failed the malware scan.") from exc
    except ScannerUnavailable as exc:
        raise HTTPException(status_code=503, detail="Upload scanning is temporarily unavailable.") from exc
    suffix = Path(file.filename or "resume").suffix
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"resume{suffix}"
            path.write_bytes(data)
            text = "\n".join(page_text for _, page_text in extract_pages(path))
    except Exception as exc:
        # Parser exceptions can contain local paths or fragments of uploaded
        # content. Keep the response and operational log free of resume data.
        logger.warning("Resume extraction failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=422,
            detail="Could not read resume. Verify the file is a valid PDF, DOCX, or text document.",
        ) from exc
    if not text.strip():
        raise HTTPException(status_code=422, detail="No readable text found in resume")
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="Resume analysis is not configured. Contact your administrator.")
    role_text = job_description.strip()
    if role_file:
        if role_text:
            raise HTTPException(status_code=422, detail="Paste role details or upload a role PDF, not both")
        role_filename = role_file.filename or "role.pdf"
        if Path(role_filename).suffix.casefold() != ".pdf":
            raise HTTPException(status_code=400, detail="The role specification must be a PDF file")
        role_data = await role_file.read(settings.max_upload_size + 1)
        try:
            validate_document(role_filename, role_data, settings.max_upload_size)
            scan_upload(role_data)
            with tempfile.TemporaryDirectory() as directory:
                role_path = Path(directory) / "role.pdf"
                role_path.write_bytes(role_data)
                role_text = "\n".join(page_text for _, page_text in extract_pages(role_path)).strip()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MalwareDetected as exc:
            raise HTTPException(status_code=400, detail="The uploaded role PDF failed the malware scan.") from exc
        except ScannerUnavailable as exc:
            raise HTTPException(status_code=503, detail="Upload scanning is temporarily unavailable.") from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Role PDF extraction failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=422, detail="Could not read role PDF. Upload a readable text-based PDF.") from exc
    if role_file and len(role_text) < 20:
        raise HTTPException(status_code=422, detail="Could not read enough text from the role PDF")
    if role_text and len(role_text) < 20:
        raise HTTPException(status_code=422, detail="Provide at least 20 characters of role information or upload a readable role PDF")
    if role_text and not job_title.strip():
        job_title = "Target role"
    try:
        ai_result = await run_in_threadpool(
            analyze_resume_text, text, job_title.strip() or None, role_text[:12000] or None,
        )
        if not isinstance(ai_result, dict) or ai_result.pop("sections_extracted_by_ai", False) is not True:
            raise RuntimeError("Incomplete AI resume analysis")
        ai_sections = ai_result.pop("extracted_sections", None)
        if not isinstance(ai_sections, dict):
            raise RuntimeError("Incomplete AI resume sections")
        section_names = ("skills", "education", "projects", "experience")
        if any(not isinstance(ai_sections.get(name), list) for name in section_names):
            raise RuntimeError("Incomplete AI resume sections")
        role_guidance = ai_result.pop("role_comparison", None)
        if (job_title.strip() or role_text) and not isinstance(role_guidance, dict):
            raise RuntimeError("Incomplete AI role comparison")
        if role_guidance:
            for change in role_guidance.get("resume_changes", []):
                if isinstance(change, dict):
                    excerpt = _grounded_resume_section([change.get("current_excerpt", "")], text, 1)
                    change["current_excerpt"] = excerpt[0] if excerpt else ""
        skills = _grounded_resume_section(ai_sections["skills"], text, 40, lowercase=True, allow_short=True)
        education = _grounded_resume_section(ai_sections["education"], text, 12)
        projects = _grounded_resume_section(ai_sections["projects"], text, 12)
        experience = _grounded_resume_section(ai_sections["experience"], text, 12)
        for area in ai_result.get("improvement_areas", []):
            if isinstance(area, dict):
                excerpt = _grounded_resume_section([area.get("current_excerpt", "")], text, 1)
                area["current_excerpt"] = excerpt[0] if excerpt else ""
    except RuntimeError as exc:
        logger.warning("Resume AI review unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Resume analysis is temporarily unavailable. Try again later.") from None
    ai_review = ai_result
    ai_status = "complete"
    feedback = []
    record = ResumeAnalysis(user_id=user.id, filename=(file.filename or "resume")[:255], skills=skills, education=education,
                           projects=projects, experience=experience, quality_feedback=feedback, ai_review=ai_review,
                           ai_status=ai_status)
    db.add(record)
    db.commit()
    role_comparison = None
    if role_guidance:
        comparison = SkillGapAnalysis(
            user_id=user.id, resume_analysis_id=record.id, job_title=job_title[:180],
            job_description_hash=sha256((role_text or job_title)[:12000].encode("utf-8")).hexdigest(),
            required_skills=role_guidance["required_skills"], matching_skills=role_guidance["matching_skills"],
            missing_skills=role_guidance["missing_skills"], roadmap=role_guidance["roadmap"],
            ai_guidance=role_guidance, ai_status="complete",
        )
        db.add(comparison)
        db.commit()
        role_comparison = {"id": comparison.id, "job_title": comparison.job_title,
                           "required_skills": comparison.required_skills, "matching_skills": comparison.matching_skills,
                           "missing_skills": comparison.missing_skills, "roadmap": comparison.roadmap,
                           "ai_guidance": comparison.ai_guidance, "ai_status": "complete",
                           "method": "Resume and role comparison is generated from the uploaded resume text and role details by the AI service. It is guidance, not a hiring or ATS score."}
    return {"id": record.id, "filename": record.filename, "skills": skills, "education": education, "projects": projects,
            "experience": experience, "quality_feedback": feedback, "ai_review": ai_review, "ai_status": ai_status,
            "role_comparison": role_comparison,
            "privacy": "The uploaded files and full resume text are not saved. Only the extracted sections and structured review are stored."}


@router.get("/latest")
def latest_resume(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    row = db.scalar(select(ResumeAnalysis).where(ResumeAnalysis.user_id == user.id).order_by(ResumeAnalysis.created_at.desc()))
    if not row:
        return {"analysis": None}
    return {"id": row.id, "filename": row.filename, "skills": row.skills, "education": row.education, "projects": row.projects,
            "experience": row.experience, "quality_feedback": row.quality_feedback, "ai_review": row.ai_review,
            "ai_status": row.ai_status or ("complete" if row.ai_review else "unavailable"), "created_at": row.created_at}


@router.post("/skill-gap")
def skill_gap(payload: dict, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    job_description = str(payload.get("job_description", ""))[:12000]
    if len(job_description.strip()) < 20:
        raise HTTPException(status_code=422, detail="Provide a job description of at least 20 characters")
    resume = db.scalar(select(ResumeAnalysis).where(ResumeAnalysis.user_id == user.id).order_by(ResumeAnalysis.created_at.desc()))
    return _build_skill_gap(payload, job_description, user, db, resume)


@router.post("/skill-gap/compare")
async def compare_resume_with_role(
    resume_analysis_id: int = Form(...),
    job_title: str = Form(default=""),
    job_description: str = Form(default=""),
    resume_file: UploadFile | None = File(default=None),
    role_file: UploadFile | None = File(default=None),
    user: User = Depends(require_roles("student")),
    db: Session = Depends(get_db),
):
    """Compare an already-analyzed resume with pasted role details or a PDF role specification."""
    resume = db.scalar(select(ResumeAnalysis).where(
        ResumeAnalysis.id == resume_analysis_id, ResumeAnalysis.user_id == user.id,
    ))
    if not resume:
        raise HTTPException(status_code=404, detail="Resume analysis not found")
    if not settings.file_uploads_enabled and (resume_file is not None or role_file is not None):
        raise HTTPException(
            status_code=503,
            detail="File uploads are disabled on this deployment until malware scanning is configured.",
        )
    job_title = job_title.strip()
    if not job_title:
        raise HTTPException(status_code=422, detail="Enter a role title")
    resume_text = ""
    if resume_file:
        resume_filename = resume_file.filename or "resume.txt"
        if resume_filename != resume.filename:
            raise HTTPException(status_code=422, detail="Use the same resume selected for the analysis")
        resume_data = await resume_file.read(settings.max_upload_size + 1)
        try:
            validate_document(resume_filename, resume_data, settings.max_upload_size)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            scan_upload(resume_data)
        except MalwareDetected as exc:
            raise HTTPException(status_code=400, detail="The uploaded resume failed the malware scan.") from exc
        except ScannerUnavailable as exc:
            raise HTTPException(status_code=503, detail="Upload scanning is temporarily unavailable.") from exc
        try:
            with tempfile.TemporaryDirectory() as directory:
                resume_path = Path(directory) / Path(resume_filename).name
                resume_path.write_bytes(resume_data)
                resume_text = "\n".join(page_text for _, page_text in extract_pages(resume_path))
        except Exception as exc:
            logger.warning("Resume extraction failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=422, detail="Could not read resume. Upload a readable PDF, DOCX, or text document.") from exc
        if not resume_text.strip():
            raise HTTPException(status_code=422, detail="No readable text found in resume")
    role_text = job_description.strip()
    if role_file:
        if role_text:
            raise HTTPException(status_code=422, detail="Paste role details or upload a role PDF, not both")
        filename = role_file.filename or "role.pdf"
        if Path(filename).suffix.casefold() != ".pdf":
            raise HTTPException(status_code=400, detail="The role specification must be a PDF file")
        content = await role_file.read(settings.max_upload_size + 1)
        try:
            validate_document(filename, content, settings.max_upload_size)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            scan_upload(content)
        except MalwareDetected as exc:
            raise HTTPException(status_code=400, detail="The uploaded role PDF failed the malware scan.") from exc
        except ScannerUnavailable as exc:
            raise HTTPException(status_code=503, detail="Upload scanning is temporarily unavailable.") from exc
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "role.pdf"
                path.write_bytes(content)
                role_text = "\n".join(page_text for _, page_text in extract_pages(path))
        except Exception as exc:
            logger.warning("Role PDF extraction failed (%s)", type(exc).__name__)
            raise HTTPException(status_code=422, detail="Could not read role PDF. Upload a readable text-based PDF.") from exc
    if role_file and len(role_text) < 20:
        raise HTTPException(status_code=422, detail="Could not read enough text from the role PDF")
    if role_text and len(role_text) < 20:
        raise HTTPException(status_code=422, detail="Role information must contain at least 20 characters when provided")
    return _build_skill_gap({"job_title": job_title}, role_text[:12000], user, db, resume, resume_text)


def _build_skill_gap(payload: dict, job_description: str, user: User, db: Session,
                     resume: ResumeAnalysis | None, resume_text: str = ""):
    if not resume:
        raise HTTPException(status_code=422, detail="Analyze a resume before comparing it with a role.")
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="Role comparison is not configured. Contact your administrator.")
    resume_summary = {
        "skills": resume.skills or [],
        "education": resume.education or [],
        "projects": resume.projects or [],
        "experience": resume.experience or [],
        "resume_text": resume_text,
    }
    try:
        ai_guidance = review_skill_gap(str(payload.get("job_title", ""))[:180] or None,
                                       job_description, resume_summary)
    except RuntimeError as exc:
        logger.warning("Skill-gap AI comparison unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Role comparison is temporarily unavailable. Try again later.") from None
    required = ai_guidance["required_skills"]
    existing = ai_guidance["matching_skills"]
    missing = ai_guidance["missing_skills"]
    roadmap = ai_guidance["roadmap"]
    for change in ai_guidance["resume_changes"]:
        excerpt = _grounded_resume_section([change.get("current_excerpt", "")],
                                           "\n".join(sum((resume_summary[name] for name in ("skills", "education", "projects", "experience")), [])), 1)
        change["current_excerpt"] = excerpt[0] if excerpt else ""
    ai_status = "complete"
    record = SkillGapAnalysis(user_id=user.id, resume_analysis_id=resume.id if resume else None,
                              job_title=str(payload.get("job_title", ""))[:180] or None,
                              job_description_hash=sha256((job_description or str(payload.get("job_title", ""))).encode("utf-8")).hexdigest(),
                              required_skills=required, matching_skills=existing, missing_skills=missing, roadmap=roadmap,
                              ai_guidance=ai_guidance, ai_status=ai_status)
    db.add(record)
    db.commit()
    return {"id": record.id, "job_title": record.job_title, "required_skills": required, "matching_skills": existing, "missing_skills": missing,
            "roadmap": roadmap, "ai_guidance": ai_guidance, "ai_status": ai_status,
            "method": "Resume and role comparison is generated from the uploaded resume sections and role details by the AI service. It is guidance, not a hiring or ATS score."}


def _grounded_resume_section(values: object, resume_text: str, limit: int, lowercase: bool = False,
                             allow_short: bool = False) -> list[str]:
    """Keep only short AI extractions that are directly present in the uploaded resume."""
    if not isinstance(values, list):
        return []
    def normalize(value: str) -> str:
        return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)
    source = normalize(resume_text)
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = re.sub(r"\*\*", "", value).strip()
        item = re.sub(r"^[\s•·▪‣\-–—*]+", "", item)[:400]
        if redact_resume_contact_details(item) != item:
            continue
        normalized = normalize(item)
        identity = item.casefold() if allow_short else normalized
        if len(normalized) < (1 if allow_short else 3) or identity in seen:
            continue
        if len(normalized) < 3:
            if not re.search(rf"(?<!\w){re.escape(item.casefold())}(?!\w)", resume_text.casefold()):
                continue
        elif normalized not in source:
            continue
        if re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", item, re.I):
            continue
        result.append(item.casefold() if lowercase else item)
        seen.add(identity)
        if len(result) >= limit:
            break
    return result


@router.get("/skill-gap/history")
def skill_gap_history(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    rows = db.scalars(select(SkillGapAnalysis).where(SkillGapAnalysis.user_id == user.id).order_by(SkillGapAnalysis.created_at.desc()).limit(50)).all()
    return [{"id": row.id, "job_title": row.job_title, "required_skills": row.required_skills,
             "matching_skills": row.matching_skills, "missing_skills": row.missing_skills,
             "roadmap": row.roadmap, "ai_guidance": row.ai_guidance, "ai_status": row.ai_status,
             "method": "Resume and role comparison is generated from the uploaded resume sections and role details by the AI service. It is guidance, not a hiring or ATS score.",
             "created_at": row.created_at} for row in rows]
