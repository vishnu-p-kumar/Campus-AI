import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.ai.retrieval import confidence_features, hybrid_retrieve as retrieve_approved_documents
from app.core.config import settings
from app.db import get_db
from app.eligibility.engine import evaluate_eligibility
from app.models import ChatMessage, Company, CompanyRequirement, Conversation, Notification, PlacementDrive, User
from app.schemas import ChatInput, ChatOutput
from app.security import require_roles

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)
CHAT_ROLES = ("student", "placement_officer", "administrator")


def _notification_answer(db: Session, user: User, question: str) -> tuple[str, list[dict]] | None:
    """Answer notification questions from the signed-in user's own messages."""
    query = question.casefold()
    notification_intent = re.search(r"\b(notifications?|announcements?)\b", query)
    message_intent = re.search(r"\b(messages?)\b", query) and (
        re.search(r"\b(read|unread|unseen|full|complete|entire|named|titled|called|title|name)\b", query)
        or re.search(r"\b(my|by name)\b", query)
    )
    if not notification_intent and not message_intent:
        return None

    notification_user = user
    requested_candidate = bool(re.search(r"\b(candidate|student)\b", query))
    email = None
    candidate_name = None
    if user.role == "student" and requested_candidate:
        if re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", query) or re.search(
            r"\b(?:candidate|student)\s+\S+\s+\S+", query
        ):
            return "For privacy, you can only view notifications sent to your account.", []
    if user.role in {"administrator", "placement_officer"} and re.search(r"\b(candidate|student)\b", query):
        email = re.search(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", query)
        if email:
            notification_user = db.scalar(
                select(User).where(func.lower(User.email) == email.group(0).casefold(), User.role == "student")
            )
        else:
            students = db.scalars(select(User).where(User.role == "student")).all()
            matches = [item for item in students if item.full_name.casefold() in query]
            if len(matches) == 1:
                notification_user = matches[0]
                candidate_name = notification_user.full_name
            elif len(matches) > 1:
                return "Please include the candidate's registered email address so I can find the correct notifications.", []
            else:
                name = re.search(
                    r"\b(?:candidate|student)\s+(.+?)(?=\s+(?:notifications?|messages?|announcements?|unread|read|status|full|complete|all|inbox|named|titled|called|title|name|by)\b|$)",
                    question,
                    re.IGNORECASE,
                )
                candidate_name = name.group(1).strip().rstrip(".,?!") if name else None
                if candidate_name:
                    candidate_name = candidate_name.removesuffix("'s").strip()
                if candidate_name:
                    matches = db.scalars(
                        select(User).where(func.lower(User.full_name) == candidate_name.casefold(), User.role == "student")
                    ).all()
                else:
                    matches = []
            if len(matches) != 1:
                return "Please include the candidate's registered email address so I can find the correct notifications.", []
            notification_user = matches[0] if len(matches) == 1 else None
        if not email and not candidate_name and notification_user.id == user.id:
            return "Please include the candidate's registered email address to check their notifications.", []
        if notification_user is None:
            return "I couldn't find a candidate account matching that request.", []

    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == notification_user.id)
        .order_by(Notification.created_at.desc())
        .limit(100)
    ).all()
    asks_unread = bool(re.search(r"\b(unread|un-seen|unseen|not read|haven't read|have not read)\b", query))
    asks_read = bool(re.search(r"\bread\b", query))
    asks_both_states = asks_unread and asks_read
    unread = asks_unread and not asks_both_states
    read = asks_read and not asks_unread
    if unread:
        rows = [item for item in rows if item.read_at is None]
    elif read:
        rows = [item for item in rows if item.read_at is not None]

    controls = {
        "notification", "notifications", "message", "messages", "announcement", "announcements",
        "read", "unread", "unseen", "seen", "not", "full", "complete", "entire", "content", "body",
        "show", "list", "display", "give", "get", "tell", "what", "which", "are", "is", "my", "me",
        "i", "the", "a", "an", "for", "of", "from", "by", "named", "name", "titled", "title",
        "all", "have", "has", "been", "please", "with", "can", "you", "your", "about", "do", "received", "receive", "marked", "mark",
        "how", "many", "number", "count",
        "candidate", "candidates", "student", "students",
    }
    title_query = query
    if notification_user.id != user.id:
        if email:
            title_query = title_query.replace(email.group(0).casefold(), " ")
        if candidate_name:
            title_query = title_query.replace(candidate_name.casefold(), " ")
    title_terms = {word for word in re.findall(r"[a-z0-9]+", title_query) if word not in controls and len(word) > 1}
    if title_terms:
        rows = [
            item for item in rows
            if title_terms.intersection(set(re.findall(r"[a-z0-9]+", f"{item.title} {item.message}".casefold())))
        ]
        if not rows:
            return "I couldn't find a notification matching that message name in your account.", []

    count_request = bool(re.search(r"\b(how many|count|number of)\b", query))
    if count_request and not title_terms:
        state = "unread " if unread else "read " if read else ""
        count = len(rows)
        label = "notification" if count == 1 else "notifications"
        owner_name = "You" if notification_user.id == user.id else notification_user.full_name
        verb = "have" if owner_name == "You" else "has"
        return f"{owner_name} {verb} {count} {state}{label}.", []
    elif unread and not rows:
        owner_name = "You" if notification_user.id == user.id else notification_user.full_name
        message = f"{owner_name} have no unread notifications." if owner_name == "You" else f"{owner_name} has no unread notifications."
        return message, []
    elif read and not rows:
        owner_name = "You" if notification_user.id == user.id else notification_user.full_name
        message = f"{owner_name} have no read notifications." if owner_name == "You" else f"{owner_name} has no read notifications."
        return message, []
    elif not rows:
        owner_name = "You" if notification_user.id == user.id else notification_user.full_name
        message = f"{owner_name} don't have any notifications yet." if owner_name == "You" else f"{owner_name} doesn't have any notifications yet."
        return message, []

    include_full = bool(title_terms) or bool(re.search(r"\b(full|complete|entire|content|body)\b", query))
    lines = []
    for item in rows[:10]:
        state = "read" if item.read_at is not None else "unread"
        date = item.created_at.strftime("%Y-%m-%d") if item.created_at else "date unavailable"
        if include_full:
            lines.append(f"{item.title} ({state}, {date})\n{item.message}")
        else:
            lines.append(f"{item.title} — {state} ({date})")
    suffix = f"\nShowing 10 of {len(rows)} matching notifications." if len(rows) > 10 else ""
    owner = "Your notifications" if notification_user.id == user.id else f"Notifications for {notification_user.full_name}"
    citations = [{
        "citation": index,
        "source_type": "notification_record",
        "notification_id": item.id,
        "title": item.title,
        "status": "read" if item.read_at is not None else "unread",
    } for index, item in enumerate(rows[:10], start=1)]
    return owner + ":\n" + "\n\n".join(lines) + suffix, citations


