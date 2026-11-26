from datetime import datetime, timezone
import mimetypes
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.documents.ingest import validate_document
from app.documents.locking import lock_document_scope
from app.models import Application, AuditLog, Company, CompanyRequirement, Notification, PlacementDrive, PlacementRecord, StudentProfile, User
from app.schemas import DriveInput, DriveOutput
from app.security import get_current_user, require_roles
from app.eligibility.engine import evaluate_eligibility
from app.core.config import settings
from app.upload_scan import MalwareDetected, ScannerUnavailable, scan_upload

router = APIRouter(prefix="/placement-drives", tags=["placement drives"])


def deadline_passed(deadline: datetime | None, *, now: datetime | None = None) -> bool:
    if deadline is None:
        return False
    current = now or datetime.now(timezone.utc)
    normalized_deadline = deadline.replace(tzinfo=timezone.utc) if deadline.tzinfo is None else deadline.astimezone(timezone.utc)
    normalized_now = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    return normalized_deadline < normalized_now


def drive_output(drive: PlacementDrive) -> DriveOutput:
    return DriveOutput(
        id=drive.id, company_id=drive.company_id, title=drive.title, role=drive.role,
        package_lpa=drive.package_lpa, location=drive.location, application_deadline=drive.application_deadline,
        drive_date=drive.drive_date, selection_process=drive.selection_process or [],
        status="closed" if drive.status == "open" and deadline_passed(drive.application_deadline) else drive.status,
        company_name=drive.company.name,
    )


def persist_application(db: Session, student_user_id: int, drive_id: int,
                        resume_filename: str | None = None,
                        resume_storage_path: str | None = None) -> Application:
    application = Application(student_user_id=student_user_id, drive_id=drive_id,
                              resume_filename=resume_filename, resume_storage_path=resume_storage_path)
    db.add(application)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(Application.id).where(
            Application.student_user_id == student_user_id,
            Application.drive_id == drive_id,
        ))
        if existing:
            raise HTTPException(status_code=409, detail="You have already applied") from exc
        raise
    return application


def load_application_drive(db: Session, drive_id: int) -> PlacementDrive | None:
    return db.scalar(select(PlacementDrive).options(
        joinedload(PlacementDrive.company)
        .joinedload(Company.requirements)
        .joinedload(CompanyRequirement.source_document)
    ).where(PlacementDrive.id == drive_id))


