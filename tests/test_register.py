class FakeCtx:
    def __init__(self, native_hooks=True):
        self.web, self.image, self.tts, self.stt, self.cli = [], [], [], [], []
        if native_hooks:
            self.register_tts_provider = self.tts.append
            self.register_transcription_provider = self.stt.append

    def register_web_search_provider(self, provider):
        self.web.append(provider)

    def register_image_gen_provider(self, provider):
        self.image.append(provider)

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli.append((name, setup_fn, handler_fn))


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
