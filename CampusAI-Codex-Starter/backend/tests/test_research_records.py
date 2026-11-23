import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.evaluation.records import build_result_record, estimate_cost_usd
from app.evaluation.metrics import summarize


def test_gemini_experiment_record_retains_ground_truth_for_retrieval_metrics():
    record = build_result_record(
        item={"question_id": "q1", "question": "What CGPA is required?", "relevant_chunk_ids": [4],
              "expected_abstain": False, "annotation": {"answer_correct": True}},
        system="bm25_rag", answer="At least 7 CGPA [1].",
        sources=[{"chunk_id": 4, "document_id": 9, "title": "Eligibility", "version": 1, "page_number": 2}],
        evidence={"score": 0.8}, citation_coverage=1.0, abstained=False, retrieval_latency_ms=4,
        total_latency_ms=40, token_count=20, model_id="gemini-test", retrieval_model_id="BM25",
        dataset_name="pilot", input_token_count=15, output_token_count=5,
        estimated_cost_usd=0.00002, input_cost_per_million_usd=1.0, output_cost_per_million_usd=1.0,
    )
    report = summarize([record], k=1)
    assert record["relevant_chunk_ids"] == [4]
    assert report["precision@1"] == 1
    assert report["recall@1"] == 1
    assert report["mrr"] == 1
    assert report["answer_correctness"] == 1
    assert report["input_token_count"] == 15
    assert report["output_token_count"] == 5
    assert record["estimated_cost_usd"] == 0.00002
    assert record["dataset_name"] == "pilot"


def test_unverified_gemini_baseline_is_excluded_from_evidence_score_calibration():
    record = build_result_record(
        item={"question_id": "q-baseline", "question": "What is the placement policy?", "relevant_chunk_ids": [],
              "expected_abstain": False},
        system="gemini_only", answer="Institution-specific details are unverified.", sources=[],
        evidence={"label": "unverified"}, citation_coverage=0.0, abstained=False,
        retrieval_latency_ms=0, total_latency_ms=5, token_count=8, model_id="gemini-test",
        retrieval_model_id="none", dataset_name="pilot",
    )
    report = summarize([record])
    assert report["evidence_label_count"] == 0
    assert report["raw_evidence_score_brier"] is None


def test_cost_estimate_requires_token_usage_and_operator_rates():
    assert estimate_cost_usd({"input_token_count": 1_000_000, "output_token_count": 500_000}, 2.0, 4.0) == 4.0
    assert estimate_cost_usd({"input_token_count": 1_000_000}, 2.0, 4.0) is None
    assert estimate_cost_usd({"input_token_count": 1_000_000, "output_token_count": 500_000}, None, None) is None


def test_research_metrics_are_reported_by_language_without_merging_labels():
    hindi = build_result_record(
        item={"question_id": "hi-1", "question": "पात्रता क्या है?", "language": "hi",
              "relevant_chunk_ids": [4], "expected_abstain": False},
        system="bm25_rag", answer="उपलब्ध स्रोत के अनुसार।", sources=[
            {"chunk_id": 4, "document_id": 9, "title": "नियम", "version": 1, "page_number": 1}
        ], evidence={"score": 0.8}, citation_coverage=1.0, abstained=False,
        retrieval_latency_ms=5, total_latency_ms=20, token_count=None,
        model_id="test", retrieval_model_id="BM25", dataset_name="multilingual",
    )
    kannada = build_result_record(
        item={"question_id": "kn-1", "question": "ಅರ್ಹತೆ ಏನು?", "language": "kn",
              "relevant_chunk_ids": [8], "expected_abstain": True},
        system="bm25_rag", answer="ಸಾಕಷ್ಟು ಸಾಕ್ಷ್ಯವಿಲ್ಲ.", sources=[],
        evidence={"score": 0.0}, citation_coverage=0.0, abstained=True,
        retrieval_latency_ms=7, total_latency_ms=24, token_count=None,
        model_id="test", retrieval_model_id="BM25", dataset_name="multilingual",
    )

    report = summarize([hindi, kannada], k=1)

    assert hindi["language"] == "hi"
    assert kannada["language"] == "kn"
    assert report["language_metrics"]["hi"]["precision@1"] == 1
    assert report["language_metrics"]["hi"]["abstention_recall"] == 0
    assert report["language_metrics"]["kn"]["precision@1"] == 0
    assert report["language_metrics"]["kn"]["abstention_recall"] == 1
    assert report["language_metrics"]["kn"]["annotated_questions"] == 0
