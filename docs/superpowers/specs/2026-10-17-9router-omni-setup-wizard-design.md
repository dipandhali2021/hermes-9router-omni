# 9router-omni v3 — install-time setup wizard, live catalogs, native TTS/STT

**Date:** 2026-10-17
**Status:** Draft for review
**Author:** brainstorming session — dipandhali2021 (owner) + agent
**Repo:** `hermes-9router-omni` (Hermes Agent plugin, `kind: backend`)

---

## 1. Intent and why

`hermes-9router-omni` routes Hermes' **web search, web extract, image generation,
TTS, and STT** through one 9router gateway. Today:

- Models are hardcoded per capability (`openclaw-search`, `openclaw-fetch`,
  `gemini/gemini-3-pro-image-preview`, `gpt-4o-mini-tts`, `openai/whisper-1`).
- The plugin reads config keys that Hermes' own pickers don't write
  (e.g. plugin reads `image_gen.9router.model`, the `hermes tools` picker
  writes `image_gen.model`) — picked models can be silently ignored.
- TTS and STT are wired via monkey-patches; Hermes v0.17 now ships native
  `ctx.register_tts_provider()` / `ctx.register_transcription_provider()` hooks.

**The change:** installing the plugin + running a small setup wizard should be
enough to fully configure all five capabilities against the user's own gateway —
base URL, API key, and a model per capability picked from the gateway's **live
catalog**, with the gateway's own combos as defaults. No hand-editing of
`config.yaml`.

**Audience:** public-quality. Others may install it: README rewrite, tests,
back-compat config reads, version bump.

---

## 2. Goals

1. `hermes plugins install dipandhali2021/hermes-9router-omni` prompts for the
   gateway URL + API key (skipped when already set) and points at the wizard.
2. A re-runnable wizard command (`hermes 9router setup`) lets the user pick,
   per capability, a model from the **live gateway catalog**, then writes
   config and enables only the capabilities they chose.
3. Catalog fetch separates model kinds correctly (search/fetch/tts/stt/image —
   never mixes in LLM/video/embedding noise).
4. New code defaults = gateway combos (`tts-combo`, `stt-combo`, `image-combo`;
   web keeps `openclaw-search` / `openclaw-fetch`) — 9router-side fallback.
5. TTS/STT migrate to native Hermes provider hooks; monkey-patches removed.
6. Config is written under the keys Hermes' dispatchers/pickers actually read,
   with old keys still accepted on read.

## 3. Non-goals / anti-goals

- **No new capabilities.** Video gen, embeddings, vision are not routed. The
  wizard never touches the full `/v1/models` LLM list (1747 entries, ~31s).
- **No `hermes tools` picker integration** — the user chose the dedicated
  wizard only. (Image/web providers will still appear there incidentally;
  nothing extra is built for it.)
- **No auto-rewrite of unrelated config.** Only the keys below are written.
- **Anti-goal:** silently writing config while the gateway is unreachable.
  The wizard must fail loudly with fix instructions instead.
- **Anti-goal:** dumping per-modality config choices the user didn't pick
  (e.g. enabling TTS because the wizard ran).

## 4. User decisions (from the 20-question Q&A)

| # | Decision |
|---|----------|
| 1 | Gateway: **no assumed default URL** — wizard always asks for base URL + API key |
| 2 | Catalogs: **fetch live from the gateway**, separated by modality |
| 3 | TTS / STT / image defaults: **gateway combos** (`tts-combo`, `stt-combo`, `image-combo`) |
| 4 | Web search & fetch models: **also configurable, fetched separately** |
| 5 | Chosen models live in **config.yaml**; code constants only as fallback |
| 6 | Prompts during **`hermes plugins install`** (env vars) + follow-up wizard (models) |
| 7 | Env prompts: **only if missing** (skip when already set) |
| 8 | On save: **enable only the picked capabilities** |
| 9 | Wizard exposed as a **dedicated CLI command** (re-runnable) |
| 10 | Model picker UX: **provider-first two-step** (pick provider, then model) |
| 11 | TTS step asks **model + voice** (not speed/format) |
| 12 | Post-save **smoke test**: connect + list models |
| 13 | Architecture: **migrate TTS/STT to native hooks** (no monkey-patch fallback) |
| 14 | Config keys: **follow Hermes conventions** on write; old keys read as fallback |
| 15 | Audience: **public-quality** |
| 16 | **pytest suite** required |