def lock_application_for_update(db: Session, application_id: int) -> Application | None:
    """Serialize status transitions for one application on databases with row locks."""
    return db.scalar(
        select(Application)
        .where(Application.id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


@router.get("/", response_model=list[DriveOutput])
def list_drives(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    drives = db.scalars(select(PlacementDrive).options(
        joinedload(PlacementDrive.company)
        .joinedload(Company.requirements)
        .joinedload(CompanyRequirement.source_document)
    ).order_by(PlacementDrive.drive_date)).unique().all()
    if user.role == "student":
        drives = [drive for drive in drives if evaluate_eligibility(
            user.student_profile, drive.company.requirements,
            source_approved=bool(drive.company.requirements and drive.company.requirements.source_document
                                 and drive.company.requirements.source_document.approval_status == "approved"),
        ).decision == "eligible"]
    return [drive_output(drive) for drive in drives]


@router.post("/", response_model=DriveOutput, status_code=201)
def create_drive(data: DriveInput, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    if not db.get(Company, data.company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    drive = PlacementDrive(**data.model_dump())
    db.add(drive)
    db.flush()
    db.add(AuditLog(actor_user_id=actor.id, action="placement_drive.create", resource_type="placement_drive", resource_id=str(drive.id)))
    db.commit()
    return drive_output(db.scalar(select(PlacementDrive).options(joinedload(PlacementDrive.company)).where(PlacementDrive.id == drive.id)))


@router.put("/{drive_id}", response_model=DriveOutput)
def update_drive(drive_id: int, data: DriveInput, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    drive = db.get(PlacementDrive, drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")
    if not db.get(Company, data.company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    for key, value in data.model_dump().items():
        setattr(drive, key, value)
    db.add(AuditLog(actor_user_id=actor.id, action="placement_drive.update", resource_type="placement_drive", resource_id=str(drive.id)))
    db.commit()
    return drive_output(db.scalar(select(PlacementDrive).options(joinedload(PlacementDrive.company)).where(PlacementDrive.id == drive.id)))


@router.get("/{drive_id}/eligible-students")
def eligible_students(drive_id: int, _: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    drive = db.scalar(select(PlacementDrive).options(joinedload(PlacementDrive.company).joinedload(Company.requirements).joinedload(CompanyRequirement.source_document)).where(PlacementDrive.id == drive_id))
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")
    users = db.scalars(select(User).options(joinedload(User.student_profile)).where(User.role == "student", User.is_active.is_(True)).order_by(User.full_name)).unique().all()
    result = []
    for student in users:
        rule = drive.company.requirements
        source_approved = bool(rule and rule.source_document and rule.source_document.approval_status == "approved")
        decision = evaluate_eligibility(student.student_profile, rule, source_approved=source_approved)
        if decision.decision == "eligible":
            result.append({"user_id": student.id, "student_id": student.student_profile.student_id, "name": student.full_name,
                           "branch": student.student_profile.branch, "decision": decision.decision, "reasons": decision.reasons,
                           "source_document_id": decision.source_document_id})
    return result


@router.patch("/{drive_id}/close", response_model=DriveOutput)
def close_drive(drive_id: int, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    drive = db.scalar(select(PlacementDrive).options(joinedload(PlacementDrive.company)).where(PlacementDrive.id == drive_id))
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")
    drive.status = "closed"
    db.add(AuditLog(actor_user_id=actor.id, action="placement_drive.close", resource_type="placement_drive", resource_id=str(drive.id)))
    db.commit()
    return drive_output(drive)


@router.post("/{drive_id}/apply", status_code=201)
async def apply_to_drive(drive_id: int, resume: UploadFile = File(...),
                         user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    payload = await resume.read(settings.max_upload_size + 1)
    original_filename = Path((resume.filename or "resume").replace("\\", "/")).name[:255] or "resume"
    try:
        extension = validate_document(original_filename, payload, settings.max_upload_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        scan_upload(payload)
    except MalwareDetected as exc:
        raise HTTPException(status_code=400, detail="The attached resume failed the malware scan.") from exc
    except ScannerUnavailable as exc:
        raise HTTPException(status_code=503, detail="Resume scanning is temporarily unavailable.") from exc

    drive = load_application_drive(db, drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Open placement drive not found")
    if drive.status != "open":
        raise HTTPException(status_code=404, detail="Open placement drive not found")
    if deadline_passed(drive.application_deadline):
        raise HTTPException(status_code=409, detail="The application deadline for this placement drive has passed")
    rule = drive.company.requirements
    if rule:
        db.execute(select(CompanyRequirement.id).where(CompanyRequirement.id == rule.id).with_for_update())
        db.expire_all()
        drive = load_application_drive(db, drive_id)
        if not drive or drive.status != "open":
            raise HTTPException(status_code=404, detail="Open placement drive not found")
        if deadline_passed(drive.application_deadline):
            raise HTTPException(status_code=409, detail="The application deadline for this placement drive has passed")
        rule = drive.company.requirements
    source_document = rule.source_document if rule else None
    if source_document:
        lock_document_scope(db, source_document.title, source_document.company_id, source_document.academic_year)
        db.expire_all()
        drive = load_application_drive(db, drive_id)
        if not drive or drive.status != "open":
            raise HTTPException(status_code=404, detail="Open placement drive not found")
        if deadline_passed(drive.application_deadline):
            raise HTTPException(status_code=409, detail="The application deadline for this placement drive has passed")
        rule = drive.company.requirements
    source_approved = bool(rule and rule.source_document and rule.source_document.approval_status == "approved")
    result = evaluate_eligibility(user.student_profile, rule, source_approved=source_approved)
    if result.decision != "eligible":
        raise HTTPException(status_code=409, detail={"message": "Application requires eligibility review", "eligibility": result.model_dump()})
    existing = db.scalar(select(Application.id).where(Application.student_user_id == user.id, Application.drive_id == drive.id))
    if existing:
        raise HTTPException(status_code=409, detail="You have already applied")
    storage_dir = Path(settings.upload_directory).resolve() / "application-resumes"
    storage_path = storage_dir / f"{uuid.uuid4().hex}{extension}"
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(payload)
        application = persist_application(db, user.id, drive.id, original_filename, str(storage_path))
    except HTTPException:
        storage_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        storage_path.unlink(missing_ok=True)
        db.rollback()
        raise HTTPException(status_code=503, detail="Could not save the attached resume. Please retry.") from exc
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise
    return {"id": application.id, "status": application.status, "drive_id": drive.id,
            "resume_filename": application.resume_filename}


@router.get("/applications/{application_id}/resume")
def download_application_resume(application_id: int,
                                user: User = Depends(require_roles("student", "placement_officer", "administrator")),
                                db: Session = Depends(get_db)):
    application = db.get(Application, application_id)
    if not application or not application.resume_storage_path or not application.resume_filename:
        raise HTTPException(status_code=404, detail="Application resume not found")
    if user.role == "student" and application.student_user_id != user.id:
        raise HTTPException(status_code=404, detail="Application resume not found")
    upload_root = (Path(settings.upload_directory).resolve() / "application-resumes").resolve()
    path = Path(application.resume_storage_path).resolve()
    if not path.is_relative_to(upload_root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Application resume not found")
    return FileResponse(path, filename=application.resume_filename,
                        media_type=mimetypes.guess_type(application.resume_filename)[0] or "application/octet-stream")


@router.patch("/applications/{application_id}/status")
def update_application_status(application_id: int, payload: dict, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    status_value = str(payload.get("status", ""))
    if status_value not in {"applied", "screening", "interview", "selected", "rejected", "withdrawn"}:
        raise HTTPException(status_code=422, detail="Unsupported application status")
    application = lock_application_for_update(db, application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    previous_status = application.status
    application.status = status_value
    drive = db.get(PlacementDrive, application.drive_id)
    placement = db.scalar(select(PlacementRecord).where(PlacementRecord.student_user_id == application.student_user_id, PlacementRecord.drive_id == application.drive_id))
    if status_value == "selected" and not placement and drive:
        db.add(PlacementRecord(student_user_id=application.student_user_id, company_id=drive.company_id, drive_id=drive.id,
                               role=drive.role, package_lpa=drive.package_lpa))
    elif status_value != "selected" and placement:
        db.delete(placement)
    if status_value != previous_status:
        db.add(Notification(
            user_id=application.student_user_id,
            title="Placement application updated",
            message=f"Your application for {drive.role if drive else 'a placement drive'} changed from {previous_status} to {status_value}.",
        ))
    db.add(AuditLog(actor_user_id=actor.id, action="application.status", resource_type="application", resource_id=str(application.id), details={"status": status_value}))
    db.commit()
    return {"id": application.id, "status": application.status}
