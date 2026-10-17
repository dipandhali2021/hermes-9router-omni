"""``hermes 9router setup`` — live-catalog model wizard.

Pure planner at module level (no Hermes imports); the interactive wizard and
the CLI subcommand live further down this module and import Hermes lazily
inside functions.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .catalog import CatalogEntry, fetch_catalog, group_by_provider, split_web
from .settings import (
    PROVIDER_NAME,
    resolve_fetch_model,
    resolve_image_model,
    resolve_search_model,
    resolve_stt_model,
    resolve_tts_model,
)

CAPABILITY_LABELS: Dict[str, str] = {
    "web_search": "Web search",
    "web_fetch": "Web fetch",
    "tts": "Text-to-speech",
    "stt": "Speech-to-text",
    "image": "Image generation",
}

_CAPABILITY_SOURCES = {
    "web_search": "web",
    "web_fetch": "web",
    "tts": "tts",
    "stt": "stt",
    "image": "image",
}


def _clean(value: Any) -> Optional[str]:
    """Stripped non-empty string, else None."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_9router(value: Any) -> bool:
    return _clean(value) == PROVIDER_NAME


def _section(cfg: Any, name: str) -> Dict[str, Any]:
    node = cfg.get(name) if isinstance(cfg, dict) else None
    return node if isinstance(node, dict) else {}


def _ensure_section(out: Dict[str, Any], name: str) -> Dict[str, Any]:
    node = out.get(name)
    if not isinstance(node, dict):
        node = {}
        out[name] = node
    return node


def _ensure_sub(node: Dict[str, Any], key: str) -> Dict[str, Any]:
    sub = node.get(key)
    if not isinstance(sub, dict):
        sub = {}
        node[key] = sub
    return sub


def current_picks(cfg: Any) -> Dict[str, bool]:
    """Which capabilities currently route through 9router (§6.2 semantics).

    Web: a set ``search_backend`` / ``extract_backend`` wins over the shared
    ``web.backend`` fallback.
    """
    web = _section(cfg, "web")
    backend = web.get("backend")
    search = _clean(web.get("search_backend")) or backend
    fetch = _clean(web.get("extract_backend")) or backend

    return {
        "web_search": _is_9router(search),
        "web_fetch": _is_9router(fetch),
        "tts": _is_9router(_section(cfg, "tts").get("provider")),
        "stt": _is_9router(_section(cfg, "stt").get("provider")),
        "image": _is_9router(_section(cfg, "image_gen").get("provider")),
    }


def default_selection(cfg: Any) -> Dict[str, bool]:
    """Checklist defaults: mirror the existing config, or all-on on first run."""
    picks = current_picks(cfg)
    if any(picks.values()):
        return picks
    return {capability: True for capability in CAPABILITY_LABELS}


def plan_writes(
    cfg: Any,
    decisions: Mapping[str, Optional[bool]],
    *,
    models: Mapping[str, Optional[str]],
    voice: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the new config dict for the wizard's decisions.

    ``True`` enables + writes the model; ``False`` disables 9router-owned
    values only (model keys stay, foreign providers stay, ``web.backend`` is
    deleted only when *both* web capabilities are turned off); ``None``
    leaves the capability untouched. Never mutates ``cfg``.
    """
    out = copy.deepcopy(cfg) if isinstance(cfg, dict) else {}

    def enabled(capability: str) -> bool:
        return decisions.get(capability) is True

    def disabled(capability: str) -> bool:
        return decisions.get(capability) is False

    # ---- enables ----------------------------------------------------------
    if enabled("web_search"):
        web = _ensure_section(out, "web")
        web["search_backend"] = PROVIDER_NAME
        search_model = _clean(models.get("web_search"))
        if search_model:
            _ensure_sub(web, "9router")["search_model"] = search_model

    if enabled("web_fetch"):
        web = _ensure_section(out, "web")
        web["extract_backend"] = PROVIDER_NAME
        fetch_model = _clean(models.get("web_fetch"))
        if fetch_model:
            _ensure_sub(web, "9router")["fetch_model"] = fetch_model

    if enabled("tts"):
        tts = _ensure_section(out, "tts")
        tts["provider"] = PROVIDER_NAME
        tts_model = _clean(models.get("tts"))
        if tts_model:
            tts["model"] = tts_model
        tts_voice = _clean(voice)
        if tts_voice:
            tts["voice"] = tts_voice

    if enabled("stt"):
        stt = _ensure_section(out, "stt")
        stt["provider"] = PROVIDER_NAME
        stt["enabled"] = True
        stt_model = _clean(models.get("stt"))
        if stt_model:
            _ensure_sub(stt, "9router")["model"] = stt_model

    if enabled("image"):
        image = _ensure_section(out, "image_gen")
        image["provider"] = PROVIDER_NAME
        image_model = _clean(models.get("image"))
        if image_model:
            image["model"] = image_model

    # ---- disables (9router-owned values only; model keys stay) ------------
    if disabled("web_search"):
        web = out.get("web")
        if isinstance(web, dict) and _is_9router(web.get("search_backend")):
            del web["search_backend"]

    if disabled("web_fetch"):
        web = out.get("web")
        if isinstance(web, dict) and _is_9router(web.get("extract_backend")):
            del web["extract_backend"]

    if disabled("web_search") and disabled("web_fetch"):
        web = out.get("web")
        if isinstance(web, dict) and _is_9router(web.get("backend")):
            del web["backend"]

    if disabled("tts"):
        tts = out.get("tts")
        if isinstance(tts, dict) and _is_9router(tts.get("provider")):
            del tts["provider"]

    if disabled("stt"):
        stt = out.get("stt")
        if isinstance(stt, dict) and _is_9router(stt.get("provider")):
            del stt["provider"]

    if disabled("image"):
        image = out.get("image_gen")
        if isinstance(image, dict) and _is_9router(image.get("provider")):
            del image["provider"]

    return out


def fetch_capability_models(capability: str) -> List[CatalogEntry]:
    """Live catalog for one wizard capability (web gets split by kind)."""
    entries = fetch_catalog(_CAPABILITY_SOURCES[capability])
    if capability in ("web_search", "web_fetch"):
        search, fetch = split_web(entries)
        return search if capability == "web_search" else fetch
    return entries


def build_scripted_plan(
    cfg: Any, args: Any
) -> Tuple[Dict[str, bool], Dict[str, str], Optional[str]]:
    """The ``--yes`` path: enable everything, flags > current config > defaults."""
    decisions = {capability: True for capability in CAPABILITY_LABELS}
    models = {
        "web_search": getattr(args, "search_model", None) or resolve_search_model(cfg),
        "web_fetch": getattr(args, "fetch_model", None) or resolve_fetch_model(cfg),
        "tts": getattr(args, "tts_model", None) or resolve_tts_model(cfg),
        "stt": getattr(args, "stt_model", None) or resolve_stt_model(cfg),
        "image": getattr(args, "image_model", None) or resolve_image_model(cfg),
    }
    voice = _clean(getattr(args, "voice", None))
    return decisions, models, voice
