from datetime import datetime, timezone
import logging
import math
import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.core.config import settings

_embedding_model = None
_cross_encoder = None
_qdrant = None
logger = logging.getLogger(__name__)
MULTILINGUAL_TERMS = {
    "पात्रता": "eligibility", "योग्यता": "eligibility", "न्यूनतम": "minimum", "सीजीपीए": "cgpa", "बैकलॉग": "backlog",
    "नियम": "policy rules", "प्लेसमेंट": "placement", "कंपनी": "company", "आवेदन": "application", "ड्राइव": "drive",
    "ಅರ್ಹತೆ": "eligibility", "ಯೋಗ್ಯತೆ": "eligibility", "ಕನಿಷ್ಠ": "minimum", "ಸಿಜಿಪಿಎ": "cgpa", "ಬ್ಯಾಕ್ಲಾಗ್": "backlog",
    "ನಿಯಮ": "policy rules", "ಪ್ಲೇಸ್ಮೆಂಟ್": "placement", "ಕಂಪನಿ": "company", "ಅರ್ಜಿ": "application", "ಡ್ರೈವ್": "drive",
}
_CONFIDENCE_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "about", "according", "be", "by", "can", "does", "did", "do", "for", "from", "how", "i", "in",
    "is", "it", "me", "my", "of", "on", "or", "our", "please", "should", "that", "the", "their", "them",
    "these", "this", "those", "to", "was", "what", "when", "where", "which", "who", "why", "will", "with",
    "details", "detail", "information", "member", "members", "tell", "give",
    "would", "you", "your", "all", "list", "listed", "listing",
    "document", "documents", "happen", "happens", "next", "named", "mention", "mentions", "mentioned",
    "specifically", "student", "students", "include", "includes", "included", "describe", "describes",
}

_SEARCH_TERM_ALIASES = {
    "application": "apply", "applications": "apply", "applicant": "apply", "applicants": "apply",
    "applied": "apply", "applying": "apply",
    "faculty": "faculty", "professor": "faculty", "lecturer": "faculty", "instructor": "faculty",
}


def normalize_search_term(term: str) -> str:
    """Normalize common placement-query variants without stemming identifiers."""
    term = term.casefold()
    if term in _SEARCH_TERM_ALIASES:
        return _SEARCH_TERM_ALIASES[term]
    if len(term) > 4 and term.endswith("ies"):
        return term[:-3] + "y"
    if len(term) > 4 and term.endswith("s"):
        return term[:-1]
    return term


def tokenize(text: str) -> list[str]:
    expanded = text.casefold()
    for term, english in MULTILINGUAL_TERMS.items():
        if term in expanded:
            expanded += " " + english
    return [normalized for token in re.findall(r"[a-z0-9]+", expanded)
            if (normalized := normalize_search_term(token))]


def retrieve(db: Session, query: str, as_of: datetime | None = None, limit: int = 6, category: str | None = None,
             company_id: int | None = None, academic_year: str | None = None, version: int | None = None) -> list[dict[str, Any]]:
    historical = as_of is not None
    as_of = as_of or datetime.now(timezone.utc)
    stmt = select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id).where(
        Document.approval_status.in_(["approved", "superseded"] if historical else ["approved"]),
        (Document.effective_date.is_(None)) | (Document.effective_date <= as_of),
        (Document.expiry_date.is_(None)) | (Document.expiry_date >= as_of),
    )
    if category:
        stmt = stmt.where(Document.category == category)
    if company_id is not None:
        # Keep institution-wide uploads in scope for company questions. Admins
        # often upload a company document before associating it with a profile.
        stmt = stmt.where(or_(Document.company_id == company_id, Document.company_id.is_(None)))
    if academic_year:
        stmt = stmt.where(Document.academic_year == academic_year)
    if version is not None:
        stmt = stmt.where(Document.version == version)
    rows = db.execute(stmt).all()
    query_tokens = tokenize(query)
    query_terms = set(query_tokens)
    ranked = []
    for chunk, document in rows:
        # Keep the original chunk intact for Gemini and citations, while also
        # making admin-assigned titles and original filenames searchable.
        searchable_text = f"{document.title} {document.filename} {chunk.text}"
        terms = tokenize(searchable_text)
        term_set = set(terms)
        overlap = len(query_terms & term_set)
        if overlap == 0:
            continue
        frequency = sum(terms.count(term) for term in query_terms)
        lexical_score = (overlap / max(len(query_terms), 1)) * (1.0 + min(frequency, 5) * 0.08)
        ranked.append({
            "chunk_id": chunk.id,
            "document_id": document.id,
            "title": document.title,
            "filename": document.filename,
            "category": document.category,
            "company_id": document.company_id,
            "academic_year": document.academic_year,
            "version": document.version,
            "approval_status": document.approval_status,
            "effective_date": document.effective_date,
            "expiry_date": document.expiry_date,
            "page_number": chunk.page_number,
            "section": chunk.section,
            "text": chunk.text,
            "lexical_score": lexical_score,
            "matched_terms": overlap,
            "query_terms": len(query_terms),
        })
    try:
        from rank_bm25 import BM25Okapi
        if rows:
            lexical_rows = [{
                "chunk_id": chunk.id, "document_id": document.id, "title": document.title,
                "filename": document.filename,
                "category": document.category, "version": document.version,
                "company_id": document.company_id, "academic_year": document.academic_year,
                "approval_status": document.approval_status, "effective_date": document.effective_date,
                "expiry_date": document.expiry_date, "page_number": chunk.page_number,
                "section": chunk.section, "text": chunk.text,
            } for chunk, document in rows]
            corpus = [tokenize(f"{row['title']} {row['filename']} {row['text']}") for row in lexical_rows]
            bm25 = BM25Okapi(corpus)
            bm25_scores = bm25.get_scores(query_tokens)
            for row, score in zip(lexical_rows, bm25_scores):
                row["bm25_score"] = float(score)
                row["lexical_score"] = max(0.0, float(score))
                row["matched_terms"] = len(set(query_tokens) & set(tokenize(f"{row['title']} {row['filename']} {row['text']}")))
                row["query_terms"] = len(set(query_tokens))
            ranked = [row for row in lexical_rows if row["matched_terms"]]
            ranked.sort(key=lambda row: (row["bm25_score"], row["matched_terms"]), reverse=True)
    except ImportError:
        pass
    return ranked[:limit]


