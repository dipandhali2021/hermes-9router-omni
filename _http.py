"""Shared HTTP helpers + base-URL / API-key resolution for 9router-omni.

All four capability modules (web, image_gen, tts, stt) import from here.

Env vars:
    NINEROUTER_BASE_URL    Base URL of the 9router gateway, e.g.
                           ``http://127.0.0.1:20128`` for a local install.
    NINEROUTER_API_KEY     Bearer token for the gateway. Optional for
                           keyless gateways; requests then omit the
                           Authorization header.

When either variable is unset, the gateway URL/key configured under
``providers.9router`` or a ``custom_providers`` entry named ``9router*`` in
``~/.hermes/config.yaml`` is used instead. 9router's ``/v1`` routes require a
key for remote access (and whenever ``settings.requireApiKey`` is on), so
this fallback prevents an otherwise-discovered gateway from returning 401.
An explicitly empty env value (``NINEROUTER_API_KEY=``) means keyless and is
never overridden by config.
"""

from __future__ import annotations

import logging
import os
from typing import Any, BinaryIO, Dict, Mapping, Optional, Tuple

from .settings import (
    load_hermes_config,
    resolve_gateway_credentials,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 60


def _env(name: str) -> Optional[str]:
    """Env value (stripped), or ``None`` when the variable is unset.

    An explicitly empty value stays empty — ``NINEROUTER_API_KEY=`` is the
    user asking for keyless mode, not a request to fall back to config.
    """
    if name not in os.environ:
        return None
    return os.environ[name].strip()


def _resolved_credentials() -> Tuple[str, str]:
    """Resolve gateway URL + key: env vars first, then Hermes config.

    Users usually configure 9router once as a model provider (including a
    valid key). Without this fallback the plugin reads only the process
    environment, sends no ``Authorization`` header, and 9router answers
    STT/TTS/web/image requests with 401.
    """
    env_base = _env("NINEROUTER_BASE_URL")
    env_key = _env("NINEROUTER_API_KEY")
    if env_base is not None and env_key is not None:
        return env_base, env_key

    try:
        cfg = load_hermes_config()
        cfg_base, cfg_key = resolve_gateway_credentials(cfg, base_url_hint=env_base)
    except Exception:  # noqa: BLE001 — config lookup must never break requests
        logger.debug("9router: could not read Hermes provider config", exc_info=True)
        cfg_base, cfg_key = None, ""

    base = env_base if env_base is not None else (cfg_base or "")
    key = env_key if env_key is not None else (cfg_key or "")
    return base, key


def base_url() -> str:
    raw = _resolved_credentials()[0]
    if not raw:
        raise ValueError(
            "NINEROUTER_BASE_URL environment variable not set. Set it to your "
            "9router gateway URL (e.g. http://127.0.0.1:20128), or configure "
            "9router as a Hermes provider."
        )
    raw = raw.rstrip("/")
    # Hermes provider configs usually include the OpenAI-compatible ``/v1``
    # suffix; the plugin's paths already start with it.
    if raw.lower().endswith("/v1"):
        raw = raw[:-3].rstrip("/")
    return raw


def api_key() -> str:
    """Bearer token, or ``""`` for keyless gateways. Never raises."""
    return _resolved_credentials()[1]


def is_configured() -> bool:
    """True when a gateway base URL is available; the API key is optional."""
    return bool(_resolved_credentials()[0])


def get_json(path: str, *, timeout: int = 15) -> Any:
    """GET ``{base}{path}`` and return parsed JSON.

    Sends the bearer header only when an API key is configured.
    """
    import httpx

    url = f"{base_url()}{path}"
    logger.info("9router GET %s", url)
    response = httpx.get(url, headers=_bearer_headers(), timeout=timeout)
    _raise_for_status(response, path)
    return response.json()


def _bearer_headers(extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    key = api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if extra:
        headers.update(extra)
    return headers


def _raise_for_status(response, path: str) -> None:
    if response.status_code >= 400:
        try:
            text = response.text
        except Exception:
            text = ""
        preview = (text or "")[:200].replace("\n", " ")
        hint = ""
        if response.status_code in (401, 403):
            hint = (
                " — 9router requires an API key for /v1 access. Set "
                "NINEROUTER_API_KEY, or configure 9router (with api_key) as a "
                "Hermes provider so the plugin can reuse it."
            )
        raise RuntimeError(
            f"9router {path} failed: {response.status_code} "
            f"{getattr(response, 'reason_phrase', '')} :: {preview}{hint}"
        )


def post_json(
    path: str,
    body: Dict[str, Any],
    *,
    timeout: int = REQUEST_TIMEOUT_S,
) -> Dict[str, Any]:
    """POST a JSON body, return parsed JSON (or ``{"_raw": text}`` on parse failure)."""
    import httpx

    url = f"{base_url()}{path}"
    headers = _bearer_headers({"Content-Type": "application/json"})
    logger.info("9router POST %s", url)
    response = httpx.post(url, json=body, headers=headers, timeout=timeout)
    _raise_for_status(response, path)
    try:
        return response.json()
    except ValueError:
        return {"_raw": response.text}


def post_json_bytes(
    path: str,
    body: Dict[str, Any],
    *,
    timeout: int = REQUEST_TIMEOUT_S,
    query: Optional[Mapping[str, str]] = None,
) -> Tuple[bytes, str]:
    """POST JSON, return raw response bytes + content-type. Used for TTS mp3 + image binary."""
    import httpx

    url = f"{base_url()}{path}"
    headers = _bearer_headers({"Content-Type": "application/json"})
    logger.info("9router POST %s (binary response)", url)
    response = httpx.post(
        url, json=body, headers=headers, params=dict(query) if query else None, timeout=timeout
    )
    _raise_for_status(response, path)
    return response.content, response.headers.get("content-type", "")


def post_form(
    path: str,
    *,
    data: Dict[str, Any],
    file_field: str,
    file_path: str,
    file_mime: str = "application/octet-stream",
    timeout: int = REQUEST_TIMEOUT_S,
) -> Dict[str, Any]:
    """POST multipart/form-data with a single file upload. Used for STT."""
    import os.path
    import httpx

    url = f"{base_url()}{path}"
    headers = _bearer_headers()  # do NOT set Content-Type; httpx sets multipart boundary
    logger.info("9router POST %s (multipart, file=%s)", url, file_path)
    with open(file_path, "rb") as fh:
        files = {file_field: (os.path.basename(file_path), fh, file_mime)}
        response = httpx.post(
            url, data=data, files=files, headers=headers, timeout=timeout
        )
    _raise_for_status(response, path)
    try:
        return response.json()
    except ValueError:
        return {"_raw": response.text}
