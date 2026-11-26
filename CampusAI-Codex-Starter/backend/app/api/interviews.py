import random
import re
import logging
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.db import get_db
from app.ai.interview import answer_interview_question, generate_question, review_answer
from app.ai.gemini import _provider_failure_diagnostic
from app.models import InterviewResponse, InterviewSession, User
from app.security import require_roles

router = APIRouter(prefix="/interviews", tags=["interview preparation"])
logger = logging.getLogger(__name__)
QUESTIONS = {
    "technical": [
        "Explain how a hash table handles collisions and compare two collision strategies.",
        "Describe a project where you made a design tradeoff. What alternatives did you consider?",
        "How would you investigate a slow SQL query in a production service?",
        "How would you design an API endpoint that validates input and reports errors consistently?",
        "What is the purpose of automated tests, and how would you test a service that depends on a database?",
        "A web service is intermittently slow. How would you use logs and metrics to narrow down the cause?",
        "How would you protect a web application endpoint that contains private student data?",
        "When would you use a cache, and how would you prevent stale data from causing problems?",
    ],
    "hr": ["Tell me about a time you received difficult feedback and what you changed.", "Describe a disagreement on a team and how you handled it.", "What kind of work would you like to learn in your first year?", "Tell me about a time you had to meet a difficult deadline. How did you prioritize?", "Describe a mistake you made and what you learned from it.", "How have you helped a teammate who was struggling with a task?", "What motivates you to apply for this role?", "How do you respond when priorities change unexpectedly?"],
    "aptitude": ["A team completes 3/5 of a task in 6 days. At the same rate, how many days are needed for the full task? Explain your reasoning.", "A product price rises by 20% and then falls by 20%. Is the final price the original price? Explain.", "The average of four numbers is 12. A fifth number, 17, is added. What is the new average?", "A bag has 3 red and 2 blue balls. What is the chance of drawing a blue ball in one draw?", "A bus travels 90 kilometers in 2 hours. How far will it travel in 5 hours at the same speed?", "Find the next number in the sequence 3, 6, 12, 24. Explain the pattern.", "A product costs 800 rupees after a 20% discount. What was its original price?", "Two workers complete a task in 6 days together. If one worker takes 10 days alone, how many days would the other take alone?"],
    "coding": ["Given an array of integers, describe an efficient approach to return the two indices whose values sum to a target. Discuss complexity and edge cases.", "Describe how you would find the first non-repeating character in a string.", "How would you reverse a singly linked list, and what is the time and space complexity?", "Given a sorted array, how would you find whether a target value exists efficiently?", "How would you use a stack to check whether brackets in a string are balanced?", "Describe an approach to find the shortest path in an unweighted graph.", "How would you remove duplicate values from a list while preserving their original order?", "Given a list of intervals, how would you merge overlapping intervals?"],
}
QUESTION_TOPICS = {
    "technical": ["data structures and complexity", "database queries and indexing", "API design and validation", "testing and debugging", "observability and production diagnosis", "security and privacy", "caching and distributed systems", "tradeoffs and system design"],
    "hr": ["receiving feedback", "team disagreement", "learning goals", "prioritization and deadlines", "mistakes and learning", "teamwork and support", "motivation for the role", "adapting to change"],
    "aptitude": ["work rates and ratios", "percentage changes", "averages", "basic probability", "distance and speed", "number patterns", "discounts", "combined work rates"],
    "coding": ["arrays and hash maps", "strings and frequency counts", "linked lists", "binary search", "stacks and validation", "graphs and shortest paths", "sets and preserving order", "sorting and interval merging"],
}
CURATED_MULTIPLE_CHOICE = {
    "technical": [
        ("Which HTTP status code usually indicates that a resource was created successfully?",
         ["200", "201", "204", "301"], "B"),
        ("What is the average lookup time for a key in a well-distributed hash table?",
         ["O(1)", "O(log n)", "O(n)", "O(n log n)"], "A"),
        ("What does atomicity mean in an ACID database transaction?",
         ["All operations commit together or none do", "Reads never wait for writes", "Every query uses an index", "Data is copied to every server"], "A"),
        ("What is a common tradeoff when adding a database index?",
         ["Reads become impossible", "Reads may get faster, while writes and storage cost more", "The table becomes read-only", "Queries no longer need filters"], "B"),
        ("What should a unit test primarily verify?",
         ["The smallest unit of behavior in isolation", "The production network as a whole", "Every screen in a browser", "The database server's uptime"], "A"),
    ],
    "hr": [
        ("A teammate disagrees with your design proposal. What is the best first step?",
         ["Ask about their concerns and compare evidence against the shared goal", "Escalate immediately without discussion", "Ignore the feedback and ship your proposal", "Ask the team to vote before explaining either option"], "A"),
        ("You realize a deadline is at risk. What should you do?",
         ["Wait until the due date to report it", "Tell stakeholders early, explain the risk, and propose priorities", "Hide the unfinished work", "Quietly remove requirements without agreement"], "B"),
        ("After receiving constructive feedback, what is the strongest response?",
         ["Clarify the feedback, choose an action, and check whether it helped", "Defend every decision immediately", "Avoid the person who gave it", "Change unrelated work to show activity"], "A"),
        ("You made an error that affected a teammate's work. What should you do first?",
         ["Acknowledge it, explain the impact, and help correct it", "Delete the evidence of the error", "Wait for someone else to notice", "Blame unclear requirements without checking"], "A"),
        ("Two urgent tasks conflict. How should you decide what to do first?",
         ["Compare impact and deadlines, then align priorities with the owner", "Choose the task that is easiest", "Work on both without telling anyone", "Always choose the task assigned most recently"], "A"),
    ],
    "aptitude": [
        ("A team completes 3/5 of a task in 6 days at a steady rate. How long does the full task take?",
         ["8 days", "10 days", "12 days", "15 days"], "B"),
        ("A price of 100 rises by 20%, then falls by 20%. What is the final price?",
         ["96", "100", "104", "120"], "A"),
        ("Four numbers have an average of 12. After adding 17, what is the average of all five?",
         ["12", "13", "14", "15"], "B"),
        ("A bus travels 90 km in 2 hours at a steady speed. How far does it travel in 5 hours?",
         ["180 km", "200 km", "225 km", "250 km"], "C"),
        ("A bag has 3 red balls and 2 blue balls. What is the probability of drawing a blue ball once?",
         ["1/5", "2/5", "3/5", "1/2"], "B"),
    ],
    "coding": [
        ("Choose the correct output for this code.\n\nCODE_SNIPPET (Python):\nvalues = [2, 4, 6]\nprint(values[1])",
         ["2", "4", "6", "IndexError"], "B"),
        ("Choose the correct output for this code.\n\nCODE_SNIPPET (Python):\ntotal = 0\nfor value in [1, 2, 3]:\n    total += value\nprint(total)",
         ["3", "5", "6", "123"], "C"),
        ("Choose the correct output for this code.\n\nCODE_SNIPPET (Python):\nitems = [1, 1, 2]\nprint(len(set(items)))",
         ["1", "2", "3", "Error"], "B"),
        ("Choose the correct output for this code.\n\nCODE_SNIPPET (Python):\nn = 9\nprint(n // 2)",
         ["4", "4.5", "5", "9"], "A"),
        ("What is the time complexity of this code?\n\nCODE_SNIPPET (Python):\nfor value in values:\n    print(value)",
         ["O(1)", "O(log n)", "O(n)", "O(n²)"], "C"),
    ],
}
DIFFICULTIES = ("easy", "medium", "difficult")


