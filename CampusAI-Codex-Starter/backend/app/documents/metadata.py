"""Conservative, explainable suggestions for placement-document metadata."""
from __future__ import annotations

import re


CATEGORY_TERMS = {
    "placement-policy": ("placement policy", "placement rules", "placement regulation", "placement procedure"),
    "company-eligibility": ("eligibility", "cgpa", "backlog", "eligible branches", "academic criteria"),
    "placement-calendar": ("placement calendar", "drive schedule", "interview schedule", "placement schedule", "recruitment calendar"),
    "student-handbook": ("student handbook", "code of conduct", "student regulations", "academic handbook"),
    "resume-guidelines": ("resume guideline", "resume format", "cv guideline", "curriculum vitae"),
    "interview-guidelines": ("interview guideline", "interview preparation", "interview process", "mock interview"),
    "training-materials": ("training material", "training module", "aptitude practice", "coding practice", "learning module"),
}
DATE_PATTERN = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
DATE_LABELS = {
    "effective": re.compile(rf"\b(?:effective(?:\s+(?:from|date|on))?|valid\s+from)\s*[:\-]?\s*({DATE_PATTERN})", re.I),
    "expiry": re.compile(rf"\b(?:expires?|expiry(?:\s+date)?|expiration(?:\s+date)?|valid\s+(?:until|through))\s*[:\-]?\s*({DATE_PATTERN})", re.I),
}


def suggest_document_metadata(pages: list[tuple[int | None, str]]) -> dict:
    text = "\n".join(page_text for _, page_text in pages)
    normalized = re.sub(r"\s+", " ", text).casefold()
    scores = {
        category: sum(len(re.findall(rf"(?<!\w){re.escape(term)}(?!\w)", normalized)) for term in terms)
        for category, terms in CATEGORY_TERMS.items()
    }
    ranked = sorted(scores.items(), key=lambda entry: (-entry[1], entry[0]))
    best_category, best_score = ranked[0]
    second_score = ranked[1][1]
    # This is a term-match margin score, not a calibrated probability.
    classification_score = round(best_score / (best_score + second_score), 3) if best_score else 0.0
    suggested_category = best_category if best_score >= 2 and best_score > second_score else None
    candidates = {
        kind: list(dict.fromkeys(match.group(1) for match in pattern.finditer(text)))[:10]
        for kind, pattern in DATE_LABELS.items()
    }
    return {
        "suggested_category": suggested_category,
        "classification_score": classification_score,
        "category_match_counts": scores,
        "date_candidates": candidates,
    }
