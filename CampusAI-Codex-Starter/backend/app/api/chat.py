import re
import unicodedata
import logging
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gemini import GeminiQuotaExhausted, generate_authorized_url_answer, generate_grounded_answer
from app.ai.faithfulness import assess_cited_claims
from app.ai.retrieval import _CONFIDENCE_STOPWORDS, confidence_features, hybrid_retrieve, tokenize
from app.core.config import settings
from app.db import get_db
from app.models import Application, ChatMessage, Company, CompanyRequirement, Conversation, Document, DocumentChunk, PlacementDrive, User
from app.schemas import ChatInput, ChatOutput
from app.security import require_roles

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)
CHAT_EVIDENCE_CHAR_BUDGET = 24_000
CHAT_EXHAUSTIVE_EVIDENCE_CHAR_BUDGET = 80_000

ABSTENTION_MESSAGES = {
    "en": "I could not find enough approved placement-document evidence to answer this reliably. Please check with the Placement Office.",
    "hi": "विश्वसनीय उत्तर देने के लिए स्वीकृत प्लेसमेंट दस्तावेज़ों में पर्याप्त प्रमाण नहीं मिला। कृपया प्लेसमेंट कार्यालय से जाँच करें।",
    "kn": "ವಿಶ್ವಾಸಾರ್ಹ ಉತ್ತರ ನೀಡಲು ಅನುಮೋದಿತ ಉದ್ಯೋಗ ನಿಯೋಜನೆ ದಾಖಲೆಗಳಲ್ಲಿ ಸಾಕಷ್ಟು ಸಾಕ್ಷ್ಯ ಸಿಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಉದ್ಯೋಗ ನಿಯೋಜನೆ ಕಚೇರಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ.",
}


def localized_conflict_message(language: str, references: str) -> str:
    if language == "hi":
        return f"स्वीकृत प्लेसमेंट दस्तावेज़ों में इस आवश्यकता के लिए विरोधी मान मिले हैं। कृपया उद्धृत स्रोतों {references} की तुलना करें और लागू नियम की पुष्टि प्लेसमेंट कार्यालय से करें। {references}"
    if language == "kn":
        return f"ಅನುಮೋದಿತ ಉದ್ಯೋಗ ನಿಯೋಜನೆ ದಾಖಲೆಗಳಲ್ಲಿ ಈ ಅರ್ಹತಾ ನಿಯಮಕ್ಕೆ ವಿರುದ್ಧವಾದ ಮೌಲ್ಯಗಳಿವೆ. ದಯವಿಟ್ಟು ಉಲ್ಲೇಖಿಸಿದ ಮೂಲಗಳನ್ನು {references} ಹೋಲಿಸಿ, ಅನ್ವಯಿಸುವ ನಿಯಮವನ್ನು ಉದ್ಯೋಗ ನಿಯೋಜನೆ ಕಚೇರಿಯಿಂದ ದೃಢೀಕರಿಸಿ. {references}"
    return f"The approved placement documents contain conflicting values for this requirement. Please compare the cited sources {references} and confirm the applicable rule with the Placement Office. {references}"


def _answer_sentences(answer: str) -> list[str]:
    """Return nonempty answer sentences, including short factual claims."""
    # A decimal point followed by whitespace is not a sentence boundary (e.g. 7.5 [1]).
    parts = re.split(r"(?<=[!?;；])\s+|(?<!\d)(?<=[.])\s+|(?<=[।॥])\s*|\n+", answer)
    return [part.strip() for part in parts
            if re.search(r"[^\W_]", re.sub(r"\[\d+\]", "", part), re.UNICODE)
            and not (part.strip().endswith(":") and not re.search(r"\[\d+\]|\d", part))]


def verify_citation_coverage(answer: str, valid_citations: set[int]) -> float:
    sentences = _answer_sentences(answer)
    if not sentences:
        return 0.0
    cited = sum(bool(set(int(number) for number in re.findall(r"\[(\d+)\]", part)) & valid_citations) for part in sentences)
    return round(cited / len(sentences), 3)


def citation_for_source(index: int, source: dict) -> dict:
    if source.get("source_type") == "company_record":
        return {"citation": index, "source_type": "company_record", "company_id": source["company_id"],
                "title": source["title"]}
    if source.get("source_type") == "application_record":
        return {"citation": index, "source_type": "application_record", "title": source["title"]}
    return {
        "citation": index, "source_type": "document", "document_id": source["document_id"],
        "company_id": source.get("company_id"), "title": source["title"], "filename": source.get("filename"),
        "version": source["version"], "page": source["page_number"], "section": source.get("section"),
        "effective_date": source["effective_date"], "status": source["approval_status"],
    }


