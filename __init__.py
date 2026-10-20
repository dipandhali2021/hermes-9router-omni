"""9router-omni Hermes plugin — web search, web extract, image gen, TTS, STT.

Routes Hermes' built-in web search, web extract, image generation, TTS, and STT
tool calls through a single 9router gateway using Hermes v0.17+ native provider
hooks (``register_web_search_provider``, ``register_image_gen_provider``,
``register_tts_provider``, ``register_transcription_provider``).

First enable automatically routes all five capabilities through 9router with
the default models. Run ``hermes 9router setup`` to pick models/voice from the
gateway's live per-modality catalogs or to disable a capability.

Env vars:
    NINEROUTER_BASE_URL    required, e.g. ``http://127.0.0.1:20128``
    NINEROUTER_API_KEY     optional — leave empty for keyless gateways
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from . import _http, setup_cmd
from .image_gen import NineRouterImageGenProvider
from .stt import NineRouterTranscriptionProvider
from .tts import NineRouterTTSProvider
from .web import NineRouterWebSearchProvider

logger = logging.getLogger(__name__)

_FIRST_INSTALL_STATE_KEY = "first_install_setup_complete"


def _auto_configure_first_install(
    ctx, capabilities: Optional[Iterable[str]] = None
) -> None:
    """One-time setup: force every supported capability through 9router.

    The marker lives in Hermes' durable plugin state, so the force happens on
    the first load only; later manual changes (including disabling a
    capability) are never overwritten. If the gateway is not configured yet,
    leave the marker unset and try again on a later load — the install flow
    normally sets ``NINEROUTER_BASE_URL`` first.
    """
    state = getattr(ctx, "state", None)
    if state is None:
        return
    try:
        if state.get(_FIRST_INSTALL_STATE_KEY):
            return
    except Exception as exc:  # noqa: BLE001 — plugin load must never fail here
        logger.warning("9router: could not read first-install marker (%s)", exc)
        return

    try:
        from hermes_cli.config import load_config, save_config

        cfg = load_config()
        if not _http.is_configured():
            logger.info(
                "9router: first-install setup deferred until NINEROUTER_BASE_URL "
                "or a 9router provider is configured"
            )
            return
        save_config(setup_cmd.first_install_plan(cfg, capabilities=capabilities))
    except Exception as exc:  # noqa: BLE001 — a config failure must not break plugin load
        logger.warning(
            "9router: first-install auto-config failed (%s); "
            "run `hermes 9router setup`",
            exc,
        )
        return

    try:
        state.set(_FIRST_INSTALL_STATE_KEY, True)
    except Exception as exc:  # noqa: BLE001 — the config is already saved
        logger.warning("9router: could not record first-install marker (%s)", exc)
        return
    logger.info("9router: first install routed all supported capabilities through 9router")


def _patch_web_tools_gating() -> None:
    """Teach ``tools.web_tools`` that ``9router`` (or any registered
    third-party provider) counts as an available backend.

    Why: ``check_web_api_key`` is the ``check_fn`` on the ``web_search`` /
    ``web_extract`` tool registrations. It and its helper
    ``_is_backend_available`` both hardcode the seven built-in providers, so
    any third-party backend registered via ``ctx.register_web_search_provider()``
    is reported as unavailable and the tools are hidden from the model. We
    wrap both so any registered provider that reports ``is_available()`` counts.
    """
    from tools import web_tools
    from agent.web_search_registry import get_provider

    if getattr(web_tools._is_backend_available, "_9router_patched", False):
        return

    original_is_available = web_tools._is_backend_available

    def patched_is_available(backend: str) -> bool:
        if original_is_available(backend):
            return True
        provider = get_provider(backend)
        if provider is not None:
            try:
                return bool(provider.is_available())
            except Exception:
                return False
        return False

    patched_is_available._9router_patched = True
    web_tools._is_backend_available = patched_is_available

    original_check_web_api_key = web_tools.check_web_api_key

    def patched_check_web_api_key() -> bool:
        configured = (web_tools._load_web_config().get("backend") or "").lower().strip()
        if configured:
            return patched_is_available(configured)
        builtins = ("exa", "parallel", "firecrawl", "tavily", "searxng", "brave-free", "ddgs")
        return any(patched_is_available(b) for b in builtins)

    web_tools.check_web_api_key = patched_check_web_api_key

    # The web_search / web_extract ToolEntry objects in the global registry
    # captured the *original* check_fn reference at module-import time
    # (before plugins loaded). Rebinding the module attribute above is not
    # enough — replace the captured reference on each entry and drop any
    # cached result so the next gating call hits the patched function.
    from tools.registry import registry, invalidate_check_fn_cache

    for tool_name in ("web_search", "web_extract"):
        entry = registry._tools.get(tool_name)
        if entry is not None and getattr(entry, "check_fn", None) is original_check_web_api_key:
            entry.check_fn = patched_check_web_api_key
    invalidate_check_fn_cache()


def register(ctx) -> None:
    """Plugin entrypoint: register all four providers + the setup CLI."""
    ctx.register_web_search_provider(NineRouterWebSearchProvider())
    ctx.register_image_gen_provider(NineRouterImageGenProvider())

    native_tts_stt = True
    try:
        ctx.register_tts_provider(NineRouterTTSProvider())
        ctx.register_transcription_provider(NineRouterTranscriptionProvider())
    except AttributeError:
        native_tts_stt = False
        logger.warning(
            "Hermes v0.17.0+ is required for native TTS/STT providers; "
            "web search and image generation remain active."
        )

    try:
        _patch_web_tools_gating()
    except Exception as exc:  # noqa: BLE001 — a Hermes refactor must not break plugin load
        logger.warning(
            "Could not patch web-tool backend gating (%s); web search/extract "
            "may report as unavailable until Hermes updates. Plugin load continues.",
            exc,
        )

    ctx.register_cli_command(
        name="9router",
        help="9router gateway setup — pick models from your gateway's live catalog",
        setup_fn=setup_cmd.register_subcommand,
        handler_fn=setup_cmd.handle_setup,
    )

    capabilities = ["web_search", "web_fetch", "image"]
    if native_tts_stt:
        capabilities += ["tts", "stt"]
    _auto_configure_first_install(ctx, capabilities)