def embed_texts(texts: list[str]) -> list[list[float]]:
    global _embedding_model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Install backend/requirements-ai.txt to enable Sentence Transformer embeddings") from exc
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(settings.embedding_model)
    return _embedding_model.encode(texts, normalize_embeddings=True).tolist()


def qdrant_client():
    global _qdrant
    if not settings.qdrant_url:
        return None
    if _qdrant is None:
        from qdrant_client import QdrantClient
        _qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=10)
    return _qdrant


def _is_collection_not_found(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) == 404:
        return True
    # Qdrant's in-memory/local client reports a missing collection as ValueError;
    # the remote HTTP client reports status 404 for the same condition.
    message = str(exc).casefold()
    return isinstance(exc, ValueError) and "collection" in message and "not found" in message


def index_chunks(chunks: list[dict]) -> int:
    client = qdrant_client()
    if client is None or not chunks:
        return 0
    from qdrant_client.http import models as qm
    vectors = embed_texts([item["text"] for item in chunks])
    try:
        collection_info = client.get_collection(settings.qdrant_collection)
    except Exception as exc:
        if not _is_collection_not_found(exc):
            raise
        client.create_collection(settings.qdrant_collection, vectors_config=qm.VectorParams(size=len(vectors[0]), distance=qm.Distance.COSINE))
        collection_info = client.get_collection(settings.qdrant_collection)
    payload_indexes = {
        "approval_status": qm.PayloadSchemaType.KEYWORD,
        "category": qm.PayloadSchemaType.KEYWORD,
        "company_id": qm.PayloadSchemaType.INTEGER,
        "academic_year": qm.PayloadSchemaType.KEYWORD,
        "version": qm.PayloadSchemaType.INTEGER,
        "effective_date": qm.PayloadSchemaType.DATETIME,
        "expiry_date": qm.PayloadSchemaType.DATETIME,
    }
    current_schema = collection_info.payload_schema or {}
    for field_name, field_type in payload_indexes.items():
        existing = current_schema.get(field_name)
        if existing is not None:
            if existing.data_type != field_type:
                raise RuntimeError(f"Qdrant payload index {field_name!r} has an incompatible schema")
            continue
        client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name=field_name,
            field_schema=field_type,
            wait=True,
        )
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[qm.PointStruct(id=item["vector_id"], vector=vector, payload={"chunk_id": item["chunk_id"], "document_id": item["document_id"], "approval_status": item["approval_status"], "category": item["category"], "company_id": item.get("company_id"), "academic_year": item.get("academic_year"), "version": item.get("version"), "effective_date": item["effective_date"].isoformat() if item.get("effective_date") else None, "expiry_date": item.get("expiry_date").isoformat() if item.get("expiry_date") else None}) for item, vector in zip(chunks, vectors)],
        wait=True,
    )
    return len(chunks)


