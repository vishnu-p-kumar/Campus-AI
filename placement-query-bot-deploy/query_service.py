"""The original placement bot routing and answer flow, without a UI dependency."""

from datetime import date
import contextlib
import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

BOT_DIRECTORY = Path(__file__).parent
# Prefer the bot's own file for standalone runs, then load CampusAI's local
# backend settings when this shared service runs inside the CampusAI process.
load_dotenv(BOT_DIRECTORY / ".env", override=False)
load_dotenv(BOT_DIRECTORY.parent / "CampusAI-Codex-Starter" / "backend" / ".env", override=False)

from log_store import log_entry
from query_store import get_query_count, update_query_count
from router import router

MAX_QUERIES = 25
_initialized = False
_initialization_lock = Lock()
_counter_lock = Lock()
_local_counter_day = date.today()
_local_query_count = 0


def initialize() -> None:
    global _initialized
    if _initialized:
        return
    with _initialization_lock:
        if _initialized:
            return
        from faq import process_folder

        folder = BOT_DIRECTORY / "resources" / "placement_texts"
        with contextlib.redirect_stdout(None):
            list(process_folder(folder, reset=False))
        _initialized = True


def get_usage() -> dict[str, int | str]:
    """Report the original bot's shared daily allowance and reset date."""
    global _local_counter_day, _local_query_count
    with _counter_lock:
        today = date.today()
        if os.getenv("JSONBIN_BIN_ID") and os.getenv("JSONBIN_API_KEY"):
            count = get_query_count()
        else:
            if _local_counter_day != today:
                _local_counter_day, _local_query_count = today, 0
            count = _local_query_count
    count = max(0, int(count or 0))
    return {
        "queries_used": count,
        "daily_query_limit": MAX_QUERIES,
        "queries_remaining": max(0, MAX_QUERIES - count),
        "reset_date": str(today),
    }


def ask(
    query: str,
    *,
    answer_override: str | None = None,
    knowledge_sources: list[dict] | None = None,
    log_query: bool = True,
) -> dict[str, str | float | int]:
    """Keep the deployed bot's FAQ / SQL / other routing and shared daily limit."""
    global _local_counter_day, _local_query_count
    route_obj = router(query)
    if answer_override is not None or knowledge_sources:
        # Admin-approved documents and CampusAI company records use the bot's
        # grounded FAQ answer path, even if the general router labels a query SQL.
        route_obj.name = "faq"
        route_obj.score = max(float(route_obj.score), 0.65)
    with _counter_lock:
        if os.getenv("JSONBIN_BIN_ID") and os.getenv("JSONBIN_API_KEY"):
            count = get_query_count()
            if count >= MAX_QUERIES:
                return {"answer": "⚠️ Sorry, the total query limit for today has been reached. Please try again tomorrow.",
                        "route": "limit", "score": 0.0, "queries_used": count,
                        "daily_query_limit": MAX_QUERIES, "queries_remaining": 0,
                        "reset_date": str(date.today())}
            update_query_count(count + 1)
            queries_used = count + 1
        else:
            today = date.today()
            if _local_counter_day != today:
                _local_counter_day, _local_query_count = today, 0
            if _local_query_count >= MAX_QUERIES:
                return {"answer": "⚠️ Sorry, the total query limit for today has been reached. Please try again tomorrow.",
                        "route": "limit", "score": 0.0, "queries_used": _local_query_count,
                        "daily_query_limit": MAX_QUERIES, "queries_remaining": 0,
                        "reset_date": str(today)}
            _local_query_count += 1
            queries_used = _local_query_count
    if answer_override is not None:
        answer = answer_override
    elif route_obj.name == "faq" and knowledge_sources:
        from faq import generate_answer

        answer, _sources = generate_answer(query, external_sources=knowledge_sources)
    elif route_obj.name == "faq":
        # SQL and out-of-scope questions do not need to load the embedding model.
        from faq import generate_answer

        initialize()
        answer, _sources = generate_answer(query)
    elif route_obj.name == "sql":
        from sql import sql_chain

        answer = sql_chain(query)
    else:
        answer = ("I'm designed to answer queries about placements and related details. "
                  "Please try asking about training, vision & mission, faculty, or hiring statistics.")
    if log_query:
        try:
            log_entry(query=query, response=answer, route=route_obj.name, score=route_obj.score)
        except Exception:
            # Query logging is optional in the original app and must not break answers.
            pass
    return {
        "answer": str(answer),
        "route": route_obj.name,
        "score": float(route_obj.score),
        "queries_used": queries_used,
        "daily_query_limit": MAX_QUERIES,
        "queries_remaining": max(0, MAX_QUERIES - queries_used),
        "reset_date": str(date.today()),
    }
