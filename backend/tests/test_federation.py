"""Unit tests for Module 3 federation adapter framework (pure, no DB)."""

import sys
import os
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import federation  # noqa: E402


def test_adapter_registry_declares_known_kinds():
    kinds = federation.adapter_kinds()
    assert set(kinds) == {"generic_hls", "grid", "mock"}
    for k in kinds:
        discover, health = federation._ADAPTERS[k]
        assert callable(discover) and callable(health)


def test_mock_adapter_is_deterministic_and_scoped():
    vms = SimpleNamespace(name="MOCK-VENDOR-A", vendor="Mock VMS Vendor A", base_url="http://web/hls")
    cams = federation._mock_discover(vms)
    assert len(cams) == 4
    assert cams == federation._mock_discover(vms)
    for i, c in enumerate(cams, start=1):
        assert c["external_ref"] == f"MOCK-VENDOR-A-CAM{i:02d}"
        assert c["vms_system"] == "MOCK-VENDOR-A"
        assert c["protocol"] == "HLS"
        assert c["source_url"].startswith("http://web/hls/cam")


def test_capabilities_constant_matches_trd_common_set():
    assert federation.CORE_CAPABILITIES == ["LIVE_STREAM", "CAMERA_STATUS", "EVENTS", "RECORDING_SEARCH"]


def test_resolve_auth_env_only_reads_named_vars(monkeypatch):
    monkeypatch.setenv("FED_TEST_KEY", "secret-value")
    out = federation.resolve_auth_env(["FED_TEST_KEY", "FED_TEST_MISSING"])
    assert out == {"FED_TEST_KEY": "secret-value"}
    assert federation.resolve_auth_env(None) == {}
