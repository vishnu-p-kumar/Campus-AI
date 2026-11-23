import pytest
from pydantic import ValidationError

from app.evaluation.metrics import evidence_calibration, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank, summarize
from app.schemas import EvaluationQuestionInput


def test_retrieval_metrics():
    retrieved, relevant = [8, 3, 5], {3, 5}
    assert precision_at_k(retrieved, relevant, 3) == 2 / 3
    assert recall_at_k(retrieved, relevant, 3) == 1
    assert reciprocal_rank(retrieved, relevant) == 0.5
    assert 0 < ndcg_at_k(retrieved, relevant, 3) <= 1


def test_answer_metrics_remain_null_without_human_annotations():
    report = summarize([{"retrieved_chunk_ids": [], "relevant_chunk_ids": [], "expected_abstain": True, "predicted_abstain": True}])
    assert report["answer_correctness"] is None
    assert report["faithfulness"] is None
    assert report["citation_correctness"] is None
    assert report["abstention_recall"] == 1
    assert report["eligibility_accuracy"] is None
    assert report["false_eligibility_rate"] is None
    assert report["historical_retrieval_accuracy"] is None


def test_abstention_metrics_remain_null_when_expected_labels_are_missing():
    report = summarize([{"retrieved_chunk_ids": [], "predicted_abstain": True}])
    assert report["abstention_precision"] is None
    assert report["abstention_recall"] is None
    assert report["evidence_label_count"] == 0


def test_labelled_temporal_and_eligibility_error_metrics():
    report = summarize([
        {"predicted_eligibility": "eligible", "annotation": {
            "eligibility_actual": "eligible", "current_policy_correct": True,
            "historical_retrieval_correct": True, "version_identification_correct": False,
            "outdated_warning_correct": True, "conflict_detection_correct": False,
        }},
        {"predicted_eligibility": "eligible", "annotation": {"eligibility_actual": "not_eligible"}},
        {"predicted_eligibility": "needs_manual_verification", "annotation": {"eligibility_actual": "eligible"}},
    ])
    assert report["eligibility_accuracy"] == 1 / 3
    assert report["false_eligibility_rate"] == 1
    assert report["false_ineligibility_rate"] == 1 / 2
    assert report["current_policy_accuracy"] == 1
    assert report["historical_retrieval_accuracy"] == 1
    assert report["version_identification_accuracy"] == 0
    assert report["outdated_warning_accuracy"] == 1
    assert report["conflict_detection_accuracy"] == 0


def test_raw_evidence_score_calibration_reports_reliability_and_threshold_curve():
    rows = [
        {"confidence_features": {"score": 0.9}, "expected_abstain": False},
        {"confidence_features": {"score": 0.8}, "expected_abstain": True},
        {"confidence_features": {"score": 0.2}, "expected_abstain": True},
        {"confidence_features": {"score": 0.3}, "expected_abstain": False},
    ]
    report = evidence_calibration(rows, bins=2, minimum_examples=4)
    assert report["raw_score_brier"] == pytest.approx(0.295)
    assert report["raw_score_ece"] == pytest.approx(0.3)
    assert report["labeled_questions"] == 4
    assert report["candidate_threshold"]["minimum_evidence_score"] == 0.9
    assert report["threshold_curve"][5] == {"threshold": 0.5, "answered": 2, "coverage": 0.5, "unsafe_answer_rate": 0.5}


def test_calibration_does_not_recommend_cutoff_before_minimum_reviewed_sample():
    rows = [{"confidence_features": {"score": 0.8}, "expected_abstain": False} for _ in range(29)]
    report = evidence_calibration(rows)
    assert report["labeled_questions"] == 29
    assert report["candidate_threshold"] is None


def test_unreviewed_or_invalid_scores_do_not_enter_calibration():
    report = evidence_calibration([
        {"confidence_features": {"score": 0.7}},
        {"confidence_features": {"score": float("nan")}, "expected_abstain": False},
        {"confidence_features": {"score": 1.1}, "expected_abstain": True},
    ])
    assert report["labeled_questions"] == 0
    assert report["raw_score_brier"] is None
    assert report["candidate_threshold"] is None