def _question_plan(category: str, index: int, question_limit: int) -> tuple[str, str]:
    topics = QUESTION_TOPICS[category]
    topic = topics[index % len(topics)]
    stage = round(2 * index / max(1, question_limit - 1))
    return topic, DIFFICULTIES[stage]


def _make_question(category: str, language: str, focus: str | None, question_type: str,
                   index: int, question_limit: int, previous_questions: list[str]):
    topic, difficulty = _question_plan(category, index, question_limit)
    try:
        generated = generate_question(category, language, focus, question_type, topic, difficulty, previous_questions)
    except Exception:
        generated = None
    if question_type == "multiple_choice":
        validated = _multiple_choice_data(generated)
        if validated:
            return validated, "gemini"
        return _curated_multiple_choice(category, index, previous_questions), "curated-question-bank"
    if isinstance(generated, dict):
        question = generated.get("question")
        reference_answer = generated.get("reference_answer")
        if isinstance(question, str) and question.strip() and isinstance(reference_answer, str) and reference_answer.strip():
            return {"question": question.strip(), "reference_answer": reference_answer.strip()}, "gemini"
    if isinstance(generated, str) and generated.strip():
        return generated, "gemini"
    bank = LOCALIZED_QUESTIONS.get(language, QUESTIONS)[category]
    asked = {item.strip().casefold() for item in previous_questions}
    candidates = [item for item in bank if item.strip().casefold() not in asked]
    return random.choice(candidates or bank), "curated-question-bank"
