"""Native Hermes transcription (STT) provider backed by a 9router gateway.

Registered through ``ctx.register_transcription_provider`` (Hermes v0.17+).
The old dispatcher monkey-patch is gone.

Endpoint: ``POST /v1/audio/transcriptions`` (OpenAI-compatible) with a
``multipart/form-data`` body carrying ``model``, ``file``, and optional
``language`` / ``prompt`` / ``response_format`` / ``temperature`` from
``stt.9router.*``. Response JSON: ``{"text": "..."}``.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from typing import Any, Dict, List, Optional

from agent.transcription_provider import TranscriptionProvider

from ._http import is_configured, post_form
from .catalog import fetch_catalog
from .settings import (
    DEFAULT_STT_MODEL,
    PROVIDER_NAME,
    build_transcription_fields,
    load_hermes_config,
    resolve_stt_model,
)

logger = logging.getLogger(__name__)

STT_FALLBACK_MODELS = (
    DEFAULT_STT_MODEL,
    "groq/whisper-large-v3",
    "openai/gpt-4o-transcribe",
)

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


def guess_mime(file_path: str) -> str:
    """Content type for an audio file: explicit overrides, then mimetypes."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _AUDIO_MIME_OVERRIDES:
        return _AUDIO_MIME_OVERRIDES[ext]
    guess, _ = mimetypes.guess_type(file_path)
    return guess or "application/octet-stream"


class NineRouterTranscriptionProvider(TranscriptionProvider):
    """Speech-to-text via the gateway's ``/v1/audio/transcriptions`` endpoint."""

    name = PROVIDER_NAME
    display_name = PROVIDER_NAME

    def is_available(self) -> bool:
        return is_configured()

    def transcribe(
        self,
        file_path: str,
        *,
        model: Optional[str] = None,
        language: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """Transcribe an audio file; returns the standard envelope, never raises."""
        if not is_configured():
            return {
                "success": False,
                "transcript": "",
                "error": (
                    "NINEROUTER_BASE_URL is not set — configure the 9router "
                    "gateway first (hermes 9router setup, or ~/.hermes/.env)."
                ),
                "provider": PROVIDER_NAME,
            }

        try:
            cfg = load_hermes_config()
            resolved = model or resolve_stt_model(cfg)
            data = build_transcription_fields(resolved, language, cfg)
            logger.info("9router STT: model=%s file=%s", resolved, file_path)
            response = post_form(
                "/v1/audio/transcriptions",
                data=data,
                file_field="file",
                file_path=file_path,
                file_mime=guess_mime(file_path),
                timeout=300,
            )
        except Exception as exc:  # noqa: BLE001 — envelope contract, never raise
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
            "model": resolved,
        }

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            entries = fetch_catalog("stt")
        except Exception as exc:  # unreachable gateway, bad key, junk payload…
            logger.debug("9router STT catalog unavailable: %s", exc)
            entries = []
        if not entries:
            return [
                {"id": model_id, "display": model_id}
                for model_id in STT_FALLBACK_MODELS
            ]
        return [
            {
                "id": entry.id,
                "display": entry.id + (" (combo)" if entry.is_combo else ""),
            }
            for entry in entries
        ]

    def default_model(self) -> str:
        return DEFAULT_STT_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": PROVIDER_NAME,
            "badge": "self-hosted",
            "tag": "Self-hosted 9router gateway — proxies /v1/audio/transcriptions.",
            "env_vars": [
                {
                    "key": "NINEROUTER_BASE_URL",
                    "prompt": "9router gateway base URL (e.g. http://127.0.0.1:20128)",
                },
                {
                    "key": "NINEROUTER_API_KEY",
                    "prompt": "9router API key (optional — leave empty for keyless gateways)",
                },
            ],
        }
