from ninerouter_omni import settings


def test_defaults_when_config_empty():
    assert settings.resolve_search_model({}) == "openclaw-search"
    assert settings.resolve_fetch_model({}) == "openclaw-fetch"
    assert settings.resolve_tts_model({}) == "tts-combo"
    assert settings.resolve_stt_model({}) == "stt-combo"
    assert settings.resolve_image_model({}) == "image-combo"


def test_tts_new_key_wins_over_old():
    cfg = {"tts": {"model": "openai/tts-1", "9router": {"model": "old"}}}
    assert settings.resolve_tts_model(cfg) == "openai/tts-1"


def test_tts_old_key_still_readable():
    assert settings.resolve_tts_model({"tts": {"9router": {"model": "old-tts"}}}) == "old-tts"


def test_image_new_then_old_then_default():
    assert settings.resolve_image_model({"image_gen": {"model": "gemini/x"}}) == "gemini/x"
    assert settings.resolve_image_model({"image_gen": {"9router": {"model": "legacy"}}}) == "legacy"


def test_web_models_read_nested_keys():
    cfg = {"web": {"9router": {"search_model": "tavily/search", "fetch_model": "exa/fetch"}}}
    assert settings.resolve_search_model(cfg) == "tavily/search"
    assert settings.resolve_fetch_model(cfg) == "exa/fetch"


def test_blank_and_nonstring_values_ignored():
    assert settings.resolve_tts_model({"tts": {"model": "   "}}) == "tts-combo"
    assert settings.resolve_tts_model({"tts": {"model": 7}}) == "tts-combo"


def test_compose_appends_and_is_idempotent():
    assert settings.compose_tts_model("openai/tts-1", "nova") == "openai/tts-1/nova"
    assert settings.compose_tts_model("openai/tts-1/nova", "nova") == "openai/tts-1/nova"
    assert settings.compose_tts_model("openai/tts-1", None) == "openai/tts-1"
    assert settings.compose_tts_model("openai/tts-1", "") == "openai/tts-1"


def test_compose_combo_gets_no_silent_drop():
    # The wizard prevents combo+voice; a hand-edited combo+voice must reach the
    # gateway so its error surfaces (rather than being silently dropped).
    assert settings.compose_tts_model("tts-combo", "nova") == "tts-combo/nova"


def test_ext_for_content_type():
    assert settings.ext_for_content_type("audio/mpeg; charset=utf-8") == "mp3"
    assert settings.ext_for_content_type("audio/wav") == "wav"
    assert settings.ext_for_content_type("audio/ogg") == "ogg"
    assert settings.ext_for_content_type("audio/webm") == "webm"
    assert settings.ext_for_content_type("audio/flac") == "flac"
    assert settings.ext_for_content_type("") == "mp3"


def test_build_transcription_fields():
    cfg = {"stt": {"9router": {"prompt": "ctx", "response_format": "json",
                               "temperature": 0.2, "language": "en"}}}
    assert settings.build_transcription_fields("m", None, cfg) == {
        "model": "m", "language": "en", "prompt": "ctx",
        "response_format": "json", "temperature": 0.2}
    assert settings.build_transcription_fields("m", "de", cfg)["language"] == "de"
    assert settings.build_transcription_fields("m", None, {}) == {"model": "m"}