def retrieve_dense(query: str, as_of: datetime | None = None, limit: int = 8, category: str | None = None,
                   company_id: int | None = None, academic_year: str | None = None, version: int | None = None) -> list[dict]:
    try:
        client = qdrant_client()
        if client is None:
            return []
        from qdrant_client.http import models as qm
        vector = embed_texts([query])[0]
        conditions = [qm.FieldCondition(key="approval_status", match=qm.MatchAny(any=["approved", "superseded"] if as_of else ["approved"]))]
        if category:
            conditions.append(qm.FieldCondition(key="category", match=qm.MatchValue(value=category)))
        if company_id is not None:
            conditions.append(qm.Filter(should=[
                qm.FieldCondition(key="company_id", match=qm.MatchValue(value=company_id)),
                qm.IsEmptyCondition(is_empty=qm.PayloadField(key="company_id")),
            ]))
        if academic_year:
            conditions.append(qm.FieldCondition(key="academic_year", match=qm.MatchValue(value=academic_year)))
        if version is not None:
            conditions.append(qm.FieldCondition(key="version", match=qm.MatchValue(value=version)))
        if as_of is not None:
            as_of_utc = as_of.replace(tzinfo=timezone.utc) if as_of.tzinfo is None else as_of.astimezone(timezone.utc)
            conditions.extend([
                qm.Filter(should=[
                    qm.FieldCondition(key="effective_date", range=qm.DatetimeRange(lte=as_of_utc)),
                    qm.IsEmptyCondition(is_empty=qm.PayloadField(key="effective_date")),
                ]),
                qm.Filter(should=[
                    qm.FieldCondition(key="expiry_date", range=qm.DatetimeRange(gte=as_of_utc)),
                    qm.IsEmptyCondition(is_empty=qm.PayloadField(key="expiry_date")),
                ]),
            ])
        response = client.query_points(collection_name=settings.qdrant_collection, query=vector, limit=limit, query_filter=qm.Filter(must=conditions))
        return [{"chunk_id": point.payload.get("chunk_id"), "dense_score": point.score} for point in response.points]
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        logger.warning(
            "Dense retrieval unavailable; falling back to lexical search (%s, status=%s)",
            type(exc).__name__,
            status_code if isinstance(status_code, int) else "unknown",
        )
        return []


def hybrid_retrieve(db: Session, query: str, as_of: datetime | None = None, limit: int = 6, category: str | None = None,
                    company_id: int | None = None, academic_year: str | None = None, version: int | None = None) -> list[dict]:
    lexical = retrieve(db, query, as_of=as_of, limit=limit * 3, category=category, company_id=company_id, academic_year=academic_year, version=version)
    dense_ids = retrieve_dense(query, as_of=as_of, limit=limit * 3, category=category, company_id=company_id, academic_year=academic_year, version=version)
    if not dense_ids:
        # Qdrant is optional, but the cross-encoder can still improve the BM25
        # candidate order when dense retrieval is unavailable.
        return rerank(query, lexical[:limit])
    as_of_filter = as_of or datetime.now(timezone.utc)
    stmt = select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id).where(
        DocumentChunk.id.in_([item["chunk_id"] for item in dense_ids]),
        Document.approval_status.in_(["approved", "superseded"] if as_of else ["approved"]),
        (Document.effective_date.is_(None)) | (Document.effective_date <= as_of_filter),
        (Document.expiry_date.is_(None)) | (Document.expiry_date >= as_of_filter),
    )
    if category:
        stmt = stmt.where(Document.category == category)
    if company_id is not None:
        stmt = stmt.where(or_(Document.company_id == company_id, Document.company_id.is_(None)))
    if academic_year:
        stmt = stmt.where(Document.academic_year == academic_year)
    if version is not None:
        stmt = stmt.where(Document.version == version)
    dense_rows = []
    by_id = {}
    for chunk, document in db.execute(stmt).all():
        row = {"chunk_id": chunk.id, "document_id": document.id, "title": document.title, "filename": document.filename, "category": document.category,
               "company_id": document.company_id, "academic_year": document.academic_year,
                "version": document.version, "approval_status": document.approval_status, "effective_date": document.effective_date,
                "category": document.category, "academic_year": document.academic_year, "company_id": document.company_id,
               "expiry_date": document.expiry_date, "page_number": chunk.page_number, "section": chunk.section, "text": chunk.text}
        by_id[str(chunk.id)] = row
    for dense in dense_ids:
        row = by_id.get(str(dense["chunk_id"]))
        if row:
            dense_rows.append({**row, **dense})
    fused = reciprocal_rank_fusion(lexical, dense_rows, limit=limit)
    all_rows = {str(row["chunk_id"]): row for row in lexical + dense_rows}
    results = [
        {**all_rows[str(item["chunk_id"])], "rrf_score": item["rrf_score"]}
        for item in fused
        if str(item["chunk_id"]) in all_rows
    ]
    return rerank(query, results)


