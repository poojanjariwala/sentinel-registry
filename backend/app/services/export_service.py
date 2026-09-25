"""CSV export for camera metadata (audited at the API layer)."""

import csv
import io

from app.services.camera_service import query_cameras, to_dict

EXPORT_FIELDS = [
    "camera_id", "camera_code", "name", "department_id", "site_id", "camera_type",
    "ownership", "public_facing", "vendor", "model", "ip_address", "latitude",
    "longitude", "district", "taluka", "address", "connectivity_status",
    "last_seen_at", "storage_type", "retention_days", "install_date", "amc_vendor",
    "amc_end_date", "maintenance_status", "status", "coverage_radius_m",
    "created_at", "updated_at",
]


def cameras_csv(db, user, **filters) -> tuple[bytes, int]:
    """Export cameras matching the filters as CSV bytes. Returns (csv_bytes, count)."""
    page_size = 10000
    page = 1
    rows: list[dict] = []
    while True:
        batch, total = query_cameras(db, user, page=page, page_size=page_size, **filters)
        rows.extend(to_dict(c) for c in batch)
        if page * page_size >= total or not batch:
            break
        page += 1

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8"), len(rows)
