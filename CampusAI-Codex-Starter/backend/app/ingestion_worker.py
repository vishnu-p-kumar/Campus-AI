"""Durable database-backed worker for document extraction and indexing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import tempfile
import time
import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.ai.retrieval import index_chunks
from app.core.config import settings
from app.db import SessionLocal, engine
from app.documents.ingest import chunk_pages, extract_pages
from app.documents.metadata import suggest_document_metadata
from app.models import Document, DocumentChunk, DocumentIngestionJob

logger = logging.getLogger("campusai.ingestion")


def process_next_ingestion_job(db: Session, *, now: datetime | None = None) -> bool:
    """Claim and process one ready job. Returns False when the queue is empty."""
    now = now or datetime.now(timezone.utc)
    ready = or_(
        and_(DocumentIngestionJob.status == "queued", DocumentIngestionJob.available_at <= now),
        and_(DocumentIngestionJob.status == "processing", DocumentIngestionJob.locked_until <= now),
    )
    job = db.scalar(select(DocumentIngestionJob).where(ready).order_by(DocumentIngestionJob.available_at, DocumentIngestionJob.id)
                    .with_for_update(skip_locked=True).limit(1))
    if job is None:
        return False
    if not job.payload:
        job.status, job.last_error = "failed", "Source payload is unavailable."
        document = db.get(Document, job.document_id)
        if document:
            document.ingestion_status, document.ingestion_error = "failed", job.last_error
        db.commit()
        return True
    job.status = "processing"
    job.attempts += 1
    job.lease_token = token = str(uuid.uuid4())
    job.locked_until = now + timedelta(seconds=settings.ingestion_job_lease_seconds)
    job.updated_at = now
    payload, document_id = bytes(job.payload), job.document_id
    db.commit()

    try:
        document = db.get(Document, document_id)
        if document is None:
            raise ValueError("Document record no longer exists.")
        suffix = Path(document.filename).suffix.lower()
        with tempfile.TemporaryDirectory(prefix="campusai-ingest-") as temp_dir:
            source = Path(temp_dir) / f"source{suffix}"
            source.write_bytes(payload)
            pages = extract_pages(source, enable_ocr=settings.ocr_enabled,
                                  ocr_languages=settings.ocr_languages, ocr_dpi=settings.ocr_dpi)
        metadata_suggestions = suggest_document_metadata(pages)
        chunks = chunk_pages(pages)
        if not chunks:
            raise ValueError("No readable text was found in the document.")
    except ValueError as exc:
        _finish_error(db, document_id, token, now, str(exc), permanent=True)
        return True
    except Exception:
        logger.warning("Document ingestion attempt failed for document %s", document_id)
        _finish_error(db, document_id, token, now, "Document extraction failed; it will be retried.", permanent=False)
        return True

    current = db.scalar(select(DocumentIngestionJob).where(DocumentIngestionJob.document_id == document_id).with_for_update())
    document = db.scalar(select(Document).where(Document.id == document_id).with_for_update())
    if current is None or current.status != "processing" or current.lease_token != token or document is None or document.approval_status == "rejected":
        db.rollback()
        return True
    records = []
    for index, chunk in enumerate(chunks):
        record = DocumentChunk(document_id=document.id, chunk_index=index, page_number=chunk["page_number"],
                               section=chunk.get("section"), text=chunk["text"], vector_id=str(uuid.uuid4()))
        db.add(record)
        db.flush()
        records.append({"chunk_id": record.id, "document_id": document.id, "vector_id": record.vector_id,
                        "text": record.text, "approval_status": document.approval_status, "category": document.category,
                        "company_id": document.company_id, "academic_year": document.academic_year,
                        "version": document.version, "effective_date": document.effective_date, "expiry_date": document.expiry_date})
    document.ingestion_status, document.ingestion_error = "completed", None
    document.suggested_category = metadata_suggestions["suggested_category"]
    document.classification_score = metadata_suggestions["classification_score"]
    document.metadata_candidates = metadata_suggestions
    current.status, current.payload, current.lease_token, current.locked_until = "completed", None, None, None
    current.last_error, current.updated_at = None, now
    db.commit()
    try:
        index_chunks(records)
    except Exception:
        # The committed chunks remain available to BM25 retrieval.
        logger.info("Vector indexing deferred for document %s", document_id)
    return True


def _finish_error(db: Session, document_id: int, token: str, now: datetime, message: str, *, permanent: bool) -> None:
    job = db.scalar(select(DocumentIngestionJob).where(DocumentIngestionJob.document_id == document_id).with_for_update())
    if job is None or job.status != "processing" or job.lease_token != token:
        db.rollback()
        return
    document = db.get(Document, document_id)
    terminal = permanent or job.attempts >= settings.ingestion_max_attempts
    job.last_error = message[:300]
    job.updated_at = now
    job.locked_until = job.lease_token = None
    if terminal:
        job.status, job.payload = "failed", None
        if document:
            document.ingestion_status, document.ingestion_error = "failed", job.last_error
    else:
        job.status = "queued"
        job.available_at = now + timedelta(seconds=min(60, 2 ** job.attempts))
    db.commit()


def run_worker() -> None:
    if settings.document_ingestion_mode != "queued":
        raise RuntimeError("Set DOCUMENT_INGESTION_MODE=queued for the ingestion worker.")
    if engine.dialect.name != "postgresql":
        raise RuntimeError("The production ingestion worker requires PostgreSQL row locking.")
    logger.info("Document ingestion worker started")
    while True:
        try:
            with SessionLocal() as db:
                worked = process_next_ingestion_job(db)
        except Exception:
            logger.warning("Ingestion queue polling failed; retrying")
            worked = False
        if not worked:
            time.sleep(settings.ingestion_worker_poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
