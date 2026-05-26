"""9router TTS provider for Hermes (monkey-patch).

Hermes has no ``TTSProvider`` ABC or ``ctx.register_tts_provider()`` API —
TTS dispatch is a hardcoded if/elif chain in
``tools/tts_tool.py::text_to_speech_tool``. We install a wrapper that
short-circuits to our 9router HTTP client when the user has configured
``tts.provider: 9router`` in ``~/.hermes/config.yaml``; everything else
falls through to the original built-in dispatcher.

9router endpoint: ``POST /v1/audio/speech`` with ``{model, input}``.
Response is raw audio bytes (mp3 by default) with the ``Content-Type``
header set accordingly.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from ._http import is_configured, post_json_bytes

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini-tts"
PROVIDER_NAME = "9router"


def _load_9router_tts_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("tts") if isinstance(cfg, dict) else None
        if not isinstance(section, dict):
            return {}
        sub = section.get("9router")
        return sub if isinstance(sub, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not load tts.9router config: %s", exc)
        return {}


def _resolve_model() -> str:
    cfg = _load_9router_tts_config()
    model = cfg.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return DEFAULT_MODEL


def _ext_for_content_type(content_type: str) -> str:
    ct = (content_type or "").split(";", 1)[0].strip().lower()
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


def _generate_9router_tts(text: str, file_path: str) -> Dict[str, Any]:
    """Hit /v1/audio/speech and write the audio bytes to ``file_path``."""
    model = _resolve_model()
    payload = {"model": model, "input": text}

    logger.info("9router TTS: model=%s len=%d → %s", model, len(text), file_path)
    audio, content_type = post_json_bytes("/v1/audio/speech", payload, timeout=120)
    if not audio:
        raise RuntimeError("9router /v1/audio/speech returned empty body")

    # Adjust file extension if the server returned something other than mp3.
    actual_ext = _ext_for_content_type(content_type)
    base, current_ext = os.path.splitext(file_path)
    if current_ext.lstrip(".").lower() != actual_ext:
        file_path = f"{base}.{actual_ext}"

    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_bytes(audio)
    return {
        "file_path": file_path,
        "content_type": content_type,
        "bytes": len(audio),
        "model": model,
    }


def _resolve_output_path(output_path: Optional[str]) -> str:
    if output_path:
        return str(Path(output_path).expanduser())
    out_dir = Path.home() / "voice-memos"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(out_dir / f"tts_{timestamp}.mp3")


def _build_response(file_path: str, voice_compatible: bool = False) -> str:
    media_tag = f"MEDIA:{file_path}"
    if voice_compatible:
        media_tag = f"[[audio_as_voice]]\n{media_tag}"
    return json.dumps(
        {
            "success": True,
            "file_path": file_path,
            "media_tag": media_tag,
            "provider": PROVIDER_NAME,
            "voice_compatible": voice_compatible,
        },
        ensure_ascii=False,
    )


def _error_response(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Monkey-patch installer
# ---------------------------------------------------------------------------


def install_tts_patch() -> None:
    from tools import tts_tool

    if getattr(tts_tool.text_to_speech_tool, "_9router_patched", False):
        return

    original = tts_tool.text_to_speech_tool

    def patched_text_to_speech_tool(
        text: str,
        output_path: Optional[str] = None,
    ) -> str:
        # Read current config on every call so flipping providers in
        # config.yaml takes effect without restarting Hermes.
        try:
            tts_config = tts_tool._load_tts_config()
            provider = tts_tool._get_provider(tts_config)
        except Exception:  # noqa: BLE001 — fall back to original on any read error
            return original(text, output_path)

        if provider != "9router":
            return original(text, output_path)

        if not text or not text.strip():
            return _error_response("Text is required")

        if not is_configured():
            return _error_response(
                "9router not configured. Set NINEROUTER_BASE_URL and "
                "NINEROUTER_API_KEY in ~/.hermes/.env."
            )

        file_path = _resolve_output_path(output_path)

        try:
            result = _generate_9router_tts(text, file_path)
        except ValueError as exc:  # missing env
            return _error_response(str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("9router TTS error: %s", exc)
            return _error_response(f"9router TTS failed: {exc}")

        actual_path = result["file_path"]
        # Opus delivery only when the platform asks for a voice bubble. Since
        # 9router default output is mp3, telegram voice will trigger ffmpeg
        # conversion downstream — we just return the raw mp3 path here.
        return _build_response(actual_path, voice_compatible=False)

    patched_text_to_speech_tool._9router_patched = True  # type: ignore[attr-defined]
    tts_tool.text_to_speech_tool = patched_text_to_speech_tool
