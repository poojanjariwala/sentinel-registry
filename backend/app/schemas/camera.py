from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORTIMixin

CameraType = str
Ownership = str
Storage = str
ConnStatus = str
MaintStatus = str
CameraStatus = str


class CameraCreate(BaseModel):
    camera_code: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=2, max_length=200)
    department_id: str
    site_id: str | None = None
    camera_type: str = "FIXED"
    ownership: str = "GOVERNMENT"
    public_facing: bool = False
    vendor: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    ip_address: str | None = Field(default=None, max_length=45)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    district: str | None = Field(default=None, max_length=100)
    taluka: str | None = Field(default=None, max_length=100)
    address: str | None = None
    connectivity_status: str = "UNKNOWN"
    storage_type: str | None = None
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    install_date: str | None = None
    amc_vendor: str | None = Field(default=None, max_length=150)
    amc_end_date: str | None = None
    maintenance_status: str = "OK"
    status: str = "ACTIVE"
    coverage_radius_m: int | None = Field(default=None, ge=10, le=5000)
    metadata: dict | None = None

    @model_validator(mode="after")
    def check_coords(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class CameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    site_id: str | None = None
    camera_type: str | None = None
    ownership: str | None = None
    public_facing: bool | None = None
    vendor: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    ip_address: str | None = Field(default=None, max_length=45)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    district: str | None = Field(default=None, max_length=100)
    taluka: str | None = Field(default=None, max_length=100)
    address: str | None = None
    connectivity_status: str | None = None
    storage_type: str | None = None
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    install_date: str | None = None
    amc_vendor: str | None = Field(default=None, max_length=150)
    amc_end_date: str | None = None
    maintenance_status: str | None = None
    status: str | None = None
    coverage_radius_m: int | None = Field(default=None, ge=10, le=5000)
    metadata: dict | None = None

    @model_validator(mode="after")
    def check_coords(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        return self


class CameraOut(ORTIMixin):
    camera_id: str
    camera_code: str
    name: str
    department_id: str
    department_name: str | None = None
    site_id: str | None = None
    site_name: str | None = None
    camera_type: str
    ownership: str
    public_facing: bool
    vendor: str | None = None
    model: str | None = None
    ip_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    district: str | None = None
    taluka: str | None = None
    address: str | None = None
    connectivity_status: str
    last_seen_at: str | None = None
    storage_type: str | None = None
    retention_days: int | None = None
    install_date: str | None = None
    amc_vendor: str | None = None
    amc_end_date: str | None = None
    maintenance_status: str
    status: str
    coverage_radius_m: int | None = None
    metadata: dict | None = None
    created_at: str | None = None
    updated_at: str | None = None


VALID_CAMERA_TYPES = {"FIXED", "PTZ", "DOME", "BULLET", "ANPR"}
VALID_OWNERSHIP = {"GOVERNMENT", "PRIVATE"}
VALID_STORAGE = {"CLOUD", "LOCAL", "NVR", "NONE"}
VALID_CONN = {"ONLINE", "OFFLINE", "UNKNOWN"}
VALID_MAINT = {"OK", "DUE", "FAULTY"}
VALID_CAMERA_STATUS = {"ACTIVE", "PENDING_VALIDATION", "DECOMMISSIONED"}