def analyze_claim_support(answer: str, sources: list[dict]) -> list[dict]:
    """Associate answer claims with citations and check numeric claims against cited text.

    This deliberately checks only observable numeric support; it does not claim to
    prove semantic faithfulness for paraphrases or non-numeric statements.
    """
    result = []
    source_sentences = _answer_sentences(answer)
    numeric_pattern = re.compile(
        r"(?<!\w)(\d[\d,]*(?:\.\d+)?)(?:\s*(%|percent(?:age)?|प्रतिशत|ಶೇಕಡಾ))?(?!\w)", re.I
    )
    number_words = {
        "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5",
        "छह": "6", "छः": "6", "सात": "7", "आठ": "8", "नौ": "9", "दस": "10",
        "ಶೂನ್ಯ": "0", "ಒಂದು": "1", "ಎರಡು": "2", "ಮೂರು": "3", "ನಾಲ್ಕು": "4", "ಐದು": "5",
        "ಆರು": "6", "ಏಳು": "7", "ಎಂಟು": "8", "ಒಂಬತ್ತು": "9", "ಹತ್ತು": "10",
    }
    decimal_markers = {"point", "दशमलव", "ದಶಮಾಂಶ"}
    word_alternation = "|".join(re.escape(word) for word in sorted(number_words, key=len, reverse=True))
    word_pattern = re.compile(rf"(?<!\w)(?:{word_alternation})(?!\w)", re.I)
    decimal_word_pattern = re.compile(
        rf"(?<!\w)({word_alternation})\s+({'|'.join(map(re.escape, decimal_markers))})\s+({word_alternation})"
        r"(?:\s*(?:%|percent(?:age)?|प्रतिशत|ಶೇಕಡಾ))?(?!\w)", re.I,
    )
    percent_suffix = re.compile(r"\s*(?:%|percent(?:age)?|प्रतिशत|ಶೇಕಡಾ)$", re.I)

    def normalized(value: str) -> str:
        value = "".join(str(unicodedata.digit(char)) if char.isdecimal() else char for char in value)
        percent_match = percent_suffix.search(value)
        percent = percent_match is not None
        clean_value = value[:percent_match.start()] if percent_match else value
        clean = clean_value.replace(",", "").strip().casefold()
        if clean in number_words:
            return number_words[clean] + ("%" if percent else "")
        decimal_words = clean.split()
        if len(decimal_words) == 3 and decimal_words[1] in decimal_markers \
                and decimal_words[0] in number_words and decimal_words[2] in number_words:
            return f"{number_words[decimal_words[0]]}.{number_words[decimal_words[2]]}" + ("%" if percent else "")
        try:
            decimal = Decimal(clean).normalize()
            return format(decimal, "f") + ("%" if percent else "")
        except InvalidOperation:
            return clean

    def extract_numeric_claims(text: str) -> list[str]:
        matches = [
            (match.group(1) + ("%" if match.group(2) else ""), match.start(), match.end())
            for match in numeric_pattern.finditer(text)
        ]
        decimal_matches = [(match.group(), match.start(), match.end()) for match in decimal_word_pattern.finditer(text)]
        matches.extend(decimal_matches)
        decimal_spans = [(start, end) for _, start, end in decimal_matches]
        matches.extend((match.group(), match.start(), match.end()) for match in word_pattern.finditer(text)
                       if not any(match.start() < end and match.end() > start for start, end in decimal_spans))
        return [value for value, _, _ in sorted(matches, key=lambda match: match[1])]

    for index, sentence in enumerate(source_sentences, start=1):
        cited = sorted({int(value) for value in re.findall(r"\[(\d+)\]", sentence)
                        if 1 <= int(value) <= len(sources)})
        claim_text = re.sub(r"\[\d+\]", "", sentence)
        numeric_claims = extract_numeric_claims(claim_text)
        cited_text = " ".join(sources[citation - 1].get("text", "") for citation in cited)
        normalized_evidence = {normalized(value) for value in extract_numeric_claims(cited_text)}
        unsupported = [value for value in numeric_claims if normalized(value) not in normalized_evidence]
        result.append({
            "sentence": index,
            "text": claim_text.strip(),
            "citation_numbers": cited,
            "citation_associated": bool(cited),
            "numeric_claims": numeric_claims,
            "unsupported_numeric_claims": unsupported,
        })
    return result


def infer_historical_date(question: str) -> datetime | None:
    normalized = "".join(str(unicodedata.digit(char)) if char.isdecimal() else char for char in question)
    match = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", normalized)
    historical_cues = (
        r"\b(?:was|were|historical|previous|past|during|in)\b",
        r"(?:था|थी|थे|ऐतिहासिक|पिछले|पिछली|पुराने|पुरानी|दौरान|में)",
        r"(?:ಇತ್ತು|ಇದ್ದ|ಹಿಂದಿನ|ಹಿಂದೆ|ಸಮಯದಲ್ಲಿ|ರಲ್ಲಿ)",
    )
    if not match or not any(re.search(cue, normalized, re.I) for cue in historical_cues):
        return None
    year = int(match.group(1))
    if year >= datetime.now(timezone.utc).year:
        return None
    return datetime.combine(date(year, 12, 31), datetime.max.time(), tzinfo=timezone.utc)


