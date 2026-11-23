import json
import sys

import pytest

from research.evaluation.dataset import load_dataset
from research.evaluation import run_experiment
from research.evaluation.eligibility_case import predict_eligibility


def row(**overrides):
    value = {
        "question_id": "q1",
        "question": "What is the policy?",
        "relevant_chunk_ids": [3],
        "expected_abstain": False,
    }
    return {**value, **overrides}


def test_dataset_preflight_normalizes_rfc3339_and_eligibility_defaults(tmp_path):
    value = row(
        as_of="2024-01-01T00:00:00Z",
        eligibility_case={
            "source_approved": True,
            "student": {},
            "requirements": {"criteria_reviewed": True, "source_document_id": 12},
        },
    )
    path = tmp_path / "dataset.jsonl"
    path.write_text(json.dumps(value), encoding="utf-8")

    [parsed] = load_dataset(path)
    assert parsed["as_of"] == "2024-01-01T00:00:00Z"
    assert parsed["language"] == "en"
    assert parsed["eligibility_case"]["student"]["technical_skills"] == []
    assert parsed["eligibility_case"]["student"]["cgpa"] is None
    assert predict_eligibility(parsed["eligibility_case"]) == "eligible"


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (row(expected_abstain="false"), "expected_abstain"),
        (row(language="fr"), "language"),
        (row(as_of="2024-01-01T00:00:00"), "timezone"),
        (row(as_of="2024-01-01 00:00:00+00:00"), "RFC3339"),
        (row(unrecognized_field=True), "unrecognized_field"),
        (row(relevant_chunk_ids=[0]), "relevant_chunk_ids"),
    ],
)
def test_dataset_preflight_rejects_invalid_rows_without_echoing_questions(tmp_path, item, message):
    path = tmp_path / "dataset.jsonl"
    path.write_text(json.dumps(item), encoding="utf-8")
    with pytest.raises(ValueError) as error:
        load_dataset(path)
    assert "Dataset line 1" in str(error.value)
    assert message in str(error.value)
    assert item["question"] not in str(error.value)


def test_dataset_preflight_rejects_duplicate_question_ids(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text("\n".join(json.dumps(row()) for _ in range(2)), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicates a prior question_id"):
        load_dataset(path)


def test_dataset_preflight_rejects_empty_datasets(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n  \n", encoding="utf-8")
    with pytest.raises(ValueError, match="contains no question records"):
        load_dataset(path)


def test_dataset_preflight_rejects_nonfinite_scores_and_invalid_source_ids(tmp_path):
    items = [
        row(eligibility_case={
            "source_approved": True, "student": {"cgpa": float("nan")},
            "requirements": {"criteria_reviewed": True, "source_document_id": 12},
        }),
        row(eligibility_case={
            "source_approved": True, "student": {},
            "requirements": {"criteria_reviewed": True, "source_document_id": 0},
        }),
    ]
    for item in items:
        path = tmp_path / "bad.jsonl"
        path.write_text(json.dumps(item), encoding="utf-8")
        with pytest.raises(ValueError, match="Dataset line 1"):
            load_dataset(path)


def test_cli_validates_dataset_before_credentials_or_provider_client(tmp_path, monkeypatch):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row(expected_abstain="no")), encoding="utf-8")
    monkeypatch.setattr(run_experiment.settings, "gemini_chat_api_key", None)
    monkeypatch.setattr(run_experiment.genai, "Client",
                        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("provider must not initialize")))
    monkeypatch.setattr(sys, "argv", ["run_experiment.py", str(path), "--output", str(tmp_path / "out.jsonl")])
    with pytest.raises(SystemExit, match="Dataset line 1"):
        run_experiment.run()
