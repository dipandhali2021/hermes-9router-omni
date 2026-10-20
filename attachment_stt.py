"""Bridge TUI/CLI file attachments to the configured 9router STT provider.

Hermes auto-transcribes voice messages from messaging gateways and voice mode, but a
file dropped into the interactive TUI is passed to the model as a generic
``[User attached file: /path]`` message. Without this bridge the model has no STT
tool and tends to install local Whisper/Vosk instead.

The ``pre_llm_call`` hook below detects audio attachments, sends them through
``tools.transcription_tools.transcribe_audio`` (which dispatches to the
plugin-registered provider), and injects the transcript into the current user
message. The ``transcribe_audio`` tool is a fallback for long files or manual
retries.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ._http import is_configured
from .settings import load_hermes_config

logger = logging.getLogger(__name__)

PROVIDER_NAME = "9router"

AUDIO_EXTENSIONS = frozenset(
    {
        ".aac",
        ".aiff",
        ".amr",
        ".flac",
        ".m4a",
        ".mp3",
        ".oga",
        ".ogg",
        ".opus",
        ".silk",
        ".wav",
        ".webm",
        ".wma",
    }
)

_ATTACHED_FILE_RE = re.compile(r"\[User attached file:\s*([^\]\n]+)\]", re.IGNORECASE)
_CACHE_MAX = 8
_cache: "OrderedDict[tuple[str, int, int], Dict[str, Any]]" = OrderedDict()
_cache_lock = threading.Lock()

AUDIO_TOOL_HINT = (
    "Audio attachments: when the user attaches an audio file, use the "
    "`transcribe_audio` tool (9router STT). Do not install local Whisper/Vosk "
    "packages or try to transcribe audio with shell commands."
)

TRANSCRIBE_AUDIO_SCHEMA = {
    "name": "transcribe_audio",
    "description": (
        "Transcribe an audio file using the configured 9router STT provider. "
        "Use this for .m4a, .mp3, .wav, .ogg, .opus, .flac, and similar "
        "attachments. Returns the transcript and provider metadata."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path to the audio file to transcribe.",
            }
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}


def find_audio_attachments(user_message: Any) -> List[str]:
    """Return existing audio-file paths referenced by ``[User attached file: ...]``."""
    if not isinstance(user_message, str):
        return []
    found: List[str] = []
    for match in _ATTACHED_FILE_RE.finditer(user_message):
        raw = match.group(1).strip().strip("'\"")
        if not raw:
            continue
        path = Path(os.path.expanduser(raw))
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        found.append(str(path))
    return found


def _provider_is_9router() -> bool:
    try:
        cfg = load_hermes_config()
    except Exception:
        return False
    stt_cfg = cfg.get("stt") if isinstance(cfg, dict) else None
    if not isinstance(stt_cfg, dict):
        return False
    return str(stt_cfg.get("provider") or "").strip().lower() == PROVIDER_NAME


def _transcribe(path: str, source: str) -> Dict[str, Any]:
    """Call Hermes' STT dispatcher (kept separate so tests can stub the network)."""
    from tools.transcription_tools import transcribe_audio

    return transcribe_audio(path, source=source)


def _cache_key(path: str) -> Optional[tuple[str, int, int]]:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (os.path.realpath(path), stat.st_mtime_ns, stat.st_size)


def _cache_get(key: tuple[str, int, int]) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        result = _cache.get(key)
        if result is not None:
            _cache.move_to_end(key)
        return result


def _cache_put(key: tuple[str, int, int], result: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = result
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)


def transcribe_attachment(
    path: str, *, source: str = "tui_attachment"
) -> Dict[str, Any]:
    """Transcribe an attachment, reusing a successful result for the same file bytes."""
    key = _cache_key(path)
    if key is not None:
        cached = _cache_get(key)
        if cached is not None:
            return dict(cached)

    result = _transcribe(path, source)
    if not isinstance(result, dict):
        result = {
            "success": False,
            "transcript": "",
            "error": "STT dispatcher returned an unexpected result",
            "provider": PROVIDER_NAME,
        }
    if result.get("success") and key is not None:
        _cache_put(key, dict(result))
    return result


def _transcript_context(path: str, result: Dict[str, Any]) -> str:
    name = os.path.basename(path)
    transcript = str(result.get("transcript") or "").strip()
    if not transcript:
        transcript = "(no speech detected)"
    model = str(result.get("model") or "").strip()
    provider = str(result.get("provider") or PROVIDER_NAME).strip()
    suffix = f", model={model}" if model else ""
    return (
        f"[{provider} STT transcript for {name}{suffix}]\n{transcript}\n"
        "(This attachment was transcribed automatically. Do not run local STT "
        "or call `transcribe_audio` again for this file.)"
    )


def _failure_context(path: str, result: Dict[str, Any]) -> str:
    name = os.path.basename(path)
    error = str(result.get("error") or "unknown error").strip()
    return (
        f"[9router STT could not transcribe {name}: {error}]\n"
        "Do not install local speech-recognition packages. Use the "
        "`transcribe_audio` tool to retry the file through 9router."
    )


def auto_transcribe_attachment(*, user_message: Any = None, **_: Any) -> Optional[Dict[str, str]]:
    """``pre_llm_call`` hook: inject 9router transcripts for attached audio files."""
    paths = find_audio_attachments(user_message)
    if not paths:
        return None
    if not _provider_is_9router() or not is_configured():
        return None

    parts: List[str] = []
    for path in paths[:3]:
        try:
            result = transcribe_attachment(path)
        except Exception as exc:  # noqa: BLE001 — a hook must never break the turn
            logger.warning("9router attachment STT failed for %s: %s", path, exc)
            result = {
                "success": False,
                "error": str(exc),
                "provider": PROVIDER_NAME,
            }
        if result.get("success"):
            logger.info("9router: auto-transcribed audio attachment %s", path)
            parts.append(_transcript_context(path, result))
        else:
            logger.warning(
                "9router: audio attachment transcription failed for %s: %s",
                path,
                result.get("error") or "unknown error",
            )
            parts.append(_failure_context(path, result))

    return {"context": "\n\n".join(parts)} if parts else None


def handle_transcribe_audio(args: Dict[str, Any], **_: Any) -> str:
    """Tool handler for agent-initiated transcription."""
    path = str((args or {}).get("path") or "").strip()
    if not path:
        return json.dumps(
            {"success": False, "error": "path is required"}, ensure_ascii=False
        )
    try:
        result = transcribe_attachment(os.path.expanduser(path), source="tool")
    except Exception as exc:  # noqa: BLE001 — return an envelope, never raise
        result = {
            "success": False,
            "error": f"transcription failed: {exc}",
            "provider": PROVIDER_NAME,
        }
    return json.dumps(result, ensure_ascii=False)
