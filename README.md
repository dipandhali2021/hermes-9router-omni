# hermes-web-9router

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that
routes `web_search` and `web_extract` tool calls through a
[9router](https://9router.ai) gateway instead of the bundled
Firecrawl / Tavily / Exa / etc. backends.

Implements `agent.web_search_provider.WebSearchProvider`:

| Tool          | Endpoint                       | Method |
|---------------|--------------------------------|--------|
| `web_search`  | `{BASE_URL}/v1/search`         | POST   |
| `web_extract` | `{BASE_URL}/v1/web/fetch`      | POST   |

`web_extract` loops over the supplied URLs (Hermes calls with up to 5 per
invocation) and issues one fetch per URL, then returns the canonical Hermes
extract shape so downstream tooling treats it identically to the built-ins.

## Install

```bash
hermes plugins install dipandhali2021/hermes-web-9router
hermes plugins enable web-9router
```

Or clone manually:

```bash
git clone https://github.com/dipandhali2021/hermes-web-9router \
  ~/.hermes/plugins/web-9router
```

## Configure

Add to `~/.hermes/.env` (Hermes auto-loads this on every startup):

```ini
NINEROUTER_BASE_URL=http://127.0.0.1:20128
NINEROUTER_API_KEY=sk-your-9router-bearer-token
```

Both are **required** — the plugin will not start without them. Point
`NINEROUTER_BASE_URL` at a local 9router (`http://127.0.0.1:20128`) or a remote
gateway, whichever you run.

Then select `9router` as the web backend in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - web-9router

web:
  backend: "9router"          # shared selector for both search and extract
  # or set per-capability:
  # search_backend: "9router"
  # extract_backend: "9router"
```

Verify with:

```bash
hermes plugins list | grep web-9router        # → enabled (user)
hermes                                         # then ask: "search the web for ..."
```

## Why a monkey-patch?

Hermes' tool-registration layer (`tools/web_tools.py`) gates `web_search` /
`web_extract` visibility on a hardcoded allowlist of the seven built-in
backends — third-party `WebSearchProvider` subclasses are correctly
discovered but invisible to the model. On registration this plugin patches
`_is_backend_available` and `check_web_api_key` (and the captured `check_fn`
on the `ToolEntry` objects already in the registry) so any registered
provider that reports `is_available() == True` counts as available. The
patch is idempotent and only widens the allowlist; built-in backends remain
fully functional.

## Layout

```
web-9router/
├── plugin.yaml      # Hermes manifest (kind: backend)
├── __init__.py      # register() — wires the provider + gating patch
├── provider.py      # NineRouterWebSearchProvider
├── LICENSE
└── README.md
```

## Troubleshooting

- **Tools not visible to the model.** Confirm `hermes plugins list` shows
  `web-9router` as `enabled` and that both env vars are set. The gating patch
  needs to fire during plugin registration.
- **`401 Unauthorized` from the gateway.** Your `NINEROUTER_API_KEY` is stale
  or wrong. The 9router admin UI is the source of truth.
- **`9router /v1/web/fetch failed: ...` per URL.** The gateway is reachable
  but the target URL timed out or returned an error — extraction continues
  for the remaining URLs and per-URL failures appear with an `error` field
  in the response.
- **Hangs / 30s+ extracts.** Some pages are genuinely slow on the gateway
  side. The plugin uses a 60s per-request timeout; tune `REQUEST_TIMEOUT_S`
  in `provider.py` if needed.

## License

MIT — see [LICENSE](LICENSE).
