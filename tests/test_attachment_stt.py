import json

from ninerouter_omni import attachment_stt


def _audio(tmp_path, name="voice.m4a"):
    path = tmp_path / name
    path.write_bytes(b"audio-bytes")
    return path


def test_find_audio_attachments_extracts_only_audio(tmp_path):
    audio = _audio(tmp_path)
    text = f"[User attached file: {audio}]\nwhat did I say?"
    assert attachment_stt.find_audio_attachments(text) == [str(audio)]

    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    assert attachment_stt.find_audio_attachments(f"[User attached file: {notes}]") == []


def test_auto_transcribe_injects_9router_transcript(monkeypatch, tmp_path):
    audio = _audio(tmp_path)
    calls = []

    monkeypatch.setattr(
        attachment_stt, "load_hermes_config", lambda: {"stt": {"provider": "9router"}}
    )
    monkeypatch.setattr(attachment_stt, "is_configured", lambda: True)
    monkeypatch.setattr(
        attachment_stt,
        "_transcribe",
        lambda path, source: calls.append((path, source))
        or {
            "success": True,
            "transcript": " Hey, what are you doing?",
            "provider": "9router",
            "model": "groq/whisper-large-v3-turbo",
        },
    )

    out = attachment_stt.auto_transcribe_attachment(
        user_message=f"[User attached file: {audio}]"
    )

    assert out is not None
    assert "Hey, what are you doing?" in out["context"]
    assert "9router STT" in out["context"]
    assert calls == [(str(audio), "tui_attachment")]


def test_auto_transcribe_skips_when_provider_is_not_9router(monkeypatch, tmp_path):
    audio = _audio(tmp_path)
    called = []
    monkeypatch.setattr(
        attachment_stt, "load_hermes_config", lambda: {"stt": {"provider": "local"}}
    )
    monkeypatch.setattr(attachment_stt, "is_configured", lambda: True)
    monkeypatch.setattr(
        attachment_stt, "_transcribe", lambda path, source: called.append(path) or {}
    )

    assert attachment_stt.auto_transcribe_attachment(
        user_message=f"[User attached file: {audio}]"
    ) is None
    assert called == []


def test_auto_transcribe_failure_points_at_tool_not_local_install(monkeypatch, tmp_path):
    audio = _audio(tmp_path)
    monkeypatch.setattr(
        attachment_stt, "load_hermes_config", lambda: {"stt": {"provider": "9router"}}
    )
    monkeypatch.setattr(attachment_stt, "is_configured", lambda: True)
    monkeypatch.setattr(
        attachment_stt,
        "_transcribe",
        lambda path, source: {
            "success": False,
            "transcript": "",
            "error": "gateway down",
            "provider": "9router",
        },
    )

    out = attachment_stt.auto_transcribe_attachment(
        user_message=f"[User attached file: {audio}]"
    )

    assert out is not None
    assert "gateway down" in out["context"]
    assert "transcribe_audio" in out["context"]
    assert "do not install local" in out["context"].lower()


def test_transcript_cache_avoids_second_network_call(monkeypatch, tmp_path):
    audio = _audio(tmp_path)
    calls = []
    monkeypatch.setattr(
        attachment_stt, "load_hermes_config", lambda: {"stt": {"provider": "9router"}}
    )
    monkeypatch.setattr(attachment_stt, "is_configured", lambda: True)
    monkeypatch.setattr(
        attachment_stt,
        "_transcribe",
        lambda path, source: calls.append(path)
        or {
            "success": True,
            "transcript": "cached transcript",
            "provider": "9router",
        },
    )

    attachment_stt.auto_transcribe_attachment(user_message=f"[User attached file: {audio}]")
    attachment_stt.auto_transcribe_attachment(user_message=f"[User attached file: {audio}]")

    assert len(calls) == 1


def test_transcribe_tool_handler_returns_json(monkeypatch, tmp_path):
    audio = _audio(tmp_path)
    monkeypatch.setattr(
        attachment_stt,
        "transcribe_attachment",
        lambda path, source="tui_attachment": {
            "success": True,
            "transcript": "tool transcript",
            "provider": "9router",
        },
    )

    out = json.loads(attachment_stt.handle_transcribe_audio({"path": str(audio)}))
    assert out["success"] is True
    assert out["transcript"] == "tool transcript"


def test_transcribe_tool_handler_requires_path():
    out = json.loads(attachment_stt.handle_transcribe_audio({}))
    assert out["success"] is False
    assert "path" in out["error"]