LOCALIZED_QUESTIONS = {
    "hi": {
        "technical": [
            "हैश टेबल में टकराव कैसे संभाले जाते हैं? टकराव संभालने की दो विधियों की तुलना करें।",
            "ऐसी परियोजना बताइए जिसमें आपने डिज़ाइन से जुड़ा समझौता किया। आपने किन विकल्पों पर विचार किया?",
            "प्रोडक्शन सेवा में धीमी SQL क्वेरी की जाँच आप कैसे करेंगे?",
        ],
        "hr": [
            "किसी कठिन प्रतिक्रिया के बाद आपने क्या बदलाव किया?",
            "टीम में असहमति को आपने कैसे संभाला?",
            "पहले वर्ष में आप किस तरह का काम सीखना चाहेंगे?",
        ],
        "aptitude": [
            "एक टीम 6 दिनों में किसी काम का 3/5 भाग पूरा करती है। इसी गति से पूरा काम कितने दिनों में होगा? अपना तर्क समझाइए।",
            "किसी वस्तु की कीमत पहले 20% बढ़ती है और फिर 20% घटती है। क्या अंतिम कीमत मूल कीमत के बराबर होगी? समझाइए।",
        ],
        "coding": [
            "पूर्णांकों की एक array में लक्ष्य योग देने वाले दो सूचकांक खोजने का कुशल तरीका बताइए। समय-जटिलता और किनारी स्थितियों पर चर्चा करें।",
            "किसी string में पहला ऐसा अक्षर कैसे खोजेंगे जो दोहराया न गया हो?",
        ],
    },
    "kn": {
        "technical": [
            "ಹ್ಯಾಶ್ ಟೇಬಲ್‌ನಲ್ಲಿ ಘರ್ಷಣೆಗಳನ್ನು ಹೇಗೆ ನಿರ್ವಹಿಸುತ್ತೀರಿ? ಎರಡು ವಿಧಾನಗಳನ್ನು ಹೋಲಿಸಿ.",
            "ವಿನ್ಯಾಸದಲ್ಲಿ ರಾಜಿ ಮಾಡಿಕೊಳ್ಳಬೇಕಾದ ಯೋಜನೆಯೊಂದನ್ನು ವಿವರಿಸಿ. ಯಾವ ಪರ್ಯಾಯಗಳನ್ನು ಪರಿಶೀಲಿಸಿದ್ದೀರಿ?",
            "ಪ್ರೊಡಕ್ಷನ್ ಸೇವೆಯ ನಿಧಾನ SQL ಪ್ರಶ್ನೆಯನ್ನು ಹೇಗೆ ತನಿಖೆ ಮಾಡುತ್ತೀರಿ?",
        ],
        "hr": [
            "ಕಠಿಣ ಪ್ರತಿಕ್ರಿಯೆ ಬಂದ ನಂತರ ನೀವು ಯಾವ ಬದಲಾವಣೆ ಮಾಡಿದ್ದೀರಿ?",
            "ತಂಡದಲ್ಲಿನ ಭಿನ್ನಾಭಿಪ್ರಾಯವನ್ನು ನೀವು ಹೇಗೆ ನಿಭಾಯಿಸಿದ್ದೀರಿ?",
            "ಮೊದಲ ವರ್ಷದಲ್ಲಿ ಯಾವ ರೀತಿಯ ಕೆಲಸವನ್ನು ಕಲಿಯಲು ಬಯಸುತ್ತೀರಿ?",
        ],
        "aptitude": [
            "ಒಂದು ತಂಡ 6 ದಿನಗಳಲ್ಲಿ ಕೆಲಸದ 3/5 ಭಾಗ ಮುಗಿಸುತ್ತದೆ. ಇದೇ ವೇಗದಲ್ಲಿ ಪೂರ್ಣ ಕೆಲಸಕ್ಕೆ ಎಷ್ಟು ದಿನ ಬೇಕು? ನಿಮ್ಮ ಲೆಕ್ಕವನ್ನು ವಿವರಿಸಿ.",
            "ಒಂದು ವಸ್ತುವಿನ ಬೆಲೆ ಮೊದಲು 20% ಏರಿ ನಂತರ 20% ಇಳಿಯುತ್ತದೆ. ಅಂತಿಮ ಬೆಲೆ ಮೂಲ ಬೆಲೆಯಷ್ಟೇ ಆಗುತ್ತದೆಯೇ? ವಿವರಿಸಿ.",
        ],
        "coding": [
            "ಪೂರ್ಣಾಂಕಗಳ array ಯಲ್ಲಿ ಗುರಿ ಮೊತ್ತ ನೀಡುವ ಎರಡು ಸೂಚ್ಯಂಕಗಳನ್ನು ಕಂಡುಹಿಡಿಯುವ ಪರಿಣಾಮಕಾರಿ ವಿಧಾನವನ್ನು ವಿವರಿಸಿ. ಸಮಯ ಸಂಕೀರ್ಣತೆ ಮತ್ತು ಅಂಚಿನ ಸಂದರ್ಭಗಳನ್ನು ಚರ್ಚಿಸಿ.",
            "ಒಂದು string ನಲ್ಲಿ ಮರುಕಳಿಸದ ಮೊದಲ ಅಕ್ಷರವನ್ನು ಹೇಗೆ ಕಂಡುಹಿಡಿಯುತ್ತೀರಿ?",
        ],
    },
}
FEEDBACK_COPY = {
    "en": {
        "detailed": "You provided a response with concrete detail.", "addressed": "You addressed the prompt.",
        "structure": "Structure the answer as situation, action, result and learning.",
        "outcome": "Add a measurable outcome or specific example where possible.",
        "note": "This is a transparent practice rubric, not an assessment equivalent to a recruiter.",
    },
    "hi": {
        "detailed": "आपने अपने उत्तर में ठोस विवरण दिया।", "addressed": "आपने प्रश्न का उत्तर दिया।",
        "structure": "उत्तर को स्थिति, कार्रवाई, परिणाम और सीख के क्रम में व्यवस्थित करें।",
        "outcome": "जहाँ संभव हो, मापने योग्य परिणाम या विशिष्ट उदाहरण जोड़ें।",
        "note": "यह पारदर्शी अभ्यास रूब्रिक है; यह भर्तीकर्ता के मूल्यांकन के बराबर नहीं है।",
    },
    "kn": {
        "detailed": "ನಿಮ್ಮ ಉತ್ತರದಲ್ಲಿ ಸ್ಪಷ್ಟವಾದ ವಿವರಗಳಿವೆ.", "addressed": "ನೀವು ಪ್ರಶ್ನೆಗೆ ಉತ್ತರಿಸಿದ್ದೀರಿ.",
        "structure": "ಉತ್ತರವನ್ನು ಪರಿಸ್ಥಿತಿ, ಕ್ರಮ, ಫಲಿತಾಂಶ ಮತ್ತು ಕಲಿಕೆಯ ಕ್ರಮದಲ್ಲಿ ರೂಪಿಸಿ.",
        "outcome": "ಸಾಧ್ಯವಾದಲ್ಲಿ ಅಳೆಯಬಹುದಾದ ಫಲಿತಾಂಶ ಅಥವಾ ನಿರ್ದಿಷ್ಟ ಉದಾಹರಣೆ ಸೇರಿಸಿ.",
        "note": "ಇದು ಪಾರದರ್ಶಕ ಅಭ್ಯಾಸ ಮಾನದಂಡ; ನೇಮಕಾತಿದಾರರ ಮೌಲ್ಯಮಾಪನಕ್ಕೆ ಸಮಾನವಲ್ಲ.",
    },
}
RUBRIC_SIGNALS = {
    "en": [("because", r"because"), ("result", r"result"), ("learning", r"learned"),
           ("tradeoff", r"tradeoff"), ("measurement", r"measure"), ("testing", r"tested"),
           ("team", r"team"), ("example", r"example"), ("sequence", r"first|then")],
    "hi": [("कारण", r"क्योंकि"), ("परिणाम", r"परिणाम"), ("सीख", r"सीखा|सीखी|सीखे"),
           ("विकल्पों की तुलना", r"समझौता|विकल्प"), ("मापन", r"मापा|माप"), ("परीक्षण", r"जाँचा|परीक्षण"),
           ("टीम", r"टीम"), ("उदाहरण", r"उदाहरण"), ("क्रम", r"पहले|फिर")],
    "kn": [("ಕಾರಣ", r"ಏಕೆಂದರೆ"), ("ಫಲಿತಾಂಶ", r"ಫಲಿತಾಂಶ"), ("ಕಲಿಕೆ", r"ಕಲಿತೆ|ಕಲಿತ"),
           ("ವಿನಿಮಯ", r"ರಾಜಿ|ಪರ್ಯಾಯ"), ("ಅಳತೆ", r"ಅಳೆಯಿತು|ಅಳತೆ"), ("ಪರೀಕ್ಷೆ", r"ಪರೀಕ್ಷೆ|ಪರಿಶೀಲನೆ"),
           ("ತಂಡ", r"ತಂಡ"), ("ಉದಾಹರಣೆ", r"ಉದಾಹರಣೆ"), ("ಕ್ರಮ", r"ಮೊದಲು|ನಂತರ")],
}