def _numeric_policy_conflicts(question: str, sources: list[dict], language: str = "en") -> tuple[list[str], set[int]]:
    checks = []
    if re.search(r"cgpa|gpa|grade|सीजीपीए|जीपीए|ಅಂಕ|ಸಿಜಿಪಿಎ", question, re.I):
        checks.append(("CGPA requirement", re.compile(r"(?:cgpa|gpa|grade|सीजीपीए|जीपीए|ಅಂಕ|ಸಿಜಿಪಿಎ)[^\d]{0,35}(\d{1,2}(?:\.\d+)?)", re.I)))
    if re.search(r"backlog|arrear|बैकलॉग|ಅರಿಯರ್|ಬ್ಯಾಕ್ಲಾಗ್", question, re.I):
        checks.append(("backlog requirement", re.compile(r"(?:backlog|arrear|बैकलॉग|ಅರಿಯರ್|ಬ್ಯಾಕ್ಲಾಗ್)[^\d]{0,35}(\d{1,2})", re.I)))
    warnings = []
    conflicting_indexes: set[int] = set()
    for label, pattern in checks:
        claims_by_document: dict[int, set[str]] = {}
        values_by_index: dict[int, set[str]] = {}
        for index, source in enumerate(sources):
            values = {match.group(1) for match in pattern.finditer(source["text"])}
            if values:
                claims_by_document.setdefault(source["document_id"], set()).update(values)
                values_by_index[index] = values
        values = {value for variants in claims_by_document.values() for value in variants}
        if len(values) > 1:
            conflicting_indexes.update(values_by_index)
            values_text = ", ".join(sorted(values))
            localized_label = {
                "hi": "सीजीपीए आवश्यकता" if label == "CGPA requirement" else "बैकलॉग आवश्यकता",
                "kn": "ಸಿಜಿಪಿಎ ಅರ್ಹತೆ" if label == "CGPA requirement" else "ಬ್ಯಾಕ್ಲಾಗ್ ಮಿತಿ",
            }.get(language, label)
            if language == "hi":
                warnings.append(f"स्वीकृत दस्तावेज़ों में {localized_label} के परस्पर विरोधी मान मिले ({values_text}); लागू नियम की पुष्टि प्लेसमेंट कार्यालय से करें।")
            elif language == "kn":
                warnings.append(f"ಅನುಮೋದಿತ ದಾಖಲೆಗಳಲ್ಲಿ {localized_label}ಗೆ ವಿರುದ್ಧವಾದ ಮೌಲ್ಯಗಳಿವೆ ({values_text}); ಅನ್ವಯಿಸುವ ನಿಯಮವನ್ನು ಉದ್ಯೋಗ ನಿಯೋಜನೆ ಕಚೇರಿಯಿಂದ ದೃಢೀಕರಿಸಿ.")
            else:
                warnings.append(f"Retrieved approved documents conflict on {label} values ({values_text}); verify the applicable rule with the Placement Office.")
    return warnings, conflicting_indexes


def detect_numeric_policy_conflicts(question: str, sources: list[dict], language: str = "en") -> list[str]:
    return _numeric_policy_conflicts(question, sources, language)[0]


def rewrite_follow_up(question: str, previous_user_questions: list[str]) -> str:
    """Resolve short references for retrieval without allowing prior answers to become evidence."""
    if not previous_user_questions:
        return question
    dependent = len(question.split()) <= 5 or re.search(
        r"\b(it|they|them|those|these|that|same|also|what about|and the|how about)\b", question, re.I
    )
    if not dependent:
        return question
    context = " ".join(previous_user_questions[-2:])
    return f"{context}\nFollow-up question: {question}"


def is_exhaustive_list_question(question: str) -> bool:
    """Detect requests for complete role/company lists to widen chunk retrieval."""
    asks_for_list = re.search(r"\b(all|list|listed|listing|which|what)\b", question, re.I)
    asks_about_entries = re.search(r"\b(roles?|positions?|companies|employers|organizations|organisations)\b", question, re.I)
    return bool(asks_for_list and asks_about_entries)


def is_comparison_question(question: str) -> bool:
    return bool(re.search(
        r"\b(compare|comparison|contrast|versus|vs\.?|similarit(?:y|ies))\b|\bdifferences?\s+between\b",
        question, re.I,
    ))


def comparison_uses_multiple_documents(question: str, sources: list[dict]) -> bool:
    if not is_comparison_question(question):
        return True
    return len({source.get("document_id") for source in sources if source.get("document_id") is not None}) >= 2


