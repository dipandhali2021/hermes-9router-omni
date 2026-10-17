"""9router gateway catalog client: live per-modality model lists + auth probe.

No Hermes imports — safe to use from tests, pickers, and the setup wizard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ._http import get_json
from .settings import DEFAULT_TTS_MODEL

CAPABILITY_PATHS: Dict[str, str] = {
    "web": "/v1/models/web",
    "tts": "/v1/models/tts",
    "stt": "/v1/models/stt",
    "image": "/v1/models/image",
}

CATALOG_TIMEOUT_S = 15


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    owned_by: str = ""
    kind: str = ""

    @property
    def is_combo(self) -> bool:
        return self.owned_by == "combo"


@dataclass(frozen=True)
class AuthProbe:
    status: int
    ok: bool
    detail: str


def parse_catalog(payload: Any) -> List[CatalogEntry]:
    """Turn a ``/v1/models/<capability>`` payload into ordered entries.

    Tolerates junk: non-dict payloads, non-list ``data``, non-dict rows, and
    rows without a non-empty string ``id`` are dropped.
    """
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    entries: List[CatalogEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or "").strip()
        if not model_id:
            continue
        entries.append(
            CatalogEntry(
                id=model_id,
                owned_by=str(row.get("owned_by") or "").strip(),
                kind=str(row.get("kind") or "").strip(),
            )
        )
    return entries


def fetch_catalog(capability: str) -> List[CatalogEntry]:
    """GET ``/v1/models/<capability>`` and parse it. Raises KeyError if the
    capability is unknown."""
    path = CAPABILITY_PATHS[capability]
    return parse_catalog(get_json(path, timeout=CATALOG_TIMEOUT_S))


def _is_web_kind(entry: CatalogEntry, kind: str, suffixes: Tuple[str, ...]) -> bool:
    if entry.kind:
        return entry.kind == kind
    return entry.id.endswith(suffixes)


def split_web(
    entries: List[CatalogEntry],
) -> Tuple[List[CatalogEntry], List[CatalogEntry]]:
    """Split the combined web catalog into (search, fetch).

    Primary rule is the ``kind`` field; when it is empty (older gateways)
    fall back to the id suffix (``/search``, ``-search``, …). Entries
    matching neither stay out of both lists.
    """
    search: List[CatalogEntry] = []
    fetch: List[CatalogEntry] = []
    for entry in entries:
        if _is_web_kind(entry, "webSearch", ("/search", "-search")):
            search.append(entry)
        elif _is_web_kind(entry, "webFetch", ("/fetch", "-fetch")):
            fetch.append(entry)
    return search, fetch


def group_by_provider(entries: List[CatalogEntry]) -> Dict[str, List[CatalogEntry]]:
    """Group entries by provider, combos first, then groups sorted by name."""
    groups: Dict[str, List[CatalogEntry]] = {}
    for entry in entries:
        if entry.is_combo:
            key = "combo"
        else:
            key = entry.owned_by or entry.id.split("/", 1)[0] or "other"
        groups.setdefault(key, []).append(entry)

    ordered: Dict[str, List[CatalogEntry]] = {}
    if "combo" in groups:
        ordered["combo"] = groups.pop("combo")
    for key in sorted(groups):
        ordered[key] = groups[key]
    return ordered


def classify_auth_probe(status_code: int) -> str:
    """Map the probe's HTTP status to ``ok`` / ``auth_failed`` / ``unexpected``.

    The probe deliberately omits the ``input`` field, so a gateway that
    accepts our credentials answers 400 (validation) rather than 2xx.
    """
    if status_code == 400:
        return "ok"
    if status_code in (401, 403):
        return "auth_failed"
    return "unexpected"


def probe_auth(base_url: str, api_key: str, *, timeout: int = 10) -> AuthProbe:
    """Probe gateway reachability + auth without depending on a real TTS call."""
    import httpx

    url = f"{base_url.rstrip('/')}/v1/audio/speech"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    try:
        response = httpx.post(
            url,
            json={"model": DEFAULT_TTS_MODEL},
            headers=headers,
            timeout=timeout,
        )
    except Exception as ex:  # httpx transport errors + anything TLS-ish
        return AuthProbe(status=0, ok=False, detail=f"unreachable: {ex}")

    status = response.status_code
    verdict = classify_auth_probe(status)
    if verdict == "ok":
        detail = (
            "gateway reachable, credentials accepted "
            f"(HTTP {status} on a request missing 'input' by design)"
        )
    elif verdict == "auth_failed":
        detail = f"API key rejected (HTTP {status})"
    else:
        preview = (getattr(response, "text", "") or "")[:200]
        detail = f"unexpected HTTP {status}: {preview}"
    return AuthProbe(status=status, ok=verdict == "ok", detail=detail)
