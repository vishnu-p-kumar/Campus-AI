from datetime import datetime, timezone
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from app.ai import retrieval
from app.ai.retrieval import confidence_features, reciprocal_rank_fusion, retrieve
from app.core.config import settings
from app.models import Document, DocumentChunk, User


def test_retrieval_uses_approved_current_documents_and_citations(db_session):
    user_id = 1
    from app.models import User
    user = User(id=user_id, email="admin@example.edu", full_name="Admin", password_hash="x", role="administrator")
    db_session.add(user)
    db_session.flush()
    doc = Document(title="Placement Rules", category="policy", filename="rules.txt", storage_path="x", version=1,
                   approval_status="approved", uploaded_by=user.id, effective_date=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db_session.add(doc)
    db_session.flush()
    db_session.add(DocumentChunk(document_id=doc.id, chunk_index=0, page_number=1, text="Minimum CGPA requirement is 7.5 for engineering branches."))
    db_session.commit()

    sources = retrieve(db_session, "What is the minimum CGPA requirement?", as_of=datetime.now(timezone.utc))
    assert sources and sources[0]["document_id"] == doc.id
    evidence = confidence_features("What is minimum CGPA?", sources)
    assert evidence["label"] in {"supported", "partial"}


def test_retrieval_can_find_complete_chunk_by_original_filename(db_session):
    admin = User(email="filename-admin@example.edu", full_name="Admin", password_hash="x", role="administrator")
    db_session.add(admin)
    db_session.flush()
    doc = Document(title="Placement Rules 2026", category="placement-policy",
                   filename="BNMIT_Placement_Handbook_2026.pdf", storage_path="x", version=1,
                   approval_status="approved", uploaded_by=admin.id)
    db_session.add(doc)
    db_session.flush()
    original_chunk = "The minimum CGPA for placement applicants is 7.5. Applications close on 30 June 2026."
    db_session.add(DocumentChunk(document_id=doc.id, chunk_index=0, page_number=3, text=original_chunk))
    db_session.commit()

    sources = retrieve(db_session, "BNMIT_Placement_Handbook_2026 CGPA requirement")

    assert sources
    assert sources[0]["filename"] == "BNMIT_Placement_Handbook_2026.pdf"
    assert sources[0]["text"] == original_chunk


def test_evidence_label_uses_configured_live_abstention_threshold(monkeypatch):
    source = {"document_id": 1, "text": "minimum", "lexical_score": 0.0}
    monkeypatch.setattr(settings, "evidence_minimum_score", 0.42)
    partial = confidence_features("minimum CGPA", [source])
    assert partial["score"] == 0.425
    assert partial["label"] == "partial"
    assert partial["minimum_score_threshold"] == 0.42

    monkeypatch.setattr(settings, "evidence_minimum_score", 0.43)
    weak = confidence_features("minimum CGPA", [source])
    assert weak["label"] == "weak"

    monkeypatch.setattr(settings, "evidence_minimum_score", 0.9)
    high_cutoff = confidence_features("minimum CGPA", [source])
    assert high_cutoff["label"] == "weak"


def test_evidence_confidence_does_not_count_stopwords_as_policy_support():
    unrelated = {"document_id": 7, "text": "The placement office is open on the main campus.", "lexical_score": 1.0}
    confidence = confidence_features("What is the cafeteria menu next Tuesday?", [unrelated])
    assert confidence["label"] == "unsupported"
    assert confidence["score"] == 0.0
    assert confidence["coverage"] == 0.0


@pytest.mark.parametrize(("query", "title", "filename", "text"), [
    ("what all roles listed from EY GDS Consulting Engineer", "EY GDS Consulting Engineer", "ey-gds.pdf", "Role description and responsibilities."),
    ("list companies which came for placement 2025 and 2026", "Placement Report", "placement-2025-2026.pdf", "Companies listed for placement in 2025 and 2026."),
])
def test_evidence_confidence_counts_upload_title_filename_and_list_plural_forms(query, title, filename, text):
    source = {"document_id": 901, "title": title, "filename": filename, "text": text, "lexical_score": 1.0}
    confidence = confidence_features(query, [source])
    assert confidence["coverage"] >= 0.45
    assert confidence["label"] == "supported"


def test_rrf_combines_independent_rankings():
    fused = reciprocal_rank_fusion([{"chunk_id": 1}, {"chunk_id": 2}], [{"chunk_id": 2}, {"chunk_id": 3}])
    assert fused[0]["chunk_id"] == 2


def test_sentence_transformer_contract_uses_configured_model_and_normalizes(monkeypatch):
    calls = []

    class Encoded:
        def tolist(self):
            return [[0.6, 0.8]]

    class SentenceTransformer:
        def __init__(self, model_name):
            calls.append(("model", model_name))

        def encode(self, texts, *, normalize_embeddings):
            calls.append(("encode", texts, normalize_embeddings))
            return Encoded()

    module = ModuleType("sentence_transformers")
    module.SentenceTransformer = SentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setattr(settings, "embedding_model", "test/sentence-model")
    monkeypatch.setattr(retrieval, "_embedding_model", None)

    assert retrieval.embed_texts(["placement policy"]) == [[0.6, 0.8]]
    assert calls == [("model", "test/sentence-model"), ("encode", ["placement policy"], True)]


def test_qdrant_collection_missing_detection_supports_cloud_and_local_errors():
    cloud_error = LookupError("missing remote collection")
    cloud_error.status_code = 404
    assert retrieval._is_collection_not_found(cloud_error)
    assert retrieval._is_collection_not_found(ValueError("Collection campusai_test not found"))
    assert not retrieval._is_collection_not_found(ValueError("invalid point payload"))


def test_qdrant_index_contract_creates_cosine_collection_and_preserves_filters(monkeypatch):
    from qdrant_client.http import models as qm

    class FakeQdrant:
        def __init__(self):
            self.collection = None
            self.indexes = {}

        def get_collection(self, collection_name):
            if self.collection is None:
                error = LookupError(collection_name)
                error.status_code = 404
                raise error
            return SimpleNamespace(payload_schema={
                name: SimpleNamespace(data_type=data_type) for name, data_type in self.indexes.items()
            })

        def create_collection(self, collection_name, *, vectors_config):
            self.collection = collection_name
            self.vectors_config = vectors_config

        def create_payload_index(self, *, collection_name, field_name, field_schema, wait):
            assert collection_name == "campusai_test" and wait is True
            self.indexes[field_name] = field_schema

        def upsert(self, *, collection_name, points, wait):
            self.upserted = (collection_name, points, wait)

    client = FakeQdrant()
    monkeypatch.setattr(settings, "qdrant_url", "https://qdrant.example.test")
    monkeypatch.setattr(settings, "qdrant_collection", "campusai_test")
    monkeypatch.setattr(retrieval, "qdrant_client", lambda: client)
    monkeypatch.setattr(retrieval, "embed_texts", lambda texts: [[0.6, 0.8] for _ in texts])
    effective = datetime(2025, 1, 1, tzinfo=timezone.utc)
    expiry = datetime(2027, 1, 1, tzinfo=timezone.utc)
    rows = [{"chunk_id": 7, "document_id": 3, "vector_id": str(uuid4()), "text": "Eligibility policy",
             "approval_status": "approved", "category": "placement-policy", "company_id": 5,
             "academic_year": "2026-27", "version": 2, "effective_date": effective, "expiry_date": expiry}]

    assert retrieval.index_chunks(rows) == 1
    assert client.collection == "campusai_test"
    assert client.vectors_config.size == 2
    assert client.vectors_config.distance == qm.Distance.COSINE
    assert client.indexes == {
        "approval_status": qm.PayloadSchemaType.KEYWORD,
        "category": qm.PayloadSchemaType.KEYWORD,
        "company_id": qm.PayloadSchemaType.INTEGER,
        "academic_year": qm.PayloadSchemaType.KEYWORD,
        "version": qm.PayloadSchemaType.INTEGER,
        "effective_date": qm.PayloadSchemaType.DATETIME,
        "expiry_date": qm.PayloadSchemaType.DATETIME,
    }
    collection, points, wait = client.upserted
    assert collection == "campusai_test" and wait is True
    assert points[0].id == rows[0]["vector_id"]
    assert points[0].vector == [0.6, 0.8]
    assert points[0].payload == {
        "chunk_id": 7, "document_id": 3, "approval_status": "approved", "category": "placement-policy",
        "company_id": 5, "academic_year": "2026-27", "version": 2,
        "effective_date": effective.isoformat(), "expiry_date": expiry.isoformat(),
    }


def test_qdrant_query_contract_applies_placement_filters(monkeypatch):
    from qdrant_client.http import models as qm

    class FakeQdrant:
        def query_points(self, **kwargs):
            self.request = kwargs
            return SimpleNamespace(points=[SimpleNamespace(payload={"chunk_id": 7}, score=0.82)])

    client = FakeQdrant()
    monkeypatch.setattr(settings, "qdrant_url", "https://qdrant.example.test")
    monkeypatch.setattr(settings, "qdrant_collection", "campusai_test")
    monkeypatch.setattr(retrieval, "qdrant_client", lambda: client)
    monkeypatch.setattr(retrieval, "embed_texts", lambda texts: [[0.6, 0.8]])

    results = retrieval.retrieve_dense("eligibility criteria", limit=5, category="company-eligibility", company_id=5, academic_year="2026-27", version=2)
    assert results == [{"chunk_id": 7, "dense_score": 0.82}]
    request = client.request
    assert request["collection_name"] == "campusai_test"
    assert request["query"] == [0.6, 0.8]
    assert request["limit"] == 5
    assert {condition.key for condition in request["query_filter"].must} == {"approval_status", "category", "company_id", "academic_year", "version"}
    status_condition = next(condition for condition in request["query_filter"].must if condition.key == "approval_status")
    assert status_condition.match == qm.MatchAny(any=["approved"])


def test_qdrant_historical_query_filters_effective_and_expiry_dates(monkeypatch):
    from qdrant_client.http import models as qm

    class FakeQdrant:
        def query_points(self, **kwargs):
            self.request = kwargs
            return SimpleNamespace(points=[])

    client = FakeQdrant()
    monkeypatch.setattr(settings, "qdrant_url", "https://qdrant.example.test")
    monkeypatch.setattr(retrieval, "qdrant_client", lambda: client)
    monkeypatch.setattr(retrieval, "embed_texts", lambda _texts: [[0.6, 0.8]])
    as_of = datetime(2025, 6, 1, tzinfo=timezone.utc)

    assert retrieval.retrieve_dense("historical policy", as_of=as_of) == []
    conditions = client.request["query_filter"].must
    status = next(condition for condition in conditions if isinstance(condition, qm.FieldCondition))
    assert status.key == "approval_status"
    assert status.match == qm.MatchAny(any=["approved", "superseded"])
    effective_filter, expiry_filter = [condition for condition in conditions if isinstance(condition, qm.Filter)]
    effective_range = next(condition for condition in effective_filter.should if isinstance(condition, qm.FieldCondition))
    expiry_range = next(condition for condition in expiry_filter.should if isinstance(condition, qm.FieldCondition))
    assert effective_range.key == "effective_date" and effective_range.range.lte == as_of
    assert expiry_range.key == "expiry_date" and expiry_range.range.gte == as_of


def test_dense_retrieval_gracefully_falls_back_when_qdrant_unavailable(monkeypatch, caplog):
    monkeypatch.setattr(settings, "qdrant_url", "https://unavailable.example.test")
    monkeypatch.setattr(retrieval, "qdrant_client", lambda: (_ for _ in ()).throw(ConnectionError("private endpoint detail")))
    assert retrieval.retrieve_dense("eligibility") == []
    assert "Dense retrieval unavailable; falling back to lexical search (ConnectionError, status=unknown)" in caplog.text
    assert "private endpoint detail" not in caplog.text


def test_hybrid_retrieval_cross_encoder_reranks_bm25_when_qdrant_is_unavailable(monkeypatch):
    candidates = [{"chunk_id": 1, "text": "first"}, {"chunk_id": 2, "text": "second"}]
    reranked = list(reversed(candidates))
    calls = []
    monkeypatch.setattr(retrieval, "retrieve", lambda *_args, **_kwargs: candidates)
    monkeypatch.setattr(retrieval, "retrieve_dense", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(retrieval, "rerank", lambda query, rows: calls.append((query, rows)) or reranked)

    assert retrieval.hybrid_retrieve(None, "placement policy") == reranked
    assert calls == [("placement policy", candidates)]


def test_hybrid_retrieval_preserves_dense_and_reciprocal_rank_scores(db_session, monkeypatch):
    user = User(email="rrf@example.edu", full_name="RRF test", password_hash="unused", role="administrator")
    db_session.add(user)
    db_session.flush()
    document = Document(
        title="RRF policy", category="placement-policy", filename="rrf.txt", storage_path="unused",
        version=1, approval_status="approved", uploaded_by=user.id,
    )
    db_session.add(document)
    db_session.flush()
    chunk = DocumentChunk(document_id=document.id, chunk_index=0, text="Minimum CGPA is 7.5.")
    db_session.add(chunk)
    db_session.flush()
    lexical = [{"chunk_id": chunk.id, "text": chunk.text, "lexical_score": 0.5}]
    dense = [{"chunk_id": chunk.id, "dense_score": 0.9}]
    monkeypatch.setattr(retrieval, "retrieve", lambda *_args, **_kwargs: lexical)
    monkeypatch.setattr(retrieval, "retrieve_dense", lambda *_args, **_kwargs: dense)
    monkeypatch.setattr(retrieval, "rerank", lambda _query, rows: rows)

    results = retrieval.hybrid_retrieve(db_session, "minimum CGPA", limit=5)

    assert len(results) == 1
    assert results[0]["dense_score"] == 0.9
    assert results[0]["rrf_score"] == pytest.approx(2 / 61)


def test_cross_encoder_failure_keeps_candidate_order(monkeypatch, caplog):
    class BrokenCrossEncoder:
        def __init__(self, _model_name):
            pass

        def predict(self, _pairs):
            raise ValueError("private model failure")

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=BrokenCrossEncoder))
    monkeypatch.setattr(settings, "reranker_model", "test/cross-encoder")
    monkeypatch.setattr(retrieval, "_cross_encoder", None)
    candidates = [{"chunk_id": 1, "text": "eligible placement policy"}]

    assert retrieval.rerank("eligibility", candidates) == candidates
    assert "Cross-encoder reranking unavailable" in caplog.text
    assert "private model failure" not in caplog.text


@pytest.mark.parametrize("scores", [[0.9], [float("nan"), 0.1]])
def test_cross_encoder_invalid_scores_keep_all_candidates(monkeypatch, caplog, scores):
    class InvalidCrossEncoder:
        def __init__(self, _model_name):
            pass

        def predict(self, _pairs):
            return scores

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=InvalidCrossEncoder))
    monkeypatch.setattr(settings, "reranker_model", "test/cross-encoder")
    monkeypatch.setattr(retrieval, "_cross_encoder", None)
    candidates = [{"chunk_id": 1, "text": "first"}, {"chunk_id": 2, "text": "second"}]

    assert retrieval.rerank("placement policy", candidates) == candidates
    assert "Cross-encoder reranking unavailable" in caplog.text
