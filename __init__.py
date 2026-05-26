"""9router-omni Hermes plugin — web search, web extract, image gen, TTS, STT.

Routes Hermes' built-in web search, web extract, image generation, TTS, and STT
tool calls through a single 9router gateway. Web and image use the proper
Hermes provider plugin APIs; TTS and STT monkey-patch the dispatchers because
Hermes has no register_tts_provider / register_transcription_provider yet.

Env vars (both required):
    NINEROUTER_BASE_URL
    NINEROUTER_API_KEY
"""

from __future__ import annotations

from .image_gen import NineRouterImageGenProvider
from .stt import install_stt_patch
from .tts import install_tts_patch
from .web import NineRouterWebSearchProvider


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
    ctx.register_web_search_provider(NineRouterWebSearchProvider())
    ctx.register_image_gen_provider(NineRouterImageGenProvider())
    _patch_web_tools_gating()
    install_tts_patch()
    install_stt_patch()