class SessionInput(BaseModel):
    category: str = Field(default="aptitude", pattern="^(technical|hr|aptitude|coding)$")
    language: str = Field(default="en", pattern="^(en|hi|kn)$")
    focus: str | None = Field(default=None, max_length=2000)
    question_type: str = Field(default="multiple_choice", pattern="^(typed|multiple_choice)$")
    question_limit: int = Field(default=5, ge=1, le=20)


class AnswerInput(BaseModel):
    question: str = Field(min_length=5, max_length=2000)
    answer: str = Field(min_length=1, max_length=8000)


class AskInput(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    focus: str | None = Field(default=None, max_length=2000)
    language: str = Field(default="en", pattern="^(en|hi|kn)$")


@router.post("/ask")
def ask_interview_question(data: AskInput, user: User = Depends(require_roles("student"))):
    try:
        answer = answer_interview_question(data.question.strip(), data.focus, data.language)
    except Exception as exc:
        if isinstance(exc, RuntimeError) and "not configured" in str(exc).casefold():
            logger.error("Interview tutor unavailable; category=configuration_missing setting=GEMINI_CHAT_API_KEY")
            raise HTTPException(
                status_code=503,
                detail="Interview AI is not configured. Contact the administrator.",
            ) from None

        category, status_code = _provider_failure_diagnostic(exc)
        logger.warning(
            "Interview tutor unavailable; category=%s status_code=%s exception_type=%s",
            category,
            status_code if status_code is not None else "unknown",
            type(exc).__name__,
        )
        if status_code in {503, 504}:
            raise HTTPException(
                status_code=503,
                detail="Gemini is temporarily overloaded or timed out. Try the interview answer again shortly.",
                headers={"Retry-After": "15"},
            ) from None
        if status_code == 429 or category in {"quota_or_rate_limited", "quota_exhausted", "rate_limited"}:
            raise HTTPException(
                status_code=503,
                detail="Gemini request limits are currently reached. Check the Gemini project limits, then retry.",
                headers={"Retry-After": "60"},
            ) from None
        if category in {"invalid_api_key", "expired_api_key", "unauthenticated", "permission_denied", "api_not_enabled", "billing_not_enabled", "model_not_found", "model_or_endpoint_not_found"}:
            raise HTTPException(
                status_code=503,
                detail="Interview AI configuration needs administrator attention.",
            ) from None
        raise HTTPException(
            status_code=503,
            detail="Interview AI could not answer right now. Try again later.",
            headers={"Retry-After": "15"},
        ) from None
    return {"answer": answer, "generation_mode": "assistant"}


def _multiple_choice_data(value):
    if not isinstance(value, dict):
        return None
    question, choices, correct = value.get("question"), value.get("choices"), value.get("correct_option")
    if (not isinstance(question, str) or not question.strip() or not isinstance(choices, list)
            or len(choices) != 4 or not isinstance(correct, str) or correct not in {"A", "B", "C", "D"}):
        return None
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
           or not isinstance(item.get("text"), str) or not item["text"].strip() for item in choices):
        return None
    ids = {item["id"] for item in choices}
    if ids != {"A", "B", "C", "D"}:
        return None
    question = re.sub(r"\*\*", "", question).strip()
    choices = [{**item, "text": re.sub(r"\*\*", "", item["text"]).strip()} for item in choices]
    return question, choices, correct


