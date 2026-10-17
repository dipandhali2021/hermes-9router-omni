import json
from pathlib import Path
from types import SimpleNamespace

from ninerouter_omni import catalog
from ninerouter_omni import setup_cmd as wizard

FIX = Path(__file__).parent / "fixtures"

ALL = list(wizard.CAPABILITY_LABELS)


def _fx(name):
    return json.loads((FIX / name).read_text())


def test_current_picks_web_backend_fallback_and_override():
    assert wizard.current_picks({"web": {"backend": "9router"}})["web_search"] is True
    picks = wizard.current_picks({"web": {"backend": "9router", "search_backend": "tavily"}})
    assert picks["web_search"] is False and picks["web_fetch"] is True


def test_current_picks_provider_sections():
    cfg = {"tts": {"provider": "9router"}, "stt": {"provider": "openai"},
           "image_gen": {"provider": "9router"}}
    assert wizard.current_picks(cfg) == {
        "web_search": False, "web_fetch": False, "tts": True, "stt": False, "image": True}


def test_default_selection_first_run_all_on():
    assert wizard.default_selection({}) == {cap: True for cap in ALL}


def test_default_selection_mirrors_existing():
    assert wizard.default_selection({"tts": {"provider": "9router"}}) == {
        "web_search": False, "web_fetch": False, "tts": True, "stt": False, "image": False}


def test_plan_enables_picked_only():
    out = wizard.plan_writes(
        {},
        {"web_search": False, "web_fetch": False, "tts": True, "stt": False, "image": False},
        models={"tts": "openai/tts-1"}, voice="nova")
    assert out == {"tts": {"provider": "9router", "model": "openai/tts-1", "voice": "nova"}}


def test_plan_writes_web_keys_with_nested_models():
    out = wizard.plan_writes(
        {},
        {"web_search": True, "web_fetch": True, "tts": False, "stt": False, "image": False},
        models={"web_search": "tavily/search", "web_fetch": "exa/fetch"})
    assert out["web"] == {
        "search_backend": "9router", "extract_backend": "9router",
        "9router": {"search_model": "tavily/search", "fetch_model": "exa/fetch"}}


def test_plan_writes_stt_and_image():
    out = wizard.plan_writes(
        {},
        {"web_search": False, "web_fetch": False, "tts": False, "stt": True, "image": True},
        models={"stt": "stt-combo", "image": "image-combo"})
    assert out["stt"] == {"provider": "9router", "enabled": True,
                          "9router": {"model": "stt-combo"}}
    assert out["image_gen"] == {"provider": "9router", "model": "image-combo"}


def test_disable_removes_only_9router_owned_values():
    cfg = {"tts": {"provider": "9router", "model": "m"}, "image_gen": {"provider": "openai"}}
    out = wizard.plan_writes(
        cfg,
        {"web_search": False, "web_fetch": False, "tts": False, "stt": False, "image": None},
        models={})
    assert "provider" not in out["tts"] and out["tts"]["model"] == "m"
    assert out["image_gen"]["provider"] == "openai"


def test_disable_keeps_foreign_web_backend():
    cfg = {"web": {"search_backend": "tavily", "backend": "9router"}}
    out = wizard.plan_writes(
        cfg, {"web_search": False, "web_fetch": None, "tts": None, "stt": None, "image": None},
        models={})
    assert out["web"]["search_backend"] == "tavily"
    assert out["web"]["backend"] == "9router"  # only ONE web cap turned off — shared stays


def test_both_web_off_deletes_shared_backend():
    cfg = {"web": {"backend": "9router"}}
    out = wizard.plan_writes(
        cfg, {"web_search": False, "web_fetch": False, "tts": None, "stt": None, "image": None},
        models={})
    assert "backend" not in out["web"]


def test_none_decisions_leave_capability_untouched():
    cfg = {"tts": {"provider": "9router"}}
    out = wizard.plan_writes(cfg, {cap: None for cap in ALL}, models={})
    assert out == cfg and out is not cfg


def test_plan_does_not_mutate_input():
    cfg = {"tts": {"provider": "9router"}}
    wizard.plan_writes(cfg, {cap: False for cap in ALL}, models={})
    assert cfg == {"tts": {"provider": "9router"}}


def test_scripted_plan_flags_then_current_then_defaults():
    args = SimpleNamespace(tts_model=None, stt_model="stt-x", image_model=None,
                           search_model=None, fetch_model=None, voice="nova")
    decisions, models, voice = wizard.build_scripted_plan({"tts": {"model": "openai/tts-1"}}, args)
    assert all(decisions.values())
    assert models == {"web_search": "openclaw-search", "web_fetch": "openclaw-fetch",
                      "tts": "openai/tts-1", "stt": "stt-x", "image": "image-combo"}
    assert voice == "nova"


def test_fetch_capability_models_splits_web(monkeypatch):
    entries = catalog.parse_catalog(_fx("models_web.json"))
    monkeypatch.setattr("ninerouter_omni.setup_cmd.fetch_catalog", lambda cap: entries)
    assert [e.id for e in wizard.fetch_capability_models("web_search")][0] == "openclaw-search"
    assert [e.id for e in wizard.fetch_capability_models("web_fetch")][0] == "openclaw-fetch"


def test_plan_never_writes_voice_with_combo_model():
    out = wizard.plan_writes(
        {},
        {"web_search": False, "web_fetch": False, "tts": True, "stt": False, "image": False},
        models={"tts": "tts-combo"}, voice="nova")
    assert out["tts"] == {"provider": "9router", "model": "tts-combo"}
