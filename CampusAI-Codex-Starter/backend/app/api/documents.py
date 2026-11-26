from datetime import datetime, timezone
import logging
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.retrieval import index_chunks
from app.core.config import settings
from app.db import get_db
from app.documents.ingest import chunk_pages, extract_pages, validate_document
from app.documents.locking import lock_document_scope
from app.documents.metadata import suggest_document_metadata
from app.models import AuditLog, Company, Document, DocumentChunk, DocumentIngestionJob, User
from app.security import require_roles
from app.upload_scan import MalwareDetected, ScannerUnavailable, scan_upload

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)
DOCUMENT_CATEGORIES = {"placement-policy", "company-eligibility", "placement-calendar", "student-handbook", "resume-guidelines", "interview-guidelines", "training-materials", "general"}


def _log_vector_index_failure(stage: str, exc: Exception) -> None:
    status = getattr(exc, "status_code", None)
    logger.warning(
        "Document vector indexing failed; stage=%s exception_type=%s status_code=%s",
        stage,
        type(exc).__name__,
        status if isinstance(status, int) else "unknown",
    )


def _document_scope(title: str, company_id: int | None, academic_year: str | None):
    clauses = [Document.title == title]
    clauses.append(Document.company_id.is_(None) if company_id is None else Document.company_id == company_id)
    clauses.append(Document.academic_year.is_(None) if academic_year is None else Document.academic_year == academic_year)
    return clauses


def _lock_document_scope(db: Session, title: str, company_id: int | None, academic_year: str | None) -> None:
    """Backward-compatible name for the shared policy-scope lock."""
    lock_document_scope(db, title, company_id, academic_year)


