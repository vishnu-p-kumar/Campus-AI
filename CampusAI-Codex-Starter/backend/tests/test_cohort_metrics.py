import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from research.evaluation.cohort_metrics import summarize_cohorts


def test_cohort_metrics_report_error_rates_and_suppress_small_groups():
    rows = [
        {"cohort": "Group A", "predicted_positive": True, "actual_positive": True},
        {"cohort": "Group A", "predicted_positive": True, "actual_positive": False},
        {"cohort": "Group A", "predicted_positive": False, "actual_positive": True},
        {"cohort": "Group A", "predicted_positive": False, "actual_positive": False},
        {"cohort": "Group A", "predicted_positive": True, "actual_positive": True},
        {"cohort": "Small cohort", "predicted_positive": True, "actual_positive": False},
    ]
    report = summarize_cohorts(rows, minimum_group_size=5)
    assert set(report["groups"]) == {"Group A"}
    assert report["suppressed_group_count"] == 1
    assert report["groups"]["Group A"]["selection_rate"] == pytest.approx(3 / 5)
    assert report["groups"]["Group A"]["true_positive_rate"] == pytest.approx(2 / 3)
    assert report["groups"]["Group A"]["false_positive_rate"] == pytest.approx(1 / 2)
    assert report["visible_selection_rate_range"] is None
    assert "not use as a fairness certification" in report["interpretation"]


def test_cohort_metrics_validate_labels_and_minimum_size():
    with pytest.raises(ValueError, match="JSON boolean"):
        summarize_cohorts([{"cohort": "A", "predicted_positive": 1, "actual_positive": True}])
    with pytest.raises(ValueError, match="at least 2"):
        summarize_cohorts([], minimum_group_size=1)