def _curated_multiple_choice(category: str, index: int, previous_questions: list[str]):
    """Provide a validated local MCQ when Gemini is unavailable or returns malformed data."""
    bank = CURATED_MULTIPLE_CHOICE[category]
    asked = {item.strip().casefold() for item in previous_questions}
    candidates = [item for item in bank if item[0].strip().casefold() not in asked]
    if not candidates:
        candidates = bank
    preferred = bank[index % len(bank)]
    question, texts, correct = preferred if preferred in candidates else candidates[0]
    return question, [{"id": chr(ord("A") + offset), "text": text} for offset, text in enumerate(texts)], correct


@router.post("/sessions", status_code=201)
def create_session(data: SessionInput, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    focus = data.focus.strip() if data.focus and data.focus.strip() else None
    question_type = "multiple_choice" if data.category in {"aptitude", "coding"} else data.question_type
    question, mode = _make_question(data.category, data.language, focus, question_type, 0, data.question_limit, [])
    options, correct_option = [], None
    reference_answer = None
    if question_type == "multiple_choice":
        mcq = question
        if not mcq:
            raise HTTPException(status_code=503, detail="The question service could not create a multiple-choice question. Check model access and free-tier availability, then retry or choose another interview category.")
        question, options, correct_option = mcq
    elif isinstance(question, dict):
        reference_answer = question["reference_answer"]
        question = question["question"]
    session = InterviewSession(user_id=user.id, category=data.category, language=data.language, focus=focus,
                               question_type=question_type, current_question=question,
                               current_options=options, current_correct_answer=correct_option,
                               current_reference_answer=reference_answer,
                               question_limit=data.question_limit)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "category": session.category, "language": session.language, "question": question,
            "generation_mode": mode,
            "focus": focus, "question_type": session.question_type, "question_limit": session.question_limit, "options": options,
            "language_note": None}


