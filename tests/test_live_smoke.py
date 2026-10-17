import os

import pytest

from ninerouter_omni import catalog

pytestmark = pytest.mark.skipif(
    not os.getenv("NINEROUTER_LIVE"),
    reason="set NINEROUTER_LIVE=1 (and NINEROUTER_BASE_URL) to probe a live gateway",
)


def test_live_catalogs():
    for capability in ("web", "tts", "stt", "image"):
        entries = catalog.fetch_catalog(capability)
        assert entries, capability
        assert entries[0].is_combo, capability


def test_live_auth_probe():
    probe = catalog.probe_auth(
        os.environ["NINEROUTER_BASE_URL"], os.getenv("NINEROUTER_API_KEY", ""))
    assert probe.ok, probe.detail
