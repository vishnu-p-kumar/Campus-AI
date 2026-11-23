"""Run the deterministic placement engine on a de-identified labelled case."""
from types import SimpleNamespace

from app.eligibility.engine import evaluate_eligibility


def predict_eligibility(case: dict | None) -> str | None:
    if case is None:
        return None
    if not isinstance(case, dict) or not isinstance(case.get("student"), dict) or not isinstance(case.get("requirements"), dict):
        raise ValueError("eligibility_case must contain student and requirements objects")
    if type(case.get("source_approved")) is not bool:
        raise ValueError("eligibility_case.source_approved must be a boolean")
    student = SimpleNamespace(**case["student"])
    rule = SimpleNamespace(**case["requirements"])
    return evaluate_eligibility(student, rule, source_approved=case["source_approved"]).decision
