# 9router-omni v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 9router-omni v3.0.0 — install-time env prompts, a re-runnable `hermes 9router setup` wizard that picks models from the gateway's live per-modality catalog, native TTS/STT providers, canonical config keys with back-compat reads, and a pytest suite.

**Architecture:** Pure logic (defaults, resolution, voice composition, wizard write planning) lives in Hermes-free modules (`settings.py`, `catalog.py`) that tests import directly. Capability modules stay thin: config via `settings`, gateway calls via `_http`/`catalog`, registration via Hermes' native provider hooks. The wizard (`setup_cmd.py`) wraps Hermes' own `curses_ui` pickers and `masked_secret_prompt` around the pure write planner.

**Tech Stack:** Python 3 (stdlib), `httpx` (lazy-imported), Hermes v0.17.0 APIs (`agent.tts_provider`, `agent.transcription_provider`, `agent.image_gen_provider`, `agent.web_search_provider`, `hermes_cli.config`, `hermes_cli.curses_ui`, `hermes_cli.secret_prompt`, `rich`), pytest + httpx for tests.

**Spec:** `docs/superpowers/specs/2026-10-17-9router-omni-setup-wizard-design.md` (binding; §N references below refer to it).

## Global Constraints

- **Min Hermes v0.17.0** for native TTS/STT hooks; web/image must keep working on older Hermes; log a clear warning when the hooks are missing (§6.5).
- **Plugin version 3.0.0** in `plugin.yaml` (§6.7).
- **Never call `GET /v1/models`** (1747 models, ~31 s). Only `/v1/models/{web,tts,stt,image}` (§5.2).
- **Code defaults:** `openclaw-search`, `openclaw-fetch`, `tts-combo`, `stt-combo`, `image-combo` (§4 #3–4).
- **Write keys / read order** exactly per the §6.2 table; old keys (`tts.9router.model`, `image_gen.9router.model`) stay readable.
- **Disable-on-uncheck** removes only 9router's own values, only when equal to `"9router"` (§6.2). Model keys are never deleted. `stt.enabled` is never touched.
- **Keyless gateways:** empty `NINEROUTER_API_KEY` is valid; omit the `Authorization` header; `is_configured()` requires only the base URL (§4 #20, §6.5).
- **TTS voice** is composed into the model id at call time (`<model>/<voice>`), skipped when already suffixed; the wizard never sets a voice on combo models (§6.3, §4 #19).
- **No catalog caching** — every fetch is live (§7 #4).
- **Auth probe:** `POST /v1/audio/speech` with `input` deliberately missing → 401/403 = bad key, 400 = auth OK (§5.2).
- **Wizard flags:** `--yes`, `--tts-model`, `--stt-model`, `--image-model`, `--search-model`, `--fetch-model`, `--voice`. Non-TTY without `--yes` refuses. `--yes` never prompts (§6.1, §7 #5).
- **Tests:** plain `pytest` + `httpx`; fixtures are small hand-trimmed snapshots of the live lists (§6.6, §7 #6).
- **Copy pins:** wizard ends with `restart the gateway: hermes gateway restart`; after-install points at `hermes 9router setup` (§6.1).
- **Style:** follow existing files (`from __future__ import annotations`, `typing.Optional` where already used, relative imports).

## Review Focus

Five failure modes the spec implies; each is pinned by a test in the owning task:

1. **Keyless gateway** — with no key set, every request omits `Authorization` and still works (Task 2 `test_is_configured_keyless`, Task 3 `test_probe_auth_ok_keyless_omits_header`).
2. **Foreign config values survive re-runs** — a `web.search_backend: tavily` override is never deleted by disable-on-uncheck (Task 8 `test_disable_keeps_foreign_backend`).
3. **Voice composition edge** — a model already suffixed with the voice is not double-suffixed; combo+voice is sent as-is so the gateway error surfaces (no silent drop) (Task 1 compose tests).
4. **Unreachable gateway** — the probe fails loudly and the wizard aborts before any `save_config` (Task 3 probe tests; Task 9 keeps `save_config` after probe + picks by construction).
5. **Old Hermes (<0.17)** — no `register_tts_provider` on ctx → plugin still loads, web/image work, warning logged (Task 10 old-ctx test).

## File Map

| File | Responsibility |
|---|---|
| `settings.py` **new** | defaults, config resolution, compose/fields/ext pure helpers |
| `catalog.py` **new** | live catalog fetch/parse/group/split + auth probe |
| `setup_cmd.py` **new** | wizard: pure planner + interactive shell + CLI subcommand |
| `_http.py` | keyless headers + `get_json` |
| `tts.py` / `stt.py` | rewritten as native providers |
| `image_gen.py` / `web.py` | new key reads + defaults |
| `__init__.py` | native registrations + gating patch + CLI command |
| `plugin.yaml` / `after-install.md` / `README.md` | packaging + docs |
| `tests/` **new** | conftest bootstrap + fixtures + per-module tests |

---

### Task 1: `settings.py` — defaults, resolution, pure helpers

**Files:**
- Create: `settings.py`
- Create: `tests/conftest.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `PROVIDER_NAME = "9router"`; `DEFAULT_SEARCH_MODEL` / `DEFAULT_FETCH_MODEL` / `DEFAULT_TTS_MODEL` / `DEFAULT_STT_MODEL` / `DEFAULT_IMAGE_MODEL`; `TTS_VOICE_SUGGESTIONS: tuple[str, ...]`; `load_hermes_config() -> dict`; `resolve_search_model(cfg) -> str`; `resolve_fetch_model(cfg) -> str`; `resolve_tts_model(cfg) -> str`; `resolve_stt_model(cfg) -> str`; `resolve_image_model(cfg) -> str`; `compose_tts_model(model: str, voice: str | None) -> str`; `build_transcription_fields(model: str, language: str | None, cfg: dict) -> dict`; `ext_for_content_type(content_type: str) -> str`.

- [ ] **Step 1: Create `tests/conftest.py`** — makes the plugin importable as a package without executing `__init__.py` (Hermes is not on sys.path in tests):

```python
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bootstrap_package(name: str = "ninerouter_omni") -> None:
    if name in sys.modules:
        return
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(ROOT)]
    pkg.__package__ = name
    sys.modules[name] = pkg


_bootstrap_package()
```

- [ ] **Step 2: Write the failing tests** in `tests/test_settings.py`:

```python
from ninerouter_omni import settings


def test_defaults_when_config_empty():
    assert settings.resolve_search_model({}) == "openclaw-search"
    assert settings.resolve_fetch_model({}) == "openclaw-fetch"
    assert settings.resolve_tts_model({}) == "tts-combo"
    assert settings.resolve_stt_model({}) == "stt-combo"
    assert settings.resolve_image_model({}) == "image-combo"


def test_tts_new_key_wins_over_old():
    cfg = {"tts": {"model": "openai/tts-1", "9router": {"model": "old"}}}
    assert settings.resolve_tts_model(cfg) == "openai/tts-1"


def test_tts_old_key_still_readable():
    assert settings.resolve_tts_model({"tts": {"9router": {"model": "old-tts"}}}) == "old-tts"


def test_image_new_then_old_then_default():
    assert settings.resolve_image_model({"image_gen": {"model": "gemini/x"}}) == "gemini/x"
    assert settings.resolve_image_model({"image_gen": {"9router": {"model": "legacy"}}}) == "legacy"


def test_web_models_read_nested_keys():
    cfg = {"web": {"9router": {"search_model": "tavily/search", "fetch_model": "exa/fetch"}}}
    assert settings.resolve_search_model(cfg) == "tavily/search"
    assert settings.resolve_fetch_model(cfg) == "exa/fetch"


def test_blank_and_nonstring_values_ignored():
    assert settings.resolve_tts_model({"tts": {"model": "   "}}) == "tts-combo"
    assert settings.resolve_tts_model({"tts": {"model": 7}}) == "tts-combo"


def test_compose_appends_and_is_idempotent():
    assert settings.compose_tts_model("openai/tts-1", "nova") == "openai/tts-1/nova"
    assert settings.compose_tts_model("openai/tts-1/nova", "nova") == "openai/tts-1/nova"
    assert settings.compose_tts_model("openai/tts-1", None) == "openai/tts-1"
    assert settings.compose_tts_model("openai/tts-1", "") == "openai/tts-1"


def test_compose_combo_gets_no_silent_drop():
    # The wizard prevents combo+voice; a hand-edited combo+voice must reach the
    # gateway so its error surfaces (rather than being silently dropped).
    assert settings.compose_tts_model("tts-combo", "nova") == "tts-combo/nova"


def test_ext_for_content_type():
    assert settings.ext_for_content_type("audio/mpeg; charset=utf-8") == "mp3"
    assert settings.ext_for_content_type("audio/wav") == "wav"
    assert settings.ext_for_content_type("audio/ogg") == "ogg"
    assert settings.ext_for_content_type("audio/webm") == "webm"
    assert settings.ext_for_content_type("audio/flac") == "flac"
    assert settings.ext_for_content_type("") == "mp3"


def test_build_transcription_fields():
    cfg = {"stt": {"9router": {"prompt": "ctx", "response_format": "json",
                               "temperature": 0.2, "language": "en"}}}
    assert settings.build_transcription_fields("m", None, cfg) == {
        "model": "m", "language": "en", "prompt": "ctx",
        "response_format": "json", "temperature": 0.2}
    assert settings.build_transcription_fields("m", "de", cfg)["language"] == "de"
    assert settings.build_transcription_fields("m", None, {}) == {"model": "m"}
```

- [ ] **Step 3: Run tests — expect import failure**

Run: `python -m pytest tests/test_settings.py -q`
Expected: collection error / `ModuleNotFoundError: ninerouter_omni.settings`.

- [ ] **Step 4: Implement `settings.py`**

Module docstring: "Pure defaults + config resolution for 9router-omni. No Hermes imports at module load." Implement:

```python
PROVIDER_NAME = "9router"
DEFAULT_SEARCH_MODEL = "openclaw-search"
DEFAULT_FETCH_MODEL = "openclaw-fetch"
DEFAULT_TTS_MODEL = "tts-combo"
DEFAULT_STT_MODEL = "stt-combo"
DEFAULT_IMAGE_MODEL = "image-combo"
TTS_VOICE_SUGGESTIONS = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")


def load_hermes_config() -> dict:
    """load_config() from hermes_cli.config; {} on any failure. Lazy import."""


def _text(value) -> str | None:      # stripped non-empty str, else None
def _nested(cfg: dict, *keys) -> str | None:   # walk dicts safely via _text at the end


def resolve_search_model(cfg) -> str:   # web.9router.search_model -> DEFAULT_SEARCH_MODEL
def resolve_fetch_model(cfg) -> str:    # web.9router.fetch_model  -> DEFAULT_FETCH_MODEL
def resolve_tts_model(cfg) -> str:      # tts.model -> tts.9router.model -> DEFAULT_TTS_MODEL
def resolve_stt_model(cfg) -> str:      # stt.9router.model -> DEFAULT_STT_MODEL
def resolve_image_model(cfg) -> str:    # image_gen.model -> image_gen.9router.model -> DEFAULT_IMAGE_MODEL


def compose_tts_model(model: str, voice: str | None) -> str:
    # voice truthy AND model not already ending with f"/{voice}" -> f"{model}/{voice}"


def build_transcription_fields(model: str, language: str | None, cfg: dict) -> dict:
    # {"model": model}; language = arg or stt.9router.language; prompt and
    # response_format copied from stt.9router.* when non-empty str; temperature
    # copied when int/float (bool excluded).


def ext_for_content_type(content_type: str) -> str:
    # mpeg|mp3 -> mp3, wav -> wav, ogg|opus -> ogg, webm -> webm, flac -> flac, else mp3
```

- [ ] **Step 5: Run tests — expect pass**

Run: `python -m pytest tests/test_settings.py -q`
Expected: `10 passed`.

- [ ] **Step 6: Commit**

```bash
git add settings.py tests/conftest.py tests/test_settings.py
git commit -m "feat(settings): pure defaults, config resolution, voice composition"
```

---

### Task 2: `_http.py` — keyless gateways + `get_json`

**Files:**
- Modify: `_http.py`
- Test: `tests/test_http.py`

**Interfaces:**
- Produces: `is_configured() -> bool` (base URL only), `api_key() -> str` (may be `""`, never raises), `get_json(path: str, *, timeout: int = 15) -> Any`; `post_json` / `post_json_bytes` / `post_form` keep their signatures but omit `Authorization` when the key is empty.

- [ ] **Step 1: Write the failing tests** in `tests/test_http.py`:

```python
import types

import pytest

from ninerouter_omni import _http


def _env(monkeypatch, base=None, key=None):
    monkeypatch.delenv("NINEROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
    if base is not None:
        monkeypatch.setenv("NINEROUTER_BASE_URL", base)
    if key is not None:
        monkeypatch.setenv("NINEROUTER_API_KEY", key)


def test_is_configured_keyless(monkeypatch):
    _env(monkeypatch, base="http://127.0.0.1:20128")
    assert _http.is_configured() is True


def test_is_configured_requires_base(monkeypatch):
    _env(monkeypatch, key="k")
    assert _http.is_configured() is False


def test_api_key_empty_is_legal(monkeypatch):
    _env(monkeypatch, base="http://x")
    assert _http.api_key() == ""


def test_get_json_parses_and_sends_bearer(monkeypatch):
    _env(monkeypatch, base="http://x", key="k")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(url=url, headers=headers, timeout=timeout)
        return types.SimpleNamespace(status_code=200, text="{}", reason_phrase="OK",
                                     json=lambda: {"object": "list", "data": []})

    monkeypatch.setattr("httpx.get", fake_get)
    assert _http.get_json("/v1/models/tts") == {"object": "list", "data": []}
    assert captured["url"] == "http://x/v1/models/tts"
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["timeout"] == 15


def test_keyless_headers_omit_authorization(monkeypatch):
    _env(monkeypatch, base="http://x")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(headers=headers)
        return types.SimpleNamespace(status_code=200, text="{}", reason_phrase="OK", json=dict)

    monkeypatch.setattr("httpx.get", fake_get)
    _http.get_json("/v1/models/tts")
    assert "Authorization" not in captured["headers"]


def test_get_json_raises_with_preview(monkeypatch):
    _env(monkeypatch, base="http://x")

    def fake_get(url, headers=None, timeout=None):
        return types.SimpleNamespace(status_code=404, text='{"error":"model_not_found"}',
                                     reason_phrase="Not Found", json=dict)

    monkeypatch.setattr("httpx.get", fake_get)
    with pytest.raises(RuntimeError, match="404"):
        _http.get_json("/v1/models/nope")
```

- [ ] **Step 2: Run tests — expect failure**

Run: `python -m pytest tests/test_http.py -q`
Expected: FAIL — `is_configured()` is False keyless; `api_key()` raises; `get_json` missing.

- [ ] **Step 3: Implement in `_http.py`**

- `api_key()` → `os.getenv("NINEROUTER_API_KEY", "").strip()` (docstring: optional; empty means keyless).
- `is_configured()` → `bool(os.getenv("NINEROUTER_BASE_URL", "").strip())`.
- `_bearer_headers(extra=None)` → start from `{}`; add `Authorization: Bearer <key>` only when key is non-empty; merge `extra`.
- `get_json(path, *, timeout=15)` → `GET f"{base_url()}{path}"` with `_bearer_headers()`, `_raise_for_status(response, path)`, return `response.json()`.
- Update module docstring: only `NINEROUTER_BASE_URL` is required; the key is optional (keyless gateways).

- [ ] **Step 4: Run tests — expect pass**

Run: `python -m pytest tests -q`
Expected: all green (16 tests: Task 1 + Task 2).

- [ ] **Step 5: Commit**

```bash
git add _http.py tests/test_http.py
git commit -m "feat(http): keyless gateway support and get_json helper"
```

---

### Task 3: `catalog.py` — live catalogs + auth probe

**Files:**
- Create: `catalog.py`
- Create: `tests/fixtures/models_tts.json`, `models_stt.json`, `models_image.json`, `models_web.json`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `_http.get_json`, `settings.DEFAULT_TTS_MODEL`.
- Produces: `CatalogEntry(id, owned_by="", kind="")` frozen dataclass with `.is_combo` property (`owned_by == "combo"`); `CAPABILITY_PATHS: dict[str, str]` (`web|tts|stt|image` → `/v1/models/<cap>`); `CATALOG_TIMEOUT_S = 15`; `parse_catalog(payload) -> list[CatalogEntry]`; `fetch_catalog(capability: str) -> list[CatalogEntry]` (KeyError on unknown capability); `split_web(entries) -> tuple[list, list]`; `group_by_provider(entries) -> dict[str, list[CatalogEntry]]`; `AuthProbe(status: int, ok: bool, detail: str)`; `classify_auth_probe(status_code: int) -> str`; `probe_auth(base_url: str, api_key: str, *, timeout: int = 10) -> AuthProbe`.

- [ ] **Step 1: Create the fixture files** — hand-trimmed snapshots of the live lists (envelope `{"object": "list", "data": [...]}`; entries carry `id`, `object`, `owned_by`, and `kind` on combos/web entries only):

`tests/fixtures/models_tts.json`:
```json
{"object": "list", "data": [
  {"id": "tts-combo", "object": "model", "owned_by": "combo", "kind": "tts"},
  {"id": "gemini/gemini-3.1-flash-tts-preview", "object": "model", "owned_by": "gemini"},
  {"id": "openai/tts-1", "object": "model", "owned_by": "openai"},
  {"id": "openai/gpt-4o-mini-tts", "object": "model", "owned_by": "openai"},
  {"id": "nvidia/fastpitch", "object": "model", "owned_by": "nvidia"},
  {"id": "openrouter/openai/tts-1", "object": "model", "owned_by": "openrouter"},
  {"id": "openrouter/fish-audio/s2.1-pro-free:free", "object": "model", "owned_by": "openrouter"}
]}
```

`tests/fixtures/models_stt.json`:
```json
{"object": "list", "data": [
  {"id": "stt-combo", "object": "model", "owned_by": "combo", "kind": "stt"},
  {"id": "gemini/gemini-2.5-pro", "object": "model", "owned_by": "gemini"},
  {"id": "groq/whisper-large-v3-turbo", "object": "model", "owned_by": "groq"},
  {"id": "dg/nova-3", "object": "model", "owned_by": "dg"},
  {"id": "openai/whisper-1", "object": "model", "owned_by": "openai"},
  {"id": "openai/gpt-4o-transcribe", "object": "model", "owned_by": "openai"},
  {"id": "el/scribe_v2", "object": "model", "owned_by": "el"}
]}
```

`tests/fixtures/models_web.json`:
```json
{"object": "list", "data": [
  {"id": "openclaw-search", "object": "model", "owned_by": "combo", "kind": "webSearch"},
  {"id": "openclaw-fetch", "object": "model", "owned_by": "combo", "kind": "webFetch"},
  {"id": "tavily/search", "object": "model", "kind": "webSearch", "owned_by": "tavily"},
  {"id": "tavily/fetch", "object": "model", "kind": "webFetch", "owned_by": "tavily"},
  {"id": "exa/search", "object": "model", "kind": "webSearch", "owned_by": "exa"},
  {"id": "exa/fetch", "object": "model", "kind": "webFetch", "owned_by": "exa"},
  {"id": "firecrawl/fetch", "object": "model", "kind": "webFetch", "owned_by": "firecrawl"},
  {"id": "serper/search", "object": "model", "kind": "webSearch", "owned_by": "serper"}
]}
```

`tests/fixtures/models_image.json`:
```json
{"object": "list", "data": [
  {"id": "image-combo", "object": "model", "owned_by": "combo", "kind": "image"},
  {"id": "gemini/gemini-3.1-flash-image-preview", "object": "model", "owned_by": "gemini"},
  {"id": "gemini/gemini-3-pro-image-preview", "object": "model", "owned_by": "gemini"},
  {"id": "gemini/gemini-2.5-flash-image", "object": "model", "owned_by": "gemini"},
  {"id": "nb/nanobanana-flash", "object": "model", "owned_by": "nb"},
  {"id": "replicate/zsxkib/aura-sr-v2", "object": "model", "owned_by": "replicate"},
  {"id": "replicate/zsxkib/step1x-edit", "object": "model", "owned_by": "replicate"}
]}
```

- [ ] **Step 2: Write the failing tests** in `tests/test_catalog.py`:

```python
import json
import types
from pathlib import Path

import pytest

from ninerouter_omni import catalog

FIX = Path(__file__).parent / "fixtures"


def _fx(name):
    return json.loads((FIX / name).read_text())


def test_parse_preserves_order_and_flags_combos():
    entries = catalog.parse_catalog(_fx("models_tts.json"))
    assert [e.id for e in entries][:2] == ["tts-combo", "gemini/gemini-3.1-flash-tts-preview"]
    assert entries[0].is_combo and entries[0].kind == "tts"
    assert not entries[1].is_combo and entries[1].owned_by == "gemini"


def test_parse_tolerates_junk():
    assert catalog.parse_catalog({}) == []
    assert catalog.parse_catalog({"data": ["x", {"no_id": 1}, {"id": "  "}]}) == []


def test_split_web_by_kind():
    search, fetch = catalog.split_web(catalog.parse_catalog(_fx("models_web.json")))
    assert [e.id for e in search] == ["openclaw-search", "tavily/search", "exa/search", "serper/search"]
    assert [e.id for e in fetch] == ["openclaw-fetch", "tavily/fetch", "exa/fetch", "firecrawl/fetch"]


def test_split_web_suffix_fallback_when_no_kind():
    entries = [catalog.CatalogEntry("foo/search"), catalog.CatalogEntry("bar/fetch"),
               catalog.CatalogEntry("openclaw-search"), catalog.CatalogEntry("mystery")]
    search, fetch = catalog.split_web(entries)
    assert [e.id for e in search] == ["foo/search", "openclaw-search"]
    assert [e.id for e in fetch] == ["bar/fetch"]


def test_group_combos_first_then_sorted():
    groups = catalog.group_by_provider(catalog.parse_catalog(_fx("models_tts.json")))
    assert list(groups) == ["combo", "gemini", "nvidia", "openai", "openrouter"]
    assert [e.id for e in groups["openai"]] == ["openai/tts-1", "openai/gpt-4o-mini-tts"]


def test_classify_auth_probe():
    assert catalog.classify_auth_probe(400) == "ok"
    assert catalog.classify_auth_probe(401) == "auth_failed"
    assert catalog.classify_auth_probe(403) == "auth_failed"
    assert catalog.classify_auth_probe(500) == "unexpected"


def test_fetch_catalog_uses_capability_path(monkeypatch):
    captured = {}

    def fake_get(path, *, timeout):
        captured.update(path=path, timeout=timeout)
        return _fx("models_web.json")

    monkeypatch.setattr("ninerouter_omni.catalog.get_json", fake_get)
    entries = catalog.fetch_catalog("web")
    assert captured == {"path": "/v1/models/web", "timeout": 15}
    assert entries[0].id == "openclaw-search"


def test_fetch_catalog_unknown_capability():
    with pytest.raises(KeyError):
        catalog.fetch_catalog("video")


def test_probe_auth_ok_keyless_omits_header(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, headers=headers, json=json)
        return types.SimpleNamespace(status_code=400, text="bad request")

    monkeypatch.setattr("httpx.post", fake_post)
    probe = catalog.probe_auth("http://127.0.0.1:20128/", "")
    assert probe.ok is True and probe.status == 400
    assert "Authorization" not in captured["headers"]
    assert captured["url"] == "http://127.0.0.1:20128/v1/audio/speech"
    assert "input" not in captured["json"] and "model" in captured["json"]


def test_probe_auth_bad_key_and_unreachable(monkeypatch):
    monkeypatch.setattr(
        "httpx.post",
        lambda url, **kw: types.SimpleNamespace(status_code=401, text="unauthorized"),
    )
    assert catalog.probe_auth("http://x", "bad").ok is False

    def boom(url, **kw):
        raise ConnectionError("refused")

    monkeypatch.setattr("httpx.post", boom)
    probe = catalog.probe_auth("http://x", "")
    assert probe.ok is False and probe.status == 0 and "unreachable" in probe.detail
```

- [ ] **Step 3: Run — expect import failure**

Run: `python -m pytest tests/test_catalog.py -q`
Expected: `ModuleNotFoundError: ninerouter_omni.catalog`.

- [ ] **Step 4: Implement `catalog.py`**

Module docstring: "9router gateway catalog client: live per-modality model lists + auth probe. No Hermes imports." Implementation notes:

- `parse_catalog`: `rows = payload.get("data") if isinstance(payload, dict) else payload`; keep rows that are dicts with a non-empty string `id`; `owned_by`/`kind` via `str(row.get(...) or "").strip()`.
- `fetch_catalog`: `get_json(CAPABILITY_PATHS[capability], timeout=CATALOG_TIMEOUT_S)` → `parse_catalog`.
- `split_web`: primary rule `kind == "webSearch"` / `"webFetch"`; when `kind` is empty fall back to the id suffix — `id.endswith("/search")` or `id.endswith("-search")` (same for fetch); entries matching neither stay out of both lists.
- `group_by_provider`: key = `"combo"` when `is_combo`, else `owned_by` or `id.split("/", 1)[0]` or `"other"`; combos group first, remaining group names sorted alphabetically; entry order preserved inside groups.
- `probe_auth`: build `headers = {"Content-Type": "application/json"}` (+ `Authorization` when key non-empty); `httpx.post(f"{base_url.rstrip('/')}/v1/audio/speech", json={"model": DEFAULT_TTS_MODEL}, headers=headers, timeout=timeout)` — deliberately no `input` field so 9router validates auth first; `httpx` import inside the function; on exception return `AuthProbe(status=0, ok=False, detail=f"unreachable: {ex}")`; else `verdict = classify_auth_probe(status_code)`, `ok = verdict == "ok"`, human-readable `detail`.

- [ ] **Step 5: Run — expect pass**

Run: `python -m pytest tests -q`
Expected: all green (Task 1–3).

- [ ] **Step 6: Commit**

```bash
git add catalog.py tests/test_catalog.py tests/fixtures/
git commit -m "feat(catalog): live per-modality catalogs, grouping, auth probe"
```

---

### Task 4: `tts.py` — native `NineRouterTTSProvider`

**Files:**
- Modify: `tts.py` (full rewrite — delete the monkey-patch)
- Modify: `tests/conftest.py` (add Hermes-stub helper)
- Test: `tests/test_tts.py`

**Interfaces:**
- Consumes: `settings.resolve_tts_model/compose_tts_model/ext_for_content_type/load_hermes_config/DEFAULT_TTS_MODEL/PROVIDER_NAME`; `_http.is_configured/post_json_bytes`; `catalog.fetch_catalog`.
- Produces: `TTS_FALLBACK_MODELS = ("tts-combo", "openai/tts-1", "openai/gpt-4o-mini-tts")`; `class NineRouterTTSProvider(TTSProvider)` — `name = "9router"`, `display_name = "9router"`, `is_available()`, `voice_compatible` property `False`, `synthesize(text, output_path, *, voice=None, model=None, speed=None, format="mp3", **extra) -> str` (writes file, returns path, raises on failure), `list_models()`, `default_model() -> "tts-combo"`, `get_setup_schema()`.

- [ ] **Step 1: Extend `tests/conftest.py`** — stub the Hermes ABC modules so provider modules import in tests (skip stubbing when Hermes is importable):

```python
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
```

- [ ] **Step 2: Write the failing tests** in `tests/test_tts.py`:

```python
import pytest

from ninerouter_omni import catalog, tts


def _provider():
    return tts.NineRouterTTSProvider()


def test_metadata():
    p = _provider()
    assert p.name == "9router" and p.display_name == "9router"
    assert p.voice_compatible is False
    assert p.default_model() == "tts-combo"


def test_is_available_tracks_base_url(monkeypatch):
    monkeypatch.setenv("NINEROUTER_BASE_URL", "http://x")
    monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
    assert _provider().is_available() is True
    monkeypatch.delenv("NINEROUTER_BASE_URL", raising=False)
    assert _provider().is_available() is False


def test_synthesize_composes_voice_and_writes(monkeypatch, tmp_path):
    captured = {}

    def fake_post(path, body, *, timeout=60):
        captured.update(path=path, body=body)
        return (b"ID3fake", "audio/mpeg; charset=utf-8")

    monkeypatch.setattr("ninerouter_omni.tts.post_json_bytes", fake_post)
    out = tmp_path / "voice.mp3"
    path = _provider().synthesize("hello", str(out), voice="nova", model="openai/tts-1")
    assert captured["path"] == "/v1/audio/speech"
    assert captured["body"] == {"model": "openai/tts-1/nova", "input": "hello"}
    assert path == str(out) and out.read_bytes() == b"ID3fake"


def test_synthesize_rewrites_extension(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ninerouter_omni.tts.post_json_bytes",
        lambda path, body, *, timeout=60: (b"RIFF", "audio/wav"),
    )
    path = _provider().synthesize("hi", str(tmp_path / "voice.mp3"), model="openai/tts-1")
    assert path == str(tmp_path / "voice.wav") and (tmp_path / "voice.wav").exists()


def test_synthesize_raises_on_empty_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ninerouter_omni.tts.post_json_bytes",
        lambda path, body, *, timeout=60: (b"", "audio/mpeg"),
    )
    with pytest.raises(RuntimeError, match="empty"):
        _provider().synthesize("hi", str(tmp_path / "v.mp3"), model="m")


def test_synthesize_defaults_model_from_config(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ninerouter_omni.tts.load_hermes_config",
        lambda: {"tts": {"model": "openai/tts-1"}},
    )
    captured = {}

    def fake_post(path, body, *, timeout=60):
        captured.update(body=body)
        return (b"a", "audio/mpeg")

    monkeypatch.setattr("ninerouter_omni.tts.post_json_bytes", fake_post)
    _provider().synthesize("hi", str(tmp_path / "v.mp3"))
    assert captured["body"]["model"] == "openai/tts-1"


def test_list_models_live_and_fallback(monkeypatch):
    entries = [catalog.CatalogEntry("tts-combo", "combo", "tts"),
               catalog.CatalogEntry("openai/tts-1", "openai")]
    monkeypatch.setattr("ninerouter_omni.tts.fetch_catalog", lambda cap: entries)
    models = _provider().list_models()
    assert models[0]["id"] == "tts-combo" and "combo" in models[0]["display"].lower()

    def boom(cap):
        raise RuntimeError("gateway down")

    monkeypatch.setattr("ninerouter_omni.tts.fetch_catalog", boom)
    assert [m["id"] for m in _provider().list_models()][0] == "tts-combo"
```

- [ ] **Step 3: Run — expect failure**

Run: `python -m pytest tests/test_tts.py -q`
Expected: FAIL — no `NineRouterTTSProvider`.

- [ ] **Step 4: Rewrite `tts.py`**

- Keep `from __future__ import annotations`; imports: `logging`, `Optional`; `from agent.tts_provider import TTSProvider`; from `.settings import DEFAULT_TTS_MODEL, PROVIDER_NAME, compose_tts_model, ext_for_content_type, load_hermes_config, resolve_tts_model`; from `._http import is_configured, post_json_bytes`; from `.catalog import fetch_catalog`.
- Class `NineRouterTTSProvider(TTSProvider)`:
  - `synthesize`: `model = model or resolve_tts_model(load_hermes_config())`; `composed = compose_tts_model(model, voice)`; `audio, content_type = post_json_bytes("/v1/audio/speech", {"model": composed, "input": text}, timeout=120)`; `RuntimeError` when `audio` empty (message contains "empty"); rewrite the extension via `ext_for_content_type`; `Path(...).parent.mkdir(parents=True, exist_ok=True)`; write bytes; return the (possibly rewritten) path string.
  - `list_models`: `fetch_catalog("tts")` → `{"id": e.id, "display": e.id + (" (combo)" if e.is_combo else "")}`; on any exception return `TTS_FALLBACK_MODELS` entries (`display` = id).
  - `default_model` → `DEFAULT_TTS_MODEL`.
  - `get_setup_schema` → `{"name": "9router", "badge": "self-hosted", "tag": "Self-hosted 9router gateway — proxies /v1/audio/speech.", "env_vars": [BASE_URL entry, API key entry with prompt "... (optional — leave empty for keyless gateways)"]}`.
- Delete `install_tts_patch`, `_generate_9router_tts`, `_resolve_output_path`, `_build_response`, `_error_response`, `_resolve_model`, `_load_9router_tts_config` (superseded by `settings`).

- [ ] **Step 5: Run — expect pass**

Run: `python -m pytest tests -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add tts.py tests/test_tts.py tests/conftest.py
git commit -m "feat(tts): native NineRouterTTSProvider with model/voice composition"
```

---

### Task 5: `stt.py` — native `NineRouterTranscriptionProvider`

**Files:**
- Modify: `stt.py` (full rewrite — delete the monkey-patch)
- Test: `tests/test_stt.py`

**Interfaces:**
- Consumes: `settings.resolve_stt_model/build_transcription_fields/load_hermes_config/DEFAULT_STT_MODEL/PROVIDER_NAME`; `_http.is_configured/post_form`; `catalog.fetch_catalog`.
- Produces: `STT_FALLBACK_MODELS = ("stt-combo", "groq/whisper-large-v3-turbo", "openai/gpt-4o-transcribe")`; `guess_mime(file_path: str) -> str` (kept, with `_AUDIO_MIME_OVERRIDES`); `class NineRouterTranscriptionProvider(TranscriptionProvider)` — `name = "9router"`, `display_name = "9router"`, `is_available()`, `transcribe(file_path, *, model=None, language=None, **extra) -> dict` (never raises; envelope `{success, transcript, provider[, model][, error]}`), `list_models()`, `default_model() -> "stt-combo"`, `get_setup_schema()`.

- [ ] **Step 1: Write the failing tests** in `tests/test_stt.py`:

```python
from ninerouter_omni import stt


def _provider():
    return stt.NineRouterTranscriptionProvider()


def test_transcribe_success_envelope(monkeypatch, tmp_path):
    monkeypatch.setenv("NINEROUTER_BASE_URL", "http://x")
    captured = {}

    def fake_post_form(path, *, data, file_field, file_path, file_mime="", timeout=60):
        captured.update(path=path, data=data, file_field=file_field)
        return {"text": "hello world"}

    monkeypatch.setattr("ninerouter_omni.stt.post_form", fake_post_form)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3")
    out = _provider().transcribe(str(audio), model="groq/whisper-large-v3-turbo")
    assert out == {"success": True, "transcript": "hello world", "provider": "9router",
                   "model": "groq/whisper-large-v3-turbo"}
    assert captured["path"] == "/v1/audio/transcriptions"
    assert captured["file_field"] == "file"
    assert captured["data"]["model"] == "groq/whisper-large-v3-turbo"
    assert "language" not in captured["data"]  # no cfg, no language arg


def test_transcribe_carries_config_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("NINEROUTER_BASE_URL", "http://x")
    monkeypatch.setattr(
        "ninerouter_omni.stt.load_hermes_config",
        lambda: {"stt": {"9router": {"prompt": "ctx", "language": "en"}}},
    )
    captured = {}

    def fake_post_form(path, *, data, file_field, file_path, file_mime="", timeout=60):
        captured.update(data=data)
        return {"text": ""}

    monkeypatch.setattr("ninerouter_omni.stt.post_form", fake_post_form)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    _provider().transcribe(str(audio))
    assert captured["data"]["model"] == "stt-combo"
    assert captured["data"]["prompt"] == "ctx"
    assert captured["data"]["language"] == "en"


def test_transcribe_never_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("NINEROUTER_BASE_URL", "http://x")

    def boom(*args, **kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr("ninerouter_omni.stt.post_form", boom)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = _provider().transcribe(str(audio))
    assert out["success"] is False and out["transcript"] == ""
    assert "gateway down" in out["error"] and out["provider"] == "9router"


def test_transcribe_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("NINEROUTER_BASE_URL", raising=False)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = _provider().transcribe(str(audio))
    assert out["success"] is False and "NINEROUTER_BASE_URL" in out["error"]


def test_list_models_fallback_and_default(monkeypatch):
    def boom(cap):
        raise RuntimeError("down")

    monkeypatch.setattr("ninerouter_omni.stt.fetch_catalog", boom)
    p = _provider()
    assert p.default_model() == "stt-combo"
    assert [m["id"] for m in p.list_models()][0] == "stt-combo"


def test_guess_mime(tmp_path):
    assert stt.guess_mime(str(tmp_path / "a.ogg")) == "audio/ogg"
    assert isinstance(stt.guess_mime(str(tmp_path / "a.unknownext")), str)
```

- [ ] **Step 2: Run — expect failure**

Run: `python -m pytest tests/test_stt.py -q`
Expected: FAIL — no `NineRouterTranscriptionProvider`.

- [ ] **Step 3: Rewrite `stt.py`**

- Imports: `logging`, `mimetypes`, `os`, `Optional`, `Dict`, `Any`; `from agent.transcription_provider import TranscriptionProvider`; from `.settings import DEFAULT_STT_MODEL, PROVIDER_NAME, build_transcription_fields, load_hermes_config, resolve_stt_model`; from `._http import is_configured, post_form`; from `.catalog import fetch_catalog`.
- Keep `_AUDIO_MIME_OVERRIDES` and rename `_guess_mime` → public `guess_mime`.
- Class `NineRouterTranscriptionProvider(TranscriptionProvider)`:
  - `transcribe`: when `not is_configured()` return the error envelope naming `NINEROUTER_BASE_URL`; `resolved = model or resolve_stt_model(load_hermes_config())`; `data = build_transcription_fields(resolved, language, load_hermes_config())`; `post_form("/v1/audio/transcriptions", data=data, file_field="file", file_path=file_path, file_mime=guess_mime(file_path), timeout=300)`; unwrap `response["text"]` (fallback `_raw` string, then `""`); success envelope includes `"model": resolved`; wrap the whole call in try/except returning `{"success": False, "transcript": "", "error": f"9router STT failed: {exc}", "provider": PROVIDER_NAME}` — never raises.
  - `list_models`: `fetch_catalog("stt")` (display = id, combos get " (combo)") else `STT_FALLBACK_MODELS`.
  - `default_model` → `DEFAULT_STT_MODEL`; `get_setup_schema` mirrors the TTS one with tag "Self-hosted 9router gateway — proxies /v1/audio/transcriptions."
- Delete `install_stt_patch`, `_transcribe_9router`, `_resolve_model`, `_load_9router_stt_config`.

- [ ] **Step 4: Run — expect pass**

Run: `python -m pytest tests -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add stt.py tests/test_stt.py
git commit -m "feat(stt): native NineRouterTranscriptionProvider"
```

---

### Task 6: `image_gen.py` — combo default + canonical key

**Files:**
- Modify: `image_gen.py`
- Test: `tests/test_image_gen.py`

**Interfaces:**
- Consumes: `settings.resolve_image_model/load_hermes_config/DEFAULT_IMAGE_MODEL`.
- Produces: `DEFAULT_MODEL = "image-combo"`; `CURATED_MODELS = ("image-combo", "gemini/gemini-3.1-flash-image-preview", "gemini/gemini-3-pro-image-preview", "nb/nanobanana-flash")`; `NineRouterImageGenProvider` with `default_model() -> "image-combo"`, `list_models()` = configured model first when it differs from `image-combo`, then the curated set (never more than `len(CURATED_MODELS) + 1`); `generate()` unchanged except the model comes from `settings.resolve_image_model(load_hermes_config())`.

- [ ] **Step 1: Write the failing tests** in `tests/test_image_gen.py`:

```python
from ninerouter_omni import image_gen


def _provider():
    return image_gen.NineRouterImageGenProvider()


def test_default_model_is_combo():
    assert _provider().default_model() == "image-combo"


def test_list_models_is_curated_not_a_dump():
    ids = [m["id"] for m in _provider().list_models()]
    assert ids[0] == "image-combo"
    assert len(ids) <= len(image_gen.CURATED_MODELS) + 1


def test_list_models_prepends_configured(monkeypatch):
    monkeypatch.setattr(
        "ninerouter_omni.image_gen.load_hermes_config",
        lambda: {"image_gen": {"model": "custom/model"}},
    )
    models = _provider().list_models()
    assert models[0]["id"] == "custom/model" and "configured" in models[0]["display"]


def test_old_key_still_resolves(monkeypatch):
    monkeypatch.setattr(
        "ninerouter_omni.image_gen.load_hermes_config",
        lambda: {"image_gen": {"9router": {"model": "legacy/model"}}},
    )
    assert _provider().list_models()[0]["id"] == "legacy/model"


def test_detect_extension():
    import base64

    jpeg = base64.b64encode(b"\xff\xd8\xff\xe0hello").decode()
    gif = base64.b64encode(b"GIF89a....").decode()
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n....").decode()
    assert image_gen._detect_image_extension(jpeg) == "jpg"
    assert image_gen._detect_image_extension(gif) == "gif"
    assert image_gen._detect_image_extension(png) == "png"
    assert image_gen._detect_image_extension("!!!not base64!!!") == "png"
```

- [ ] **Step 2: Run — expect failure**

Run: `python -m pytest tests/test_image_gen.py -q`
Expected: FAIL — default is `gemini/gemini-3-pro-image-preview`.

- [ ] **Step 3: Implement in `image_gen.py`**

- `DEFAULT_MODEL = "image-combo"`; add `CURATED_MODELS`.
- Replace `_resolve_model` with `_resolve_model() -> str: return resolve_image_model(load_hermes_config())` (delegates to settings; keeps the old `image_gen.9router.model` readable).
- `list_models`: start from curated entries (`display` = pretty short label, e.g. `"9router image combo (default)"` for `image-combo`); when the resolved model is not in the curated set, insert it at index 0 with `"(configured)"` in `display`.
- `generate`: replace its `_resolve_model` use with the settings-based one; keep `image_gen.9router.quality` passthrough and everything else.
- Delete `_load_9router_image_config` for the model path only — keep reading optional `quality` from `image_gen.9router` (small helper may stay for that).

- [ ] **Step 4: Run — expect pass; commit**

Run: `python -m pytest tests -q` → green.

```bash
git add image_gen.py tests/test_image_gen.py
git commit -m "feat(image): image-combo default and image_gen.model reads"
```

---

### Task 7: `web.py` — model names from config

**Files:**
- Modify: `web.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `settings.resolve_search_model/resolve_fetch_model/load_hermes_config/DEFAULT_SEARCH_MODEL/DEFAULT_FETCH_MODEL`.
- Produces: `NineRouterWebSearchProvider` unchanged in shape; `search()` posts the resolved search model, `extract()` posts the resolved fetch model. The module constants `SEARCH_MODEL`/`FETCH_MODEL` are removed (defaults now live in `settings`).

- [ ] **Step 1: Write the failing tests** in `tests/test_web.py`:

```python
from ninerouter_omni import web


def _provider():
    return web.NineRouterWebSearchProvider()


def test_search_uses_configured_model(monkeypatch):
    monkeypatch.setattr(
        "ninerouter_omni.web.load_hermes_config",
        lambda: {"web": {"9router": {"search_model": "tavily/search"}}},
    )
    captured = {}

    def fake_post_json(path, body, *, timeout=60):
        captured.update(path=path, body=body)
        return {"results": [{"title": "T", "url": "http://u", "snippet": "S"}]}

    monkeypatch.setattr("ninerouter_omni.web.post_json", fake_post_json)
    out = _provider().search("query", limit=3)
    assert captured["path"] == "/v1/search"
    assert captured["body"]["model"] == "tavily/search"
    assert captured["body"]["max_results"] == 3
    assert out["success"] is True and out["data"]["web"][0]["position"] == 1


def test_search_default_model(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ninerouter_omni.web.post_json",
        lambda path, body, *, timeout=60: captured.update(body=body) or {"results": []},
    )
    _provider().search("q")
    assert captured["body"]["model"] == "openclaw-search"


def test_extract_uses_fetch_model(monkeypatch):
    captured = {}

    def fake_post_json(path, body, *, timeout=60):
        captured.update(path=path, body=body)
        return {"content": {"text": "page text"}}

    monkeypatch.setattr("ninerouter_omni.web.post_json", fake_post_json)
    results = _provider().extract(["http://example.com"])
    assert captured["path"] == "/v1/web/fetch"
    assert captured["body"]["model"] == "openclaw-fetch"
    assert results[0]["content"] == "page text"
```

Note: `lambda path, body, *, timeout=60: captured.update(body=body) or {"results": []}` works because `dict.update` returns `None` (falsy) so `or` yields the dict.

- [ ] **Step 2: Run — expect failure**

Run: `python -m pytest tests/test_web.py -q`
Expected: FAIL on `ninerouter_omni.web.load_hermes_config` (attribute missing).

- [ ] **Step 3: Implement in `web.py`**

- Add imports from `.settings` (`resolve_search_model`, `resolve_fetch_model`, `load_hermes_config`).
- In `search()`: `model = resolve_search_model(load_hermes_config())` passed as `"model"` in the payload.
- In `extract()`: `model = resolve_fetch_model(load_hermes_config())` per URL call.
- Remove `SEARCH_MODEL`/`FETCH_MODEL` constants. Everything else (normalization, interrupt checks, error shapes) stays.

- [ ] **Step 4: Run — expect pass; commit**

Run: `python -m pytest tests -q` → green.

```bash
git add web.py tests/test_web.py
git commit -m "feat(web): search/fetch models from config keys"
```

---

### Task 8: `setup_cmd.py` — pure write planner

**Files:**
- Create: `setup_cmd.py` (pure section only in this task)
- Test: `tests/test_wizard.py`

**Interfaces:**
- Consumes: `settings.resolve_*` / defaults; `catalog.fetch_catalog/split_web/group_by_provider/CatalogEntry`.
- Produces:
  - `CAPABILITY_LABELS: dict[str, str]` — ordered: `web_search` "Web search", `web_fetch` "Web fetch", `tts` "Text-to-speech", `stt` "Speech-to-text", `image` "Image generation".
  - `current_picks(cfg) -> dict[str, bool]` — §6.2 activation semantics: `web.search_backend` if set else `web.backend`; `tts.provider`; `stt.provider`; `image_gen.provider` equal to `"9router"`.
  - `default_selection(cfg) -> dict[str, bool]` — current picks when any is on; else all `True` (first run, §6.1).
  - `plan_writes(cfg, decisions: Mapping[str, bool | None], *, models: Mapping[str, str | None], voice: str | None = None) -> dict` — deep-copies `cfg` (never mutates input). `True` = enable + write model (`models[...]` skipped when falsy); `False` = disable-on-uncheck (delete only values equal to `"9router"`; model keys kept; `stt.enabled` untouched; `web.backend` deleted only when **both** web decisions are `False`); `None` = leave untouched (§6.2, §6.5 "skipped capability is left untouched").
  - `fetch_capability_models(capability) -> list[CatalogEntry]` — web caps via `split_web(fetch_catalog("web"))`; `tts`/`stt`/`image` direct.
  - `build_scripted_plan(cfg, args) -> tuple[dict[str, bool], dict[str, str], str | None]` — `--yes` path: all five `True`; models = flag or current-resolved (settings resolvers, which fall back to defaults); voice = `args.voice` or `None`.

- [ ] **Step 1: Write the failing tests** in `tests/test_wizard.py`:

```python
import json
from pathlib import Path
from types import SimpleNamespace

from ninerouter_omni import catalog
from ninerouter_omni import setup_cmd as wizard

FIX = Path(__file__).parent / "fixtures"

ALL = list(wizard.CAPABILITY_LABELS)


def _fx(name):
    return json.loads((FIX / name).read_text())


def test_current_picks_web_backend_fallback_and_override():
    assert wizard.current_picks({"web": {"backend": "9router"}})["web_search"] is True
    picks = wizard.current_picks({"web": {"backend": "9router", "search_backend": "tavily"}})
    assert picks["web_search"] is False and picks["web_fetch"] is True


def test_current_picks_provider_sections():
    cfg = {"tts": {"provider": "9router"}, "stt": {"provider": "openai"},
           "image_gen": {"provider": "9router"}}
    assert wizard.current_picks(cfg) == {
        "web_search": False, "web_fetch": False, "tts": True, "stt": False, "image": True}


def test_default_selection_first_run_all_on():
    assert wizard.default_selection({}) == {cap: True for cap in ALL}


def test_default_selection_mirrors_existing():
    assert wizard.default_selection({"tts": {"provider": "9router"}}) == {
        "web_search": False, "web_fetch": False, "tts": True, "stt": False, "image": False}


def test_plan_enables_picked_only():
    out = wizard.plan_writes(
        {},
        {"web_search": False, "web_fetch": False, "tts": True, "stt": False, "image": False},
        models={"tts": "openai/tts-1"}, voice="nova")
    assert out == {"tts": {"provider": "9router", "model": "openai/tts-1", "voice": "nova"}}


def test_plan_writes_web_keys_with_nested_models():
    out = wizard.plan_writes(
        {},
        {"web_search": True, "web_fetch": True, "tts": False, "stt": False, "image": False},
        models={"web_search": "tavily/search", "web_fetch": "exa/fetch"})
    assert out["web"] == {
        "search_backend": "9router", "extract_backend": "9router",
        "9router": {"search_model": "tavily/search", "fetch_model": "exa/fetch"}}


def test_plan_writes_stt_and_image():
    out = wizard.plan_writes(
        {},
        {"web_search": False, "web_fetch": False, "tts": False, "stt": True, "image": True},
        models={"stt": "stt-combo", "image": "image-combo"})
    assert out["stt"] == {"provider": "9router", "enabled": True,
                          "9router": {"model": "stt-combo"}}
    assert out["image_gen"] == {"provider": "9router", "model": "image-combo"}


def test_disable_removes_only_9router_owned_values():
    cfg = {"tts": {"provider": "9router", "model": "m"}, "image_gen": {"provider": "openai"}}
    out = wizard.plan_writes(
        cfg,
        {"web_search": False, "web_fetch": False, "tts": False, "stt": False, "image": None},
        models={})
    assert "provider" not in out["tts"] and out["tts"]["model"] == "m"
    assert out["image_gen"]["provider"] == "openai"


def test_disable_keeps_foreign_web_backend():
    cfg = {"web": {"search_backend": "tavily", "backend": "9router"}}
    out = wizard.plan_writes(
        cfg, {"web_search": False, "web_fetch": None, "tts": None, "stt": None, "image": None},
        models={})
    assert out["web"]["search_backend"] == "tavily"
    assert out["web"]["backend"] == "9router"  # only ONE web cap turned off — shared stays


def test_both_web_off_deletes_shared_backend():
    cfg = {"web": {"backend": "9router"}}
    out = wizard.plan_writes(
        cfg, {"web_search": False, "web_fetch": False, "tts": None, "stt": None, "image": None},
        models={})
    assert "backend" not in out["web"]


def test_none_decisions_leave_capability_untouched():
    cfg = {"tts": {"provider": "9router"}}
    out = wizard.plan_writes(cfg, {cap: None for cap in ALL}, models={})
    assert out == cfg and out is not cfg


def test_plan_does_not_mutate_input():
    cfg = {"tts": {"provider": "9router"}}
    wizard.plan_writes(cfg, {cap: False for cap in ALL}, models={})
    assert cfg == {"tts": {"provider": "9router"}}


def test_scripted_plan_flags_then_current_then_defaults():
    args = SimpleNamespace(tts_model=None, stt_model="stt-x", image_model=None,
                           search_model=None, fetch_model=None, voice="nova")
    decisions, models, voice = wizard.build_scripted_plan({"tts": {"model": "openai/tts-1"}}, args)
    assert all(decisions.values())
    assert models == {"web_search": "openclaw-search", "web_fetch": "openclaw-fetch",
                      "tts": "openai/tts-1", "stt": "stt-x", "image": "image-combo"}
    assert voice == "nova"


def test_fetch_capability_models_splits_web(monkeypatch):
    entries = catalog.parse_catalog(_fx("models_web.json"))
    monkeypatch.setattr("ninerouter_omni.setup_cmd.fetch_catalog", lambda cap: entries)
    assert [e.id for e in wizard.fetch_capability_models("web_search")][0] == "openclaw-search"
    assert [e.id for e in wizard.fetch_capability_models("web_fetch")][0] == "openclaw-fetch"
```

- [ ] **Step 2: Run — expect failure**

Run: `python -m pytest tests/test_wizard.py -q`
Expected: `ModuleNotFoundError: ninerouter_omni.setup_cmd`.

- [ ] **Step 3: Implement the pure section of `setup_cmd.py`**

Module docstring: "hermes 9router setup — live-catalog model wizard. Pure planner at module level; all Hermes imports are lazy inside functions." Implementation notes:

- `CAPABILITY_LABELS` — plain dict in the order above (dict preserves order).
- `current_picks` — read `web.search_backend` / `web.extract_backend` / `web.backend` exactly per §6.2; a set-but-different key overrides the shared fallback.
- `plan_writes` — `copy.deepcopy(cfg)`, then per-capability enable (`True`) or disable (`False`), then the both-web rule; `voice` written only under `tts` and only when truthy; model writes only when the value is a non-empty string.
- `fetch_capability_models` — mapping `{"web_search": "web", "web_fetch": "web", "tts": "tts", "stt": "stt", "image": "image"}`.
- No Hermes imports at module level (tests import this module without Hermes).

- [ ] **Step 4: Run — expect pass**

Run: `python -m pytest tests -q`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add setup_cmd.py tests/test_wizard.py
git commit -m "feat(wizard): pure write planner for capability enable/disable"
```

---

### Task 9: `setup_cmd.py` — interactive wizard + CLI subcommand

**Files:**
- Modify: `setup_cmd.py` (wizard section + CLI registration)
- Test: `tests/test_wizard_cli.py`

**Interfaces:**
- Produces: `register_subcommand(parser) -> None` (setup_fn — adds the `setup` subparser with `dest="nine_router_command"`, all seven flags, and `sp.set_defaults(func=handle_setup)`); `handle_setup(args) -> int | None` (handler_fn).
- Consumes (all lazy inside functions): `hermes_cli.config.load_config/save_config/get_env_value/save_env_value`, `hermes_cli.curses_ui.curses_checklist/curses_single_select`, `hermes_cli.secret_prompt.masked_secret_prompt`, `rich.prompt.Confirm`, `rich.console.Console`.

- [ ] **Step 1: Write the failing tests** in `tests/test_wizard_cli.py`:

```python
import argparse

from ninerouter_omni import setup_cmd


def _parse(argv):
    parser = argparse.ArgumentParser(prog="hermes")
    subs = parser.add_subparsers(dest="command")
    p9 = subs.add_parser("9router")
    setup_cmd.register_subcommand(p9)
    return parser.parse_args(argv)


def test_subcommand_registers_setup_with_flags():
    ns = _parse(["9router", "setup", "--yes", "--tts-model", "openai/tts-1", "--voice", "nova"])
    assert ns.nine_router_command == "setup"
    assert ns.yes is True and ns.tts_model == "openai/tts-1" and ns.voice == "nova"
    assert ns.func is setup_cmd.handle_setup


def test_subcommand_defaults():
    ns = _parse(["9router", "setup"])
    assert ns.yes is False and ns.tts_model is None and ns.voice is None
```

- [ ] **Step 2: Run — expect failure**

Run: `python -m pytest tests/test_wizard_cli.py -q`
Expected: `AttributeError: module ... has no attribute 'register_subcommand'`.

- [ ] **Step 3: Implement the wizard**

Follow §6.1 exactly. Structure:

- `register_subcommand(parser)`: `sub = parser.add_subparsers(dest="nine_router_command")`; `sp = sub.add_parser("setup", help="Pick 9router models from your gateway's live catalog")`; flags: `--yes` (`action="store_true"`, help "Non-interactive: mirror the existing config, fill the rest with defaults, enable all five capabilities"); `--tts-model`, `--stt-model`, `--image-model`, `--search-model`, `--fetch-model` (plain `default=None`); `--voice` (free text); `sp.set_defaults(func=handle_setup)`.
- `handle_setup(args)`: if `getattr(args, "nine_router_command", None) != "setup"` print "Run `hermes 9router setup` to configure models." and return 1; else `return run_wizard(args)`.
- `run_wizard(args)` (wizard section — all Hermes imports inside the function):
  1. `yes = bool(getattr(args, "yes", False))`; if `not yes and not sys.stdin.isatty()` → print "Refusing to run interactively without a TTY — use `--yes` for scripted installs." and return 1.
  2. `cfg = load_config()`.
  3. **`--yes` path:** `base = get_env_value("NINEROUTER_BASE_URL") or ""`; if empty → print "Set NINEROUTER_BASE_URL first" and return 1. No prompts, no env writes. `decisions, models, voice = build_scripted_plan(cfg, args)`; skip to step 8.
  4. **Interactive env:** `base = get_env_value("NINEROUTER_BASE_URL") or ""`; when empty, prompt `input("9router gateway base URL (e.g. http://127.0.0.1:20128): ")` — abort (return 1) when still empty. `require_key = Confirm.ask("Does your gateway require an API key?", default=True)`; when `require_key` and no key stored, `key = masked_secret_prompt("NINEROUTER_API_KEY: ").strip()`; when not `require_key`, `key = ""` (persist keyless by `save_env_value("NINEROUTER_API_KEY", "")` when a value existed). Persist via `save_env_value` + update `os.environ`.
  5. **Probe loop (max 3 attempts):** connect check `fetch_catalog("tts")` — on exception print the error and re-prompt URL/key; then `probe = probe_auth(base, key)` — `probe.ok` → break; `probe.status in (401, 403)` → print "API key rejected" and re-prompt the key; anything else → print `probe.detail` and re-prompt URL/key. All 3 attempts spent → print fix instructions and return 1 **without writing any config**.
  6. **Capability checklist:** items = `list(CAPABILITY_LABELS.values())`; `selected = {i for i, cap in enumerate(CAPABILITY_LABELS) if default_selection(cfg)[cap]}`; `chosen = curses_checklist("Route which capabilities through 9router?", items, selected, cancel_returns=selected)`; `decisions = {cap: (i in chosen) for i, cap in enumerate(CAPABILITY_LABELS)}`.
  7. **Per selected capability** (skip caps where a `--*-model` flag was given — use the flag and mark the model as chosen): `entries = fetch_capability_models(cap)` — on exception offer retry/skip; on skip set `decisions[cap] = None` (left untouched, §6.5) and continue. Two-step pick: `groups = group_by_provider(entries)`; labels = group key, with `"combo"` rendered as `"Combos (auto-fallback)"`; group via `curses_single_select(..., searchable=True)` — cancel → back out of the capability (`decisions[cap] = None`). Within the group, mark the currently resolved model `"(currently in use)"` and use its index as `default_index`; model via `curses_single_select` — cancel → back to the group step. Record `models[cap] = entry.id` and remember whether the picked entry `is_combo`.
  8. **TTS voice:** only when `decisions["tts"] is True` and the picked model is not a combo and no `--voice` was given — print `settings.TTS_VOICE_SUGGESTIONS` and take a free-text `input()`; empty → `voice = None` (leave `tts.voice` alone).
  9. `out = plan_writes(cfg, decisions, models=models, voice=voice)`; print a human summary of enabled/disabled capabilities and their models; `save_config(out)`.
  10. **Smoke test:** for every enabled capability, `fetch_capability_models(cap)` → print `✓`/`✗`; if any fails print remediation and return 1 (config already saved, per §6.1 order).
  11. Final line exactly: `restart the gateway: hermes gateway restart`. Return 0.

- [ ] **Step 4: Run — expect pass**

Run: `python -m pytest tests -q && python -m py_compile setup_cmd.py`
Expected: all green, no output from py_compile.

- [ ] **Step 5: Commit**

```bash
git add setup_cmd.py tests/test_wizard_cli.py
git commit -m "feat(wizard): interactive live-catalog setup with --yes scripted mode"
```

---

### Task 10: `__init__.py` — native registrations + CLI wiring

**Files:**
- Modify: `__init__.py`
- Modify: `tests/conftest.py` (add the `plugin_pkg` fixture)
- Test: `tests/test_register.py`

**Interfaces:**
- Consumes: the four provider classes (Tasks 4–7), `setup_cmd.register_subcommand/handle_setup` (Task 9).
- Produces: `register(ctx)` — registers web search, image gen, TTS, transcription providers (all named `9router`) and the `9router` CLI command; logs a warning and keeps web/image when native TTS/STT hooks are missing (Hermes < 0.17, §6.5).

- [ ] **Step 1: Add the package fixture to `tests/conftest.py`**

```python
import importlib.util

import pytest


def _load_plugin_package():
    """Load the real __init__.py the way Hermes does (as a package)."""
    name = "ninerouter_omni_pkg"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    module.__package__ = name
    module.__path__ = [str(ROOT)]
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def plugin_pkg():
    return _load_plugin_package()
```

- [ ] **Step 2: Write the failing tests** in `tests/test_register.py`:

```python
class FakeCtx:
    def __init__(self, native_hooks=True):
        self.web, self.image, self.tts, self.stt, self.cli = [], [], [], [], []
        if native_hooks:
            self.register_tts_provider = self.tts.append
            self.register_transcription_provider = self.stt.append

    def register_web_search_provider(self, provider):
        self.web.append(provider)

    def register_image_gen_provider(self, provider):
        self.image.append(provider)

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli.append((name, setup_fn, handler_fn))


def test_register_all_providers_and_cli(plugin_pkg, monkeypatch):
    monkeypatch.setattr(plugin_pkg, "_patch_web_tools_gating", lambda: None)
    ctx = FakeCtx()
    plugin_pkg.register(ctx)
    assert [p.name for p in ctx.web] == ["9router"]
    assert [p.name for p in ctx.image] == ["9router"]
    assert [p.name for p in ctx.tts] == ["9router"]
    assert [p.name for p in ctx.stt] == ["9router"]
    name, setup_fn, handler_fn = ctx.cli[0]
    assert name == "9router"
    assert setup_fn is plugin_pkg.setup_cmd.register_subcommand
    assert handler_fn is plugin_pkg.setup_cmd.handle_setup


def test_register_old_hermes_warns_but_keeps_web_image(plugin_pkg, monkeypatch, caplog):
    monkeypatch.setattr(plugin_pkg, "_patch_web_tools_gating", lambda: None)
    ctx = FakeCtx(native_hooks=False)
    with caplog.at_level("WARNING"):
        plugin_pkg.register(ctx)  # must not raise
    assert ctx.web and ctx.image and ctx.cli
    assert not ctx.tts and not ctx.stt
    assert any("0.17" in record.message for record in caplog.records)
```

- [ ] **Step 3: Run — expect failure**

Run: `python -m pytest tests/test_register.py -q`
Expected: FAIL — current `register()` installs monkey-patches, no CLI command.

- [ ] **Step 4: Rewrite `register()` in `__init__.py`**

- Imports: the four provider classes, `from . import setup_cmd`.
- `register(ctx)`: register web + image first; then `try: ctx.register_tts_provider(NineRouterTTSProvider()); ctx.register_transcription_provider(NineRouterTranscriptionProvider())` / `except AttributeError: logger.warning("Hermes v0.17.0+ is required for native TTS/STT providers; web search and image generation remain active.")`; then `_patch_web_tools_gating()` inside `try/except Exception` with an explanatory warning (a Hermes refactor must not break plugin load); then `ctx.register_cli_command(name="9router", help="9router gateway setup — pick models from your gateway's live catalog", setup_fn=setup_cmd.register_subcommand, handler_fn=setup_cmd.handle_setup)`.
- Keep `_patch_web_tools_gating()` (web tool gating) as-is otherwise; update the module docstring (native hooks, keyless, wizard).
- Remove the TTS/STT monkey-patch installation calls.

- [ ] **Step 5: Run — expect pass; commit**

Run: `python -m pytest tests -q` → green.

```bash
git add __init__.py tests/conftest.py tests/test_register.py
git commit -m "feat(plugin): native provider registrations + CLI wizard wiring"
```

---

### Task 11: `plugin.yaml` + `after-install.md`

**Files:**
- Modify: `plugin.yaml`
- Create: `after-install.md`

- [ ] **Step 1: Update `plugin.yaml`** to exactly:

```yaml
name: 9router-omni
version: 3.0.0
description: "Route web search, web extract, image generation, TTS, and STT through a 9router gateway."
author: dipandhali2021
kind: backend
provides_web_providers:
  - 9router
provides_image_gen_providers:
  - 9router
requires_env:
  - name: NINEROUTER_BASE_URL
    description: "9router gateway base URL, e.g. http://127.0.0.1:20128"
  - name: NINEROUTER_API_KEY
    description: "9router API key (optional — leave empty for keyless gateways)"
    secret: true
```

(The rich `requires_env` dicts are what `hermes_cli/plugins_cmd.py::_prompt_plugin_env_vars` prompts for at install; already-set variables are skipped.)

- [ ] **Step 2: Create `after-install.md`** exactly:

```markdown
## 9router-omni installed

Next: pick models from your gateway's live catalog:

    hermes 9router setup

The wizard configures web search, web extract, TTS, STT, and image
generation. Re-run it any time to change models or disable a capability.

Keyless gateways are supported — leave `NINEROUTER_API_KEY` empty.
```

- [ ] **Step 3: Verify the manifest parses**

Run: `python3 -c "import pathlib, yaml; m = yaml.safe_load(pathlib.Path('plugin.yaml').read_text()); assert m['version'] == '3.0.0' and m['requires_env'][1]['secret'] is True; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add plugin.yaml after-install.md
git commit -m "chore: v3.0.0 manifest + install-time env prompts + after-install note"
```

---

### Task 12: README rewrite

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Rewrite `README.md`** with these sections (keep it concise, no marketing):

1. **Title + one paragraph** — all five capabilities through one 9router gateway.
2. **Requirements** — Hermes ≥ v0.17.0 for native TTS/STT hooks (web search/image generation work on older versions); a reachable 9router gateway.
3. **Install** — `hermes plugins install` flow → env prompts (URL required, API key optional for keyless) → enable → `hermes 9router setup`.
4. **Setup wizard** — what it does; the exact keys it writes (compact table from §6.2); re-run semantics: unchecking **disables 9router for that capability only** (never deletes another provider's values, never deletes model keys); flags `--yes` / `--*-model` / `--voice` for scripted installs; non-TTY without `--yes` refuses.
5. **Verify** — `hermes tools` rows show 9router; example one-liners for a search, an image, a TTS call.
6. **Models** — per-modality catalog endpoints (`GET {base}/v1/models/{web,tts,stt,image}`); defaults table (`openclaw-search`, `openclaw-fetch`, `tts-combo`, `stt-combo`, `image-combo`); note that the full `/v1/models` list is not used.
7. **Troubleshooting** — unreachable gateway; 401 vs 400 auth-probe meaning; `combo + voice` rejection (voice is composed as `model/voice`; combos take no voice); old v2 keys still read.
8. **Upgrade note** — v3.0.0 reads old keys and rewrites config through the wizard; run `hermes 9router setup` after upgrading.
9. **Development** — `python -m pytest tests -q` (needs `pytest` + `httpx`); opt-in live checks: `NINEROUTER_LIVE=1 NINEROUTER_BASE_URL=... python -m pytest tests/test_live_smoke.py`.

- [ ] **Step 2: Sanity-check all referenced commands/paths exist**

Run: `grep -n "hermes 9router setup\|hermes plugins install\|/v1/models/" README.md`
Expected: every command/path in the README is one that exists in this repo or the Hermes CLI (`hermes 9router setup` registered in Task 10; endpoints in `catalog.py`).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for v3 install → wizard → verify flow"
```

---

### Task 13: End-to-end verification

**Files:**
- Create: `tests/test_live_smoke.py`

- [ ] **Step 1: Add the opt-in live check** `tests/test_live_smoke.py`:

```python
import os

import pytest

from ninerouter_omni import catalog

pytestmark = pytest.mark.skipif(
    not os.getenv("NINEROUTER_LIVE"),
    reason="set NINEROUTER_LIVE=1 (and NINEROUTER_BASE_URL) to probe a live gateway",
)


def test_live_catalogs():
    for capability in ("web", "tts", "stt", "image"):
        entries = catalog.fetch_catalog(capability)
        assert entries, capability
        assert entries[0].is_combo, capability


def test_live_auth_probe():
    probe = catalog.probe_auth(
        os.environ["NINEROUTER_BASE_URL"], os.getenv("NINEROUTER_API_KEY", ""))
    assert probe.ok, probe.detail
```

- [ ] **Step 2: Full suite + compile gate**

Run: `python -m pytest tests -q && python -m py_compile _http.py settings.py catalog.py tts.py stt.py image_gen.py web.py setup_cmd.py __init__.py`
Expected: all green (the two live tests skipped), no output from py_compile.

- [ ] **Step 3: Live read-only gateway check**

Run: `NINEROUTER_LIVE=1 NINEROUTER_BASE_URL=http://localhost:20128 python -m pytest tests/test_live_smoke.py -v`
Expected: `2 passed` — four catalogs fetch with the combo first, auth probe returns 400 → ok.

- [ ] **Step 4: Owner walkthrough (human step — hand off, do not automate)**

1. Reinstall the plugin into real Hermes (`hermes plugins install <repo path or git URL>`), accept the env prompts.
2. Run `hermes 9router setup`, walk the checklist + two-step picks, confirm the summary.
3. `hermes gateway restart`.
4. Verify: `hermes tools` shows the 9router rows; run one live web search and one TTS call.
5. Re-run the wizard and uncheck one capability → confirm only 9router's own keys changed (`git diff` the config or read it).

- [ ] **Step 5: Commit**

```bash
git add tests/test_live_smoke.py
git commit -m "test(live): opt-in live gateway smoke checks"
```

---

## Post-Plan Notes

- **Push:** owner decision — nothing is pushed automatically.
- **Design doc:** flip its status line to `Approved 2026-10-17 — implementation plan: docs/superpowers/plans/2026-10-17-9router-omni-v3-setup-wizard.md` when execution starts.
- **Interfaces locked:** `settings.resolve_*`, `catalog.CatalogEntry/fetch_catalog/split_web/group_by_provider/probe_auth`, `setup_cmd.plan_writes/current_picks/default_selection/build_scripted_plan/register_subcommand/handle_setup`, provider class names — later tasks depend on these names exactly.

