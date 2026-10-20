import sys
import types


class FakeState(dict):
    def set(self, key, value):
        self[key] = value


class FakeCtx:
    def __init__(self, native_hooks=True, state=None):
        self.web, self.image, self.tts, self.stt, self.cli = [], [], [], [], []
        self.hooks, self.tools, self.prompt_sections = [], [], []
        self.state = state
        if native_hooks:
            self.register_tts_provider = self.tts.append
            self.register_transcription_provider = self.stt.append

    def register_web_search_provider(self, provider):
        self.web.append(provider)

    def register_image_gen_provider(self, provider):
        self.image.append(provider)

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli.append((name, setup_fn, handler_fn))

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)

    def register_system_prompt_section(self, id, content, **kwargs):
        self.prompt_sections.append((id, content))


def test_web_gate_accepts_search_and_extract_backend_pins(plugin_pkg):
    for key in ("search_backend", "extract_backend"):
        assert plugin_pkg._web_gate_is_available(
            load_web_config=lambda key=key: {key: "9router"},
            is_available=lambda name: name == "9router",
            original_check=lambda: False,
        ) is True


def test_web_gate_preserves_native_availability_check(plugin_pkg):
    assert plugin_pkg._web_gate_is_available(
        load_web_config=lambda: {},
        is_available=lambda name: False,
        original_check=lambda: True,
    ) is True


def test_web_gate_falls_back_to_registered_provider(plugin_pkg):
    assert plugin_pkg._web_gate_is_available(
        load_web_config=lambda: {},
        is_available=lambda name: name == "9router",
        original_check=lambda: False,
        registered_provider_names=["9router"],
    ) is True


def test_web_gate_is_false_when_nothing_is_available(plugin_pkg):
    assert plugin_pkg._web_gate_is_available(
        load_web_config=lambda: {"search_backend": "9router"},
        is_available=lambda name: False,
        original_check=lambda: False,
    ) is False


def test_register_audio_bridge(plugin_pkg):
    ctx = FakeCtx()
    plugin_pkg._register_audio_bridge(ctx)

    assert [tool["name"] for tool in ctx.tools] == ["transcribe_audio"]
    assert ctx.tools[0]["toolset"] == "file"
    assert ctx.hooks and ctx.hooks[0][0] == "pre_llm_call"
    assert ctx.prompt_sections and ctx.prompt_sections[0][0] == "9router-audio"


def test_register_all_providers_and_cli(plugin_pkg, monkeypatch):
    monkeypatch.setattr(plugin_pkg, "_patch_web_tools_gating", lambda: None)
    ctx = FakeCtx()
    plugin_pkg.register(ctx)
    assert [p.name for p in ctx.web] == ["9router"]
    assert [p.name for p in ctx.image] == ["9router"]
    assert [p.name for p in ctx.tts] == ["9router"]
    assert [p.name for p in ctx.stt] == ["9router"]
    name, setup_fn, handler_fn = ctx.cli[0]
    assert name == "9router"
    assert setup_fn is plugin_pkg.setup_cmd.register_subcommand
    assert handler_fn is plugin_pkg.setup_cmd.handle_setup


def test_register_old_hermes_warns_but_keeps_web_image(plugin_pkg, monkeypatch, caplog):
    monkeypatch.setattr(plugin_pkg, "_patch_web_tools_gating", lambda: None)
    ctx = FakeCtx(native_hooks=False)
    with caplog.at_level("WARNING"):
        plugin_pkg.register(ctx)  # must not raise
    assert ctx.web and ctx.image and ctx.cli
    assert not ctx.tts and not ctx.stt
    assert any("0.17" in record.message for record in caplog.records)


def _fake_hermes_config(monkeypatch, load_result, *, save_error=None):
    saved = {}

    def save(cfg):
        if save_error is not None:
            raise save_error
        saved.update(cfg)

    module = types.ModuleType("hermes_cli.config")
    module.load_config = lambda: load_result
    module.save_config = save
    package = types.ModuleType("hermes_cli")
    package.config = module
    monkeypatch.setitem(sys.modules, "hermes_cli", package)
    monkeypatch.setitem(sys.modules, "hermes_cli.config", module)
    return saved


