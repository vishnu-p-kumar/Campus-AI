"""Load the placement-query-bot backend used by the standalone deployment."""

import importlib
import os
from pathlib import Path
import sys
from typing import Any


def _bot_directory() -> Path:
    configured = os.getenv("PLACEMENT_QUERY_BOT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    # Repository layout: CampusAI-Codex-Starter/backend/app and sibling bot project.
    return Path(__file__).resolve().parents[3] / "placement-query-bot-deploy"


def ask(question: str, **options: Any) -> dict[str, Any]:
    service = _load_service()
    return service.ask(question, **options)


def get_usage() -> dict[str, Any]:
    """Expose the placement bot's shared daily usage counter to CampusAI."""
    service = _load_service()
    return service.get_usage()


def _load_service():
    bot_directory = _bot_directory()
    if not (bot_directory / "query_service.py").is_file():
        raise RuntimeError("Placement query bot backend files were not found")
    bot_path = str(bot_directory)
    if bot_path not in sys.path:
        sys.path.insert(0, bot_path)
    return importlib.import_module("query_service")
