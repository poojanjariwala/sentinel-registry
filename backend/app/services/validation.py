"""Validation helpers shared by manual entry and bulk import.

Designed for messy government/Excel data: dates arrive in many formats and
enum fields use department-specific vocabulary. Both are normalized here.
"""

import re
from datetime import date, datetime, timedelta

GUJARAT_BBOX = (68.1, 20.1, 74.5, 24.7)  # minLng, minLat, maxLng, maxLat

VALID_CAMERA_TYPES = {"FIXED", "PTZ", "DOME", "BULLET", "ANPR"}
VALID_OWNERSHIP = {"GOVERNMENT", "PRIVATE"}
VALID_STORAGE = {"CLOUD", "LOCAL", "NVR", "NONE"}
VALID_CONN = {"ONLINE", "OFFLINE", "UNKNOWN"}
VALID_MAINT = {"OK", "DUE", "FAULTY"}
VALID_CAMERA_STATUS = {"ACTIVE", "PENDING_VALIDATION", "DECOMMISSIONED"}

# Common department vocabulary mapped onto canonical enum values.
ENUM_ALIASES: dict[str, dict[str, str]] = {
    "camera_type": {
        "FIXED": "FIXED", "FIX": "FIXED", "STATIC": "FIXED", "BOX": "FIXED",
        "PTZ": "PTZ", "PTZ-DOME": "PTZ", "SPEED DOME": "PTZ",
        "DOME": "DOME", "TURRET": "DOME",
        "BULLET": "BULLET", "OUTDOOR": "BULLET",
        "ANPR": "ANPR", "LPR": "ANPR", "NUMBER PLATE": "ANPR", "ALPR": "ANPR",
    },
    "ownership": {
        "GOVERNMENT": "GOVERNMENT", "GOVT": "GOVERNMENT", "GOVT.": "GOVERNMENT", "G": "GOVERNMENT",
        "SEMI-GOVT": "GOVERNMENT", "SEMI GOVT": "GOVERNMENT", "SEMI-GOV": "GOVERNMENT",
        "SEMI GOVERNMENT": "GOVERNMENT", "PUBLIC SECTOR": "GOVERNMENT",
        "PRIVATE": "PRIVATE", "PVT": "PRIVATE", "PVT.": "PRIVATE", "P": "PRIVATE",
    },
    "storage_type": {
        "CLOUD": "CLOUD", "ONLINE STORAGE": "CLOUD",
        "LOCAL": "LOCAL", "LOCAL STORAGE": "LOCAL", "SD": "LOCAL", "SD CARD": "LOCAL",
        "NVR": "NVR", "DVR": "NVR", "SERVER": "NVR",
        "NONE": "NONE", "NA": "NONE", "N/A": "NONE", "-": "NONE",
    },
    "connectivity_status": {
        "ONLINE": "ONLINE", "LIVE": "ONLINE", "UP": "ONLINE", "WORKING": "ONLINE", "CONNECTED": "ONLINE", "Y": "ONLINE",
        "OFFLINE": "OFFLINE", "DOWN": "OFFLINE", "DEAD": "OFFLINE", "NOT WORKING": "OFFLINE",
        "DISCONNECTED": "OFFLINE", "FAULTY": "OFFLINE", "DAMAGED": "OFFLINE", "MAINTENANCE": "OFFLINE", "N": "OFFLINE",
        "UNKNOWN": "UNKNOWN", "NA": "UNKNOWN", "N/A": "UNKNOWN", "-": "UNKNOWN",
    },
    "maintenance_status": {
        "OK": "OK", "HEALTHY": "OK", "GOOD": "OK", "NORMAL": "OK", "WORKING": "OK",
        "DUE": "DUE", "PENDING": "DUE", "DUE SOON": "DUE", "AMC DUE": "DUE",
        "OVERDUE": "DUE", "OVER-DUE": "DUE", "PAST DUE": "DUE", "EXPIRED": "DUE",
        "UNDER MAINTENANCE": "DUE", "MAINTENANCE": "DUE", "REPAIR": "DUE",
        "FAULTY": "FAULTY", "BROKEN": "FAULTY", "FAILED": "FAULTY", "DAMAGED": "FAULTY", "NOT WORKING": "FAULTY",
    },
    "status": {
        "ACTIVE": "ACTIVE", "LIVE": "ACTIVE", "IN SERVICE": "ACTIVE", "OPERATIONAL": "ACTIVE",
        "PENDING_VALIDATION": "PENDING_VALIDATION", "PENDING": "PENDING_VALIDATION",
        "NEW": "PENDING_VALIDATION", "UNDER REVIEW": "PENDING_VALIDATION",
        "MAINTENANCE": "PENDING_VALIDATION", "UNDER MAINTENANCE": "PENDING_VALIDATION",
        "UNDER REPAIR": "PENDING_VALIDATION", "DAMAGED": "PENDING_VALIDATION",
        "DECOMMISSIONED": "DECOMMISSIONED", "RETIRED": "DECOMMISSIONED",
        "DISABLED": "DECOMMISSIONED", "INACTIVE": "DECOMMISSIONED", "REMOVED": "DECOMMISSIONED",
    },
}

