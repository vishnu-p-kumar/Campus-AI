"""Pure experiment record construction, separated for inexpensive tests."""
from __future__ import annotations

import platform


ANSWER_ANNOTATION_FIELDS = (
    "answer_correct", "faithful", "citation_correct", "unsupported_claims",
    "temporal_correct", "current_policy_correct", "historical_retrieval_correct",
    "version_identification_correct", "outdated_warning_correct", "conflict_detection_correct",
)


def estimate_cost_usd(usage: dict, input_rate_per_million: float | None,
                      output_rate_per_million: float | None) -> float | None:
    """Estimate provider cost only when current per-token rates are supplied."""
    if input_rate_per_million is None or output_rate_per_million is None:
        return None
    input_tokens, output_tokens = usage.get("input_token_count"), usage.get("output_token_count")
    if input_tokens is None or output_tokens is None:
        return None
    return round((input_tokens * input_rate_per_million + output_tokens * output_rate_per_million) / 1_000_000, 8)


def build_result_record(*, item: dict, system: str, answer: str, sources: list[dict], evidence: dict,
                        citation_coverage: float, abstained: bool, retrieval_latency_ms: float,
                        total_latency_ms: float, token_count: int | None, model_id: str,
                        retrieval_model_id: str, dataset_name: str,
                        cited_source_numbers: list[int] | None = None,
                        claim_support: list[dict] | None = None,
                        semantic_verifier_status: str = "not_run",
                        dataset_version: str = "unversioned",
                        dataset_sha256: str | None = None,
                        provider_configuration: dict | None = None,
                        embedding_model_id: str | None = None,
                        reranker_model_id: str | None = None,
                        faithfulness_model_id: str | None = None,
                        faithfulness_min_entailment: float | None = None,
                        evidence_minimum_score: float | None = None,
                        runtime: dict | None = None,
                        predicted_eligibility: str | None = None,
                        input_token_count: int | None = None, output_token_count: int | None = None,
                        estimated_cost_usd: float | None = None,
                        input_cost_per_million_usd: float | None = None,
                        output_cost_per_million_usd: float | None = None) -> dict:
    annotation = {key: value for key, value in (item.get("annotation") or {}).items() if value is not None}
    expected_annotation_fields = list(ANSWER_ANNOTATION_FIELDS)
    if item.get("eligibility_case") is not None:
        expected_annotation_fields.append("eligibility_actual")
    corpus_filter_names = ("as_of", "category", "company_id", "academic_year", "document_version")
    return {
        "question_id": item["question_id"],
        "system": system,
        "question": item["question"],
        "language": item.get("language", "en"),
        "answer": answer,
        "retrieved_chunk_ids": [source["chunk_id"] for source in sources],
        "relevant_chunk_ids": item.get("relevant_chunk_ids", []),
        "citations": [{"citation": number, "document_id": sources[number - 1]["document_id"],
                       "title": sources[number - 1]["title"], "version": sources[number - 1]["version"],
                       "page": sources[number - 1]["page_number"]}
                      for number in (cited_source_numbers or []) if 1 <= number <= len(sources)],
        "claim_support": claim_support or [],
        "semantic_verifier_status": semantic_verifier_status,
        "embedding_model_id": embedding_model_id,
        "reranker_model_id": reranker_model_id,
        "faithfulness_model_id": faithfulness_model_id,
        "faithfulness_min_entailment": faithfulness_min_entailment,
        "evidence_minimum_score": evidence_minimum_score,
        "provider_configuration": provider_configuration or {},
        "runtime": runtime or {"python_version": platform.python_version()},
        "corpus_filters": {key: item[key] for key in corpus_filter_names if item.get(key) is not None},
        "confidence_features": evidence,
        "citation_coverage": citation_coverage,
        "predicted_abstain": abstained,
        "expected_abstain": item["expected_abstain"],
        "retrieval_latency_ms": retrieval_latency_ms,
        "total_latency_ms": total_latency_ms,
        "token_count": token_count,
        "input_token_count": input_token_count,
        "output_token_count": output_token_count,
        "estimated_cost_usd": estimated_cost_usd,
        "input_cost_per_million_usd": input_cost_per_million_usd,
        "output_cost_per_million_usd": output_cost_per_million_usd,
        "annotation": annotation or None,
        "missing_annotations": [field for field in expected_annotation_fields if annotation.get(field) is None],
        "dataset_name": dataset_name,
        "dataset_version": dataset_version or item.get("dataset_version") or "unversioned",
        "dataset_sha256": dataset_sha256,
        "model_id": model_id,
        "retrieval_model_id": retrieval_model_id,
        "predicted_eligibility": predicted_eligibility,
    }