@router.get("/")
def list_documents(_: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    docs = db.scalars(select(Document).order_by(Document.created_at.desc())).all()
    return [{"id": d.id, "title": d.title, "category": d.category, "filename": d.filename, "version": d.version,
             "effective_date": d.effective_date, "expiry_date": d.expiry_date, "approval_status": d.approval_status,
             "supersedes_id": d.supersedes_id, "created_at": d.created_at,
             "ingestion_status": d.ingestion_status, "ingestion_error": d.ingestion_error,
             "suggested_category": d.suggested_category, "classification_score": d.classification_score,
             "metadata_candidates": d.metadata_candidates or {}} for d in docs]


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...), title: str = Form(..., min_length=1, max_length=240), category: str = Form(...),
    effective_date: datetime | None = Form(default=None), expiry_date: datetime | None = Form(default=None),
    supersedes_id: int | None = Form(default=None), company_id: int | None = Form(default=None), academic_year: str | None = Form(default=None),
    actor: User = Depends(require_roles("placement_officer", "administrator")),
    db: Session = Depends(get_db),
):
    payload = await file.read(settings.max_upload_size + 1)
    try:
        ext = validate_document(file.filename or "", payload, settings.max_upload_size)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        scan_upload(payload)
    except MalwareDetected as exc:
        raise HTTPException(status_code=400, detail="The uploaded document failed the malware scan.") from exc
    except ScannerUnavailable as exc:
        raise HTTPException(status_code=503, detail="Upload scanning is temporarily unavailable.") from exc
    if category not in DOCUMENT_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Category must be one of: {', '.join(sorted(DOCUMENT_CATEGORIES))}")
    if effective_date and expiry_date and expiry_date < effective_date:
        raise HTTPException(status_code=422, detail="Expiry date cannot be earlier than effective date")
    title = title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title must contain a non-whitespace character")
    academic_year = academic_year.strip() if academic_year and academic_year.strip() else None
    if company_id is not None and not db.get(Company, company_id):
        raise HTTPException(status_code=404, detail="Company not found")
    _lock_document_scope(db, title, company_id, academic_year)
    scope_rows = db.scalars(select(Document).where(*_document_scope(title, company_id, academic_year)).order_by(Document.version.desc())).all()
    if any(document.approval_status == "pending" for document in scope_rows):
        raise HTTPException(status_code=409, detail="Resolve the pending document review before uploading another version")
    approved_versions = [document for document in scope_rows if document.approval_status == "approved"]
    current_approved = max(approved_versions, key=lambda document: document.version) if approved_versions else None
    if supersedes_id is not None:
        previous = db.get(Document, supersedes_id)
        if not previous:
            raise HTTPException(status_code=404, detail="Document version to supersede was not found")
        if previous.id not in {document.id for document in scope_rows}:
            raise HTTPException(status_code=422, detail="A document version can only supersede a version with the same title, company, and academic year")
        if previous.approval_status != "approved" or current_approved is None or previous.id != current_approved.id:
            raise HTTPException(status_code=409, detail="Only the current approved document version can be superseded")
    elif current_approved:
        supersedes_id = current_approved.id
    version = max((document.version for document in scope_rows), default=0) + 1
    if settings.document_ingestion_mode == "queued":
        doc = Document(title=title.strip(), category=category.strip(), filename=(file.filename or "document")[:255],
                       storage_path=f"queue://document/{uuid.uuid4().hex}", version=version,
                       effective_date=effective_date, expiry_date=expiry_date, approval_status="pending",
                       ingestion_status="queued", supersedes_id=supersedes_id, uploaded_by=actor.id,
                       company_id=company_id, academic_year=academic_year)
        db.add(doc)
        db.flush()
        db.add(DocumentIngestionJob(document_id=doc.id, payload=payload))
        db.add(AuditLog(actor_user_id=actor.id, action="document.upload", resource_type="document",
                        resource_id=str(doc.id), details={"ingestion": "queued"}))
        db.commit()
        return {"id": doc.id, "title": doc.title, "version": doc.version, "approval_status": doc.approval_status,
                "ingestion_status": doc.ingestion_status, "chunks_created": 0, "vectors_indexed": 0,
                "retrieval_ready": False}
    storage_dir = Path(settings.upload_directory).resolve()
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / f"{uuid.uuid4().hex}{ext}"
    storage_path.write_bytes(payload)
    try:
        pages = extract_pages(storage_path, enable_ocr=settings.ocr_enabled, ocr_languages=settings.ocr_languages, ocr_dpi=settings.ocr_dpi)
        chunks = chunk_pages(pages)
        if not chunks:
            raise ValueError("No readable text was found. Scanned documents require OCR before ingestion.")
    except Exception as exc:
        storage_path.unlink(missing_ok=True)
        logger.warning("Document extraction failed; exception_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=422,
            detail="Document text extraction failed. Check that the file is readable; scanned PDFs require OCR with Tesseract.",
        ) from exc
    metadata_suggestions = suggest_document_metadata(pages)
    doc = Document(title=title.strip(), category=category.strip(), filename=(file.filename or "document")[:255],
                   storage_path=str(storage_path), version=version, effective_date=effective_date, expiry_date=expiry_date,
                   approval_status="pending", supersedes_id=supersedes_id, uploaded_by=actor.id,
                   company_id=company_id, academic_year=academic_year,
                   suggested_category=metadata_suggestions["suggested_category"],
                   classification_score=metadata_suggestions["classification_score"],
                   metadata_candidates=metadata_suggestions)
    db.add(doc)
    db.flush()
    indexed = []
    chunk_ids = []
    for index, chunk in enumerate(chunks):
        record = DocumentChunk(document_id=doc.id, chunk_index=index, page_number=chunk["page_number"],
                               section=chunk.get("section"), text=chunk["text"], vector_id=str(uuid.uuid4()))
        db.add(record)
        db.flush()
        chunk_ids.append(record.id)
        indexed.append({"chunk_id": record.id, "document_id": doc.id, "vector_id": record.vector_id, "text": record.text,
                        "approval_status": "pending", "category": doc.category, "company_id": doc.company_id,
                        "academic_year": doc.academic_year, "version": doc.version, "effective_date": doc.effective_date,
                        "expiry_date": doc.expiry_date})
    db.add(AuditLog(actor_user_id=actor.id, action="document.upload", resource_type="document", resource_id=str(doc.id), details={"chunks": len(chunks)}))
    db.commit()
    vector_count = 0
    try:
        vector_count = index_chunks(indexed)
    except Exception as exc:
        # Extracted chunks remain available to keyword retrieval; a later approval can retry vector indexing.
        _log_vector_index_failure("upload", exc)
        vector_count = 0
    return {"id": doc.id, "title": doc.title, "version": doc.version, "approval_status": doc.approval_status,
            "ingestion_status": "completed", "chunks_created": len(chunks), "chunk_ids": chunk_ids,
            "vectors_indexed": vector_count, "retrieval_ready": False}


