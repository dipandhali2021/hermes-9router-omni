# hermes-9router-omni

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that
routes Hermes' built-in **web search**, **web extract**, **image generation**,
**TTS**, and **STT** tool calls through a single
[9router](https://9router.com) gateway. One install, one set of credentials,
all five capabilities wired up.

| Capability    | Hermes hook                                | 9router endpoint                                     |
|---------------|--------------------------------------------|------------------------------------------------------|
| `web_search`  | `ctx.register_web_search_provider`         | `POST /v1/search`                                    |
| `web_extract` | `ctx.register_web_search_provider`         | `POST /v1/web/fetch` (one call per URL)              |
| `image_generate` | `ctx.register_image_gen_provider`       | `POST /v1/images/generations`                        |
| TTS           | monkey-patch `tools.tts_tool.text_to_speech_tool`        | `POST /v1/audio/speech`              |
| STT           | monkey-patch `tools.transcription_tools.transcribe_audio` | `POST /v1/audio/transcriptions` (multipart)  |

## Install

```bash
hermes plugins install dipandhali2021/hermes-9router-omni
hermes plugins enable 9router-omni
```

Or clone manually:

```bash
git clone https://github.com/dipandhali2021/hermes-9router-omni \
  ~/.hermes/plugins/9router-omni
```

## Configure

Two env vars are **required**. Add to `~/.hermes/.env` (Hermes auto-loads it on
every startup):

```ini
NINEROUTER_BASE_URL=http://127.0.0.1:20128
NINEROUTER_API_KEY=sk-your-9router-bearer-token
```

Then flip 9router on as the backend for each capability you want it to serve.
Edit `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - 9router-omni

# Web search + extract
web:
  backend: "9router"          # or set search_backend / extract_backend separately

# Image generation
image_gen:
  provider: "9router"
  9router:
    model: "gemini/gemini-3-pro-image-preview"   # optional; default shown
    # quality: "high"                            # optional pass-through

# TTS
tts:
  provider: "9router"
  9router:
    model: "gpt-4o-mini-tts"                     # optional; default shown

# STT
stt:
  enabled: true
  provider: "9router"
  9router:
    model: "openai/whisper-1"                    # optional; default shown
    # language: "en"                             # optional ISO-639-1
    # prompt: "Domain hint here"                 # optional transcription hint
    # temperature: 0                             # optional 0..1
```

Cherry-pick whichever sections you want — you don't have to flip all four. Any
capability whose `provider` / `backend` you leave unchanged keeps using its
existing Hermes default.

Verify:

```bash
hermes plugins list | grep 9router-omni        # → enabled (user)
hermes                                          # then ask the agent to:
#   "search the web for ..."
#   "generate an image of a sunset"
#   /tts hello
# or feed a voice clip via Telegram / Discord
```

## Why a monkey-patch for TTS and STT?

Hermes has a clean plugin API for web search backends (`WebSearchProvider`)
and image generation backends (`ImageGenProvider`), but **not yet** for TTS
or STT — those dispatchers are hardcoded if/elif chains over a built-in
provider list. To add a third-party provider without modifying Hermes core,
this plugin's `register()` wraps `text_to_speech_tool` and `transcribe_audio`
with a short-circuit that runs our httpx client when the user has selected
`9router`, falling through to the original dispatcher for every other
provider. The patches are idempotent and only fire when configured.

Web tools have a separate gating problem: `check_web_api_key` /
`_is_backend_available` hardcode a seven-name allowlist, so any third-party
`WebSearchProvider` is correctly discovered but invisible to the model.
The plugin patches both functions (and the captured `ToolEntry.check_fn`
references in the registry) so any registered provider that reports
`is_available() == True` counts.

If/when Hermes upstream adds `register_tts_provider` and
`register_transcription_provider`, those patches can be replaced with proper
provider classes.

## Layout

```
9router-omni/
├── plugin.yaml      # Hermes manifest (kind: backend)
├── __init__.py      # register() — wires providers + installs patches
├── _http.py         # shared httpx helpers (JSON, binary-response, multipart)
├── web.py           # NineRouterWebSearchProvider
├── image_gen.py     # NineRouterImageGenProvider
├── tts.py           # _generate_9router_tts + install_tts_patch
├── stt.py           # _transcribe_9router + install_stt_patch
├── LICENSE
└── README.md
```

## Troubleshooting

- **Tool not visible to the model.** Confirm `hermes plugins list` shows
  `9router-omni` as `enabled` and that both env vars are set in
  `~/.hermes/.env`. Web search/extract has a known gating quirk handled by
  the plugin's monkey-patch — make sure the plugin registered successfully
  (look for `Plugin '9router-omni' registered web provider: 9router` in
  `~/.hermes/logs/agent.log`).
- **`401 Unauthorized` from the gateway.** Your `NINEROUTER_API_KEY` is
  stale or wrong. Check the 9router admin UI.
- **Image saves with wrong extension.** The gateway returned a `Content-Type`
  other than what we expected. For image, response is always saved as
  `.png` via Hermes' `save_b64_image`; for TTS, the extension is adjusted
  from the `Content-Type` header.
- **STT returns empty transcript.** Check the gateway logs — most 9router
  STT providers handle short / silent audio gracefully, but some return
  `{"text": ""}` rather than an error.

## License

MIT — see [LICENSE](LICENSE).