def _register_with_auto_config(plugin_pkg, monkeypatch, cfg, *, state=None, native_hooks=True):
    monkeypatch.setattr(plugin_pkg, "_patch_web_tools_gating", lambda: None)
    monkeypatch.setattr(plugin_pkg._http, "is_configured", lambda: True)
    saved = _fake_hermes_config(monkeypatch, cfg)
    ctx = FakeCtx(native_hooks=native_hooks, state=state)
    plugin_pkg.register(ctx)
    return saved, ctx


def test_first_install_enables_all_five_capabilities(plugin_pkg, monkeypatch):
    state = FakeState()
    saved, ctx = _register_with_auto_config(
        plugin_pkg,
        monkeypatch,
        {"stt": {"provider": "local"}, "tts": {"provider": "edge"}},
        state=state,
    )
    assert saved["web"]["search_backend"] == "9router"
    assert saved["web"]["extract_backend"] == "9router"
    assert saved["tts"]["provider"] == "9router"
    assert saved["stt"]["provider"] == "9router"
    assert saved["stt"]["enabled"] is True
    assert saved["image_gen"]["provider"] == "9router"
    assert state[plugin_pkg._FIRST_INSTALL_STATE_KEY] is True
    assert ctx.stt  # provider registration still happened


def test_first_install_waits_until_gateway_is_configured(plugin_pkg, monkeypatch):
    monkeypatch.setattr(plugin_pkg, "_patch_web_tools_gating", lambda: None)
    monkeypatch.setattr(plugin_pkg._http, "is_configured", lambda: False)
    saved = _fake_hermes_config(monkeypatch, {"stt": {"provider": "local"}})
    state = FakeState()
    plugin_pkg.register(FakeCtx(state=state))
    assert saved == {}
    assert plugin_pkg._FIRST_INSTALL_STATE_KEY not in state


def test_first_install_save_failure_does_not_mark_done(plugin_pkg, monkeypatch, caplog):
    monkeypatch.setattr(plugin_pkg, "_patch_web_tools_gating", lambda: None)
    monkeypatch.setattr(plugin_pkg._http, "is_configured", lambda: True)
    _fake_hermes_config(
        monkeypatch,
        {"stt": {"provider": "local"}},
        save_error=RuntimeError("disk full"),
    )
    state = FakeState()
    with caplog.at_level("WARNING"):
        plugin_pkg.register(FakeCtx(state=state))
    assert plugin_pkg._FIRST_INSTALL_STATE_KEY not in state
    assert any("auto-config failed" in record.message for record in caplog.records)


def test_first_install_forces_all_even_with_partial_router_config(plugin_pkg, monkeypatch):
    state = FakeState()
    saved, _ctx = _register_with_auto_config(
        plugin_pkg,
        monkeypatch,
        {"tts": {"provider": "9router", "model": "openai/tts-1"}},
        state=state,
    )
    assert saved["web"]["search_backend"] == "9router"
    assert saved["tts"]["provider"] == "9router"
    assert saved["tts"]["model"] == "openai/tts-1"
    assert saved["stt"]["provider"] == "9router"
    assert saved["image_gen"]["provider"] == "9router"
    assert state[plugin_pkg._FIRST_INSTALL_STATE_KEY] is True


def test_first_install_marker_prevents_rewrites(plugin_pkg, monkeypatch):
    state = FakeState()
    saved, _ctx = _register_with_auto_config(
        plugin_pkg, monkeypatch, {"stt": {"provider": "local"}}, state=state
    )
    assert saved
    saved.clear()
    saved, _ctx = _register_with_auto_config(
        plugin_pkg, monkeypatch, {"stt": {"provider": "local"}}, state=state
    )
    assert saved == {}


def test_first_install_on_old_hermes_only_enables_supported_capabilities(plugin_pkg, monkeypatch):
    state = FakeState()
    saved, _ctx = _register_with_auto_config(
        plugin_pkg,
        monkeypatch,
        {"stt": {"provider": "local"}, "tts": {"provider": "edge"}},
        state=state,
        native_hooks=False,
    )
    assert saved["web"]["search_backend"] == "9router"
    assert saved["image_gen"]["provider"] == "9router"
    assert saved["stt"] == {"provider": "local"}
    assert saved["tts"] == {"provider": "edge"}