def rerank(query: str, candidates: list[dict]) -> list[dict]:
    global _cross_encoder
    if not candidates:
        return []
    try:
        from sentence_transformers import CrossEncoder
        if _cross_encoder is None:
            _cross_encoder = CrossEncoder(settings.reranker_model)
        scores = list(_cross_encoder.predict([(query, item["text"]) for item in candidates]))
        if len(scores) != len(candidates) or any(not math.isfinite(float(score)) for score in scores):
            raise ValueError("Cross-encoder returned invalid scores")
        return [item for _, item in sorted(zip(scores, candidates), key=lambda pair: float(pair[0]), reverse=True)]
    except ImportError:
        # Reranking is an optional extra; BM25/RRF remain usable without it.
        return candidates
    except Exception as exc:
        logger.warning("Cross-encoder reranking unavailable; retaining retrieval order (%s)", type(exc).__name__)
        return candidates


def reciprocal_rank_fusion(*rankings: list[dict], limit: int = 8, k: int = 60) -> list[dict]:
    fused: dict[str, dict] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            key = str(item.get("chunk_id", item.get("id")))
            current = fused.setdefault(key, {**item, "rrf_score": 0.0})
            current["rrf_score"] += 1 / (k + rank)
    return sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)[:limit]


def confidence_features(query: str, sources: list[dict]) -> dict:
    minimum_score = settings.evidence_minimum_score
    def meaningful_terms(text: str) -> set[str]:
        tokens = tokenize(text)
        uppercase_tokens = {
            token.casefold() for token in re.findall(r"[A-Za-z0-9]+", text)
            if token.isupper()
        }
        terms = {normalized for token in tokens
                 if (normalized := (token if token in uppercase_tokens else normalize_search_term(token)))}
        terms -= _CONFIDENCE_STOPWORDS
        acronym_components: set[str] = set()
        for index in range(len(tokens) - 1):
            left, right = tokens[index:index + 2]
            if (left in uppercase_tokens and right in uppercase_tokens
                    and len(left) <= 3 and len(right) <= 4):
                terms.add(left + right)
                acronym_components.update((left, right))
        # Treat split and unspaced spellings of an acronym as the same entity
        # instead of counting each fragment as a separate evidence requirement.
        terms.difference_update(acronym_components)
        return terms

    terms = meaningful_terms(query)
    if not terms or not sources:
        return {"score": 0.0, "label": "unsupported", "coverage": 0.0,
                "minimum_score_threshold": minimum_score}
    # Titles and original filenames are evidence too: users often refer to an
    # uploaded job description by its organization or role, while the chunk
    # body contains only the duties and requirements.
    evidence_terms = set(
        term
        for src in sources
        for term in meaningful_terms(" ".join(str(src.get(field) or "") for field in ("title", "filename", "text")))
    )
    coverage = len(terms & evidence_terms) / max(len(terms), 1)
    if coverage == 0:
        # A high cosine match can find relevant passages even when the
        # student's wording uses different terms from the admin's document.
        # Keep this as partial evidence so the answer model must stay grounded.
        dense_score = max((float(source.get("dense_score") or 0.0) for source in sources), default=0.0)
        if dense_score >= 0.72:
            return {"score": round(min(1.0, max(minimum_score, dense_score * 0.65)), 3),
                    "label": "partial", "coverage": 0.0,
                    "minimum_score_threshold": minimum_score}
        return {"score": 0.0, "label": "unsupported", "coverage": 0.0,
                "minimum_score_threshold": minimum_score}
    source_count = len({source["document_id"] for source in sources})
    top = max(
        max((float(source.get("lexical_score") or 0.0) for source in sources), default=0.0),
        max((float(source.get("dense_score") or 0.0) for source in sources), default=0.0),
    )
    score = min(1.0, coverage * 0.65 + min(source_count, 2) * 0.1 + min(top, 1.0) * 0.15)
    label = ("weak" if score < minimum_score else
             "supported" if score >= 0.62 and coverage >= 0.45 else "partial")
    return {"score": round(score, 3), "label": label, "coverage": round(coverage, 3),
            "minimum_score_threshold": minimum_score}


def should_abstain_for_evidence(features: dict) -> bool:
    """Use the shared production gate in chat and every evaluation runner."""
    return features.get("label") != "supported"
