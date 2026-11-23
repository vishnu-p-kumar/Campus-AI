"""Privacy-conscious cohort diagnostics for reviewed binary decisions.

This produces descriptive error-rate comparisons. It is not a legal fairness test,
does not validate label quality, and must not be used to rank or screen students.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _binary(value: Any, field: str, row_number: int) -> bool:
    if type(value) is not bool:
        raise ValueError(f"Record {row_number}: {field} must be a JSON boolean")
    return value


def summarize_cohorts(records: list[dict], *, minimum_group_size: int = 5) -> dict:
    if minimum_group_size < 2:
        raise ValueError("minimum_group_size must be at least 2")
    groups: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    overall: list[tuple[bool, bool]] = []
    for number, row in enumerate(records, start=1):
        label = row.get("cohort")
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f"Record {number}: cohort must be a non-empty string")
        predicted = _binary(row.get("predicted_positive"), "predicted_positive", number)
        actual = _binary(row.get("actual_positive"), "actual_positive", number)
        pair = (predicted, actual)
        groups[label.strip()].append(pair)
        overall.append(pair)

    def rates(items: list[tuple[bool, bool]]) -> dict:
        count = len(items)
        tp = sum(predicted and actual for predicted, actual in items)
        fp = sum(predicted and not actual for predicted, actual in items)
        tn = sum(not predicted and not actual for predicted, actual in items)
        fn = sum(not predicted and actual for predicted, actual in items)
        positives = tp + fn
        negatives = fp + tn
        return {
            "n": count,
            "selection_rate": sum(predicted for predicted, _ in items) / count,
            "true_positive_rate": tp / positives if positives else None,
            "false_positive_rate": fp / negatives if negatives else None,
            "accuracy": (tp + tn) / count,
            "confusion": {"true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn},
        }

    visible = {label: rates(items) for label, items in sorted(groups.items()) if len(items) >= minimum_group_size}
    hidden_count = sum(len(items) < minimum_group_size for items in groups.values())
    selection_rates = [item["selection_rate"] for item in visible.values()]
    return {
        "overall": rates(overall) if overall else None,
        "groups": visible,
        "suppressed_group_count": hidden_count,
        "minimum_group_size": minimum_group_size,
        "visible_selection_rate_range": (max(selection_rates) - min(selection_rates)) if len(selection_rates) >= 2 else None,
        "interpretation": "Descriptive diagnostic only. Review label quality, context and error causes with humans; do not use as a fairness certification or student ranking signal.",
    }
