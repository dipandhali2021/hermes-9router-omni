import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# pytest creates a ``Package`` collector node for the repository root because
# the plugin's ``__init__.py`` lives there, and imports that file at test-setup
# time. The repo directory name (``hermes-9router-omni``) is not a Python
# identifier, so pytest cannot resolve it as a package and falls back to
# importing the file as a top-level module literally named ``__init__`` — where
# the plugin's relative imports explode. Pre-seeding a placeholder under that
# name short-circuits the import; the real plugin ``__init__.py`` is never
# needed by these tests.
sys.modules.setdefault("__init__", types.ModuleType("__init__"))


def _bootstrap_package(name: str = "ninerouter_omni") -> None:
    if name in sys.modules:
        return
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(ROOT)]
    pkg.__package__ = name
    sys.modules[name] = pkg


_bootstrap_package()


def _ensure_module(mod_name: str, attrs: dict) -> None:
    if mod_name in sys.modules:
        return
    try:
        __import__(mod_name)
        return
    except Exception:
        pass
    if "." in mod_name:
        parent = mod_name.rsplit(".", 1)[0]
        if parent not in sys.modules:
            _ensure_module(parent, {})
    mod = types.ModuleType(mod_name)
    mod.__dict__.update(attrs)
    if "." not in mod_name:
        mod.__path__ = []  # type: ignore[attr-defined]
    sys.modules[mod_name] = mod


class _StubProviderBase:
    pass


def _stub_hermes_modules() -> None:
    _ensure_module("agent.tts_provider", {"TTSProvider": _StubProviderBase})
    _ensure_module("agent.transcription_provider", {"TranscriptionProvider": _StubProviderBase})
    _ensure_module("agent.web_search_provider", {"WebSearchProvider": _StubProviderBase})
    _ensure_module("agent.image_gen_provider", {
        "ImageGenProvider": _StubProviderBase,
        "DEFAULT_ASPECT_RATIO": "square",
        "error_response": lambda **kw: {"success": False, **kw},
        "success_response": lambda **kw: {"success": True, **kw},
        "resolve_aspect_ratio": lambda v: v if v in ("landscape", "square", "portrait") else "square",
        "save_b64_image": lambda b64, prefix="img", extension="png": f"/tmp/{prefix}.{extension}",
    })
    _ensure_module("tools.interrupt", {"is_interrupted": lambda: False})


_stub_hermes_modules()
