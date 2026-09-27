"""Unit tests for the shared ANPR pipeline (pure logic, no DB)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.anpr_pipeline import looks_like_plate, normalize_plate  # noqa: E402


def test_normalize_strips_and_maps_confusions():
    assert normalize_plate("gj 01-ab 1234") == "GJ01AB1234"
    assert normalize_plate("GJ-01-AB-1O34") == "GJ01AB1034"  # O->0 only where mapped
    assert normalize_plate("GJ01AI1234") == "GJ01A11234"  # I->1, length kept
    assert normalize_plate("") == ""


def test_plate_shape_gate():
    assert looks_like_plate("GJ01AB1234")
    assert looks_like_plate("MH12DE9012")
    assert looks_like_plate("GJ18KB5678")
    # garbage / partial OCR is rejected, never asserted as identity
    assert not looks_like_plate("GUJARAT")
    assert not looks_like_plate("1234567890")
    assert not looks_like_plate("GJ01AB123")
    assert not looks_like_plate("")
