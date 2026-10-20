import types

import pytest

from ninerouter_omni import _http


def _env(monkeypatch, base=None, key=None, cfg=None):
    monkeypatch.delenv("NINEROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
    if base is not None:
        monkeypatch.setenv("NINEROUTER_BASE_URL", base)
    if key is not None:
        monkeypatch.setenv("NINEROUTER_API_KEY", key)
    monkeypatch.setattr("ninerouter_omni._http.load_hermes_config", lambda: cfg or {})


def test_is_configured_keyless(monkeypatch):
    _env(monkeypatch, base="http://127.0.0.1:20128")
    assert _http.is_configured() is True


def test_is_configured_requires_base(monkeypatch):
    _env(monkeypatch, key="k")
    assert _http.is_configured() is False


def test_api_key_empty_is_legal(monkeypatch):
    _env(monkeypatch, base="http://x")
    assert _http.api_key() == ""


def test_get_json_parses_and_sends_bearer(monkeypatch):
    _env(monkeypatch, base="http://x", key="k")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(url=url, headers=headers, timeout=timeout)
        return types.SimpleNamespace(status_code=200, text="{}", reason_phrase="OK",
                                     json=lambda: {"object": "list", "data": []})

    monkeypatch.setattr("httpx.get", fake_get)
    assert _http.get_json("/v1/models/tts") == {"object": "list", "data": []}
    assert captured["url"] == "http://x/v1/models/tts"
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["timeout"] == 15


def test_keyless_headers_omit_authorization(monkeypatch):
    _env(monkeypatch, base="http://x")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(headers=headers)
        return types.SimpleNamespace(status_code=200, text="{}", reason_phrase="OK", json=dict)

    monkeypatch.setattr("httpx.get", fake_get)
    _http.get_json("/v1/models/tts")
    assert "Authorization" not in captured["headers"]


def test_api_key_falls_back_to_hermes_provider_config(monkeypatch):
    _env(
        monkeypatch,
        base="https://gateway.example",
        cfg={
            "providers": {
                "9router": {
                    "api": "https://gateway.example/v1",
                    "api_key": "cfg-key",
                }
            }
        },
    )
    assert _http.api_key() == "cfg-key"


def test_base_url_falls_back_to_hermes_provider_config(monkeypatch):
    _env(
        monkeypatch,
        cfg={
            "providers": {
                "9router": {
                    "api": "https://gateway.example/v1",
                    "api_key": "cfg-key",
                }
            }
        },
    )
    # The provider config's OpenAI-compatible /v1 suffix is stripped: the
    # plugin's request paths already start with /v1.
    assert _http.base_url() == "https://gateway.example"
    assert _http.is_configured() is True
    assert _http.api_key() == "cfg-key"


def test_base_url_strips_v1_suffix(monkeypatch):
    _env(monkeypatch, base="https://gateway.example/v1/", key="k")
    assert _http.base_url() == "https://gateway.example"


def test_explicit_empty_api_key_stays_keyless(monkeypatch):
    _env(
        monkeypatch,
        base="https://gateway.example",
        key="",
        cfg={"providers": {"9router": {"api_key": "cfg-key"}}},
    )
    assert _http.api_key() == ""


def test_explicit_empty_base_url_stays_unconfigured(monkeypatch):
    _env(
        monkeypatch,
        base="",
        cfg={"providers": {"9router": {"api": "https://gateway.example/v1"}}},
    )
    assert _http.is_configured() is False
    with pytest.raises(ValueError, match="NINEROUTER_BASE_URL"):
        _http.base_url()


def test_get_json_raises_with_preview(monkeypatch):
    _env(monkeypatch, base="http://x")

    def fake_get(url, headers=None, timeout=None):
        return types.SimpleNamespace(status_code=404, text='{"error":"model_not_found"}',
                                     reason_phrase="Not Found", json=dict)

    monkeypatch.setattr("httpx.get", fake_get)
    with pytest.raises(RuntimeError, match="404"):
        _http.get_json("/v1/models/nope")


def test_401_error_mentions_api_key(monkeypatch):
    _env(monkeypatch, base="http://x")

    def fake_get(url, headers=None, timeout=None):
        return types.SimpleNamespace(
            status_code=401,
            text='{"error":"API key required for remote API access"}',
            reason_phrase="Unauthorized",
            json=dict,
        )

    monkeypatch.setattr("httpx.get", fake_get)
    with pytest.raises(RuntimeError, match="NINEROUTER_API_KEY"):
        _http.get_json("/v1/models/stt")
