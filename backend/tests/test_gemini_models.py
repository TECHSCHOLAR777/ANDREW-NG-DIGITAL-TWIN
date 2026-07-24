"""Regression tests for Gemini model lifecycle and request-contract handling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import gemini_client, model_config  # noqa: E402


def test_defaults_use_current_stable_models():
    assert model_config.GENERATION_MODEL == "gemini-3.6-flash"
    assert model_config.UTILITY_MODEL == "gemini-3.5-flash-lite"
    assert model_config.REWRITE_MODEL == model_config.UTILITY_MODEL
    assert model_config.TRIPLET_MODEL == model_config.UTILITY_MODEL


def test_current_models_use_thinking_levels():
    assert gemini_client._uses_thinking_levels("gemini-3.6-flash")
    assert gemini_client._uses_thinking_levels("models/gemini-3.6-flash")
    assert gemini_client._uses_thinking_levels("gemini-3.5-flash-lite")
    assert not gemini_client._uses_thinking_levels("gemini-2.5-flash")


def test_routing_budgets_map_to_supported_levels():
    assert gemini_client._thinking_level_for_budget(None) is None
    assert gemini_client._thinking_level_for_budget(0) == "low"
    assert gemini_client._thinking_level_for_budget(512) == "low"
    assert gemini_client._thinking_level_for_budget(2048) == "medium"


def test_legacy_cache_model_is_qualified_once():
    assert (
        model_config.legacy_cache_model_name("gemini-3.6-flash")
        == "models/gemini-3.6-flash"
    )
    assert (
        model_config.legacy_cache_model_name("models/gemini-3.6-flash")
        == "models/gemini-3.6-flash"
    )


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