def _normalize_entity_name(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _mentioned_companies(db: Session, question: str) -> list[Company]:
    normalized_question = f" {_normalize_entity_name(question)} "
    compact_question = normalized_question.replace(" ", "")
    matches = []
    for company in db.scalars(select(Company).order_by(Company.name)).all():
        normalized_name = _normalize_entity_name(company.name)
        compact_name = normalized_name.replace(" ", "")
        if normalized_name and (f" {normalized_name} " in normalized_question
                                or (len(compact_name) >= 4 and compact_name in compact_question)):
            matches.append(company)
    return sorted(matches, key=lambda company: len(_normalize_entity_name(company.name)), reverse=True)


def _is_own_application_question(question: str) -> bool:
    has_first_person_or_student = bool(re.search(
        r"\b(my|mine|i|i've|i have|the student|you|your)\b|\bstudent\s+(?:has|have)\s+applied\b",
        question, re.I,
    ))
    has_application_topic = bool(re.search(r"\b(applied|applications?)\b", question, re.I)) or bool(
        re.search(r"\b(?:did|have|has)\s+(?:i|you|the student)\s+(?:ever\s+)?apply\b", question, re.I)
    ) or bool(re.search(r"\bstudent\s+(?:(?:has|have)\s+)?applied\b", question, re.I))
    return has_first_person_or_student and has_application_topic


def _student_application_answer(db: Session, user: User, question: str) -> tuple[str, list[dict]] | None:
    """Answer personal application questions from only the signed-in student's records."""
    mentions_own_status = (
        bool(re.search(r"\b(my|mine|i|i've|i have|the student|you|your)\b", question, re.I))
        and bool(re.search(r"\bstatus\b", question, re.I))
        and bool(_mentioned_companies(db, question))
    )
    if user.role != "student" or _asks_company_details(question) or not (_is_own_application_question(question) or mentions_own_status):
        return None
    rows = db.execute(
        select(Application, PlacementDrive, Company)
        .join(PlacementDrive, PlacementDrive.id == Application.drive_id)
        .join(Company, Company.id == PlacementDrive.company_id)
        .where(Application.student_user_id == user.id)
        .order_by(Application.applied_at.desc(), Application.id.desc())
    ).all()
    named_companies = _mentioned_companies(db, question)
    if named_companies:
        requested_ids = {company.id for company in named_companies}
        rows = [row for row in rows if row[2].id in requested_ids]

    citation = {"citation": 1, "source_type": "application_record", "title": "Your application records"}
    status_requested = bool(re.search(r"\bstatus\b", question, re.I))
    yes_no_requested = bool(re.search(r"^\s*(did|have|has)\s+(?:i|you|the student)\b", question, re.I))

    if not rows:
        if named_companies:
            names = ", ".join(company.name for company in named_companies)
            answer = f"No application record was found for {names} [1]."
        else:
            answer = "You have not applied to any companies yet [1]."
        return answer, [citation]

    if status_requested:
        details = [f"{company.name} ({drive.role}): {application.status}" for application, drive, company in rows]
        return f"Your application status: {'; '.join(details)} [1].", [citation]

    if yes_no_requested:
        if named_companies:
            found_ids = {company.id for _, _, company in rows}
            missing = [company.name for company in named_companies if company.id not in found_ids]
            if missing:
                return f"No application record was found for {', '.join(missing)} [1].", [citation]
            return f"Yes, you have applied to {', '.join(company.name for company in named_companies)} [1].", [citation]
        return "Yes, you have applied to at least one company [1].", [citation]

    company_names = list(dict.fromkeys(company.name for _, _, company in rows))
    return f"Companies you have applied to: {', '.join(company_names)} [1].", [citation]


def _company_drive_status_answer(db: Session, question: str, company: Company | None) -> tuple[str, list[dict]] | None:
    if not company or not re.search(r"\bstatus\b", question, re.I):
        return None
    drives = db.scalars(
        select(PlacementDrive).where(PlacementDrive.company_id == company.id)
        .order_by(PlacementDrive.created_at.desc(), PlacementDrive.id.desc())
    ).all()
    citation = {"citation": 1, "source_type": "drive_record", "title": f"Placement drive records: {company.name}"}
    if not drives:
        return f"No placement drive status is recorded for {company.name} [1].", [citation]
    from app.api.placement import deadline_passed
    statuses = "; ".join(
        f"{drive.title} ({drive.role}): {'closed' if drive.status == 'open' and deadline_passed(drive.application_deadline) else drive.status}"
        for drive in drives
    )
    return f"{company.name} placement drive status: {statuses} [1].", [citation]


def _company_record_source(db: Session, company: Company) -> dict | None:
    requirements = company.requirements
    drives = [
        {"title": drive.title, "role": drive.role, "status": drive.status,
         "package_lpa": drive.package_lpa,
         "compensation_package_lpa": drive.package_lpa,
         "location": drive.location,
         "application_deadline": drive.application_deadline.isoformat() if drive.application_deadline else None,
         "drive_date": drive.drive_date.isoformat() if drive.drive_date else None,
         "selection_process": drive.selection_process or []}
        for drive in db.scalars(
            select(PlacementDrive).where(PlacementDrive.company_id == company.id)
            .order_by(PlacementDrive.created_at.desc(), PlacementDrive.id.desc())
        ).all()
    ]
    record = {
        "industry": company.industry,
        "description": company.description,
        "website": company.website,
        "job_roles": company.job_roles or [],
        "placement_drives": drives,
        "eligibility_requirements": ({
            "minimum_cgpa": requirements.min_cgpa,
            "eligible_branches": requirements.eligible_branches,
            "graduation_years": requirements.graduation_years,
            "maximum_active_backlogs": requirements.max_active_backlogs,
            "maximum_historical_backlogs": requirements.max_historical_backlogs,
            "required_skills": requirements.required_skills or [],
            "criteria_reviewed": requirements.criteria_reviewed,
            "source_document": requirements.source_document.title
            if requirements.source_document and requirements.source_document.approval_status == "approved" else None,
        } if requirements else None),
    }
    if not any(record.values()):
        return None
    return {
        "chunk_id": f"company-{company.id}", "document_id": None, "company_id": company.id,
        "source_type": "company_record", "title": f"Admin-entered company details: {company.name}",
        "filename": None, "version": 1, "category": "company-details", "approval_status": "approved",
        "effective_date": None, "expiry_date": None, "page_number": None, "section": None,
        "text": json.dumps(record, ensure_ascii=False), "lexical_score": 1.0,
    }


def _approved_company_document_sources(db: Session, company_ids: set[int], as_of: datetime | None = None) -> list[dict]:
    """Return every current approved chunk belonging to or linked to companies.

    Admin-uploaded source documents are not always assigned ``company_id``;
    eligibility documents may instead be linked through CompanyRequirement.
    Resolve both relationships plus documents whose title/filename names the
    company, then include every chunk from each matching approved document.
    """
    if not company_ids:
        return []
    as_of = as_of or datetime.now(timezone.utc)
    company_names = db.scalars(select(Company.name).where(Company.id.in_(company_ids))).all()
    linked_document_ids = set(db.scalars(
        select(CompanyRequirement.source_document_id)
        .where(CompanyRequirement.company_id.in_(company_ids), CompanyRequirement.source_document_id.is_not(None))
    ).all())
    approved_docs = db.scalars(select(Document).where(
        Document.approval_status == "approved",
        (Document.effective_date.is_(None)) | (Document.effective_date <= as_of),
        (Document.expiry_date.is_(None)) | (Document.expiry_date >= as_of),
    )).all()
    compact_company_names = {
        "".join(re.findall(r"[a-z0-9]+", name.casefold()))
        for name in company_names
        if len("".join(re.findall(r"[a-z0-9]+", name.casefold()))) >= 4
    }
    document_ids = set(linked_document_ids)
    for document in approved_docs:
        if document.company_id in company_ids:
            document_ids.add(document.id)
            continue
        compact_document_name = "".join(re.findall(
            r"[a-z0-9]+", f"{document.title} {document.filename}".casefold()
        ))
        if any(name in compact_document_name for name in compact_company_names):
            document_ids.add(document.id)
    if not document_ids:
        return []
    rows = db.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.id.in_(document_ids),
            Document.approval_status == "approved",
            (Document.effective_date.is_(None)) | (Document.effective_date <= as_of),
            (Document.expiry_date.is_(None)) | (Document.expiry_date >= as_of),
        )
        .order_by(Document.id, DocumentChunk.chunk_index)
    ).all()
    return [{
        "chunk_id": chunk.id, "document_id": document.id, "company_id": document.company_id,
        "title": document.title, "filename": document.filename, "category": document.category,
        "version": document.version, "approval_status": document.approval_status,
        "effective_date": document.effective_date, "expiry_date": document.expiry_date,
        "page_number": chunk.page_number, "section": chunk.section, "text": chunk.text,
        "lexical_score": 0.0, "_retrieval_selected": False, "source_type": "document",
    } for chunk, document in rows]


