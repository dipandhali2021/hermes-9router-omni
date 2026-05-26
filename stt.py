"""9router STT provider for Hermes (monkey-patch).

Hermes has no STT plugin API — ``tools/transcription_tools.py::transcribe_audio``
dispatches via a hardcoded if/elif chain over a small set of provider names.
We install a wrapper that intercepts the call when the user has set
``stt.provider: 9router`` in ``~/.hermes/config.yaml``; other providers
fall through to the original dispatcher.

9router endpoint: ``POST /v1/audio/transcriptions`` (OpenAI-compatible) with
a ``multipart/form-data`` body carrying ``model``, ``file`` (the audio
upload), and optional ``language`` / ``prompt`` / ``response_format`` /
``temperature``. Response is JSON: ``{"text": "..."}``.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from typing import Any, Dict, Optional

from ._http import is_configured, post_form

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/whisper-1"
PROVIDER_NAME = "9router"

_AUDIO_MIME_OVERRIDES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
}


def _load_9router_stt_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("stt") if isinstance(cfg, dict) else None
        if not isinstance(section, dict):
            return {}
        sub = section.get("9router")
        return sub if isinstance(sub, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not load stt.9router config: %s", exc)
        return {}


def _resolve_model(override: Optional[str]) -> str:
    if isinstance(override, str) and override.strip():
        return override.strip()
    cfg = _load_9router_stt_config()
    model = cfg.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return DEFAULT_MODEL


def _guess_mime(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _AUDIO_MIME_OVERRIDES:
        return _AUDIO_MIME_OVERRIDES[ext]
    guess, _ = mimetypes.guess_type(file_path)
    return guess or "application/octet-stream"


def _transcribe_9router(file_path: str, model: Optional[str]) -> Dict[str, Any]:
    if not is_configured():
        return {
            "success": False,
            "transcript": "",
            "error": (
                "9router not configured. Set NINEROUTER_BASE_URL and "
                "NINEROUTER_API_KEY in ~/.hermes/.env."
            ),
            "provider": PROVIDER_NAME,
        }

    resolved_model = _resolve_model(model)
    cfg = _load_9router_stt_config()
    data: Dict[str, Any] = {"model": resolved_model}

    for key in ("language", "prompt", "response_format"):
        value = cfg.get(key)
        if isinstance(value, str) and value.strip():
            data[key] = value.strip()
    temperature = cfg.get("temperature")
    if isinstance(temperature, (int, float)):
        data["temperature"] = temperature

    logger.info("9router STT: model=%s file=%s", resolved_model, file_path)
    try:
        response = post_form(
            "/v1/audio/transcriptions",
            data=data,
            file_field="file",
            file_path=file_path,
            file_mime=_guess_mime(file_path),
            timeout=300,
        )
    except ValueError as exc:  # missing env
        return {
            "success": False,
            "transcript": "",
            "error": str(exc),
            "provider": PROVIDER_NAME,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("9router STT error: %s", exc)
        return {
            "success": False,
            "transcript": "",
            "error": f"9router STT failed: {exc}",
            "provider": PROVIDER_NAME,
        }

    text = ""
    if isinstance(response, dict):
        if isinstance(response.get("text"), str):
            text = response["text"]
        elif isinstance(response.get("_raw"), str):
            text = response["_raw"]
    elif isinstance(response, str):
        text = response

    return {
        "success": True,
        "transcript": text,
        "provider": PROVIDER_NAME,
        "model": resolved_model,
    }


# ---------------------------------------------------------------------------
# Monkey-patch installer
# ---------------------------------------------------------------------------


def install_stt_patch() -> None:
    from tools import transcription_tools

    if getattr(transcription_tools.transcribe_audio, "_9router_patched", False):
        return

    original = transcription_tools.transcribe_audio

    def patched_transcribe_audio(
        file_path: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            stt_config = transcription_tools._load_stt_config()
            provider = transcription_tools._get_provider(stt_config)
        except Exception:  # noqa: BLE001
            return original(file_path, model)

        if provider != "9router":
            return original(file_path, model)

        # Validate the audio file via Hermes' own helper so the error
        # shape matches what the rest of the codebase expects.
        validation_error = transcription_tools._validate_audio_file(file_path)
        if validation_error:
            return validation_error

        if not transcription_tools.is_stt_enabled(stt_config):
            return {
                "success": False,
                "transcript": "",
                "error": "STT is disabled in config.yaml (stt.enabled: false).",
            }

        return _transcribe_9router(file_path, model)

    patched_transcribe_audio._9router_patched = True  # type: ignore[attr-defined]
    transcription_tools.transcribe_audio = patched_transcribe_audio
