from math import isfinite, log2


def precision_at_k(retrieved: list[int], relevant: set[int], k: int = 5) -> float:
    return sum(item in relevant for item in retrieved[:k]) / k if k else 0.0


def recall_at_k(retrieved: list[int], relevant: set[int], k: int = 5) -> float:
    return sum(item in relevant for item in retrieved[:k]) / len(relevant) if relevant else 0.0


def reciprocal_rank(retrieved: list[int], relevant: set[int]) -> float:
    return next((1 / rank for rank, item in enumerate(retrieved, start=1) if item in relevant), 0.0)


def ndcg_at_k(retrieved: list[int], relevant: set[int], k: int = 5) -> float:
    dcg = sum(1 / log2(rank + 1) for rank, item in enumerate(retrieved[:k], start=1) if item in relevant)
    ideal = sum(1 / log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _annotation_mean(rows: list[dict], key: str) -> float | None:
    return mean([float(row["annotation"][key]) for row in rows
                 if row.get("annotation") and key in row["annotation"]])


def _configured_evidence_thresholds(records: list[dict]) -> list[float]:
    values = set()
    for row in records:
        value = (row.get("confidence_features") or {}).get("minimum_score_threshold")
        if isinstance(value, bool):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(value) and 0 <= value <= 1:
            values.add(round(value, 6))
    return sorted(values)


def evidence_calibration(records: list[dict], bins: int = 5, minimum_examples: int = 30,
                         maximum_unsafe_answer_rate: float = 0.05) -> dict:
    """Report how raw evidence scores relate to manual answerability labels.

    The retrieval score is a feature, not a probability. Reliability metrics are
    diagnostics; a candidate cutoff is only emitted with enough reviewed labels.
    """
    rows = []
    for row in records:
        expected_abstain = row.get("expected_abstain")
        features = row.get("confidence_features") or {}
        score = features.get("score", row.get("evidence_score"))
        if not isinstance(expected_abstain, bool) or isinstance(score, bool):
            continue
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        if not isfinite(score) or not 0 <= score <= 1:
            continue
        rows.append((score, not expected_abstain))

    count = len(rows)
    if not count:
        return {"labeled_questions": 0, "raw_score_brier": None, "raw_score_ece": None,
                "reliability_bins": [], "threshold_curve": [], "candidate_threshold": None,
                "threshold_target_unsafe_answer_rate": maximum_unsafe_answer_rate,
                "minimum_examples_for_candidate": minimum_examples}

    brier = sum((score - float(answerable)) ** 2 for score, answerable in rows) / count
    reliability_bins = []
    ece = 0.0
    for index in range(bins):
        lower, upper = index / bins, (index + 1) / bins
        members = [(score, answerable) for score, answerable in rows
                   if lower <= score and (score < upper or index == bins - 1 and score <= upper)]
        if not members:
            continue
        mean_score = sum(score for score, _ in members) / len(members)
        observed_answerable = sum(answerable for _, answerable in members) / len(members)
        ece += len(members) / count * abs(mean_score - observed_answerable)
        reliability_bins.append({"lower": lower, "upper": upper, "count": len(members),
                                 "mean_score": round(mean_score, 4),
                                 "observed_answerable_rate": round(observed_answerable, 4)})

    curve = []
    for step in range(11):
        threshold = step / 10
        answered = [answerable for score, answerable in rows if score >= threshold]
        curve.append({"threshold": threshold, "answered": len(answered), "coverage": round(len(answered) / count, 4),
                      "unsafe_answer_rate": round(sum(not answerable for answerable in answered) / len(answered), 4) if answered else None})

    candidate = None
    if count >= minimum_examples:
        thresholds = sorted({score for score, _ in rows} | {0.0, 1.0})
        for threshold in thresholds:
            answered = [answerable for score, answerable in rows if score >= threshold]
            if answered and sum(not answerable for answerable in answered) / len(answered) <= maximum_unsafe_answer_rate:
                candidate = {"minimum_evidence_score": round(threshold, 4),
                             "coverage_on_reviewed_set": round(len(answered) / count, 4)}
                break

    return {"labeled_questions": count, "raw_score_brier": round(brier, 6),
            "raw_score_ece": round(ece, 6), "reliability_bins": reliability_bins,
            "threshold_curve": curve, "candidate_threshold": candidate,
            "threshold_target_unsafe_answer_rate": maximum_unsafe_answer_rate,
            "minimum_examples_for_candidate": minimum_examples}


def _summarize_metrics(records: list[dict], k: int = 5) -> dict:
    annotated = [row for row in records if row.get("annotation")]
    abstention_labels = [(row["expected_abstain"], row["predicted_abstain"]) for row in records
                         if isinstance(row.get("expected_abstain"), bool) and isinstance(row.get("predicted_abstain"), bool)]
    expected = [label[0] for label in abstention_labels]
    predicted = [label[1] for label in abstention_labels]
    tp = sum(a and b for a, b in zip(expected, predicted))
    fp = sum((not a) and b for a, b in zip(expected, predicted))
    fn = sum(a and (not b) for a, b in zip(expected, predicted))
    eligibility_rows = [
        (row["predicted_eligibility"], row["annotation"]["eligibility_actual"])
        for row in records if row.get("predicted_eligibility") in {"eligible", "not_eligible", "needs_manual_verification"}
        and row.get("annotation") and row["annotation"].get("eligibility_actual") in {"eligible", "not_eligible", "needs_manual_verification"}
    ]
    binary_eligibility_rows = [(predicted, actual) for predicted, actual in eligibility_rows if actual in {"eligible", "not_eligible"}]
    eligible_actual = [(predicted, actual) for predicted, actual in binary_eligibility_rows if actual == "eligible"]
    ineligible_actual = [(predicted, actual) for predicted, actual in binary_eligibility_rows if actual == "not_eligible"]
    false_eligible = sum(predicted == "eligible" for predicted, _ in ineligible_actual)
    false_ineligible = sum(predicted != "eligible" for predicted, _ in eligible_actual)
    calibration = evidence_calibration(records)
    evidence_thresholds = _configured_evidence_thresholds(records)
    return {
        "question_count": len(records),
        f"precision@{k}": mean([precision_at_k(row.get("retrieved_chunk_ids", []), set(row.get("relevant_chunk_ids", [])), k) for row in records]),
        f"recall@{k}": mean([recall_at_k(row.get("retrieved_chunk_ids", []), set(row.get("relevant_chunk_ids", [])), k) for row in records if row.get("relevant_chunk_ids")]),
        "mrr": mean([reciprocal_rank(row.get("retrieved_chunk_ids", []), set(row.get("relevant_chunk_ids", []))) for row in records if row.get("relevant_chunk_ids")]),
        f"ndcg@{k}": mean([ndcg_at_k(row.get("retrieved_chunk_ids", []), set(row.get("relevant_chunk_ids", [])), k) for row in records if row.get("relevant_chunk_ids")]),
        "answer_correctness": mean([float(row["annotation"]["answer_correct"]) for row in annotated if "answer_correct" in row["annotation"]]),
        "faithfulness": mean([float(row["annotation"]["faithful"]) for row in annotated if "faithful" in row["annotation"]]),
        "citation_correctness": mean([float(row["annotation"]["citation_correct"]) for row in annotated if "citation_correct" in row["annotation"]]),
        "unsupported_claim_rate": mean([float(row["annotation"].get("unsupported_claims", 0) > 0) for row in annotated if "unsupported_claims" in row["annotation"]]),
        "temporal_accuracy": _annotation_mean(annotated, "temporal_correct"),
        "current_policy_accuracy": _annotation_mean(annotated, "current_policy_correct"),
        "historical_retrieval_accuracy": _annotation_mean(annotated, "historical_retrieval_correct"),
        "version_identification_accuracy": _annotation_mean(annotated, "version_identification_correct"),
        "outdated_warning_accuracy": _annotation_mean(annotated, "outdated_warning_correct"),
        "conflict_detection_accuracy": _annotation_mean(annotated, "conflict_detection_correct"),
        "eligibility_accuracy": mean([float(predicted == actual) for predicted, actual in eligibility_rows]),
        "false_eligibility_rate": false_eligible / len(ineligible_actual) if ineligible_actual else None,
        "false_ineligibility_rate": false_ineligible / len(eligible_actual) if eligible_actual else None,
        "abstention_precision": tp / (tp + fp) if tp + fp else 0.0 if abstention_labels else None,
        "abstention_recall": tp / (tp + fn) if tp + fn else 0.0 if abstention_labels else None,
        "raw_evidence_score_brier": calibration["raw_score_brier"],
        "raw_evidence_score_ece": calibration["raw_score_ece"],
        "evidence_label_count": calibration["labeled_questions"],
        "candidate_evidence_threshold": (calibration["candidate_threshold"] or {}).get("minimum_evidence_score"),
        "applied_evidence_threshold": evidence_thresholds[0] if len(evidence_thresholds) == 1 else None,
        "evidence_threshold_values": evidence_thresholds,
        "evidence_calibration": calibration,
        "retrieval_latency_ms": mean([float(row["retrieval_latency_ms"]) for row in records if "retrieval_latency_ms" in row]),
        "total_latency_ms": mean([float(row["total_latency_ms"]) for row in records if "total_latency_ms" in row]),
        "token_count": mean([float(row["token_count"]) for row in records if row.get("token_count") is not None]),
        "input_token_count": mean([float(row["input_token_count"]) for row in records if row.get("input_token_count") is not None]),
        "output_token_count": mean([float(row["output_token_count"]) for row in records if row.get("output_token_count") is not None]),
        "estimated_cost_usd": mean([float(row["estimated_cost_usd"]) for row in records if row.get("estimated_cost_usd") is not None]),
        "annotated_questions": len(annotated),
    }


def summarize(records: list[dict], k: int = 5) -> dict:
    """Summarize overall quality and break out metrics by requested language."""
    report = _summarize_metrics(records, k)
    languages = sorted({row.get("language", "en") for row in records})
    report["language_metrics"] = {
        language: _summarize_metrics([row for row in records if row.get("language", "en") == language], k)
        for language in languages
    }
    return report