---

## 5. Verified facts (as of 2026-10-17)

### 5.1 Hermes (local install, v0.17.0 "2026.6.19")

- Native hooks exist on `ctx`: `register_tts_provider`,
  `register_transcription_provider`, `register_image_gen_provider`,
  `register_web_search_provider`. Plugin-registered names are rejected if they
  collide with built-ins — `9router` is free.
- `TTSProvider.synthesize(text, output_path, *, voice, model, speed, format, **extra) -> str`
  (writes the audio file, returns path; raise on failure).
  Dispatcher passes `tts.model`, `tts.voice`, `tts.speed`, `tts.output_format`
  from config.
- `TranscriptionProvider.transcribe(file_path, *, model, language, **extra) -> dict`
  (returns `{success, transcript, provider[, error]}`; must not raise).
  Dispatcher reads `stt.<provider>.model` / `stt.<provider>.language` and
  forwards them; top-level `model` argument overrides config.
- Image provider: existing `ImageGenProvider`; the `hermes tools` picker calls
  `list_models()` / `default_model()` and writes the pick to **`image_gen.model`**.
- Plugin CLI commands: `ctx.register_cli_command(name, help, setup_fn, handler_fn)`
  → surfaces as `hermes <name> ...` (wired into the main parser from
  `get_plugin_manager()._cli_commands`).
- Install-time surfaces (`hermes plugins install`): rich `requires_env` prompts
  (`name` / `description` / `url` / `secret` — skipped when already set via
  `get_env_value`), then `after-install.md` shown as a panel, then "enable now?".
  There is **no** install-time hook for interactive model picking — hence the
  wizard command.
- Config helpers: `hermes_cli.config.load_config()`, `save_config(cfg)`,
  `get_env_value(key)`, `save_env_value(key, value)`.
- `tools.web_tools._is_backend_available()` **still hardcodes** the built-in
  web providers (exa, parallel, firecrawl, tavily, searxng, brave-free, ddgs,
  xai) in v0.17 → the plugin's web-gating patch is still required.

### 5.2 9router gateway (verified live on `http://localhost:20128`)

| Endpoint | Result | Notes |
|---|---|---|
| `GET /v1/models/image` | 200, 174 models, ~1 s | `image-combo` first (`kind:"image"`, `owned_by:"combo"`) |
| `GET /v1/models/tts` | 200, 14 models, fast | `tts-combo` first; `openai/tts-1`, `openai/gpt-4o-mini-tts`, `gemini/*-tts-preview`, `openrouter/fish-audio/s2.1-pro-free:free`, … |
| `GET /v1/models/stt` | 200, 18 models, fast | `stt-combo` first; `groq/whisper-large-v3-turbo`, `dg/nova-3`, `openai/gpt-4o-transcribe`, `el/scribe_v2`, … |
| `GET /v1/models/web` | 200, 13 models, **fast (0.03 s)** | `kind:"webSearch"` (7): `openclaw-search` (combo), `tavily/search`, `exa/search`, `serper/search`, `linkup/search`, `youcom/search`, `tinyfish/search`; `kind:"webFetch"` (6): `openclaw-fetch` (combo), `tavily/fetch`, `exa/fetch`, `firecrawl/fetch`, `ollama/fetch`, `tinyfish/fetch` |
| `GET /v1/models` (full) | 200, **1747 models, ~31 s** | Never used by the plugin |
| `GET /v1/models/search` / `/fetch` | **do not exist** | fall through to generic model-retrieve → 404 `model_not_found` after ~30 s |
| `GET /v1/audio/voices` | requires `?provider=elevenlabs\|deepgram\|inworld\|edge-tts\|local-device` + auth | **No OpenAI-style voices listing** |

Canonical discovery per 9router's own shipped skills
(`skills/9router-web-search`, `skills/9router-web-fetch` in the 9router repo):
search IDs end in `/search`, fetch IDs in `/fetch`; combos (`owned_by:"combo"`)
chain providers with auto-fallback; discover via `/v1/models/web` + `kind` filter.

