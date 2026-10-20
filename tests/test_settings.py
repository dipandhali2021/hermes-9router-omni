from ninerouter_omni import settings


def test_defaults_when_config_empty():
    assert settings.resolve_search_model({}) == "openclaw-search"
    assert settings.resolve_fetch_model({}) == "openclaw-fetch"
    assert settings.resolve_tts_model({}) == "openrouter/fish-audio/s2.1-pro-free:free"
    assert settings.resolve_stt_model({}) == "groq/whisper-large-v3-turbo"
    assert settings.resolve_image_model({}) == "ag/gemini-3.1-flash-image"


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
    assert settings.resolve_tts_model({"tts": {"model": "   "}}) == "openrouter/fish-audio/s2.1-pro-free:free"
    assert settings.resolve_tts_model({"tts": {"model": 7}}) == "openrouter/fish-audio/s2.1-pro-free:free"


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


def test_gateway_credentials_prefer_model_provider():
    cfg = {
        "model": {"provider": "custom:9router-local"},
        "providers": {
            "9router": {
                "api": "https://9router.example/v1",
                "api_key": "remote-key",
            }
        },
        "custom_providers": [
            {
                "name": "9router-local",
                "base_url": "http://localhost:20128/v1",
                "api_key": "local-key",
            }
        ],
    }
    assert settings.resolve_gateway_credentials(cfg) == (
        "http://localhost:20128/v1",
        "local-key",
    )


def test_gateway_credentials_match_base_url_hint():
    cfg = {
        "providers": {
            "9router": {
                "api": "https://9router.example/v1",
                "api_key": "remote-key",
            }
        },
        "custom_providers": [
            {
                "name": "9router-local",
                "base_url": "http://localhost:20128/v1",
                "api_key": "local-key",
            }
        ],
    }
    assert settings.resolve_gateway_credentials(
        cfg, base_url_hint="https://9router.example"
    ) == ("https://9router.example/v1", "remote-key")
    # 127.0.0.1 and localhost are the same gateway.
    assert settings.resolve_gateway_credentials(
        cfg, base_url_hint="http://127.0.0.1:20128"
    ) == ("http://localhost:20128/v1", "local-key")


def test_gateway_credentials_match_any_provider_by_base_url():
    cfg = {
        "providers": {
            "my-gateway": {
                "base_url": "https://gateway.example/v1",
                "api_key": "k",
            }
        }
    }
    assert settings.resolve_gateway_credentials(
        cfg, base_url_hint="https://gateway.example"
    ) == ("https://gateway.example/v1", "k")


def test_gateway_credentials_default_to_9router_provider():
    cfg = {
        "providers": {
            "9router": {"api": "https://9router.example/v1", "api_key": "k"}
        }
    }
    assert settings.resolve_gateway_credentials(cfg) == (
        "https://9router.example/v1",
        "k",
    )


def test_gateway_credentials_no_candidates():
    assert settings.resolve_gateway_credentials({}) == (None, "")
    assert settings.resolve_gateway_credentials(None) == (None, "")


def test_gateway_credentials_ignore_unrelated_provider_without_hint():
    cfg = {
        "providers": {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-openai",
            }
        }
    }
    assert settings.resolve_gateway_credentials(cfg) == (None, "")


def test_gateway_credentials_do_not_borrow_unrelated_key_with_hint():
    # Never send an OpenAI/Anthropic key to a 9router host.
    cfg = {
        "providers": {
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-openai",
            }
        }
    }
    assert settings.resolve_gateway_credentials(
        cfg, base_url_hint="https://9router.example"
    ) == (None, "")


def test_build_transcription_fields():
    cfg = {"stt": {"9router": {"prompt": "ctx", "response_format": "json",
                               "temperature": 0.2, "language": "en"}}}
    assert settings.build_transcription_fields("m", None, cfg) == {
        "model": "m", "language": "en", "prompt": "ctx",
        "response_format": "json", "temperature": 0.2}
    assert settings.build_transcription_fields("m", "de", cfg)["language"] == "de"
    assert settings.build_transcription_fields("m", None, {}) == {"model": "m"}