def _expand_retrieved_documents(db: Session, selected_sources: list[dict], as_of: datetime | None = None) -> list[dict]:
    """Replace matching top-k chunks with every eligible chunk in those documents."""
    document_ids = {source.get("document_id") for source in selected_sources
                    if isinstance(source.get("document_id"), int)}
    if not document_ids:
        return selected_sources
    historical = as_of is not None
    as_of = as_of or datetime.now(timezone.utc)
    rows = db.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.id.in_(document_ids),
            Document.approval_status.in_(["approved", "superseded"] if historical else ["approved"]),
            (Document.effective_date.is_(None)) | (Document.effective_date <= as_of),
            (Document.expiry_date.is_(None)) | (Document.expiry_date >= as_of),
        )
        .order_by(Document.id, DocumentChunk.chunk_index)
    ).all()
    selected_scores = {
        source.get("chunk_id"): float(source.get("lexical_score") or 0.0)
        for source in selected_sources
        if source.get("chunk_id") is not None and (
            source.get("_retrieval_selected") or float(source.get("lexical_score") or 0.0) > 0
        )
    }
    full_documents = [{
        "chunk_id": chunk.id, "document_id": document.id, "company_id": document.company_id,
        "title": document.title, "filename": document.filename, "category": document.category,
        "academic_year": document.academic_year, "version": document.version,
        "approval_status": document.approval_status, "effective_date": document.effective_date,
        "expiry_date": document.expiry_date, "page_number": chunk.page_number,
        "section": chunk.section, "text": chunk.text,
        "lexical_score": selected_scores.get(chunk.id, 0.0),
        "_retrieval_selected": chunk.id in selected_scores,
        "source_type": "document",
    } for chunk, document in rows]
    expanded_ids = {source["document_id"] for source in full_documents}
    preserved_sources = [source for source in selected_sources
                         if source.get("document_id") is None or source.get("document_id") not in expanded_ids]
    return preserved_sources + full_documents


def _chat_relevance_terms(text: str) -> set[str]:
    uppercase_tokens = {
        token.casefold() for token in re.findall(r"[A-Za-z0-9]+", text)
        if token.isupper()
    }

    def normalize(term: str) -> str:
        if term in uppercase_tokens:
            return term
        if len(term) > 4 and term.endswith("ies"):
            return term[:-3] + "y"
        if len(term) > 4 and term.endswith("s"):
            return term[:-1]
        return term

    tokens = [normalize(term) for term in tokenize(text)]
    terms = set(tokens) - _CONFIDENCE_STOPWORDS - {"company", "companies", "role", "roles", "year"}
    # Join adjacent acronym pieces so EYGDS matches “EY GDS” and similar
    # company names in uploaded file text.
    terms.update(
        tokens[index] + tokens[index + 1]
        for index in range(len(tokens) - 1)
        if len(tokens[index]) <= 3 and len(tokens[index + 1]) <= 4
        and tokens[index] not in _CONFIDENCE_STOPWORDS
        and tokens[index + 1] not in _CONFIDENCE_STOPWORDS
    )
    return terms


def _chat_relevance_matches(question: str, text: str) -> int:
    question_terms = _chat_relevance_terms(question)
    if not question_terms:
        return 0
    return len(question_terms & _chat_relevance_terms(text))


def _document_candidate_is_relevant(question: str, source: dict) -> bool:
    searchable = " ".join(str(source.get(field) or "")
                           for field in ("title", "filename", "section", "text"))
    terms = _chat_relevance_terms(question)
    matches = _chat_relevance_matches(question, searchable)
    required = max(1, int(len(terms) * 0.35 + 0.999))
    # A confident semantic/dense or lexical retrieval hit is useful for
    # paraphrases, but weak generic matches should fall through to URL Context.
    retrieval_score = max(float(source.get("lexical_score") or 0.0),
                          float(source.get("dense_score") or 0.0))
    return matches >= required or retrieval_score >= 0.55


