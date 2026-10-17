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
