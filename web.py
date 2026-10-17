"""9router web search + extract provider for Hermes.

Implements :class:`agent.web_search_provider.WebSearchProvider`. Routes
``web_search`` to ``POST /v1/search`` and ``web_extract`` to ``POST /v1/web/fetch``
on the configured 9router gateway. Activate via ``web.backend: "9router"`` (or
``web.search_backend`` / ``web.extract_backend``) in ``~/.hermes/config.yaml``.

Model names come from config (``web.9router.search_model`` /
``web.9router.fetch_model``), falling back to the gateway combo defaults.

Env vars:
    NINEROUTER_BASE_URL    Base URL of the 9router gateway, e.g.
                           ``http://127.0.0.1:20128`` for a local install.
                           Required.
    NINEROUTER_API_KEY     Bearer token. Optional — leave unset (or empty)
                           for keyless gateways.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from agent.web_search_provider import WebSearchProvider

from ._http import is_configured, post_json
from .settings import load_hermes_config, resolve_fetch_model, resolve_search_model

logger = logging.getLogger(__name__)


def _normalize_search(data: Dict[str, Any]) -> Dict[str, Any]:
    raw = data.get("results")
    if not isinstance(raw, list):
        nested = data.get("data") if isinstance(data, dict) else None
        if isinstance(nested, dict) and isinstance(nested.get("results"), list):
            raw = nested["results"]
        else:
            raw = []
    web = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        web.append(
            {
                "title": str(item.get("title", "")),
                "url": str(item.get("url") or item.get("link") or ""),
                "description": str(
                    item.get("snippet")
                    or item.get("description")
                    or item.get("content")
                    or ""
                ),
                "position": i + 1,
            }
        )
    return {"success": True, "data": {"web": web}}


def _extract_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    if not isinstance(data, dict):
        return ""
    content = data.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    if isinstance(content, str):
        return content
    nested = data.get("data")
    if isinstance(nested, dict):
        text = _extract_text(nested)
        if text:
            return text
    for key in ("markdown", "text", "result", "_raw"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


class NineRouterWebSearchProvider(WebSearchProvider):
    """9router-backed search + extract provider."""

    @property
    def name(self) -> str:
        return "9router"

    @property
    def display_name(self) -> str:
        return "9router"

    def is_available(self) -> bool:
        return is_configured()

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def supports_crawl(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return {"success": False, "error": "Interrupted"}

            count = max(1, min(int(limit or 5), 20))
            logger.info("9router search: '%s' (limit=%d)", query, count)
            raw = post_json(
                "/v1/search",
                {
                    "model": resolve_search_model(load_hermes_config()),
                    "query": query,
                    "search_type": "web",
                    "max_results": count,
                },
            )
            return _normalize_search(raw if isinstance(raw, dict) else {})
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        except Exception as exc:
            logger.warning("9router search error: %s", exc)
            return {"success": False, "error": f"9router search failed: {exc}"}

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return [
                    {"url": u, "title": "", "content": "", "error": "Interrupted"}
                    for u in urls
                ]

            extract_mode = "text" if kwargs.get("format") == "text" else "markdown"
            max_chars = kwargs.get("max_chars")
            if not isinstance(max_chars, int) or max_chars <= 0:
                max_chars = 50000

            results: List[Dict[str, Any]] = []
            for url in urls:
                try:
                    logger.info("9router fetch: %s", url)
                    raw = post_json(
                        "/v1/web/fetch",
                        {
                            "model": resolve_fetch_model(load_hermes_config()),
                            "url": url,
                            "extract_mode": extract_mode,
                            "max_chars": max_chars,
                        },
                    )
                    text = _extract_text(raw)
                    final_url = url
                    title = ""
                    if isinstance(raw, dict):
                        final_url = str(raw.get("finalUrl") or raw.get("url") or url)
                        title = str(raw.get("title", ""))
                    results.append(
                        {
                            "url": final_url,
                            "title": title,
                            "content": text,
                            "raw_content": text,
                            "metadata": {"sourceURL": final_url, "title": title},
                        }
                    )
                except Exception as exc:
                    logger.warning("9router fetch %s error: %s", url, exc)
                    results.append(
                        {
                            "url": url,
                            "title": "",
                            "content": "",
                            "raw_content": "",
                            "error": f"9router fetch failed: {exc}",
                            "metadata": {"sourceURL": url},
                        }
                    )
            return results
        except ValueError as exc:
            return [
                {"url": u, "title": "", "content": "", "error": str(exc)} for u in urls
            ]

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "9router",
            "badge": "self-hosted",
            "tag": "Self-hosted 9router gateway — proxies /v1/search and /v1/web/fetch.",
            "env_vars": [
                {
                    "key": "NINEROUTER_BASE_URL",
                    "prompt": "9router gateway base URL (e.g. http://127.0.0.1:20128)",
                    "url": "",
                },
                {
                    "key": "NINEROUTER_API_KEY",
                    "prompt": "9router API key (optional — leave empty for keyless gateways)",
                    "url": "",
                },
            ],
        }
