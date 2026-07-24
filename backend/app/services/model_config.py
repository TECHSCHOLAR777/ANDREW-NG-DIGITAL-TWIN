"""
Current Gemini model configuration.

Keep model selection in one place so the answer, query-rewrite, and graph-
extraction paths cannot silently drift onto different retired defaults.
"""

from __future__ import annotations

import os


DEFAULT_GENERATION_MODEL = "gemini-3.6-flash"
DEFAULT_UTILITY_MODEL = "gemini-3.5-flash-lite"


def _env_model(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


GENERATION_MODEL = _env_model("GEMINI_MODEL", DEFAULT_GENERATION_MODEL)
UTILITY_MODEL = _env_model("GEMINI_UTILITY_MODEL", DEFAULT_UTILITY_MODEL)
REWRITE_MODEL = _env_model("REWRITE_MODEL", UTILITY_MODEL)
TRIPLET_MODEL = _env_model("GEMINI_TRIPLET_MODEL", UTILITY_MODEL)


def bare_model_name(model: str) -> str:
    """Return the API model id without the optional ``models/`` prefix."""
    return model.removeprefix("models/")


def legacy_cache_model_name(model: str) -> str:
    """The deprecated caching SDK requires the fully-qualified model name."""
    return f"models/{bare_model_name(model)}"
