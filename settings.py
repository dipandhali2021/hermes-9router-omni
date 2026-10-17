"""Pure defaults + config resolution for 9router-omni. No Hermes imports at
module load time.

Everything in this module is deterministic and side-effect free so the test
suite can exercise it without a Hermes install. ``load_hermes_config()`` is
the only function that touches Hermes, and it imports lazily and fails soft.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

PROVIDER_NAME = "9router"

DEFAULT_SEARCH_MODEL = "openclaw-search"
DEFAULT_FETCH_MODEL = "openclaw-fetch"
DEFAULT_TTS_MODEL = "tts-combo"
DEFAULT_STT_MODEL = "stt-combo"
DEFAULT_IMAGE_MODEL = "image-combo"

TTS_VOICE_SUGGESTIONS = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")


def load_hermes_config() -> Dict[str, Any]:
    """Return ``hermes_cli.config.load_config()``, or ``{}`` on any failure.

    Lazy import keeps this module Hermes-free for tests and pickers.
    """
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _text(value: Any) -> Optional[str]:
    """Stripped non-empty string, else None."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _nested(cfg: Any, *keys: str) -> Optional[str]:
    """Walk nested dicts safely; return the final value as text (or None)."""
    node: Any = cfg
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return _text(node)


def resolve_search_model(cfg: Any) -> str:
    """web.9router.search_model -> DEFAULT_SEARCH_MODEL."""
    return _nested(cfg, "web", "9router", "search_model") or DEFAULT_SEARCH_MODEL


def resolve_fetch_model(cfg: Any) -> str:
    """web.9router.fetch_model -> DEFAULT_FETCH_MODEL."""
    return _nested(cfg, "web", "9router", "fetch_model") or DEFAULT_FETCH_MODEL


def resolve_tts_model(cfg: Any) -> str:
    """tts.model -> tts.9router.model -> DEFAULT_TTS_MODEL."""
    return (
        _nested(cfg, "tts", "model")
        or _nested(cfg, "tts", "9router", "model")
        or DEFAULT_TTS_MODEL
    )


def resolve_stt_model(cfg: Any) -> str:
    """stt.9router.model -> DEFAULT_STT_MODEL."""
    return _nested(cfg, "stt", "9router", "model") or DEFAULT_STT_MODEL


def resolve_image_model(cfg: Any) -> str:
    """image_gen.model -> image_gen.9router.model -> DEFAULT_IMAGE_MODEL."""
    return (
        _nested(cfg, "image_gen", "model")
        or _nested(cfg, "image_gen", "9router", "model")
        or DEFAULT_IMAGE_MODEL
    )


def compose_tts_model(model: str, voice: Optional[str]) -> str:
    """Compose ``<model>/<voice>`` at call time.

    No-op when no voice is set or the model already ends with the voice.
    Combo models are not special-cased (no silent drop): a hand-edited
    combo+voice config reaches the gateway, whose error surfaces normally.
    """
    normalized = _text(voice)
    if not normalized:
        return model
    if model.endswith(f"/{normalized}"):
        return model
    return f"{model}/{normalized}"


def build_transcription_fields(
    model: str, language: Optional[str], cfg: Any
) -> Dict[str, Any]:
    """Assemble the multipart form fields for /v1/audio/transcriptions.

    ``language`` argument wins over ``stt.9router.language``; prompt /
    response_format pass through when non-empty strings; temperature passes
    through when numeric (bool excluded).
    """
    fields: Dict[str, Any] = {"model": model}

    lang = _text(language) or _nested(cfg, "stt", "9router", "language")
    if lang:
        fields["language"] = lang

    for key in ("prompt", "response_format"):
        value = _nested(cfg, "stt", "9router", key)
        if value:
            fields[key] = value

    temperature: Any = cfg
    for key in ("stt", "9router", "temperature"):
        temperature = temperature.get(key) if isinstance(temperature, dict) else None
    if isinstance(temperature, (int, float)) and not isinstance(temperature, bool):
        fields["temperature"] = temperature

    return fields


def ext_for_content_type(content_type: str) -> str:
    """Map an audio content type to a file extension (default mp3)."""
    ct = (content_type or "").lower()
    if "mpeg" in ct or "mp3" in ct:
        return "mp3"
    if "wav" in ct:
        return "wav"
    if "ogg" in ct or "opus" in ct:
        return "ogg"
    if "webm" in ct:
        return "webm"
    if "flac" in ct:
        return "flac"
    return "mp3"
