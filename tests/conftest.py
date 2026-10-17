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
