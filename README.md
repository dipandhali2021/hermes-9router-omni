# hermes-9router-omni

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that
routes Hermes' built-in **web search**, **web extract**, **image generation**,
**TTS**, and **STT** tool calls through a single
[9router](https://9router.com) gateway — one install, one set of credentials,
all five capabilities wired up.

| Capability       | Hermes hook                              | 9router endpoint                            |
|------------------|------------------------------------------|---------------------------------------------|
| `web_search`     | `ctx.register_web_search_provider`       | `POST /v1/search`                           |
| `web_extract`    | `ctx.register_web_search_provider`       | `POST /v1/web/fetch` (one call per URL)     |
| `image_generate` | `ctx.register_image_gen_provider`        | `POST /v1/images/generations`               |
| TTS              | `ctx.register_tts_provider`              | `POST /v1/audio/speech`                     |
| STT              | `ctx.register_transcription_provider`    | `POST /v1/audio/transcriptions` (multipart) |

## Requirements

- Hermes Agent **v0.17.0+** for the native TTS/STT provider hooks. On older
  versions the plugin still registers web search and image generation (with a
  warning in the log).
- A reachable 9router gateway. Keyless gateways are supported only when the
  gateway has `requireApiKey` disabled; remote `/v1` access always needs a key.

## Install

```bash
hermes plugins install dipandhali2021/hermes-9router-omni
hermes plugins enable 9router-omni
```

The install prompts for env vars (values already set are skipped):

- `NINEROUTER_BASE_URL` — required, e.g. `http://127.0.0.1:20128`
- `NINEROUTER_API_KEY` — optional; leave empty for keyless gateways

On first enable, the plugin automatically routes **all five capabilities** through
9router using the defaults below and records a one-time marker in Hermes' plugin
state. Later manual changes — including disabling a capability — are left alone.

Run the setup wizard when you want to choose different models or a voice:

```bash
hermes 9router setup
```

## Setup wizard

`hermes 9router setup` reads your gateway's live per-modality catalogs and:

1. verifies reachability + auth — the probe deliberately omits a required
   field, so **HTTP 400 = credentials accepted**, **401/403 = key rejected**;
   failures re-prompt up to 3 times and never write config;
2. asks which capabilities to route through 9router (first run: all on;
   re-run: mirrors current config);
3. two-step model pick per capability — provider group first (combos pinned),
   then model, with the current value marked "(currently in use)";
4. asks for a TTS voice for non-combo models (empty = leave `tts.voice` alone);
5. writes config and runs a smoke test for every enabled capability;
6. prints `restart the gateway: hermes gateway restart`.

Keys it writes:

| Capability  | Wizard writes                                                        | Provider reads (first hit wins)                                     |
|-------------|----------------------------------------------------------------------|---------------------------------------------------------------------|
| Web search  | `web.search_backend: "9router"`, `web.9router.search_model`          | `web.search_backend` → `web.backend` → `openclaw-search`            |
| Web fetch   | `web.extract_backend: "9router"`, `web.9router.fetch_model`          | `web.extract_backend` → `web.backend` → `openclaw-fetch`            |
| TTS         | `tts.provider: "9router"`, `tts.model`, (`tts.voice` if given)       | dispatcher model → `tts.model` → `tts.9router.model` → `openrouter/fish-audio/s2.1-pro-free:free` |
| STT         | `stt.provider: "9router"`, `stt.enabled: true`, `stt.9router.model`  | dispatcher model → `stt.9router.model` → `groq/whisper-large-v3-turbo` |
| Image       | `image_gen.provider: "9router"`, `image_gen.model`                   | `image_gen.model` → `image_gen.9router.model` → `ag/gemini-3.1-flash-image` |

**Re-running:** the wizard mirrors your current config. Unchecking a capability
**disables 9router for that capability only** — it never deletes another
provider's values and never deletes model keys (inert while disabled, reused
if you re-enable).

