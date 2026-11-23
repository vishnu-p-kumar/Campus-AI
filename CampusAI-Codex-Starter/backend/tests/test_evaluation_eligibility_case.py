import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from research.evaluation.eligibility_case import predict_eligibility


def test_eligibility_case_uses_same_deterministic_engine():
    case = {
        "source_approved": True,
        "student": {"cgpa": 8.0, "branch": "CSE", "graduation_year": 2027,
                    "active_backlogs": 0, "historical_backlogs": 0, "technical_skills": ["Python"]},
        "requirements": {"min_cgpa": 7.0, "eligible_branches": ["CSE"], "graduation_years": [2027],
                         "max_active_backlogs": 0, "max_historical_backlogs": 1, "required_skills": ["Python"],
                         "criteria_reviewed": True, "source_document_id": 17, "rule_version": 1},
    }
    assert predict_eligibility(case) == "eligible"
    case["source_approved"] = False
    assert predict_eligibility(case) == "needs_manual_verification"


def test_eligibility_case_requires_explicit_source_review_state():
    with pytest.raises(ValueError, match="source_approved"):
        predict_eligibility({"student": {}, "requirements": {}})