def _company_answer(db: Session, user: User, question: str, requested_company_id: int | None = None):
    """Format admin-managed company profiles and open drives without exposing private records."""
    query = question.casefold()
    detail_terms = re.search(
        r"\b(details?|profile|description|industry|roles?|positions?|eligibility|requirements?|skills?|website|about|drive|salary|package|compensation|hiring|recruitment|process|selection|location|deadline|offers?|open)\b",
        query,
    ) or re.search(r"\b(tell me about|what is|who is|what does|what do|describe|explain)\b", query)
    list_terms = re.search(r"\b(list|show|all|added|available)\b", query)
    company_word = bool(re.search(r"\b(compan(?:y|ies))\b", query))
    aggregate_terms = re.search(r"\b(average|highest|placements|placed|visited|came|statistics|how many|count|number of)\b", query)

    companies = db.scalars(
        select(Company)
        .options(joinedload(Company.requirements).joinedload(CompanyRequirement.source_document))
        .order_by(Company.name)
    ).unique().all()
    if requested_company_id is not None:
        companies = [item for item in companies if item.id == requested_company_id]
    else:
        normalized_query = " ".join(re.findall(r"[a-z0-9]+", query))
        padded_query = f" {normalized_query} "
        named = []
        for item in companies:
            normalized_name = " ".join(re.findall(r"[a-z0-9]+", item.name.casefold()))
            if normalized_name and f" {normalized_name} " in padded_query:
                named.append(item)
        if named:
            companies = named
        elif not ((list_terms or detail_terms) and company_word):
            return None
    if aggregate_terms or (not detail_terms and not (list_terms and company_word)):
        return None

    if user.role == "student":
        companies = [item for item in companies if evaluate_eligibility(
            user.student_profile,
            item.requirements,
            source_approved=bool(item.requirements and item.requirements.source_document
                                 and item.requirements.source_document.approval_status == "approved"),
        ).decision == "eligible"]
    if not companies:
        return ("I couldn't find a company profile available to your account that matches that request.", [])

    stats = db.scalars(
        select(PlacementDrive)
        .where(PlacementDrive.company_id.in_([item.id for item in companies]), PlacementDrive.status == "open")
        .order_by(PlacementDrive.application_deadline.asc())
    ).all()
    drives_by_company: dict[int, list[PlacementDrive]] = {}
    for drive in stats:
        drives_by_company.setdefault(drive.company_id, []).append(drive)

    answer_lines = []
    citations = []
    for company in companies[:8]:
        requirement = company.requirements
        answer_lines.extend([f"{company.name}", f"Industry: {company.industry or 'Not provided'}"])
        if company.description:
            answer_lines.append(f"About: {company.description}")
        if company.website:
            answer_lines.append(f"Website: {company.website}")
        if company.job_roles:
            answer_lines.append("Roles: " + ", ".join(map(str, company.job_roles)))
        if requirement:
            criteria = []
            if requirement.min_cgpa is not None:
                criteria.append(f"minimum CGPA {requirement.min_cgpa:g}")
            if requirement.eligible_branches:
                criteria.append("branches " + ", ".join(map(str, requirement.eligible_branches)))
            if requirement.graduation_years:
                criteria.append("graduation years " + ", ".join(map(str, requirement.graduation_years)))
            if requirement.max_active_backlogs is not None:
                criteria.append(f"up to {requirement.max_active_backlogs} active backlogs")
            if requirement.max_historical_backlogs is not None:
                criteria.append(f"up to {requirement.max_historical_backlogs} historical backlogs")
            if requirement.required_skills:
                criteria.append("skills " + ", ".join(map(str, requirement.required_skills)))
            if criteria:
                review = "reviewed" if requirement.criteria_reviewed else "not marked as reviewed"
                answer_lines.append(f"Eligibility criteria ({review}): " + "; ".join(criteria))
        for drive in drives_by_company.get(company.id, [])[:5]:
            details = [f"Open drive: {drive.title} — {drive.role}"]
            if drive.package_lpa is not None:
                details.append(f"{drive.package_lpa:g} LPA")
            if drive.location:
                details.append(drive.location)
            if drive.application_deadline:
                details.append(f"deadline {drive.application_deadline.strftime('%Y-%m-%d')}")
            if drive.selection_process:
                details.append("selection: " + ", ".join(map(str, drive.selection_process)))
            answer_lines.append("; ".join(details))
        citations.append({
            "citation": len(citations) + 1,
            "source_type": "company_record",
            "company_id": company.id,
            "title": f"Company profile: {company.name}",
        })
        answer_lines.append("")
    if len(companies) > 8:
        answer_lines.append(f"Showing 8 of {len(companies)} company profiles.")
    return "\n".join(answer_lines).strip(), citations