# Safe fallbacks when a value cannot be understood at all (row imports with a warning).
ENUM_FALLBACK: dict[str, str | None] = {
    "camera_type": "FIXED",
    "ownership": "GOVERNMENT",
    "storage_type": None,
    "connectivity_status": "UNKNOWN",
    "maintenance_status": "OK",
    "status": "PENDING_VALIDATION",
}

MAX_IMPORT_ROWS = 5000

_EXCEL_EPOCH = date(1899, 12, 30)


def _from_numeric_parts(a: str, b: str, c: str) -> date | None:
    """Interpret a/b/c numeric date parts with day-month disambiguation."""
    # Year first: 2021/12/15
    if len(a) == 4:
        y, mo, d = int(a), int(b), int(c)
    else:
        y_raw = c
        y = int(y_raw)
        if y < 100:
            y += 2000
        x, n = int(a), int(b)
        if x > 12 and n <= 12:      # first must be the day -> DD/MM/YYYY
            d, mo = x, n
        elif n > 12 and x <= 12:    # second must be the day -> MM/DD/YYYY (US)
            mo, d = x, n
        else:                        # ambiguous: default to Indian DD/MM/YYYY
            d, mo = x, n
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_date(s):
    """Parse dates liberally; returns a date or None.

    Accepted: datetime/date objects, ISO (2021-12-15), DD/MM/YYYY, MM/DD/YYYY
    (auto-disambiguated), 2-digit years, D-MMM-YYYY (15-Dec-2021), Month D, YYYY,
    and 5-digit Excel serial numbers.
    """
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s

    s = str(s).strip()
    if not s or s.upper() in {"NA", "N/A", "-", "NULL", "NONE"}:
        return None

    s = re.split(r"[ T]\d{1,2}:\d{2}", s)[0].strip()  # drop time component

    if re.fullmatch(r"\d{5}", s):  # Excel serial date
        try:
            return _EXCEL_EPOCH + timedelta(days=int(s))
        except (ValueError, OverflowError):
            return None

    text_formats = (
        "%Y-%m-%d", "%Y/%m/%d",
        "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y",
        "%b %d, %Y", "%B %d, %Y", "%d.%m.%Y",
    )
    for f in text_formats:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue

    m = re.fullmatch(r"(\d{1,4})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        return _from_numeric_parts(m.group(1), m.group(2), m.group(3))
    return None


def _norm_enum(field: str, raw) -> tuple[str | None, bool]:
    """Return (canonical_value, was_provided).

    Lookup order: exact alias -> substring heuristics -> None (unrecognized).
    """
    val = raw
    if val in (None, ""):
        return None, False
    key = str(val).strip().upper()
    canonical = ENUM_ALIASES.get(field, {}).get(key)
    if canonical:
        return canonical, True

    # Substring heuristics for department-specific phrasing.
    if field == "camera_type":
        if any(k in key for k in ("ANPR", "LPR", "PLATE")):
            return "ANPR", True
        if "PTZ" in key:
            return "PTZ", True
        if "DOME" in key:
            return "DOME", True
        if "BULLET" in key:
            return "BULLET", True
        if any(k in key for k in ("FIX", "STATIC", "BOX")):
            return "FIXED", True
    elif field == "ownership":
        if "GOV" in key:
            return "GOVERNMENT", True
        if "PVT" in key or "PRIVATE" in key:
            return "PRIVATE", True
    elif field == "connectivity_status":
        # Negative markers first: "NOT WORKING" must not match "WORKING".
        if any(k in key for k in ("NOT WORK", "OFFLINE", "DOWN", "DEAD", "FAULT", "MAINT", "DAMAG", "DISCONN")):
            return "OFFLINE", True
        if any(k in key for k in ("ONLINE", "LIVE", "WORKING", "CONNECT", " UP")):
            return "ONLINE", True
    elif field == "maintenance_status":
        if any(k in key for k in ("OVER", "DUE", "EXPIRE", "PENDING")):
            return "DUE", True
        if any(k in key for k in ("FAULT", "BROKEN", "DAMAG", "FAILED", "REPAIR", "NOT WORK")):
            return "FAULTY", True
        if any(k in key for k in ("OK", "GOOD", "HEALTH", "NORMAL", "WORKING")):
            return "OK", True
    elif field == "status":
        if any(k in key for k in ("DECOM", "RETIRED", "DISABLE", "INACTIVE", "REMOVED")):
            return "DECOMMISSIONED", True
        if any(k in key for k in ("PENDING", "MAINT", "REVIEW", "REPAIR", "NEW", "DAMAG")):
            return "PENDING_VALIDATION", True
        if any(k in key for k in ("ACTIVE", "OPERATIONAL", "LIVE", "SERVIC")):
            return "ACTIVE", True
    elif field == "storage_type":
        if "CLOUD" in key:
            return "CLOUD", True
        if "NVR" in key or "DVR" in key or "SERVER" in key:
            return "NVR", True
        if "LOCAL" in key or "SD" in key:
            return "LOCAL", True

    return None, True


def validate_camera_row(row: dict) -> list[str]:
    """Validate/normalize one camera row in place; returns list of error strings."""
    errors: list[str] = []

    code = str(row.get("camera_code") or "").strip()
    name = str(row.get("name") or "").strip()
    if not code:
        errors.append("camera_code is required")
    elif len(code) < 3:
        errors.append("camera_code must be at least 3 characters")
    if not name:
        errors.append("name is required")

    dept = str(row.get("department_id") or "").strip()
    if not dept:
        errors.append("department_id is required")

    lat, lng = row.get("latitude"), row.get("longitude")
    if lat in (None, "") or lng in (None, ""):
        errors.append("latitude and longitude are required")
    else:
        try:
            lat_f, lng_f = float(str(lat).strip()), float(str(lng).strip())
            if not (GUJARAT_BBOX[1] <= lat_f <= GUJARAT_BBOX[3]):
                errors.append(f"latitude {lat_f} outside Gujarat bounding box")
            if not (GUJARAT_BBOX[0] <= lng_f <= GUJARAT_BBOX[2]):
                errors.append(f"longitude {lng_f} outside Gujarat bounding box")
            row["latitude"] = lat_f
            row["longitude"] = lng_f
        except (TypeError, ValueError):
            errors.append("latitude/longitude must be decimal numbers")

    warnings: list[str] = row.setdefault("__warnings", [])
    for field in ("camera_type", "ownership", "storage_type",
                  "connectivity_status", "maintenance_status", "status"):
        canonical, provided = _norm_enum(field, row.get(field))
        if not provided:
            continue
        if canonical is None:
            fallback = ENUM_FALLBACK[field]
            warnings.append(
                f"{field} '{row.get(field)}' not recognized - imported as '{fallback or 'empty'}'"
            )
            row[field] = fallback
        else:
            row[field] = canonical

    for field in ("retention_days", "coverage_radius_m"):
        v = row.get(field)
        if v not in (None, ""):
            try:
                row[field] = int(str(v).strip().replace(",", ""))
            except (TypeError, ValueError):
                errors.append(f"{field} must be an integer")

    for field in ("install_date", "amc_end_date"):
        if row.get(field) not in (None, ""):
            parsed = parse_date(row[field])
            if parsed is None:
                errors.append(
                    f"{field} '{row[field]}' is not a valid date "
                    "(accepted: YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, 15-Dec-2021, Excel date)"
                )
            else:
                row[field] = parsed

    return errors
