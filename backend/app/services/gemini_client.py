"""
services/gemini_client.py
─────────────────────────────────────────────────────────────────────────────
One place that talks to Gemini, so per-request API keys stay per-request.

THE BUG THIS EXISTS TO FIX
──────────────────────────
The legacy `google-generativeai` package configures the API key as MODULE
GLOBAL state:

    genai.configure(api_key=...)          # process-wide
    model = genai.GenerativeModel(...)    # resolves the key lazily, at call time

In a single-user script that is fine. In an async server handling concurrent
requests it is a cross-tenant key leak: request A calls configure() with A's
key, request B calls configure() with B's key, then A's generation executes and
picks up whichever key was configured most recently. For a bring-your-own-key
product this is the worst available bug, because the entire promise is that a
user's key is used only for that user's work.

The correct fix is the newer `google-genai` package, where the key belongs to a
client instance:

    client = genai.Client(api_key=user_key)   # no global state anywhere

That package is not installed here yet, and swapping a dependency out from
under a deployment that currently works is its own hazard. So this module picks
the best available option at import time:

  * `google-genai` present  -> per-request Client. Fully concurrent, no leak.
  * only the legacy package -> a process-wide lock serialises
    configure()+generate() into one atomic section. Correct, but concurrent
    requests queue behind each other.

Installing `google-genai` (already added to requirements.txt) removes the lock
automatically with no code change. The legacy package additionally prints
"All support for the google.generativeai package has ended" on import, so it
should not be relied on for long.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from .model_config import bare_model_name

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# BACKEND SELECTION
# ─────────────────────────────────────────────────────────────────────────────
_BACKEND: str
try:
    from google import genai as _genai_new  # type: ignore
    from google.genai import types as _genai_types  # type: ignore
    _BACKEND = "google-genai"
except ImportError:  # pragma: no cover - depends on environment
    _genai_new = None  # type: ignore
    _genai_types = None  # type: ignore
    try:
        import google.generativeai as _genai_legacy  # type: ignore
        _BACKEND = "legacy"
    except ImportError:
        _genai_legacy = None  # type: ignore
        _BACKEND = "none"


def backend_name() -> str:
    return _BACKEND


def legacy_lock():
    """
    The lock guarding legacy global configure().

    Exposed so the few operations that must call the legacy SDK directly (the
    explicit context-cache create and delete, which have no wrapper here) can
    hold the same lock. Anything touching genai.configure() outside this lock
    reintroduces the cross-request key leak.
    """
    return _legacy_lock


# Serialises configure()+generate() on the legacy SDK. Only ever contended when
# running on the deprecated package.
_legacy_lock = threading.Lock()


@dataclass
class GenerationResult:
    text: str
    cached_tokens: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    raw: Any = field(default=None, repr=False)


def _extract_usage(response: Any) -> tuple[int, int, int]:
    """Pull real token counts out of whichever response shape we got."""
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0, 0
    cached = int(getattr(usage, "cached_content_token_count", 0) or 0)
    prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
    output = int(
        getattr(usage, "candidates_token_count", 0)
        or getattr(usage, "response_token_count", 0)
        or 0
    )
    return cached, prompt, output


def _extract_text(response: Any) -> str:
    """
    Get the visible answer out of a response.

    Gemini raises rather than returning empty when a response has no simple
    text part (safety stop, tool call, or a thinking-only completion), so the
    candidate walk is a real fallback and not defensive noise.
    """
    try:
        text = response.text
        if text:
            return text
    except Exception:  # noqa: BLE001
        pass

    try:
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", None) or []:
                part_text = getattr(part, "text", None)
                if part_text:
                    return part_text
    except Exception:  # noqa: BLE001
        pass

    return ""


def _uses_thinking_levels(model: str) -> bool:
    """
    Return whether a model follows the current Gemini request contract.

    Gemini 3.6 Flash and Gemini 3.5 Flash-Lite replaced numeric thinking
    budgets with thinking levels and deprecated sampling parameters.
    """
    name = bare_model_name(model)
    return name.startswith("gemini-3.6-") or name.startswith("gemini-3.5-flash-lite")


def _thinking_level_for_budget(thinking_budget: int | None) -> str | None:
    """Map the old routing budgets onto the supported current model levels."""
    if thinking_budget is None:
        return None
    return "medium" if thinking_budget >= 1536 else "low"


def _google_config_kwargs(
    *,
    model: str,
    system_instruction: str | None,
    temperature: float,
    max_output_tokens: int,
    thinking_budget: int | None,
    cached_content: str | None,
) -> dict[str, Any]:
    """Build a GenerateContentConfig that matches the selected model family."""
    modern_contract = _uses_thinking_levels(model)
    config_kwargs: dict[str, Any] = {
        "max_output_tokens": max_output_tokens,
    }
    if not modern_contract:
        config_kwargs["temperature"] = temperature
    if system_instruction and not cached_content:
        config_kwargs["system_instruction"] = system_instruction
    if cached_content:
        config_kwargs["cached_content"] = cached_content
    if thinking_budget is not None:
        try:
            thinking_kwargs = (
                {"thinking_level": _thinking_level_for_budget(thinking_budget)}
                if modern_contract
                else {"thinking_budget": thinking_budget}
            )
            config_kwargs["thinking_config"] = _genai_types.ThinkingConfig(
                **thinking_kwargs
            )
        except Exception:  # noqa: BLE001 - older SDK builds omit these fields
            pass
    return config_kwargs


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────
def generate_sync(
    api_key: str,
    model: str,
    contents: list[dict],
    system_instruction: str | None = None,
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    thinking_budget: int | None = None,
    cached_content: str | None = None,
) -> GenerationResult:
    """
    Blocking generation. Call via `generate()` from async code.

    ``thinking_budget`` remains the internal routing interface for compatibility.
    Current models receive a mapped thinking level; older models receive the
    numeric token budget they expect.
    """
    if _BACKEND == "none":
        raise RuntimeError(
            "No Gemini SDK installed. Run: pip install google-genai"
        )

    if _BACKEND == "google-genai":
        client = _genai_new.Client(api_key=api_key)  # per-call, no global state

        config_kwargs = _google_config_kwargs(
            model=model,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            cached_content=cached_content,
        )

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=_genai_types.GenerateContentConfig(**config_kwargs),
        )
    else:
        # Legacy path: the lock makes configure()+generate() atomic so a
        # concurrent request cannot swap the global key in between.
        with _legacy_lock:
            _genai_legacy.configure(api_key=api_key)
            generation_kwargs: dict[str, Any] = {
                "max_output_tokens": max_output_tokens,
            }
            if not _uses_thinking_levels(model):
                generation_kwargs["temperature"] = temperature
            gen_config = _genai_legacy.GenerationConfig(**generation_kwargs)
            if cached_content:
                from google.generativeai import caching as _caching  # type: ignore
                handle = _caching.CachedContent.get(cached_content)
                model_obj = _genai_legacy.GenerativeModel.from_cached_content(
                    cached_content=handle,
                    generation_config=gen_config,
                )
            else:
                model_obj = _genai_legacy.GenerativeModel(
                    model_name=model,
                    system_instruction=system_instruction,
                    generation_config=gen_config,
                )
            response = model_obj.generate_content(contents)

    cached, prompt_tokens, output_tokens = _extract_usage(response)
    return GenerationResult(
        text=_extract_text(response),
        cached_tokens=cached,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        raw=response,
    )


async def generate(
    api_key: str,
    model: str,
    contents: list[dict],
    system_instruction: str | None = None,
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    thinking_budget: int | None = None,
    cached_content: str | None = None,
) -> GenerationResult:
    """Async wrapper. Both SDKs are synchronous, so this runs in a thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: generate_sync(
            api_key=api_key,
            model=model,
            contents=contents,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            cached_content=cached_content,
        ),
    )


