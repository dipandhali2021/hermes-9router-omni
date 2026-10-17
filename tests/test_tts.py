import pytest

from ninerouter_omni import catalog, tts


def _provider():
    return tts.NineRouterTTSProvider()


def test_metadata():
    p = _provider()
    assert p.name == "9router" and p.display_name == "9router"
    assert p.voice_compatible is False
    assert p.default_model() == "tts-combo"


def test_is_available_tracks_base_url(monkeypatch):
    monkeypatch.setenv("NINEROUTER_BASE_URL", "http://x")
    monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
    assert _provider().is_available() is True
    monkeypatch.delenv("NINEROUTER_BASE_URL", raising=False)
    assert _provider().is_available() is False


def test_synthesize_composes_voice_and_writes(monkeypatch, tmp_path):
    captured = {}

    def fake_post(path, body, *, timeout=60):
        captured.update(path=path, body=body)
        return (b"ID3fake", "audio/mpeg; charset=utf-8")

    monkeypatch.setattr("ninerouter_omni.tts.post_json_bytes", fake_post)
    out = tmp_path / "voice.mp3"
    path = _provider().synthesize("hello", str(out), voice="nova", model="openai/tts-1")
    assert captured["path"] == "/v1/audio/speech"
    assert captured["body"] == {"model": "openai/tts-1/nova", "input": "hello"}
    assert path == str(out) and out.read_bytes() == b"ID3fake"


def test_synthesize_rewrites_extension(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ninerouter_omni.tts.post_json_bytes",
        lambda path, body, *, timeout=60: (b"RIFF", "audio/wav"),
    )
    path = _provider().synthesize("hi", str(tmp_path / "voice.mp3"), model="openai/tts-1")
    assert path == str(tmp_path / "voice.wav") and (tmp_path / "voice.wav").exists()


def test_synthesize_raises_on_empty_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ninerouter_omni.tts.post_json_bytes",
        lambda path, body, *, timeout=60: (b"", "audio/mpeg"),
    )
    with pytest.raises(RuntimeError, match="empty"):
        _provider().synthesize("hi", str(tmp_path / "v.mp3"), model="m")


def test_synthesize_defaults_model_from_config(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "ninerouter_omni.tts.load_hermes_config",
        lambda: {"tts": {"model": "openai/tts-1"}},
    )
    captured = {}

    def fake_post(path, body, *, timeout=60):
        captured.update(body=body)
        return (b"a", "audio/mpeg")

    monkeypatch.setattr("ninerouter_omni.tts.post_json_bytes", fake_post)
    _provider().synthesize("hi", str(tmp_path / "v.mp3"))
    assert captured["body"]["model"] == "openai/tts-1"


def test_list_models_live_and_fallback(monkeypatch):
    entries = [catalog.CatalogEntry("tts-combo", "combo", "tts"),
               catalog.CatalogEntry("openai/tts-1", "openai")]
    monkeypatch.setattr("ninerouter_omni.tts.fetch_catalog", lambda cap: entries)
    models = _provider().list_models()
    assert models[0]["id"] == "tts-combo" and "combo" in models[0]["display"].lower()

    def boom(cap):
        raise RuntimeError("gateway down")

    monkeypatch.setattr("ninerouter_omni.tts.fetch_catalog", boom)
    assert [m["id"] for m in _provider().list_models()][0] == "tts-combo"