@router.post("/{document_id}/approve")
def approve_document(document_id: int, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.approval_status == "rejected":
        raise HTTPException(status_code=409, detail="Rejected document must be uploaded as a new version before approval")
    _lock_document_scope(db, doc.title, doc.company_id, doc.academic_year)
    db.refresh(doc)
    if doc.approval_status != "pending":
        raise HTTPException(status_code=409, detail="Document is no longer pending review")
    if doc.ingestion_status != "completed":
        raise HTTPException(status_code=409, detail="Document cannot be approved until ingestion completes")
    scope_rows = db.scalars(select(Document).where(*_document_scope(doc.title, doc.company_id, doc.academic_year))).all()
    if any(row.version > doc.version for row in scope_rows):
        raise HTTPException(status_code=409, detail="A newer document version exists; this version cannot be approved")
    approved_versions = [row for row in scope_rows if row.approval_status == "approved"]
    current_approved = max(approved_versions, key=lambda row: row.version) if approved_versions else None
    superseded_docs = []
    if doc.supersedes_id:
        previous = db.get(Document, doc.supersedes_id)
        if not previous:
            raise HTTPException(status_code=409, detail="The document version this upload supersedes no longer exists")
        if previous.id not in {row.id for row in scope_rows}:
            raise HTTPException(status_code=409, detail="The superseded document is outside this version chain")
        if previous.approval_status != "approved" or current_approved is None or previous.id != current_approved.id:
            raise HTTPException(status_code=409, detail="Only the current approved document version can be superseded")
        previous.approval_status = "superseded"
        superseded_docs.append(previous)
    else:
        if current_approved:
            current_approved.approval_status = "superseded"
            superseded_docs.append(current_approved)
            doc.supersedes_id = current_approved.id
    doc.approval_status = "approved"
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)).all()
    records = [{"chunk_id": c.id, "document_id": doc.id, "vector_id": c.vector_id, "text": c.text,
                "approval_status": "approved", "category": doc.category, "company_id": doc.company_id,
                "academic_year": doc.academic_year, "version": doc.version, "effective_date": doc.effective_date,
                "expiry_date": doc.expiry_date} for c in chunks]
    db.add(AuditLog(actor_user_id=actor.id, action="document.approve", resource_type="document", resource_id=str(doc.id)))
    db.commit()
    vectors = 0
    try:
        vectors = index_chunks(records)
    except Exception as exc:
        _log_vector_index_failure("approval", exc)
    for previous in superseded_docs:
        old_chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == previous.id)).all()
        old_records = [{"chunk_id": c.id, "document_id": previous.id, "vector_id": c.vector_id, "text": c.text,
                        "approval_status": "superseded", "category": previous.category, "company_id": previous.company_id,
                        "academic_year": previous.academic_year, "version": previous.version, "effective_date": previous.effective_date,
                        "expiry_date": previous.expiry_date} for c in old_chunks]
        try:
            index_chunks(old_records)
        except Exception as exc:
            _log_vector_index_failure("superseded_version", exc)
    return {"id": doc.id, "approval_status": doc.approval_status, "chunks": len(chunks), "vectors_indexed": vectors}


@router.post("/{document_id}/reject")
def reject_document(document_id: int, actor: User = Depends(require_roles("placement_officer", "administrator")), db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    _lock_document_scope(db, doc.title, doc.company_id, doc.academic_year)
    db.refresh(doc)
    if doc.approval_status != "pending":
        raise HTTPException(status_code=409, detail="Only pending documents can be rejected")
    doc.approval_status = "rejected"
    job = db.scalar(select(DocumentIngestionJob).where(DocumentIngestionJob.document_id == doc.id))
    if job and job.status in {"queued", "processing"}:
        job.status = "cancelled"
        job.payload = None
        job.lease_token = None
        job.locked_until = None
        doc.ingestion_status = "cancelled"
    db.add(AuditLog(actor_user_id=actor.id, action="document.reject", resource_type="document", resource_id=str(doc.id)))
    db.commit()
    return {"id": doc.id, "approval_status": doc.approval_status}
