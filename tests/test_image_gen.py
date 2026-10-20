from ninerouter_omni import image_gen


def _provider():
    return image_gen.NineRouterImageGenProvider()


def test_default_model_is_flash_image():
    assert _provider().default_model() == "ag/gemini-3.1-flash-image"


def test_list_models_is_curated_not_a_dump():
    ids = [m["id"] for m in _provider().list_models()]
    assert ids[0] == "ag/gemini-3.1-flash-image"
    assert len(ids) <= len(image_gen.CURATED_MODELS) + 1


def test_list_models_prepends_configured(monkeypatch):
    monkeypatch.setattr(
        "ninerouter_omni.image_gen.load_hermes_config",
        lambda: {"image_gen": {"model": "custom/model"}},
    )
    models = _provider().list_models()
    assert models[0]["id"] == "custom/model" and "configured" in models[0]["display"]


def test_old_key_still_resolves(monkeypatch):
    monkeypatch.setattr(
        "ninerouter_omni.image_gen.load_hermes_config",
        lambda: {"image_gen": {"9router": {"model": "legacy/model"}}},
    )
    assert _provider().list_models()[0]["id"] == "legacy/model"


def test_detect_extension():
    import base64

    jpeg = base64.b64encode(b"\xff\xd8\xff\xe0hello").decode()
    gif = base64.b64encode(b"GIF89a....").decode()
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n....").decode()
    assert image_gen._detect_image_extension(jpeg) == "jpg"
    assert image_gen._detect_image_extension(gif) == "gif"
    assert image_gen._detect_image_extension(png) == "png"
    assert image_gen._detect_image_extension("!!!not base64!!!") == "png"
