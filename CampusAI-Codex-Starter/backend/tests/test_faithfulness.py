import pytest

from app.ai import faithfulness
from app.core.config import settings


def test_optional_verifier_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "faithfulness_model", None)
    assert faithfulness.assess_cited_claims([{"sentence": 1}], []) == [{"sentence": 1}]


def test_nli_checks_cited_evidence_and_returns_entailment_scores(monkeypatch):
    class Config:
        id2label = {0: "contradiction", 1: "neutral", 2: "entailment"}

    class Model:
        model = type("Inner", (), {"config": Config()})()

        def predict(self, pairs, **_kwargs):
            assert pairs == [("The minimum CGPA is 6.0.", "Students need a minimum CGPA of 6.0.")]
            return [[0.1, 0.2, 4.0]]

    monkeypatch.setattr(settings, "faithfulness_model", "test/multilingual-nli")
    monkeypatch.setattr(settings, "faithfulness_min_entailment", 0.7)
    monkeypatch.setattr(faithfulness, "_model_and_labels", lambda: (Model(), {0: "contradiction", 1: "neutral", 2: "entailment"}))
    result = faithfulness.assess_cited_claims(
        [{"sentence": 1, "text": "Students need a minimum CGPA of 6.0.", "citation_numbers": [1]}],
        [{"text": "The minimum CGPA is 6.0."}],
    )
    assert result[0]["semantic_support"] is True
    assert result[0]["entailment_score"] > result[0]["contradiction_score"]


def test_verifier_rejects_model_without_explicit_nli_label_map(monkeypatch):
    class Model:
        model = type("Inner", (), {"config": object()})()

    monkeypatch.setattr(settings, "faithfulness_model", "test/no-label-map")
    monkeypatch.setattr(faithfulness, "_model_and_labels", lambda: (Model(), {}))
    # A broken/misconfigured model cannot be silently interpreted as a pass.
    claims = [{"sentence": 1, "text": "Claim", "citation_numbers": [1]}]
    monkeypatch.setattr(faithfulness, "_model_and_labels", lambda: (_ for _ in ()).throw(RuntimeError("bad label map")))
    with pytest.raises(RuntimeError):
        faithfulness.assess_cited_claims(claims, [{"text": "Evidence"}])
