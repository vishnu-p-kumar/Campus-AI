"""Apply the production cited-answer safety checks to generated RAG experiments."""
from __future__ import annotations

import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.ai.faithfulness import assess_cited_claims
from app.core.config import settings
from app.api.chat import analyze_claim_support, verify_citation_coverage


def validate_rag_answer(answer: str, sources: list[dict]) -> dict:
    valid = set(range(1, len(sources) + 1))
    answer = re.sub(
        r"\[(\d+)\]",
        lambda match: match.group(0) if int(match.group(1)) in valid else "",
        answer,
    )
    coverage = verify_citation_coverage(answer, valid)
    claims = analyze_claim_support(answer, sources)
    verifier_configured = bool(settings.faithfulness_model)
    if verifier_configured and not claims:
        verifier_status = "no_claims"
    else:
        try:
            claims = assess_cited_claims(claims, sources)
            verifier_status = "passed" if verifier_configured else "disabled"
        except Exception:
            # A configured semantic verifier must not fail open in research output.
            return {"answer": "Insufficient verified evidence.", "citation_coverage": coverage,
                    "abstained": True, "claim_support": [], "cited_source_numbers": [],
                    "semantic_verifier_status": "failed"}
    used = sorted({number for claim in claims for number in claim["citation_numbers"]})
    unsupported = any(claim["unsupported_numeric_claims"] for claim in claims)
    semantic_rejection = any(claim.get("semantic_support") is False for claim in claims)
    abstained = not used or coverage < 1.0 or unsupported or semantic_rejection
    if abstained:
        answer = "Insufficient verified evidence."
        used = []
    return {"answer": answer, "citation_coverage": coverage, "abstained": abstained,
            "claim_support": claims, "cited_source_numbers": used,
            "semantic_verifier_status": verifier_status}
