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
