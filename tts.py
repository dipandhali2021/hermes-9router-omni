"""Native Hermes TTS provider backed by a 9router gateway.

Registered through ``ctx.register_tts_provider`` (Hermes v0.17+). The old
dispatcher monkey-patch approach is gone — this module is a plain
``TTSProvider`` subclass.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.tts_provider import TTSProvider

from ._http import is_configured, post_json_bytes
from .catalog import fetch_catalog
from .settings import (
    DEFAULT_TTS_MODEL,
    PROVIDER_NAME,
    compose_tts_model,
    ext_for_content_type,
    load_hermes_config,
    resolve_tts_model,
)

logger = logging.getLogger(__name__)

TTS_FALLBACK_MODELS = ("tts-combo", "openai/tts-1", "openai/gpt-4o-mini-tts")


class NineRouterTTSProvider(TTSProvider):
    """Text-to-speech via the gateway's ``/v1/audio/speech`` endpoint."""

    name = PROVIDER_NAME
    display_name = PROVIDER_NAME

    @property
    def voice_compatible(self) -> bool:  # type: ignore[override]
        """False: the wizard decides per model.

        A global passthrough would compose voices onto combo models, which
        the gateway rejects; non-combo models get their voice composed into
        the model id at synthesize time.
        """
        return False

    def is_available(self) -> bool:
        return is_configured()

    def synthesize(
        self,
        text: str,
        output_path: str,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        speed: Optional[float] = None,
        format: str = "mp3",
        **extra: Any,
    ) -> str:
        """Synthesize ``text`` to ``output_path``; return the final path."""
        resolved = model or resolve_tts_model(load_hermes_config())
        composed = compose_tts_model(resolved, voice)
        audio, content_type = post_json_bytes(
            "/v1/audio/speech",
            {"model": composed, "input": text},
            timeout=120,
        )
        if not audio:
            raise RuntimeError(
                f"9router TTS returned empty audio for model {composed!r}"
            )

        path = Path(output_path)
        extension = ext_for_content_type(content_type)
        if path.suffix.lower() != f".{extension}":
            path = path.with_suffix(f".{extension}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return str(path)

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            entries = fetch_catalog("tts")
        except Exception as exc:  # unreachable gateway, bad key, junk payload…
            logger.debug("9router TTS catalog unavailable: %s", exc)
            entries = []
        if not entries:
            return [
                {"id": model_id, "display": model_id}
                for model_id in TTS_FALLBACK_MODELS
            ]
        return [
            {
                "id": entry.id,
                "display": entry.id + (" (combo)" if entry.is_combo else ""),
            }
            for entry in entries
        ]

    def default_model(self) -> str:
        return DEFAULT_TTS_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": PROVIDER_NAME,
            "badge": "self-hosted",
            "tag": "Self-hosted 9router gateway — proxies /v1/audio/speech.",
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