def test_evaluation_summary_reports_one_active_cutoff_and_marks_mixed_runs():
    rows = [
        {"confidence_features": {"score": 0.8, "minimum_score_threshold": 0.35}, "expected_abstain": False},
        {"confidence_features": {"score": 0.4, "minimum_score_threshold": 0.35}, "expected_abstain": True},
    ]
    report = summarize(rows)
    assert report["applied_evidence_threshold"] == 0.35
    assert report["evidence_threshold_values"] == [0.35]

    rows[1]["confidence_features"]["minimum_score_threshold"] = 0.5
    mixed = summarize(rows)
    assert mixed["applied_evidence_threshold"] is None
    assert mixed["evidence_threshold_values"] == [0.35, 0.5]


def test_evaluation_question_requires_a_human_abstention_label():
    with pytest.raises(ValidationError):
        EvaluationQuestionInput(question_id="unlabelled", question="Should the assistant answer?", relevant_chunk_ids=[])


def test_evaluation_question_validates_supported_language_codes():
    question = EvaluationQuestionInput(question_id="hi-q", question="पात्रता क्या है?", language="hi",
                                       expected_abstain=False)
    assert question.language == "hi"
    with pytest.raises(ValidationError):
        EvaluationQuestionInput(question_id="xx-q", question="Question?", language="xx", expected_abstain=False)


def test_retrieval_evaluation_counts_no_evidence_as_predicted_abstention(client, db_session, monkeypatch):
    from app.api import evaluation as evaluation_api
    from app.models import User
    from app.security import hash_password

    admin = User(email="evaluation-admin@example.edu", full_name="Evaluation Admin",
                 password_hash=hash_password("evaluation-admin-password"), role="administrator")
    db_session.add(admin)
    db_session.commit()
    login = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "evaluation-admin-password"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    monkeypatch.setattr(evaluation_api, "hybrid_retrieve", lambda *_args, **_kwargs: [])

    result = client.post("/api/v1/evaluation/runs", headers=headers, json={
        "name": "No evidence test", "dataset_name": "manual labels",
        "questions": [{"question_id": "q-no-source", "question": "What is this unknown policy?", "language": "kn",
                       "relevant_chunk_ids": [], "expected_abstain": True}],
    })
    assert result.status_code == 201, result.text
    metrics = result.json()["metrics"]
    assert metrics["abstention_recall"] == 1
    assert metrics["raw_evidence_score_brier"] == 0
    assert metrics["applied_evidence_threshold"] == 0.35
    assert metrics["evidence_label_count"] == 1
    assert metrics["language_metrics"]["kn"]["abstention_recall"] == 1


def test_retrieval_evaluation_counts_partial_evidence_as_predicted_abstention(client, db_session, monkeypatch):
    from app.api import evaluation as evaluation_api
    from app.models import User
    from app.security import hash_password

    admin = User(email="partial-evaluation-admin@example.edu", full_name="Evaluation Admin",
                 password_hash=hash_password("partial-evaluation-password"), role="administrator")
    db_session.add(admin)
    db_session.commit()
    login = client.post("/api/v1/auth/login", json={"email": admin.email, "password": "partial-evaluation-password"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    monkeypatch.setattr(evaluation_api, "hybrid_retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(evaluation_api, "confidence_features", lambda *_args, **_kwargs: {
        "score": 0.5, "label": "partial", "coverage": 0.5, "minimum_score_threshold": 0.35,
    })

    response = client.post("/api/v1/evaluation/runs", headers=headers, json={
        "name": "Partial evidence gate test", "dataset_name": "manual labels",
        "questions": [{"question_id": "partial", "question": "What is the policy?", "language": "en",
                       "relevant_chunk_ids": [], "expected_abstain": True}],
    })
    assert response.status_code == 201, response.text
    assert response.json()["metrics"]["abstention_recall"] == 1
    assert response.json()["metrics"]["raw_evidence_score_brier"] == 0.25
