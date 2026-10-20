from ninerouter_omni import stt


def _provider():
    return stt.NineRouterTranscriptionProvider()


def test_transcribe_success_envelope(monkeypatch, tmp_path):
    monkeypatch.setenv("NINEROUTER_BASE_URL", "http://x")
    captured = {}

    def fake_post_form(path, *, data, file_field, file_path, file_mime="", timeout=60):
        captured.update(path=path, data=data, file_field=file_field)
        return {"text": "hello world"}

    monkeypatch.setattr("ninerouter_omni.stt.post_form", fake_post_form)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"ID3")
    out = _provider().transcribe(str(audio), model="groq/whisper-large-v3-turbo")
    assert out == {"success": True, "transcript": "hello world", "provider": "9router",
                   "model": "groq/whisper-large-v3-turbo"}
    assert captured["path"] == "/v1/audio/transcriptions"
    assert captured["file_field"] == "file"
    assert captured["data"]["model"] == "groq/whisper-large-v3-turbo"
    assert "language" not in captured["data"]  # no cfg, no language arg


def test_transcribe_carries_config_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("NINEROUTER_BASE_URL", "http://x")
    monkeypatch.setattr(
        "ninerouter_omni.stt.load_hermes_config",
        lambda: {"stt": {"9router": {"prompt": "ctx", "language": "en"}}},
    )
    captured = {}

    def fake_post_form(path, *, data, file_field, file_path, file_mime="", timeout=60):
        captured.update(data=data)
        return {"text": ""}

    monkeypatch.setattr("ninerouter_omni.stt.post_form", fake_post_form)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    _provider().transcribe(str(audio))
    assert captured["data"]["model"] == "groq/whisper-large-v3-turbo"
    assert captured["data"]["prompt"] == "ctx"
    assert captured["data"]["language"] == "en"


def test_transcribe_never_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("NINEROUTER_BASE_URL", "http://x")

    def boom(*args, **kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr("ninerouter_omni.stt.post_form", boom)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = _provider().transcribe(str(audio))
    assert out["success"] is False and out["transcript"] == ""
    assert "gateway down" in out["error"] and out["provider"] == "9router"


def test_transcribe_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("NINEROUTER_BASE_URL", raising=False)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = _provider().transcribe(str(audio))
    assert out["success"] is False and "NINEROUTER_BASE_URL" in out["error"]


def test_list_models_fallback_and_default(monkeypatch):
    def boom(cap):
        raise RuntimeError("down")

    monkeypatch.setattr("ninerouter_omni.stt.fetch_catalog", boom)
    p = _provider()
    assert p.default_model() == "groq/whisper-large-v3-turbo"
    assert [m["id"] for m in p.list_models()][0] == "groq/whisper-large-v3-turbo"


def test_guess_mime(tmp_path):
    assert stt.guess_mime(str(tmp_path / "a.ogg")) == "audio/ogg"
    assert isinstance(stt.guess_mime(str(tmp_path / "a.unknownext")), str)
