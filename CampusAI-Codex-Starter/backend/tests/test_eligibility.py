from types import SimpleNamespace

from app.eligibility.engine import evaluate_eligibility


def make_student(**overrides):
    values = {"cgpa": 8.2, "branch": "Computer Science", "graduation_year": 2027, "technical_skills": ["Python"],
              "active_backlogs": 0, "historical_backlogs": 0}
    values.update(overrides)
    return SimpleNamespace(**values)


def make_rule(**overrides):
    values = {"min_cgpa": 7.5, "eligible_branches": ["Computer Science"], "graduation_years": [2027],
              "max_active_backlogs": 0, "max_historical_backlogs": 1, "rule_version": 2,
              "source_document_id": 42, "criteria_reviewed": True, "required_skills": ["Python"]}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_eligible_and_source_linked():
    result = evaluate_eligibility(make_student(), make_rule(), source_approved=True)
    assert result.decision == "eligible"
    assert result.source_document_id == 42


def test_ineligible_reasons_are_deterministic():
    result = evaluate_eligibility(make_student(cgpa=6.9), make_rule(), source_approved=True)
    assert result.decision == "not_eligible"
    assert any("CGPA" in reason for reason in result.reasons)


def test_incomplete_policy_requires_manual_review():
    result = evaluate_eligibility(make_student(), make_rule(criteria_reviewed=False), source_approved=True)
    assert result.decision == "needs_manual_verification"
    assert "approved source-linked eligibility criteria" in result.missing_fields


def test_unapproved_or_missing_source_cannot_produce_eligibility_decision():
    result = evaluate_eligibility(make_student(), make_rule(), source_approved=False)
    assert result.decision == "needs_manual_verification"
    assert "approved source-linked eligibility criteria" in result.missing_fields
