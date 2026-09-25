from pydantic import BaseModel, Field

from app.schemas.common import ORTIMixin


class GapAnalysisRequest(BaseModel):
    departments: list[str] | None = None
    districts: list[str] | None = None
    resolution: int = Field(default=8, ge=4, le=10)
    min_cameras_per_cell: int = Field(default=1, ge=1, le=50)
    ageing_years: float = Field(default=5.0, ge=1, le=20)
    geometry: bool = True


class GapCell(BaseModel):
    cell_id: str
    camera_count: int
    classification: str


class GapSummary(ORTIMixin):
    run_id: str
    created_at: str | None = None
    params: dict
    total_cameras: int
    hex_covered: int
    hex_thin: int
    hex_uncovered_in_bbox: int
    ageing_count: int
    amc_expired_count: int
    by_district: list[dict]
    top_uncovered_cells: list[GapCell]
    ageing_sample: list[dict]
