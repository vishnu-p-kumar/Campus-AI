"""Exercise real PDF ingestion, embeddings, Qdrant, hybrid retrieval and safe abstention.

By default, this verifier uses the real local Qdrant engine in memory and local
PostgreSQL test rows. With --allow-qdrant-cloud-write, it uses a uniquely named
temporary Qdrant Cloud collection instead. It never calls Gemini. Temporary
vectors, database rows and the uploaded file are removed on exit.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from starlette.datastructures import UploadFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai import retrieval  # noqa: E402
from app.api import chat as chat_api, documents as documents_api  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import AuditLog, ChatMessage, Conversation, Document, DocumentChunk, User  # noqa: E402
from app.schemas import ChatInput  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path, help="Path to a public or institution-approved placement PDF")
    parser.add_argument(
        "--allow-qdrant-cloud-write",
        action="store_true",
        help="Explicitly write vectors to a unique temporary collection in configured Qdrant Cloud",
    )
    args = parser.parse_args()
    pdf_path = args.pdf.resolve()
    if pdf_path.suffix.lower() != ".pdf" or not pdf_path.is_file():
        parser.error("--pdf must refer to an existing PDF file")
    db_url = make_url(settings.database_url)
    if db_url.drivername != "postgresql+psycopg" or db_url.host not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("This verifier only accepts a loopback PostgreSQL database")

    from qdrant_client import QdrantClient

    collection = f"campusai_pdfcheck_{uuid4().hex[:12]}"
    if args.allow_qdrant_cloud_write and (not settings.qdrant_url or not settings.qdrant_api_key):
        parser.error("Qdrant Cloud mode requires QDRANT_URL and QDRANT_API_KEY in backend/.env")
    original_collection = settings.qdrant_collection
    original_upload_directory = settings.upload_directory
    original_qdrant_client = retrieval._qdrant
    original_generator = chat_api.generate_grounded_answer
    qdrant = None
    collection_owned = False
    document_id: int | None = None
    user_id: int | None = None
    stage = "setup"
    chat_api.generate_grounded_answer = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("The live PDF verifier must not call Gemini")
    )
    status = 1
    try:
        if args.allow_qdrant_cloud_write:
            qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)
            existing = {item.name for item in qdrant.get_collections().collections}
            if collection in existing:
                raise RuntimeError("The temporary Qdrant collection name already exists")
            collection_owned = True
            print("QDRANT_TARGET", "cloud")
        else:
            qdrant = QdrantClient(":memory:")
            print("QDRANT_TARGET", "local_memory")
        retrieval._qdrant = qdrant
        settings.qdrant_collection = collection
        with TemporaryDirectory(prefix="campusai-pdf-rag-") as upload_dir:
            settings.upload_directory = upload_dir
            with SessionLocal() as db:
                user = User(
                    email=f"pdf-rag-{uuid4().hex}@example.invalid",
                    full_name="CampusAI PDF Integration Check",
                    password_hash="unused-pdf-test-account",
                    role="administrator",
                )
                db.add(user)
                db.commit()
                db.refresh(user)
                user_id = user.id

                payload = pdf_path.read_bytes()
                upload = UploadFile(filename=pdf_path.name, file=BytesIO(payload))
                stage = "PDF upload, extraction and embedding"
                uploaded = asyncio.run(documents_api.upload_document(
                    file=upload,
                    title=f"CampusAI PDF integration {uuid4().hex[:12]}",
                    category="placement-policy",
                    effective_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
                    expiry_date=None,
                    supersedes_id=None,
                    company_id=None,
                    academic_year="2023-24",
                    actor=user,
                    db=db,
                ))
                document_id = uploaded["id"]
                chunk_ids = uploaded["chunk_ids"]
                stage = "validate extraction and initial Qdrant indexing"
                print("UPLOAD_CHUNK_COUNT", uploaded["chunks_created"])
                print("UPLOAD_VECTOR_COUNT", uploaded["vectors_indexed"])
                assert chunk_ids and uploaded["vectors_indexed"] == uploaded["chunks_created"]
                assert uploaded["chunks_created"] > 0

                stage = "document approval and Qdrant point count"
                approved = documents_api.approve_document(document_id, actor=user, db=db)
                assert approved["approval_status"] == "approved"
                assert approved["vectors_indexed"] == uploaded["chunks_created"]
                assert qdrant.count(collection_name=collection, exact=True).count == uploaded["chunks_created"]

                query = "What minimum CGPA is required to register for campus placements?"
                stage = "BM25, dense, hybrid retrieval and reranking"
                lexical = retrieval.retrieve(db, query, limit=10, category="placement-policy")
                dense = retrieval.retrieve_dense(query, limit=10, category="placement-policy")
                hybrid = retrieval.hybrid_retrieve(db, query, limit=10, category="placement-policy")
                assert any(row["document_id"] == document_id for row in lexical)
                assert any(row["chunk_id"] in chunk_ids for row in dense)
                target_rows = [row for row in hybrid if row["document_id"] == document_id]
                assert target_rows and all("rrf_score" in row for row in target_rows)
                assert retrieval._cross_encoder is not None

                stage = "historical policy retrieval"
                historical = retrieval.hybrid_retrieve(
                    db,
                    query,
                    as_of=datetime(2024, 6, 1, tzinfo=timezone.utc),
                    limit=10,
                    category="placement-policy",
                )
                assert any(row["document_id"] == document_id for row in historical)

                unsupported_question = "What is the cafeteria menu next Tuesday?"
                stage = "confidence-gated unsupported-question abstention"
                unsupported_evidence = retrieval.hybrid_retrieve(db, unsupported_question, limit=6)
                features = retrieval.confidence_features(unsupported_question, unsupported_evidence)
                print("UNSUPPORTED_QUERY_CONFIDENCE", features["label"], features["score"], features["coverage"])
                assert features["label"] in {"weak", "unsupported", "partial"}
                abstention = chat_api.chat(ChatInput(question=unsupported_question), user=user, db=db)
                print("UNSUPPORTED_QUERY_ABSTAINED", abstention.abstained)
                assert abstention.abstained is True
                assert not abstention.citations

                print("PYTHON_RUNTIME", sys.version.split()[0])
                print("PDF_FILE", pdf_path.name)
                print("PDF_UPLOAD_AND_EXTRACTION", "passed")
                print("CHUNKS_CREATED", uploaded["chunks_created"])
                print("REAL_EMBEDDINGS_AND_QDRANT_POINTS", uploaded["vectors_indexed"])
                print("DENSE_RETRIEVAL", "passed")
                print("BM25_RETRIEVAL", "passed")
                print("RRF_AND_CROSS_ENCODER_RERANKING", "passed")
                print("HISTORICAL_POLICY_RETRIEVAL", "passed")
                print("UNSUPPORTED_QUERY_ABSTENTION_WITHOUT_GEMINI", "passed")
                print("GEMINI_REQUESTS", 0)
                status = 0
    except HTTPException as exc:
        print("PDF_RAG_HTTP_STATUS", exc.status_code)
        print("PDF_RAG_FAILURE", "application rejected the integration request")
    except Exception as exc:
        print("PDF_RAG_FAILURE_AT", stage)
        print("PDF_RAG_FAILURE_TYPE", type(exc).__name__)
        status = 1
    finally:
        settings.qdrant_collection = original_collection
        settings.upload_directory = original_upload_directory
        retrieval._qdrant = original_qdrant_client
        chat_api.generate_grounded_answer = original_generator
        try:
            if qdrant is not None and collection_owned and collection in {
                entry.name for entry in qdrant.get_collections().collections
            }:
                qdrant.delete_collection(collection_name=collection)
            elif qdrant is not None and not args.allow_qdrant_cloud_write and collection in {
                entry.name for entry in qdrant.get_collections().collections
            }:
                qdrant.delete_collection(collection_name=collection)
        except Exception as exc:
            print("TEMPORARY_QDRANT_CLEANUP_FAILURE", type(exc).__name__)
            status = 1
        try:
            with SessionLocal.begin() as cleanup:
                if user_id is not None:
                    conversation_ids = select(Conversation.id).where(Conversation.user_id == user_id)
                    cleanup.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conversation_ids)))
                    cleanup.execute(delete(Conversation).where(Conversation.user_id == user_id))
                    cleanup.execute(delete(AuditLog).where(AuditLog.actor_user_id == user_id))
                if document_id is not None:
                    cleanup.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
                    cleanup.execute(delete(AuditLog).where(
                        AuditLog.resource_type == "document",
                        AuditLog.resource_id == str(document_id),
                    ))
                    cleanup.execute(delete(Document).where(Document.id == document_id))
                if user_id is not None:
                    cleanup.execute(delete(User).where(User.id == user_id))
        except Exception as exc:
            print("TEMPORARY_POSTGRES_CLEANUP_FAILURE", type(exc).__name__)
            status = 1
        if qdrant is not None:
            qdrant.close()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