**Scripted installs:** `--yes` accepts the current config, fills the rest with
defaults, and enables all five capabilities. Per-capability flags
`--search-model`, `--fetch-model`, `--tts-model`, `--stt-model`,
`--image-model`, and `--voice` override the picks. Without a TTY and without
`--yes`, the wizard refuses to run.

## Verify

```bash
hermes tools        # the 9router rows should show as available
```

Then ask the agent, for example:

- "search the web for the 9router changelog" (web search)
- "generate an image of a sunset over a router rack" (image generation)
- `/tts hello` (TTS), or send a voice clip via Telegram/Discord (STT)

## Models

The plugin uses the gateway's live per-modality catalogs (the full
`/v1/models` list — ~1700 entries, ~30 s — is never used):

- `GET {base}/v1/models/web` — search + fetch, split by `kind`
- `GET {base}/v1/models/tts`
- `GET {base}/v1/models/stt`
- `GET {base}/v1/models/image`

Defaults used when nothing is configured (or a catalog is unreachable):

| Capability  | Default                                 |
|-------------|-----------------------------------------|
| Web search  | `openclaw-search` (combo)               |
| Web fetch   | `openclaw-fetch` (combo)                |
| TTS         | `openrouter/fish-audio/s2.1-pro-free:free` |
| STT         | `groq/whisper-large-v3-turbo`           |
| Image       | `ag/gemini-3.1-flash-image`             |

## Troubleshooting

- **Gateway unreachable.** Check `NINEROUTER_BASE_URL` and that 9router is
  running; `hermes 9router setup` re-prompts URL/key up to 3 times before
  aborting without writing config.
- **401/403 during setup.** `NINEROUTER_API_KEY` is wrong — or required and
  unset. A 400 on the auth probe is *success* (the probe intentionally omits
  the `input` field).
- **401 `API key required for remote API access` on STT / voice messages.**
  9router received no `Authorization` header. Set `NINEROUTER_API_KEY`, or
  configure 9router as a Hermes provider (`providers.9router.api_key`, or a
  `custom_providers` entry named `9router*`) — the plugin reuses that key
  automatically. An explicitly empty `NINEROUTER_API_KEY=` disables the
  fallback for keyless gateways.
- **`combo + voice` rejected.** Voice is composed into the model id
  (`openai/tts-1` + `nova` → `openai/tts-1/nova`); combo models take no voice
  suffix. The wizard skips the voice prompt for combos — clear `tts.voice` if
  you hand-edited a combo + voice config.
- **TTS/STT missing on older Hermes.** Native TTS/STT registration requires
  Hermes v0.17.0+; the plugin logs a warning and keeps web search + image
  generation active.
- **Old v2 keys.** `tts.9router.model` and `image_gen.9router.model` are still
  read, so existing installs keep working.

## Upgrading from v2

v3.0.0 replaces the TTS/STT monkey-patches with native providers, keeps reading
old model keys, and manages configuration through the wizard. Upgrading to
v3.1.0 force-enables all five capabilities once on the first load, using any
existing model choices. Run `hermes 9router setup` afterward if you want
different models or want to disable a capability.

## Development

```bash
python -m pytest tests -q           # needs pytest + httpx
```

Opt-in live checks against a real gateway:

```bash
NINEROUTER_LIVE=1 NINEROUTER_BASE_URL=http://127.0.0.1:20128 \
  python -m pytest tests/test_live_smoke.py
```

## Layout

```
9router-omni/
├── plugin.yaml      # Hermes manifest (kind: backend)
├── after-install.md # shown by the installer
├── __init__.py      # register() — native providers + CLI wiring
├── settings.py      # config resolution + pure helpers
├── _http.py         # shared httpx helpers (JSON, binary-response, multipart)
├── catalog.py       # live catalogs, provider grouping, auth probe
├── web.py           # NineRouterWebSearchProvider
├── image_gen.py     # NineRouterImageGenProvider
├── tts.py           # NineRouterTTSProvider
├── stt.py           # NineRouterTranscriptionProvider
├── setup_cmd.py     # `hermes 9router setup` wizard
├── LICENSE
└── README.md
```

## License

MIT — see [LICENSE](LICENSE).