def _bound_chat_evidence(sources: list[dict], question: str,
                         max_chars: int = CHAT_EVIDENCE_CHAR_BUDGET) -> list[dict]:
    """Return only question-relevant evidence, within the Gemini context budget."""
    non_document_sources = [source for source in sources
                            if source.get("document_id") is None
                            or source.get("source_type") in {"company_record", "application_record", "drive_record"}]
    selected_docs = [source for source in sources if source not in non_document_sources]
    record_chars = sum(len(str(source.get("text") or "")) for source in non_document_sources)
    remaining = max(0, max_chars - record_chars)

    terms = _chat_relevance_terms(question)

    # Identical repeated chunks commonly result from duplicate admin uploads.
    # Keep one citation for duplicate text instead of sending it twice.
    deduplicated = []
    seen_text_hashes: set[str] = set()
    for source in selected_docs:
        content = str(source.get("text") or "")
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        if digest in seen_text_hashes:
            continue
        seen_text_hashes.add(digest)
        tokens = _chat_relevance_terms(content)
        matches = len(terms & tokens)
        ranked = dict(source)
        ranked["_relevance_matches"] = matches
        ranked["_relevance_score"] = float(source.get("lexical_score") or 0.0)
        deduplicated.append(ranked)

    # A candidate is relevant when retrieval selected it (lexical, dense, or
    # reranked match), or its own chunk contains at least one meaningful query
    # term. Never send unrelated chunks just because they share a large file.
    relevant_docs = [source for source in deduplicated if source["_relevance_matches"] > 0]

    ranked_docs = sorted(
        relevant_docs,
        key=lambda source: (
            -int(source["_relevance_matches"]),
            -int(bool(source.get("_retrieval_selected"))),
            -float(source["_relevance_score"]),
            str(source.get("document_id") or ""),
            int(source.get("page_number") or 0),
            str(source.get("chunk_id") or ""),
        ),
    )
    kept_docs = []
    for source in ranked_docs:
        size = len(str(source.get("text") or ""))
        if size <= remaining:
            kept_docs.append(source)
            remaining -= size
    # Restore source order after relevance-based selection for readable
    # citations and stable answers.
    kept_ids = {source.get("chunk_id") for source in kept_docs}
    ordered = [source for source in sources if source in non_document_sources or source.get("chunk_id") in kept_ids]
    input_chars = sum(len(str(source.get("text") or "")) for source in sources)
    logger.info("Placement chat evidence filtered; input_chunks=%s output_chunks=%s input_chars=%s output_chars=%s",
                len(sources), len(ordered), input_chars,
                sum(len(str(source.get("text") or "")) for source in ordered))
    return [{key: value for key, value in source.items() if not key.startswith("_")}
            for source in ordered]


def _student_application_context_source(db: Session, user: User) -> dict | None:
    rows = db.execute(
        select(Application, PlacementDrive, Company)
        .join(PlacementDrive, PlacementDrive.id == Application.drive_id)
        .join(Company, Company.id == PlacementDrive.company_id)
        .where(Application.student_user_id == user.id)
        .order_by(Application.applied_at.desc(), Application.id.desc())
    ).all()
    if not rows:
        return None
    records = [{"company": company.name, "role_applied_for": drive.role,
                "application_status": application.status}
               for application, drive, company in rows]
    return {
        "chunk_id": f"applications-{user.id}", "document_id": None, "company_id": None,
        "source_type": "application_record", "title": "This student's application records",
        "filename": None, "version": 1, "category": "student-applications",
        "approval_status": "approved", "effective_date": None, "expiry_date": None,
        "page_number": None, "section": None,
        "text": json.dumps(records, ensure_ascii=False), "lexical_score": 1.0,
    }


def _asks_company_details(question: str) -> bool:
    return bool(re.search(
        r"\b(role|position|salary|pay|package|ctc|compensation|job description|responsibilit(?:y|ies)|location|offer(?:ed)?|details?)\b",
        question, re.I,
    ))


def list_evidence_covers_requested_years(question: str, sources: list[dict]) -> bool:
    """Require placement/company evidence for every year in a requested list."""
    requested_years = set(re.findall(r"\b(?:19|20)\d{2}\b", question))
    if not requested_years:
        return True

    by_document: dict[str, list[dict]] = {}
    for source in sources:
        by_document.setdefault(str(source.get("document_id", source.get("filename", source.get("title", "")))), []).append(source)

    evidenced_years: set[str] = set()
    for document_sources in by_document.values():
        document_text = " ".join(
            str(source.get(field) or "")
            for source in document_sources
            for field in ("title", "filename", "text")
        )
        years_in_document = set(re.findall(r"\b(?:19|20)\d{2}\b", document_text))
        has_company_placement_context = bool(re.search(
            r"\b(compan(?:y|ies)|employers?|organizations?|organisations?|recruit(?:ment|ing)?|placement|hiring|visited)\b",
            document_text, re.I,
        ))
        if has_company_placement_context:
            evidenced_years.update(years_in_document)
    return requested_years.issubset(evidenced_years)


