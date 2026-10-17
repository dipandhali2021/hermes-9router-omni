"""Shared HTTP helpers + base-URL / API-key resolution for 9router-omni.

All four capability modules (web, image_gen, tts, stt) import from here.

Env vars:
    NINEROUTER_BASE_URL    Base URL of the 9router gateway, e.g.
                           ``http://127.0.0.1:20128`` for a local install.
                           Required.
    NINEROUTER_API_KEY     Bearer token for the gateway. Optional — leave
                           unset (or empty) for keyless gateways; requests
                           then omit the Authorization header.
"""

from __future__ import annotations

import logging
import os
from typing import Any, BinaryIO, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 60


def base_url() -> str:
    raw = os.getenv("NINEROUTER_BASE_URL", "").strip()
    if not raw:
        raise ValueError(
            "NINEROUTER_BASE_URL environment variable not set. "
            "Set it to your 9router gateway URL (e.g. http://127.0.0.1:20128)."
        )
    return raw.rstrip("/")


def api_key() -> str:
    """Bearer token, or ``""`` for keyless gateways. Never raises."""
    return os.getenv("NINEROUTER_API_KEY", "").strip()


def is_configured() -> bool:
    """True when a base URL is set; the API key is optional."""
    return bool(os.getenv("NINEROUTER_BASE_URL", "").strip())


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
        raise RuntimeError(
            f"9router {path} failed: {response.status_code} "
            f"{getattr(response, 'reason_phrase', '')} :: {preview}"
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
