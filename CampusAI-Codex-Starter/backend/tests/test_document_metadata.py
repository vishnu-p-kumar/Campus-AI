from app.documents.metadata import suggest_document_metadata


def test_document_metadata_suggests_category_and_labelled_date_candidates():
    result = suggest_document_metadata([(1, "COMPANY ELIGIBILITY RULES\nEligibility criteria: minimum CGPA 7.5 and no active backlog.\nEffective from: 2026-07-01. Valid until 2027-06-30.")])
    assert result["suggested_category"] == "company-eligibility"
    assert result["classification_score"] > 0
    assert result["date_candidates"]["effective"] == ["2026-07-01"]
    assert result["date_candidates"]["expiry"] == ["2027-06-30"]


def test_ambiguous_or_uninformative_text_does_not_force_category():
    result = suggest_document_metadata([(None, "Welcome to CampusAI. Contact the placement office for help.")])
    assert result["suggested_category"] is None
    assert result["classification_score"] == 0