Model list entries carry `owned_by` (provider prefix) and `kind` on combos and
web entries; per-modality endpoints are already partitioned by capability.

---

## 6. Design

### 6.1 User flow (install → fully configured)

1. `hermes plugins install dipandhali2021/hermes-9router-omni`
   - Rich env prompts (only if missing): `NINEROUTER_BASE_URL`
     ("9router gateway base URL, e.g. http://127.0.0.1:20128"),
     `NINEROUTER_API_KEY` (secret, masked).
   - `after-install.md` panel: "Next: run `hermes 9router setup` to pick models
     from your gateway's live catalog."
2. `hermes 9router setup` — the wizard (re-runnable any time):
   1. **Env check** — prompt for missing URL / key (masked), save to `.env`.
   2. **Connect check** — `GET {base}/v1/models/tts` with auth.
      On failure: clear error + re-prompt URL/key or abort (never proceed
      silently). Note: localhost model lists answer unauthenticated, so the
      check must actually validate the key path the plugin uses.
   3. **Capability multiselect** — web search, web fetch, TTS, STT, image.
      First run: all five on. Re-run: mirror current config state.
   4. **Per capability** (in order: web search, web fetch, TTS, STT, image):
      fetch that capability's live catalog → **provider-first two-step pick**
      (step 1: pick `owned_by` group, combos pinned first; step 2: pick the
      model; current value pre-selected and marked "currently in use").
   5. **TTS extra:** voice prompt (free-text with common suggestions:
      alloy/echo/fable/onyx/nova/shimmer + any voices found for the TTS
      provider if the voices endpoint works). Empty = don't touch `tts.voice`.
   6. **Write config** (see 6.2) + enable only picked capabilities.
   7. **Smoke test:** re-fetch each selected capability's list endpoint and
      print a ✓ summary table. Non-zero exit if any fails.
   8. Print "restart the gateway: `hermes gateway restart`".
3. Flags for scripted installs: `--yes` (accept current config + defaults,
   no prompts) and per-capability model flags
   (`--tts-model`, `--stt-model`, `--image-model`, `--search-model`,
   `--fetch-model`, `--voice`). Non-TTY without `--yes` → refuse with a clear
   message.

### 6.2 Canonical config keys (write) and read order

| Capability | Wizard writes | Provider reads (first hit wins) |
|---|---|---|
| Web search | `web.backend: "9router"`, `web.9router.search_model` | `web.9router.search_model` → code default `openclaw-search` |
| Web fetch | `web.9router.fetch_model` | `web.9router.fetch_model` → code default `openclaw-fetch` |
| TTS | `tts.provider: "9router"`, `tts.model`, (`tts.voice` if given) | dispatcher-passed `model` → `tts.model` → `tts.9router.model` → code default `tts-combo` |
| STT | `stt.provider: "9router"`, `stt.enabled: true`, `stt.9router.model` | dispatcher-passed `model` → `stt.9router.model` → code default `stt-combo` |
| Image | `image_gen.provider: "9router"`, `image_gen.model` | `image_gen.model` → `image_gen.9router.model` → code default `image-combo` |

Old keys (`tts.9router.model`, `image_gen.9router.model`) remain readable so
existing installs keep working after update. Nothing is deleted or rewritten
outside this table.

### 6.3 Provider implementations

- **`tts.py` → `NineRouterTTSProvider(TTSProvider)`**
  - `synthesize()`: `POST /v1/audio/speech {model, input, voice?}`; write bytes,
    fix extension from `Content-Type` (keep existing logic); `voice_compatible = False`.
  - `list_models()`: live `/v1/models/tts` (cached in-process for the call),
    fallback shortlist; `default_model()` → `tts-combo`.
  - `get_setup_schema()`: name "9router", badge "self-hosted", env vars.
- **`stt.py` → `NineRouterTranscriptionProvider(TranscriptionProvider)`**
  - `transcribe()`: multipart to `/v1/audio/transcriptions` (keep MIME overrides,
    optional `language`/`prompt`/`response_format`/`temperature` from
    `stt.9router.*`); return the standard envelope, never raise.
  - `list_models()` live `/v1/models/stt`; `default_model()` → `stt-combo`.
