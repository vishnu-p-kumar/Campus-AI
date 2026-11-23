from research.evaluation import answer_validation
from research.evaluation.records import build_result_record


def source(text):
    return {"chunk_id": 1, "document_id": 4, "title": "Policy", "version": 2, "page_number": 3, "text": text}


def test_rag_experiment_abstains_on_numeric_claim_not_supported_by_citation(monkeypatch):
    monkeypatch.setattr(answer_validation.settings, "faithfulness_model", None)
    monkeypatch.setattr(answer_validation, "assess_cited_claims", lambda claims, _sources: claims)
    checked = answer_validation.validate_rag_answer("The minimum CGPA is 9.0 [1].", [source("The minimum CGPA is 7.5.")])
    assert checked["abstained"] is True
    assert checked["cited_source_numbers"] == []
    assert checked["claim_support"][0]["unsupported_numeric_claims"] == ["9.0"]


def test_rag_experiment_keeps_supported_answer_and_strips_invalid_citation(monkeypatch):
    monkeypatch.setattr(answer_validation.settings, "faithfulness_model", None)
    monkeypatch.setattr(answer_validation, "assess_cited_claims", lambda claims, _sources: claims)
    supported = answer_validation.validate_rag_answer("The minimum CGPA is 7.5 [1].",
                                                       [source("The minimum CGPA is 7.5.")])
    assert supported["abstained"] is False
    assert supported["cited_source_numbers"] == [1]
    assert supported["semantic_verifier_status"] == "disabled"
    assert supported["answer"].endswith("[1].")

    invalid = answer_validation.validate_rag_answer("The minimum CGPA is 7.5 [9].",
                                                     [source("The minimum CGPA is 7.5.")])
    assert invalid["abstained"] is True
    assert invalid["cited_source_numbers"] == []


def test_rag_experiment_fails_closed_on_nli_rejection_and_verifier_error(monkeypatch):
    claim = "The office is in the library [1]."
    monkeypatch.setattr(answer_validation.settings, "faithfulness_model", "test/multilingual-nli")
    monkeypatch.setattr(answer_validation, "assess_cited_claims",
                        lambda claims, _sources: [{**item, "semantic_support": True} for item in claims])
    passed = answer_validation.validate_rag_answer(claim, [source("The office is in the main building.")])
    assert passed["abstained"] is False
    assert passed["semantic_verifier_status"] == "passed"

    monkeypatch.setattr(answer_validation, "assess_cited_claims",
                        lambda claims, _sources: [{**item, "semantic_support": False} for item in claims])
    rejected = answer_validation.validate_rag_answer(claim, [source("The office is in the main building.")])
    assert rejected["abstained"] is True
    assert rejected["semantic_verifier_status"] == "passed"
    assert rejected["cited_source_numbers"] == []

    monkeypatch.setattr(answer_validation, "assess_cited_claims",
                        lambda *_args: (_ for _ in ()).throw(RuntimeError("model unavailable")))
    failed = answer_validation.validate_rag_answer(claim, [source("The office is in the main building.")])
    assert failed["abstained"] is True
    assert failed["claim_support"] == []
    assert failed["semantic_verifier_status"] == "failed"
    assert "model unavailable" not in failed["answer"]


def test_configured_verifier_is_not_loaded_when_answer_has_no_claims(monkeypatch):
    monkeypatch.setattr(answer_validation.settings, "faithfulness_model", "test/multilingual-nli")
    monkeypatch.setattr(answer_validation, "assess_cited_claims",
                        lambda *_args: (_ for _ in ()).throw(AssertionError("no claim should skip inference")))
    checked = answer_validation.validate_rag_answer("", [source("Some evidence.")])
    assert checked["abstained"] is True
    assert checked["semantic_verifier_status"] == "no_claims"


def test_research_record_contains_only_sources_cited_in_the_answer():
    sources = [source("First source"), {**source("Second source"), "document_id": 5, "page_number": 8}]
    record = build_result_record(
        item={"question_id": "q1", "question": "Where is it?", "relevant_chunk_ids": [1], "expected_abstain": False},
        system="bm25_rag", answer="A cited answer.", sources=sources, evidence={"score": .8},
        citation_coverage=1, abstained=False, retrieval_latency_ms=1, total_latency_ms=2,
        token_count=5, model_id="test", retrieval_model_id="BM25", dataset_name="test",
        cited_source_numbers=[2], claim_support=[],
    )
    assert record["citations"] == [{"citation": 2, "document_id": 5, "title": "Policy", "version": 2, "page": 8}]