def _document_citations(sources: list[dict]) -> list[dict]:
    citations = []
    for source in sources:
        effective_date = source.get("effective_date")
        citations.append({
            "citation": len(citations) + 1,
            "source_type": "document",
            "document_id": source.get("document_id"),
            "company_id": source.get("company_id"),
            "title": source.get("title") or source.get("filename") or "Approved placement document",
            "filename": source.get("filename"),
            "version": source.get("version"),
            "page": source.get("page_number"),
            "section": source.get("section"),
            "effective_date": effective_date.isoformat() if effective_date else None,
            "status": source.get("approval_status"),
        })
    return citations


def _chat_answer_text(answer: object) -> str:
    """Keep answer text structured while omitting markdown emphasis and source blocks."""
    text = re.sub(r"\*\*", "", str(answer)).strip()
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*(?:sources?|references?|citations?)\s*:", line, re.IGNORECASE):
            break
        lines.append(re.sub(r"\s*\[\d+\]", "", line))
    return "\n".join(lines).strip()


@router.post("/", response_model=ChatOutput)
def chat(
    data: ChatInput,
    user: User = Depends(require_roles(*CHAT_ROLES)),
    db: Session = Depends(get_db),
):
    """Use the placement-query-bot backend while retaining CampusAI chat history."""
    conversation = db.get(Conversation, data.conversation_id) if data.conversation_id else None
    if data.conversation_id and (not conversation or conversation.user_id != user.id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not conversation:
        conversation = Conversation(user_id=user.id, title=data.question[:120])
        db.add(conversation)
        db.flush()

    source_citations: list[dict] = []
    knowledge_sources: list[dict] = []
    notification_result = _notification_answer(db, user, data.question)
    answer_override = None
    company_result = None
    if notification_result is not None:
        answer_override, source_citations = notification_result
    if answer_override is None:
        company_result = _company_answer(db, user, data.question, data.company_id)
    if answer_override is None:
        try:
            retrieval_company_id = data.company_id
            if retrieval_company_id is None and company_result is not None:
                matching_company_ids = {
                    citation.get("company_id")
                    for citation in company_result[1]
                    if citation.get("company_id") is not None
                }
                if len(matching_company_ids) == 1:
                    retrieval_company_id = next(iter(matching_company_ids))
            candidates = retrieve_approved_documents(
                db,
                data.question,
                as_of=data.historical_as_of,
                limit=6,
                category=data.category,
                company_id=retrieval_company_id,
                academic_year=data.academic_year,
                version=data.document_version,
            )
            if candidates:
                evidence = confidence_features(data.question, candidates)
                if evidence["label"] in {"supported", "partial"} and evidence["score"] >= settings.evidence_minimum_score:
                    knowledge_sources = candidates
                    source_citations = _document_citations(candidates)
        except Exception as exc:
            # The placement bot and its static FAQ/SQL flow remain available if
            # the admin-managed document index cannot be queried.
            logger.warning("Admin document retrieval unavailable (%s)", type(exc).__name__)

    if answer_override is None and company_result is not None:
        if knowledge_sources:
            company_title = company_result[1][0]["title"] if company_result[1] else "Admin-managed company profile"
            knowledge_sources.insert(0, {
                "title": company_title,
                "filename": None,
                "text": company_result[0],
            })
            source_citations = company_result[1] + _document_citations(knowledge_sources[1:6])
        else:
            answer_override, source_citations = company_result

    try:
        from app.placement_query_bot import ask

        if answer_override is not None:
            result = ask(data.question, answer_override=answer_override, log_query=False)
        elif knowledge_sources:
            result = ask(data.question, knowledge_sources=knowledge_sources, log_query=False)
        else:
            result = ask(data.question)
    except Exception as exc:
        if isinstance(exc, ModuleNotFoundError):
            logger.error(
                "Placement query bot unavailable; category=dependency_missing module=%s",
                exc.name or "unknown",
            )
        elif isinstance(exc, RuntimeError) and "GROQ_API_KEY" in str(exc):
            logger.error(
                "Placement query bot unavailable; category=configuration_missing setting=GROQ_API_KEY"
            )
        else:
            logger.warning(
                "Placement query bot unavailable; category=runtime_error exception_type=%s",
                type(exc).__name__,
            )
        detail = "Placement assistant is unavailable. Check its backend configuration and try again."
        if isinstance(exc, ModuleNotFoundError):
            detail = "Placement assistant server dependencies are missing. Contact the administrator."
        elif isinstance(exc, RuntimeError) and "GROQ_API_KEY" in str(exc):
            detail = "Placement answer generation is not configured. Contact the administrator."
        raise HTTPException(
            status_code=503,
            detail=detail,
        ) from None

    answer = _chat_answer_text(result["answer"])
    route = str(result["route"])
    confidence = max(0.0, min(1.0, float(result.get("score", 0.0))))
    abstained = route == "other"
    citations = source_citations if route == "faq" else []
    db.add(ChatMessage(conversation_id=conversation.id, role="user", content=data.question))
    db.add(ChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        citations=citations,
        confidence=confidence,
    ))
    db.commit()
    return ChatOutput(
        conversation_id=conversation.id,
        answer=answer,
        route=route,
        queries_used=int(result.get("queries_used", 0)),
        daily_query_limit=int(result.get("daily_query_limit", 25)),
        queries_remaining=int(result.get("queries_remaining", 25)),
        reset_date=str(result.get("reset_date", "")) or None,
        confidence=confidence,
        confidence_label="out_of_scope" if abstained else "routed",
        evidence_minimum_score=0.15,
        citation_coverage=1.0 if citations else 0.0,
        citations=citations,
        temporal_warnings=[f"Routed to {route} handler."],
        claim_support=[],
        abstained=abstained,
    )


@router.get("/usage")
def query_usage(user: User = Depends(require_roles(*CHAT_ROLES))):
    try:
        from app.placement_query_bot import get_usage

        return get_usage()
    except Exception as exc:
        logger.warning("Placement query usage unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Placement assistant usage is unavailable.",
        ) from None


@router.get("/conversations")
def conversations(
    user: User = Depends(require_roles(*CHAT_ROLES)), db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.created_at.desc())
    ).all()
    return [{"id": item.id, "title": item.title, "created_at": item.created_at} for item in rows]


@router.get("/conversations/{conversation_id}")
def conversation_history(
    conversation_id: int,
    user: User = Depends(require_roles(*CHAT_ROLES)),
    db: Session = Depends(get_db),
):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.created_at)
    ).all()
    return [{
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "citations": message.citations,
        "confidence": message.confidence,
        "created_at": message.created_at,
    } for message in messages]


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    user: User = Depends(require_roles(*CHAT_ROLES)),
    db: Session = Depends(get_db),
):
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.query(ChatMessage).filter(
        ChatMessage.conversation_id == conversation.id
    ).delete(synchronize_session=False)
    db.delete(conversation)
    db.commit()
    return Response(status_code=204)