@router.post("/", response_model=ChatOutput)
def chat(data: ChatInput, user: User = Depends(require_roles("student", "placement_officer", "administrator")), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, data.conversation_id) if data.conversation_id else None
    if conversation and conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if data.conversation_id and not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    prior_messages = []
    if conversation:
        prior_messages = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id)
                                    .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(6)).all()
        prior_messages.reverse()
    prior_user_questions = [message.content for message in prior_messages if message.role == "user"]
    retrieval_query = rewrite_follow_up(data.question, prior_user_questions)
    context_for_generation = [{"role": message.role, "content": message.content} for message in prior_messages]
    if not conversation:
        conversation = Conversation(user_id=user.id, title=data.question[:120])
        db.add(conversation)
        db.flush()
    personal_answer = _student_application_answer(db, user, data.question)
    if personal_answer:
        answer, citations = personal_answer
        db.add(ChatMessage(conversation_id=conversation.id, role="user", content=data.question))
        db.add(ChatMessage(conversation_id=conversation.id, role="assistant", content=answer, citations=citations, confidence=1.0))
        db.commit()
        return ChatOutput(conversation_id=conversation.id, answer=answer, confidence=1.0,
                          confidence_label="supported", evidence_minimum_score=settings.evidence_minimum_score,
                          citation_coverage=1.0, citations=citations, temporal_warnings=[], claim_support=[], abstained=False)

    mentioned_companies = _mentioned_companies(db, data.question)
    specified_company = mentioned_companies[0] if len(mentioned_companies) == 1 else None
    drive_status_answer = _company_drive_status_answer(db, data.question, specified_company)
    if drive_status_answer:
        answer, citations = drive_status_answer
        db.add(ChatMessage(conversation_id=conversation.id, role="user", content=data.question))
        db.add(ChatMessage(conversation_id=conversation.id, role="assistant", content=answer, citations=citations, confidence=1.0))
        db.commit()
        return ChatOutput(conversation_id=conversation.id, answer=answer, confidence=1.0,
                          confidence_label="supported", evidence_minimum_score=settings.evidence_minimum_score,
                          citation_coverage=1.0, citations=citations, temporal_warnings=[], claim_support=[], abstained=False)
    as_of = data.historical_as_of or infer_historical_date(data.question)
    # A short top-k context can omit the later pages of a company/role list.
    # Broaden only explicit enumeration questions; ordinary Q&A keeps its
    # smaller, more focused evidence set.
    retrieval_limit = 24 if is_exhaustive_list_question(data.question) or is_comparison_question(data.question) else 6
    own_company_detail_question = (
        user.role == "student" and _is_own_application_question(data.question)
        and _asks_company_details(data.question)
    )
    application_context = _student_application_context_source(db, user) if own_company_detail_question else None
    if own_company_detail_question:
        company_ids_for_context = set(db.scalars(
            select(PlacementDrive.company_id)
            .join(Application, Application.drive_id == PlacementDrive.id)
            .where(Application.student_user_id == user.id)
        ).all())
    elif specified_company:
        company_ids_for_context = {specified_company.id}
    else:
        company_ids_for_context = set()
    retrieval_company_id = specified_company.id if specified_company else data.company_id
    if company_ids_for_context:
        sources = _approved_company_document_sources(db, company_ids_for_context, as_of=as_of)
        for company_id in sorted(company_ids_for_context):
            company = db.get(Company, company_id)
            company_source = _company_record_source(db, company) if company else None
            if company_source:
                sources.insert(0, company_source)
        if application_context:
            sources.insert(0, application_context)
    else:
        sources = hybrid_retrieve(db, retrieval_query, limit=retrieval_limit, as_of=as_of, category=data.category,
                                  company_id=retrieval_company_id, academic_year=data.academic_year,
                                  version=data.document_version)
        sources = [source for source in sources if _document_candidate_is_relevant(data.question, source)]
    sources = _expand_retrieved_documents(
        db, sources,
        as_of=as_of if data.historical_as_of or infer_historical_date(data.question) else None,
    )
    evidence_budget = (CHAT_EXHAUSTIVE_EVIDENCE_CHAR_BUDGET
                       if is_exhaustive_list_question(data.question) or is_comparison_question(data.question)
                       else CHAT_EVIDENCE_CHAR_BUDGET)
    sources = _bound_chat_evidence(sources, data.question, max_chars=evidence_budget)
    company_context_available = bool(company_ids_for_context and sources)
    evidence = confidence_features(retrieval_query, sources)
    logger.info("Placement chat retrieval completed; label=%s source_count=%s", evidence["label"], len(sources))
    temporal_warnings: list[str] = []
    if as_of and any(source["approval_status"] == "superseded" for source in sources):
        if data.language == "hi":
            temporal_warnings.append(f"{as_of.date()} की ऐतिहासिक खोज में पुराने नीति संस्करण शामिल हैं।")
        elif data.language == "kn":
            temporal_warnings.append(f"{as_of.date()}ರ ಐತಿಹಾಸಿಕ ಹುಡುಕಾಟದಲ್ಲಿ ಹಿಂದಿನ ನೀತಿ ಆವೃತ್ತಿಗಳಿವೆ.")
        else:
            temporal_warnings.append(f"Historical retrieval as of {as_of.date()} includes superseded policy versions.")
    conflict_warnings, conflicting_indexes = _numeric_policy_conflicts(data.question, sources, data.language)
    temporal_warnings.extend(conflict_warnings)
    versions_by_title: dict[str, set[int]] = {}
    for source in sources:
        versions_by_title.setdefault(source["title"].casefold(), set()).add(source["version"])
    if any(len(versions) > 1 for versions in versions_by_title.values()):
        if data.language == "hi":
            temporal_warnings.append("एक ही दस्तावेज़ के कई संस्करण मिले; कार्रवाई से पहले उनकी लागू तिथियों की तुलना करें।")
        elif data.language == "kn":
            temporal_warnings.append("ಒಂದೇ ದಾಖಲೆಯ ಹಲವು ಆವೃತ್ತಿಗಳು ಕಂಡುಬಂದಿವೆ; ಕ್ರಮ ಕೈಗೊಳ್ಳುವ ಮೊದಲು ಅವುಗಳ ಜಾರಿಗೆ ಬಂದ ದಿನಾಂಕಗಳನ್ನು ಹೋಲಿಸಿ.")
        else:
            temporal_warnings.append("Multiple versions of the same document matched; compare the effective dates before acting.")
    citation_coverage = 0.0
    claim_support: list[dict] = []
    if conflict_warnings:
        references = " ".join(f"[{index + 1}]" for index in sorted(conflicting_indexes))
        answer = localized_conflict_message(data.language, references)
        citations = [citation_for_source(index, source)
                     for index, source in enumerate(sources, start=1) if index - 1 in conflicting_indexes]
        citation_coverage = verify_citation_coverage(answer, set(range(1, len(sources) + 1)))
        claim_support = analyze_claim_support(answer, sources)
        abstained = True
    elif (not sources or (evidence["label"] == "unsupported" and not company_context_available)
          or (is_comparison_question(data.question)
              and not comparison_uses_multiple_documents(data.question, sources))
          or (is_exhaustive_list_question(data.question)
              and not list_evidence_covers_requested_years(data.question, sources))):
        # A broad lexical match can return unrelated policy chunks (especially
        # in small corpora). Do not present those chunks as evidence; query the
        # admin-authorized official-site search instead.
        web_result = generate_authorized_url_answer(data.question, data.language, db=db)
        if not web_result:
            logger.warning("Placement URL Context fallback returned no grounded answer; route=no_document_evidence")
        if web_result:
            answer, citations = web_result
            citation_coverage = 1.0
            claim_support = []
            abstained = False
        else:
            answer = ABSTENTION_MESSAGES[data.language]
            citations = []
            abstained = True
    else:
        try:
            answer = generate_grounded_answer(data.question, sources, data.language, context_for_generation)
        except GeminiQuotaExhausted as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="AI response service is unavailable. Check its configuration and try again later.") from exc
        used_numbers = {int(value) for value in re.findall(r"\[(\d+)\]", answer)}
        valid_numbers = set(range(1, len(sources) + 1))
        if used_numbers - valid_numbers:
            answer = re.sub(r"\[(\d+)\]", lambda match: match.group(0) if int(match.group(1)) in valid_numbers else "", answer)
        citations = [citation_for_source(index, source)
                     for index, source in enumerate(sources, start=1) if index in used_numbers]
        citation_coverage = verify_citation_coverage(answer, valid_numbers)
        claim_support = analyze_claim_support(answer, sources)
        abstained = False
        try:
            if claim_support:
                claim_support = assess_cited_claims(claim_support, sources)
        except Exception as exc:
            # A configured verifier must never silently fail open. Keep logs free
            # of model inputs, endpoints, credentials, and student content.
            import logging
            logging.getLogger(__name__).warning("Faithfulness verification unavailable (%s)", type(exc).__name__)
            claim_support = []
            citations = []
            answer = ABSTENTION_MESSAGES[data.language]
            abstained = True
        unsupported_numeric = any(item["unsupported_numeric_claims"] for item in claim_support)
        unsupported_semantic = any(item.get("semantic_support") is False for item in claim_support)
        if abstained:
            pass
        elif (not citations or citation_coverage < 1.0 or unsupported_numeric or unsupported_semantic
              or (is_comparison_question(data.question)
                  and not comparison_uses_multiple_documents(data.question, [
                      sources[index - 1] for index in used_numbers if 1 <= index <= len(sources)
                  ]))):
            # The retrieved document chunks were sent to Gemini first. If its
            # answer cannot be grounded in those chunks, try the explicitly
            # authorized official-site fallback before abstaining.
            web_result = generate_authorized_url_answer(data.question, data.language, db=db)
            if not web_result:
                logger.warning("Placement URL Context fallback returned no grounded answer; route=document_answer_unsupported")
            if web_result:
                answer, citations = web_result
                citation_coverage = 1.0
                claim_support = []
                abstained = False
            else:
                answer = ABSTENTION_MESSAGES[data.language]
                citations = []
                abstained = True
        else:
            abstained = False
    db.add(ChatMessage(conversation_id=conversation.id, role="user", content=data.question))
    db.add(ChatMessage(conversation_id=conversation.id, role="assistant", content=answer, citations=citations, confidence=evidence["score"]))
    db.commit()
    label = evidence["label"]
    return ChatOutput(conversation_id=conversation.id, answer=answer, confidence=evidence["score"], confidence_label=label,
                      evidence_minimum_score=evidence["minimum_score_threshold"],
                      citation_coverage=citation_coverage, citations=citations, temporal_warnings=temporal_warnings,
                      claim_support=claim_support, abstained=abstained)


@router.get("/conversations")
def conversations(user: User = Depends(require_roles("student", "placement_officer", "administrator")), db: Session = Depends(get_db)):
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.created_at.desc())).all()
    return [{"id": item.id, "title": item.title, "created_at": item.created_at} for item in rows]


@router.get("/conversations/{conversation_id}")
def conversation_history(conversation_id: int, user: User = Depends(require_roles("student", "placement_officer", "administrator")), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.created_at)).all()
    return [{"id": m.id, "role": m.role, "content": m.content, "citations": m.citations, "confidence": m.confidence, "created_at": m.created_at} for m in messages]


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, user: User = Depends(require_roles("student", "placement_officer", "administrator")), db: Session = Depends(get_db)):
    conversation = db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user.id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Delete children explicitly so privacy deletion works consistently with SQLite
    # configurations that do not enable foreign-key cascades.
    db.query(ChatMessage).filter(ChatMessage.conversation_id == conversation.id).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
    return Response(status_code=204)