def active_session(session_id: int, user: User, db: Session) -> InterviewSession:
    session = db.get(InterviewSession, session_id)
    if not session or session.user_id != user.id or session.status != "active":
        raise HTTPException(status_code=404, detail="Active interview session not found")
    return session


@router.post("/sessions/{session_id}/next-question")
def next_question(session_id: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    session = active_session(session_id, user, db)
    answered_count = db.scalar(select(func.count(InterviewResponse.id)).where(InterviewResponse.session_id == session.id)) or 0
    if answered_count >= session.question_limit:
        raise HTTPException(status_code=409, detail="The requested number of questions is complete.")
    asked = list(db.scalars(select(InterviewResponse.question).where(InterviewResponse.session_id == session.id).order_by(InterviewResponse.id)).all())
    if session.current_question:
        asked.append(session.current_question)
    question, mode = _make_question(session.category, session.language, session.focus, session.question_type,
                                    answered_count, session.question_limit, asked)
    options, correct_option, reference_answer = [], None, None
    if session.question_type == "multiple_choice":
        mcq = question
        if not mcq:
            raise HTTPException(status_code=503, detail="The question service could not create another multiple-choice question. Check model access and free-tier availability, then retry.")
        question, options, correct_option = mcq
    elif isinstance(question, dict):
        reference_answer = question["reference_answer"]
        question = question["question"]
    session.current_question = question
    session.current_options = options
    session.current_correct_answer = correct_option
    session.current_reference_answer = reference_answer
    db.commit()
    return {"question": question, "options": options, "question_type": session.question_type, "generation_mode": mode,
            "question_limit": session.question_limit,
            "language_note": None}


def _practice_results(session: InterviewSession, db: Session):
    rows = db.scalars(select(InterviewResponse).where(InterviewResponse.session_id == session.id)
                      .order_by(InterviewResponse.id)).all()
    return [{"question": re.sub(r"\*\*", "", row.question), "answer": re.sub(r"\*\*", "", row.answer),
             "score": row.score, "feedback": row.feedback or {}}
            for row in rows]


def _complete_result(session: InterviewSession, db: Session):
    session.status = "completed"
    session.current_question = None
    session.current_options = []
    session.current_correct_answer = None
    session.current_reference_answer = None
    session.score = db.scalar(select(func.avg(InterviewResponse.score)).where(InterviewResponse.session_id == session.id))
    db.commit()
    results = _practice_results(session, db)
    correct_count = sum(1 for item in results if item["score"] == 1) if session.question_type == "multiple_choice" else None
    return {"id": session.id, "status": session.status, "completed": True, "answered_count": len(results),
            "question_limit": session.question_limit, "average_score": round(float(session.score), 2) if session.score is not None else None,
            "question_type": session.question_type, "correct_count": correct_count,
            "results": results}


@router.post("/sessions/{session_id}/responses")
def submit_answer(session_id: int, data: AnswerInput, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    session = active_session(session_id, user, db)
    if not session.current_question or data.question.strip() != session.current_question:
        raise HTTPException(status_code=409, detail="Answer must match the current session question")
    answer = data.answer.strip()
    if session.question_type == "multiple_choice":
        selected = answer.upper()
        valid_ids = {item.get("id") for item in (session.current_options or []) if isinstance(item, dict)}
        if selected not in valid_ids:
            raise HTTPException(status_code=422, detail="Choose one of the listed answer options.")
        selected_option = next(item["text"] for item in session.current_options if item.get("id") == selected)
        correct = selected == session.current_correct_answer
        correct_text = next((item["text"] for item in session.current_options if item.get("id") == session.current_correct_answer), "")
        score = 1.0 if correct else 0.0
        feedback = {
            "strengths": ["Correct choice: 1 point earned." if correct else "Incorrect choice: 0 points earned."],
            "improvements": [f"Correct answer: {session.current_correct_answer}. {correct_text}"],
            "assessment_note": "Answer check for practice only; this is not a recruiter assessment.",
            "options": session.current_options or [],
            "correct_option": session.current_correct_answer,
            "correct_text": correct_text,
            "selected_option": selected,
        }
        answer = f"{selected}. {selected_option}"
        record = InterviewResponse(session_id=session.id, question=data.question, answer=answer, feedback=feedback, score=score)
        db.add(record)
        db.flush()
        count = db.scalar(select(func.count(InterviewResponse.id)).where(InterviewResponse.session_id == session.id)) or 0
        if count >= session.question_limit:
            return _complete_result(session, db)
        asked = list(db.scalars(select(InterviewResponse.question).where(InterviewResponse.session_id == session.id).order_by(InterviewResponse.id)).all())
        next_payload, mode = _make_question(session.category, session.language, session.focus, session.question_type,
                                             count, session.question_limit, asked)
        if next_payload:
            next_question_text, next_options, next_correct = next_payload
            session.current_question = next_question_text
            session.current_options = next_options
            session.current_correct_answer = next_correct
            session.current_reference_answer = None
        else:
            session.current_question = None
            session.current_options = []
            session.current_correct_answer = None
            session.current_reference_answer = None
        db.commit()
        return {"completed": False, "answered_count": count, "question_limit": session.question_limit,
                "question": session.current_question, "options": session.current_options,
                "question_type": session.question_type, "generation_mode": mode}
    if len(answer) < 10:
        raise HTTPException(status_code=422, detail="Please write at least 10 characters for a typed answer.")
    sentences = [item for item in re.split(r"(?<=[.!?।॥])\s+", answer) if item]
    present = sorted(label for label, pattern in RUBRIC_SIGNALS[session.language]
                     if re.search(rf"(?<!\w)(?:{pattern})(?!\w)", answer, re.I))
    reference_answer = session.current_reference_answer
    if reference_answer:
        expected_tokens = {token.casefold() for token in re.findall(r"\w+", reference_answer) if len(token) > 2}
        answer_tokens = {token.casefold() for token in re.findall(r"\w+", answer) if len(token) > 2}
        overlap = len(expected_tokens & answer_tokens)
        precision = overlap / len(answer_tokens) if answer_tokens else 0
        recall = overlap / len(expected_tokens) if expected_tokens else 0
        score = round(5 * (2 * precision * recall / (precision + recall)) if precision + recall else 0, 1)
    else:
        score = min(5.0, round(1.0 + min(len(sentences), 4) * 0.35 + min(len(present), 4) * 0.3 + min(len(answer) / 500, 1), 1))
    copy = FEEDBACK_COPY[session.language]
    feedback = {
        "strengths": [copy["detailed"] if len(answer) > 120 else copy["addressed"]],
        "improvements": [copy["structure"] if len(present) < 3 else copy["outcome"]],
        "rubric_signals": present,
        "assessment_note": copy["note"],
    }
    if reference_answer:
        feedback["correct_answer"] = reference_answer
    record = InterviewResponse(session_id=session.id, question=data.question, answer=answer, feedback=feedback, score=score)
    db.add(record)
    db.flush()
    count = db.scalar(select(func.count(InterviewResponse.id)).where(InterviewResponse.session_id == session.id)) or 0
    if count >= session.question_limit:
        try:
            ai_feedback = review_answer(data.question, answer, session.language, reference_answer)
            if ai_feedback:
                record.score = ai_feedback["score"]
                record.feedback = {**ai_feedback, "correct_answer": reference_answer or ai_feedback.get("correct_answer"),
                                   "rubric_signals": present}
        except Exception:
            pass
        return _complete_result(session, db)

    asked = list(db.scalars(select(InterviewResponse.question).where(InterviewResponse.session_id == session.id).order_by(InterviewResponse.id)).all())
    with ThreadPoolExecutor(max_workers=2) as executor:
        feedback_future = executor.submit(review_answer, data.question, answer, session.language, reference_answer)
        question_future = executor.submit(_make_question, session.category, session.language, session.focus,
                                         session.question_type, count, session.question_limit, asked)
        try:
            ai_feedback = feedback_future.result()
            if ai_feedback:
                record.score = ai_feedback["score"]
                record.feedback = {**ai_feedback, "correct_answer": reference_answer or ai_feedback.get("correct_answer"),
                                   "rubric_signals": present}
        except Exception:
            pass
        try:
            next_payload, mode = question_future.result()
        except Exception:
            next_payload, mode = None, "curated-question-bank"
    if next_payload:
        if session.question_type == "multiple_choice":
            next_question_text, next_options, next_correct = next_payload
            next_reference_answer = None
        elif isinstance(next_payload, dict):
            next_question_text, next_options, next_correct = next_payload["question"], [], None
            next_reference_answer = next_payload["reference_answer"]
        else:
            next_question_text, next_options, next_correct, next_reference_answer = next_payload, [], None, None
        session.current_question = next_question_text
        session.current_options = next_options
        session.current_correct_answer = next_correct
        session.current_reference_answer = next_reference_answer
    else:
        session.current_question = None
        session.current_options = []
        session.current_correct_answer = None
        session.current_reference_answer = None
    db.commit()
    return {"completed": False, "answered_count": count, "question_limit": session.question_limit,
            "question": session.current_question, "options": session.current_options,
            "question_type": session.question_type, "generation_mode": mode}


@router.post("/sessions/{session_id}/complete")
def complete_session(session_id: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    session = active_session(session_id, user, db)
    return _complete_result(session, db)


@router.get("/history")
def history(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    rows = db.scalars(select(InterviewSession).where(InterviewSession.user_id == user.id).order_by(InterviewSession.created_at.desc())).all()
    response_stats = {}
    if rows:
        stats = db.execute(select(InterviewResponse.session_id, func.count(InterviewResponse.id),
                                  func.avg(InterviewResponse.score), func.max(InterviewResponse.created_at))
                           .where(InterviewResponse.session_id.in_([s.id for s in rows]))
                           .group_by(InterviewResponse.session_id)).all()
        response_stats = {session_id: {"response_count": count, "average_score": round(float(average), 2) if average is not None else None,
                                       "last_response_at": last_response}
                          for session_id, count, average, last_response in stats}
    return [{"id": s.id, "category": s.category, "language": s.language, "focus": s.focus,
             "question_type": s.question_type,
             "status": s.status, "average_score": s.score, "question_limit": s.question_limit,
             "response_count": response_stats.get(s.id, {}).get("response_count", 0),
             "last_response_at": response_stats.get(s.id, {}).get("last_response_at"), "created_at": s.created_at}
            for s in rows]


@router.get("/history/{session_id}")
def history_detail(session_id: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    session = db.get(InterviewSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Practice session not found")
    if session.status != "completed":
        raise HTTPException(status_code=409, detail="Practice answers are available after the session is complete")
    results = _practice_results(session, db)
    return {"id": session.id, "category": session.category, "language": session.language,
            "focus": session.focus, "question_type": session.question_type, "question_limit": session.question_limit,
            "status": session.status, "average_score": session.score, "answered_count": len(results),
            "results": results}


@router.delete("/history/{session_id}", status_code=204)
def delete_history(session_id: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    session = db.scalar(select(InterviewSession).where(
        InterviewSession.id == session_id, InterviewSession.user_id == user.id,
    ))
    if not session:
        raise HTTPException(status_code=404, detail="Practice session not found")
    # Explicit child deletion keeps local SQLite behavior aligned with PostgreSQL
    # even when SQLite foreign-key enforcement is disabled.
    db.execute(delete(InterviewResponse).where(InterviewResponse.session_id == session.id))
    db.delete(session)
    db.commit()
    return Response(status_code=204)
