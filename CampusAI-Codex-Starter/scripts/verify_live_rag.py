"""Verify the real document -> embedding -> Qdrant -> retrieval -> Gemini path.

The script uses synthetic policy text and a temporary local upload directory. It
requires explicit flags because it writes temporary vectors to Qdrant and makes
exactly one Gemini generation request. Test vectors and local database records
are removed in a finally block; a newly created empty Qdrant collection remains.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from io import BytesIO
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from starlette.datastructures import UploadFile
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.ai import gemini, retrieval  # noqa: E402
from app.api import chat as chat_api, documents as documents_api  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    ChatMessage,
    Conversation,
    Document,
    DocumentChunk,
    User,
)
from app.schemas import ChatInput  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-qdrant-test-write", action="store_true")
    parser.add_argument("--allow-one-gemini-request", action="store_true")
    args = parser.parse_args()
    if not args.allow_qdrant_test_write or not args.allow_one_gemini_request:
        print("Pass both --allow-qdrant-test-write and --allow-one-gemini-request to run this live check.")
        return 2
    if not settings.qdrant_url or not settings.qdrant_api_key:
        print("Qdrant is not configured in backend/.env.")
        return 2
    if not settings.gemini_chat_api_key:
        print("Gemini is not configured in backend/.env.")
        return 2
    database_url = make_url(settings.database_url)
    if database_url.drivername != "postgresql+psycopg" or database_url.host not in {"localhost", "127.0.0.1", "::1"}:
        print("This verification requires the configured local PostgreSQL database.")
        return 2

    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels

    qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=15)
    collection = settings.qdrant_collection
    initial_names = {item.name for item in qdrant.get_collections().collections}
    collection_preexisted = collection in initial_names
    baseline_count = qdrant.count(collection, exact=True).count if collection_preexisted else 0

    test_key = uuid4().hex
    title = f"CampusAI live RAG verification {test_key}"
    email = f"rag-verification-{test_key}@example.invalid"
    user_id: int | None = None
    document_ids: list[int] = []
    vector_ids: list[str] = []
    generation_calls = 0
    generation_usage: dict = {}
    original_generator = chat_api.generate_grounded_answer
    stage = "setup"
    original_upload_directory = settings.upload_directory
    status = 1

    def capture_single_generation(question: str, sources: list[dict], language: str = "en", conversation_context=None) -> str:
        nonlocal generation_calls, generation_usage
        generation_calls += 1
        if generation_calls > 1:
            raise RuntimeError("Live verification exceeded the single-request limit")
        answer, usage = gemini.generate_grounded_answer_with_usage(
            question, sources, language, conversation_context
        )
        generation_usage = usage
        return answer

    chat_api.generate_grounded_answer = capture_single_generation
    try:
        with TemporaryDirectory(prefix="campusai-live-rag-") as temporary_uploads:
            settings.upload_directory = temporary_uploads
            with SessionLocal() as db:
                actor = User(
                    email=email,
                    full_name="CampusAI Live Integration Test",
                    password_hash="unused-live-test-account",
                    role="administrator",
                )
                db.add(actor)
                db.commit()
                db.refresh(actor)
                user_id = actor.id

                async def upload_text(filename: str, content: str, effective: datetime, expires: datetime | None = None, supersedes: int | None = None) -> dict:
                    upload = UploadFile(filename=filename, file=BytesIO(content.encode("utf-8")))
                    return await documents_api.upload_document(
                        file=upload,
                        title=title if supersedes is not None or filename == "policy-v1.txt" else f"CampusAI live RAG glossary {test_key}",
                        category="placement-policy",
                        effective_date=effective,
                        expiry_date=expires,
                        supersedes_id=supersedes,
                        company_id=None,
                        academic_year="2025-26",
                        actor=actor,
                        db=db,
                    )

                stage = "upload and embed policy v1"
                v1 = asyncio.run(upload_text(
                    "policy-v1.txt",
                    "CGPA REQUIREMENT\n\nFor placement eligibility during 2025, students must have a minimum CGPA of 7.0. This is the official campus placement policy.",
                    datetime(2024, 1, 1, tzinfo=timezone.utc),
                    datetime(2025, 12, 31, tzinfo=timezone.utc),
                ))
                document_ids.append(v1["id"])
                assert v1["chunks_created"] > 0 and v1["vectors_indexed"] == v1["chunks_created"]
                stage = "approve policy v1 and index approved vectors"
                approved_v1 = documents_api.approve_document(v1["id"], actor=actor, db=db)
                assert approved_v1["approval_status"] == "approved"
                assert approved_v1["vectors_indexed"] == v1["chunks_created"]

                stage = "upload and embed policy v2"
                v2 = asyncio.run(upload_text(
                    "policy-v2.txt",
                    "CGPA REQUIREMENT\n\nFor placement eligibility from 2026 onward, students must have a minimum CGPA of 7.5. This is the current official campus placement policy.",
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    supersedes=v1["id"],
                ))
                document_ids.append(v2["id"])
                assert v2["version"] == 2 and v2["chunks_created"] > 0
                stage = "approve policy v2 and update Qdrant payloads"
                approved_v2 = documents_api.approve_document(v2["id"], actor=actor, db=db)
                assert approved_v2["approval_status"] == "approved"
                assert approved_v2["vectors_indexed"] == v2["chunks_created"]

                stage = "upload and approve second current evidence source"
                glossary = asyncio.run(upload_text(
                    "glossary.txt",
                    "PLACEMENT ELIGIBILITY\n\nThe placement office publishes CGPA eligibility criteria in official placement policy documents. Students should consult the currently effective policy for minimum eligibility requirements.",
                    datetime(2024, 1, 1, tzinfo=timezone.utc),
                ))
                document_ids.append(glossary["id"])
                documents_api.approve_document(glossary["id"], actor=actor, db=db)
                all_vectors = db.scalars(select(DocumentChunk.vector_id).where(DocumentChunk.document_id.in_(document_ids))).all()
                vector_ids = list(all_vectors)

                stage = "verify Qdrant point count and dense retrieval"
                point_count = qdrant.count(collection, exact=True).count
                assert point_count >= baseline_count + len(vector_ids)
                query = "What is the minimum CGPA required for placement eligibility?"
                dense = retrieval.retrieve_dense(query, limit=10, academic_year="2025-26")
                assert any(item["chunk_id"] in v2["chunk_ids"] for item in dense), dense

                stage = "verify BM25, RRF, and cross-encoder reranking"
                lexical = retrieval.retrieve(db, query, limit=10, academic_year="2025-26")
                bm25_hits_v2 = any(item["document_id"] == v2["id"] for item in lexical)
                hybrid = retrieval.hybrid_retrieve(db, query, limit=10, academic_year="2025-26")
                hybrid_hits_v2 = any(item["document_id"] == v2["id"] for item in hybrid)
                hybrid_has_fused_dense = any("rrf_score" in item and "dense_score" in item for item in hybrid)
                print("BM25_HITS_CURRENT_POLICY", bm25_hits_v2)
                print("HYBRID_HITS_CURRENT_POLICY", hybrid_hits_v2)
                print("HYBRID_HAS_DENSE_AND_RRF_SCORES", hybrid_has_fused_dense)
                assert bm25_hits_v2
                assert hybrid_hits_v2
                assert hybrid_has_fused_dense

                stage = "verify historical retrieval of superseded policy v1"
                historical_as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)
                historical_dense = retrieval.retrieve_dense(
                    query, as_of=historical_as_of, limit=10, academic_year="2025-26"
                )
                assert any(item["chunk_id"] in v1["chunk_ids"] for item in historical_dense)
                historical = retrieval.hybrid_retrieve(
                    db, query, as_of=historical_as_of, limit=10, academic_year="2025-26"
                )
                assert any(item["document_id"] == v1["id"] and item["approval_status"] == "superseded" for item in historical)
                assert not any(item["document_id"] == v2["id"] for item in historical)
                print("LIVE_UPLOAD_EMBED_QDRANT_RETRIEVAL_OK", True)
                print("CURRENT_POLICY_V2_DENSE_AND_HYBRID_OK", True)
                print("HISTORICAL_POLICY_V1_RETRIEVAL_OK", True)

                stage = "verify supported grounded chatbot answer with one Gemini request"
                supported = chat_api.chat(
                    ChatInput(question=query, language="en", academic_year="2025-26"),
                    user=actor,
                    db=db,
                )
                assert generation_calls == 1
                assert not supported.abstained
                assert supported.citation_coverage == 1.0
                assert any(citation["document_id"] == v2["id"] for citation in supported.citations)
                assert "7.5" in supported.answer

                stage = "verify confidence-aware abstention on unsupported question"
                unsupported = chat_api.chat(
                    ChatInput(question="Which shuttle bus routes operate on Fridays?", language="en", academic_year="2025-26"),
                    user=actor,
                    db=db,
                )
                assert unsupported.abstained
                assert unsupported.citations == []
                assert generation_calls == 1

                print("PYTHON_RUNTIME", sys.version.split()[0])
                print("EMBEDDING_MODEL", settings.embedding_model)
                print("RERANKER_MODEL", settings.reranker_model)
                print("UPLOAD_CHUNKS", len(vector_ids))
                print("QDRANT_COLLECTION", collection)
                print("QDRANT_POINT_COUNT_DURING_TEST", point_count)
                print("DENSE_RETRIEVAL_HITS_V2", True)
                print("BM25_AND_RRF_HITS_V2", True)
                print("HISTORICAL_RETRIEVAL_HITS_SUPERSEDED_V1", True)
                print("GROUNDED_CHAT_CITATION_COVERAGE", supported.citation_coverage)
                print("GROUNDED_CHAT_CONFIDENCE_LABEL", supported.confidence_label)
                print("GROUNDED_CHAT_CITED_V2", True)
                print("UNSUPPORTED_QUESTION_ABSTAINED", unsupported.abstained)
                print("GEMINI_GENERATION_REQUESTS", generation_calls)
                print("GEMINI_INPUT_TOKENS", generation_usage.get("input_token_count"))
                print("GEMINI_OUTPUT_TOKENS", generation_usage.get("output_token_count"))
                status = 0
    except Exception as exc:
        print(f"LIVE_RAG_CHECK_FAILED_AT={stage}")
        print(f"ERROR_TYPE={type(exc).__name__}")
        if isinstance(exc, HTTPException):
            print("HTTP_STATUS", exc.status_code)
        print("GEMINI_GENERATION_REQUESTS", generation_calls)
        status = 1
    finally:
        chat_api.generate_grounded_answer = original_generator
        settings.upload_directory = original_upload_directory
        try:
            with SessionLocal() as cleanup_read:
                scoped_titles = [title, f"CampusAI live RAG glossary {test_key}"]
                discovered_ids = cleanup_read.scalars(select(Document.id).where(Document.title.in_(scoped_titles))).all()
                document_ids = sorted(set(document_ids) | set(discovered_ids))
                if document_ids:
                    vector_ids = cleanup_read.scalars(
                        select(DocumentChunk.vector_id).where(DocumentChunk.document_id.in_(document_ids))
                    ).all()
            if vector_ids:
                qdrant.delete(
                    collection_name=collection,
                    points_selector=qmodels.PointIdsList(points=vector_ids),
                    wait=True,
                )
            remaining = qdrant.count(collection, exact=True).count if collection in {c.name for c in qdrant.get_collections().collections} else 0
            if remaining != baseline_count:
                print("QDRANT_CLEANUP_COUNT_MISMATCH", baseline_count, remaining)
                status = 1
        except Exception as exc:
            print("QDRANT_CLEANUP_FAILED", type(exc).__name__)
            status = 1
        try:
            with SessionLocal.begin() as cleanup:
                if user_id is not None:
                    conversation_ids = select(Conversation.id).where(Conversation.user_id == user_id)
                    cleanup.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conversation_ids)))
                    cleanup.execute(delete(Conversation).where(Conversation.user_id == user_id))
                    cleanup.execute(delete(AuditLog).where(AuditLog.actor_user_id == user_id))
                if document_ids:
                    cleanup.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids)))
                    cleanup.execute(delete(AuditLog).where(
                        AuditLog.resource_type == "document",
                        AuditLog.resource_id.in_([str(item) for item in document_ids]),
                    ))
                    cleanup.execute(delete(Document).where(Document.id.in_(document_ids)))
                if user_id is not None:
                    cleanup.execute(delete(User).where(User.id == user_id))
        except Exception as exc:
            print("DATABASE_CLEANUP_FAILED", type(exc).__name__)
            status = 1
        qdrant.close()
    return status


if __name__ == "__main__":
    raise SystemExit(main())