def stream_sync(
    api_key: str,
    model: str,
    contents: list[dict],
    system_instruction: str | None = None,
    temperature: float = 0.7,
    max_output_tokens: int = 2048,
    thinking_budget: int | None = None,
    cached_content: str | None = None,
):
    """
    Yield text fragments as the model produces them.

    Streaming is what makes voice viable. The old pipeline ran three full
    completions in series (recognise, generate everything, synthesise every
    sentence), giving a floor around 8 to 30 seconds to first audio. No amount
    of tuning any single stage fixes that, because the problem is the shape.
    Streaming lets sentence one reach the speaker while sentence three is still
    being written.
    """
    if _BACKEND == "none":
        raise RuntimeError("No Gemini SDK installed. Run: pip install google-genai")

    if _BACKEND == "google-genai":
        client = _genai_new.Client(api_key=api_key)
        config_kwargs = _google_config_kwargs(
            model=model,
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_budget=thinking_budget,
            cached_content=cached_content,
        )

        for chunk in client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=_genai_types.GenerateContentConfig(**config_kwargs),
        ):
            piece = getattr(chunk, "text", None)
            if piece:
                yield piece
    else:
        with _legacy_lock:
            _genai_legacy.configure(api_key=api_key)
            generation_kwargs: dict[str, Any] = {
                "max_output_tokens": max_output_tokens,
            }
            if not _uses_thinking_levels(model):
                generation_kwargs["temperature"] = temperature
            gen_config = _genai_legacy.GenerationConfig(**generation_kwargs)
            if cached_content:
                from google.generativeai import caching as _caching  # type: ignore
                handle = _caching.CachedContent.get(cached_content)
                model_obj = _genai_legacy.GenerativeModel.from_cached_content(
                    cached_content=handle, generation_config=gen_config,
                )
            else:
                model_obj = _genai_legacy.GenerativeModel(
                    model_name=model,
                    system_instruction=system_instruction,
                    generation_config=gen_config,
                )
            for chunk in model_obj.generate_content(contents, stream=True):
                try:
                    piece = chunk.text
                except Exception:  # noqa: BLE001 - empty/safety chunks raise
                    piece = None
                if piece:
                    yield piece


def log_backend_once() -> None:
    if _BACKEND == "google-genai":
        logger.info("Gemini SDK: google-genai (per-request clients, fully concurrent)")
    elif _BACKEND == "legacy":
        logger.warning(
            "Gemini SDK: legacy google-generativeai. Calls are serialised by a "
            "process lock to prevent cross-request API key bleed. "
            "Install google-genai to remove this bottleneck."
        )
    else:
        logger.error("No Gemini SDK installed. Generation will fail.")