- **`image_gen.py`**: `default_model()` → `image-combo`; `generate()` reads
  `image_gen.model` first, then the old key; `list_models()` returns combos +
  configured + a short curated set (do **not** dump 174 models into
  `hermes tools`).
- **`web.py`**: model names from config (6.2); keep providers as-is otherwise.
- **`__init__.py`**: register the four providers; **remove**
  `install_tts_patch()` / `install_stt_patch()`; **keep**
  `_patch_web_tools_gating()` (still required in v0.17, see 5.1).
- **`catalog.py` (new)**: gateway catalog client — `get_json` via `_http.py`,
  per-capability fetch + `kind` filtering for web, provider grouping,
  combo detection, generous timeouts (~15 s), no reliance on the 31 s full list.

### 6.4 Files

```
__init__.py      # register() — native providers + web gating patch only
catalog.py       # NEW — live gateway catalog fetch/group/filter
setup_cmd.py     # NEW — `hermes 9router setup` wizard (+ pure logic for tests)
tts.py           # rewritten — NineRouterTTSProvider
stt.py           # rewritten — NineRouterTranscriptionProvider
image_gen.py     # updated keys + defaults
web.py           # updated model reads
_http.py         # + get_json helper
plugin.yaml      # v3.0.0, rich requires_env entries
after-install.md # NEW — post-install panel → run the wizard
README.md        # rewritten: install → wizard → verify; min Hermes v0.17
tests/           # NEW — pytest suite (fixtures from the real gateway)
```

### 6.5 Edge cases & failure behavior

- Gateway unreachable at wizard start → abort with fix instructions (no config
  writes).
- Catalog fetch fails mid-wizard → offer retry/skip; skipped capability is left
  untouched (never re-enabled implicitly).
- Runtime model missing from gateway → provider returns the standard error
  envelope (TTS raises; dispatcher converts) — no silent fallback to another
  model.
- Hermes < v0.17 (no native hooks) → providers can't register; plugin logs a
  clear warning; web/image still work. README documents v0.17+ as minimum for
  TTS/STT.
- Upgrade from v2: old keys keep working (6.2); README gets an upgrade note.

### 6.6 Tests (pytest)

- `catalog`: fixture JSONs from the live gateway → modality separation for all
  five capabilities, web `kind` filtering, provider grouping, combo-first
  ordering.
- Config resolution: read-order fallbacks for all five capabilities (new +
  old keys) — pure functions, no Hermes import required.
- Wizard write logic: mocked `load_config`/`save_config` → exact keys written
  for each capability subset ("only picked capabilities"); `--yes` path.
- Defaults: combo constants resolve when config is empty.
- Stretch: mocked httpx for TTS synthesize (extension fix) and STT multipart
  field assembly.

### 6.7 Versioning & docs

- `plugin.yaml` version → **3.0.0** (breaking: min Hermes for TTS/STT,
  config normalization; old keys still read).
- README: install → env → wizard → verify → troubleshooting; endpoint table;
  min Hermes; upgrade note from v2.
- Keep `provides_web_providers` / `provides_image_gen_providers` manifest keys;
  add TTS/STT equivalents only if a consumer exists (checked: manifest parser
  ignores unknown keys; harmless either way).

---

## 7. Builder calls (decided here, changeable)

1. **Wizard command name:** `hermes 9router setup` (registered as CLI command
   name `9router`, subcommand `setup`).
2. **Web code defaults** stay `openclaw-search` / `openclaw-fetch` — verified
   to exist as combos on this gateway (public users get their own list via the
   wizard; a fresh 9router may name combos differently).
3. **Voice input is free-text + suggestions** — the gateway's voices endpoint
   covers only 4 named providers and no OpenAI; no reliable enumeration.
4. **No catalog caching in v3** — wizard is interactive and rare; fetch live.
5. **`--yes` + model flags** for scripted installs; non-TTY without `--yes`
   refuses.
6. **Tests runnable with plain `pytest` + `httpx`** (no packaging changes);
   fixtures are small hand-trimmed snapshots of the live lists.
7. TTS `output_format`/`speed` remain optional manual config passthroughs —
   not prompted (user chose model + voice only).

## 8. Open items (need the owner)

*(Filled in after the builder review — anything only the owner can answer.)*
