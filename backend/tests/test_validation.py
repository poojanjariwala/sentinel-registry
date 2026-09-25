"""Unit tests for camera row validation (pure functions, no DB)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.validation import parse_date, validate_camera_row  # noqa: E402


def test_parse_date_accepts_multiple_formats():
    assert parse_date("2024-01-15").isoformat() == "2024-01-15"
    assert parse_date("15-01-2024").isoformat() == "2024-01-15"
    assert parse_date("15/01/2024").isoformat() == "2024-01-15"
    assert parse_date("") is None
    assert parse_date(None) is None


def test_valid_row_passes():
    row = {
        "camera_code": "CAM-X-001",
        "name": "Test Camera",
        "department_id": "POLICE",
        "latitude": "23.02",
        "longitude": "72.57",
    }
    assert validate_camera_row(row) == []


def test_missing_required_fields():
    row = {"camera_code": "", "name": "", "department_id": ""}
    errors = validate_camera_row(row)
    assert any("camera_code" in e for e in errors)
    assert any("name" in e for e in errors)
    assert any("department_id" in e for e in errors)
    assert any("latitude and longitude are required" in e for e in errors)


def test_out_of_bbox_rejected():
    row = {
        "camera_code": "CAM-X-002",
        "name": "Test",
        "department_id": "POLICE",
        "latitude": "99.0",
        "longitude": "72.5",
    }
    errors = validate_camera_row(row)
    assert any("outside Gujarat" in e for e in errors)


def test_unrecognized_enum_falls_back_with_warning():
    """Unrecognized enum values no longer hard-fail: they map to a safe
    fallback and surface a warning instead."""
    row = {
        "camera_code": "CAM-X-003",
        "name": "Test",
        "department_id": "POLICE",
        "latitude": "23.0",
        "longitude": "72.5",
        "camera_type": "THERMAL-ELITE",
    }
    errors = validate_camera_row(row)
    assert errors == []
    assert row["camera_type"] == "FIXED"
    warnings = row.pop("__warnings", [])
    assert any("camera_type" in w and "THERMAL-ELITE" in w for w in warnings)


def test_department_vocabulary_is_mapped():
    row = {
        "camera_code": "CAM-X-009", "name": "T", "department_id": "POLICE",
        "latitude": "23.0", "longitude": "72.5",
        "maintenance_status": "OVERDUE", "status": "MAINTENANCE",
        "ownership": "SEMI-GOVT", "connectivity_status": "NOT WORKING FROM 2 DAYS",
    }
    errors = validate_camera_row(row)
    assert errors == []
    assert row["maintenance_status"] == "DUE"
    assert row["status"] == "PENDING_VALIDATION"
    assert row["ownership"] == "GOVERNMENT"
    assert row["connectivity_status"] == "OFFLINE"
    assert not row.get("__warnings")


def test_bad_date_format():
    row = {
        "camera_code": "CAM-X-004",
        "name": "Test",
        "department_id": "POLICE",
        "latitude": "23.0",
        "longitude": "72.5",
        "install_date": "15/01/24x",
    }
    errors = validate_camera_row(row)
    assert any("not a valid date" in e for e in errors)
