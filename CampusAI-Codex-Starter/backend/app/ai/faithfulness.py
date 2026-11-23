"""Optional NLI claim checking for cited chatbot sentences.

The verifier is deliberately disabled unless an operator selects and downloads a
model whose label map includes entailment, neutral, and contradiction.
"""
from __future__ import annotations

import math
import re
from functools import lru_cache

from app.core.config import settings


@lru_cache(maxsize=1)
def _model_and_labels():
    if not settings.faithfulness_model:
        return None
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(settings.faithfulness_model)
    raw = getattr(getattr(model, "model", None), "config", None)
    labels = getattr(raw, "id2label", None)
    if not isinstance(labels, dict):
        raise RuntimeError("Faithfulness model does not expose a classification label map")
    normalized = {int(index): str(label).casefold() for index, label in labels.items()}
    required = {"entailment", "neutral", "contradiction"}
    if not all(any(name in label for label in normalized.values()) for name in required):
        raise RuntimeError("Faithfulness model must expose entailment, neutral, and contradiction labels")
    return model, normalized


def _softmax(values) -> list[float]:
    logits = [float(value) for value in values]
    if not logits or not all(math.isfinite(value) for value in logits):
        raise RuntimeError("Faithfulness model returned invalid scores")
    peak = max(logits)
    exps = [math.exp(value - peak) for value in logits]
    total = sum(exps)
    if not math.isfinite(total) or total <= 0:
        raise RuntimeError("Faithfulness model returned invalid scores")
    return [value / total for value in exps]


def assess_cited_claims(claims: list[dict], sources: list[dict]) -> list[dict]:
    """Score each cited answer sentence against its cited evidence, if enabled.

    Values are model scores, not calibrated probabilities. Any infrastructure or
    model-contract error propagates so the API can abstain instead of bypassing it.
    """
    loaded = _model_and_labels()
    if loaded is None:
        return claims
    model, labels = loaded
    pairs = []
    for claim in claims:
        citations = claim.get("citation_numbers", [])
        evidence = "\n".join(str(sources[number - 1].get("text", "")) for number in citations
                              if 1 <= number <= len(sources))
        pairs.append((evidence, re.sub(r"\[\d+\]", "", claim["text"])))
    if not pairs:
        return claims
    predictions = model.predict(pairs, apply_softmax=False, convert_to_numpy=True)
    if len(predictions) != len(claims):
        raise RuntimeError("Faithfulness model returned an unexpected number of scores")
    entail_index = next(i for i, label in labels.items() if "entailment" in label)
    contradiction_index = next(i for i, label in labels.items() if "contradiction" in label)
    checked = []
    for claim, row in zip(claims, predictions):
        probs = _softmax(row)
        if max(entail_index, contradiction_index) >= len(probs):
            raise RuntimeError("Faithfulness score count does not match its label map")
        entailment = probs[entail_index]
        contradiction = probs[contradiction_index]
        checked.append({**claim, "entailment_score": round(entailment, 4),
                        "contradiction_score": round(contradiction, 4),
                        "semantic_support": entailment >= settings.faithfulness_min_entailment
                        and contradiction < entailment})
    return checked
