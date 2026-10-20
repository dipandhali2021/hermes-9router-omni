"""Pure defaults + config resolution for 9router-omni. No Hermes imports at
module load time.

Everything in this module is deterministic and side-effect free so the test
suite can exercise it without a Hermes install. ``load_hermes_config()`` is
the only function that touches Hermes, and it imports lazily and fails soft.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

PROVIDER_NAME = "9router"

DEFAULT_SEARCH_MODEL = "openclaw-search"
DEFAULT_FETCH_MODEL = "openclaw-fetch"
DEFAULT_TTS_MODEL = "openrouter/fish-audio/s2.1-pro-free:free"
DEFAULT_STT_MODEL = "groq/whisper-large-v3-turbo"
DEFAULT_IMAGE_MODEL = "ag/gemini-3.1-flash-image"

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


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})


def _is_9router_name(name: str) -> bool:
    return name.strip().lower().startswith("9router")


def _provider_base(spec: Dict[str, Any]) -> Optional[str]:
    """First non-empty base URL field used by Hermes provider configs."""
    return (
        _text(spec.get("base_url"))
        or _text(spec.get("api"))
        or _text(spec.get("api_base"))
    )


def _provider_candidates(cfg: Any) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """Every ``(name, base_url, api_key)`` provider entry in the config.

    Hermes stores custom providers in two places: a ``providers`` mapping
    (model-provider settings, keyed by name) and a ``custom_providers``
    list. Both spell the URL as ``api`` or ``base_url`` depending on age.
    """
    if not isinstance(cfg, dict):
        return []

    out: List[Tuple[str, Optional[str], Optional[str]]] = []
    providers = cfg.get("providers")
    if isinstance(providers, dict):
        for name, spec in providers.items():
            if isinstance(name, str) and isinstance(spec, dict):
                out.append((name, _provider_base(spec), _text(spec.get("api_key"))))

    custom = cfg.get("custom_providers")
    if isinstance(custom, list):
        for spec in custom:
            if not isinstance(spec, dict):
                continue
            name = _text(spec.get("name"))
            if name:
                out.append((name, _provider_base(spec), _text(spec.get("api_key"))))
    return out


def _normalize_gateway_url(url: Optional[str]) -> str:
    """Compare gateway URLs ignoring ``/v1``, trailing slashes, and loopback spelling.

    ``http://127.0.0.1:20128`` and ``http://localhost:20128/v1`` are the same
    gateway; ``https://host`` and ``https://host/v1`` are the same gateway.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = f"http://{raw}"
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return raw.rstrip("/").lower()
    if host in _LOOPBACK_HOSTS:
        host = "localhost"
    netloc = host if not port else f"{host}:{port}"
    path = (parts.path or "").rstrip("/")
    if path.lower() == "/v1":
        path = ""
    return f"{parts.scheme.lower()}://{netloc}{path}"


def _model_provider_name(cfg: Any) -> Optional[str]:
    """Provider selected for chat, with the ``custom:`` prefix stripped."""
    model = cfg.get("model") if isinstance(cfg, dict) else None
    name = _text(model.get("provider")) if isinstance(model, dict) else None
    if not name:
        return None
    if name.lower().startswith("custom:"):
        name = name.split(":", 1)[1].strip()
    return name or None


def resolve_gateway_credentials(
    cfg: Any, base_url_hint: Optional[str] = None
) -> Tuple[Optional[str], str]:
    """Find the 9router gateway's base URL and API key in Hermes config.

    Used when the ``NINEROUTER_*`` env vars are absent, so users who already
    configured 9router as a model provider do not have to duplicate the URL
    and key. ``base_url_hint`` (normally the env-configured base URL) picks
    the provider entry for the same gateway; without a hint the chat model's
    provider wins, then ``providers.9router``.

    Returns ``(base_url or None, api_key or "")``. Never raises.
    """
    candidates = _provider_candidates(cfg)
    if not candidates:
        return None, ""

    chosen: Optional[Tuple[str, Optional[str], Optional[str]]] = None
    hint = _normalize_gateway_url(base_url_hint)
    if hint:
        matching = [
            item
            for item in candidates
            if item[1] and _normalize_gateway_url(item[1]) == hint
        ]
        # Prefer a proper 9router entry, but accept any provider whose URL
        # matches — users rename their providers.
        chosen = next((item for item in matching if _is_9router_name(item[0])), None)
        if chosen is None and matching:
            chosen = matching[0]

    if chosen is None:
        preferred = _model_provider_name(cfg)
        if preferred:
            chosen = next(
                (item for item in candidates if item[0].lower() == preferred.lower()),
                None,
            )
        if chosen is None:
            chosen = next(
                (item for item in candidates if item[0].lower() == "9router"), None
            )
        if chosen is None:
            named = [item for item in candidates if _is_9router_name(item[0])]
            chosen = named[0] if named else None

    if chosen is None:
        # A matching URL was not configured, but the caller knows the
        # gateway; borrow a 9router-named key rather than sending a
        # guaranteed-401 request. Never borrow an unrelated provider's key
        # (that would leak it to the gateway). Without a hint, never guess.
        if hint:
            keyed = [
                item
                for item in candidates
                if item[2] and _is_9router_name(item[0])
            ]
            if keyed:
                return None, keyed[0][2] or ""
        return None, ""

    _, base, key = chosen
    if base and not key:
        # Provider entries sometimes split the URL and key across config
        # sections; join them when they point at the same gateway.
        normalized = _normalize_gateway_url(base)
        sibling = next(
            (
                item
                for item in candidates
                if item[2] and _normalize_gateway_url(item[1]) == normalized
            ),
            None,
        )
        if sibling is not None:
            key = sibling[2]
    return base, key or ""


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
