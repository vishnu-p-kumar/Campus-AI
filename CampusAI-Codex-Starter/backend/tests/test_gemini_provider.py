from types import SimpleNamespace

import pytest

from app.ai import gemini
from app.core.config import settings


def test_default_gemini_model_uses_the_current_low_cost_replacement():
    from app.core.config import Settings

    assert Settings.model_fields["gemini_model"].default == "gemini-3.5-flash-lite"
    assert Settings.model_fields["gemini_fallback_models"].default == "gemini-3.1-flash-lite"
