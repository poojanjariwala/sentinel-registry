from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://sentinel:sentinel@localhost:5432/sentinel_registry"
    jwt_secret: str = "dev-only-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    cors_origins: str = "http://localhost:5173"
    seed_demo_data: bool = True
    log_level: str = "info"

    # Module 2
    enable_module2_workers: bool = True
    sentinel_api_base: str = ""  # e.g. http://<sandbox-host> for /api/ingest catalogue
    sentinel_hls_base: str = "http://web/hls/cam1"  # local mediagen (compose network)

    # Real Gujarat Police feeds (Sentinel Camera Grid, password-gated HLS origin)
    grid_base_url: str = ""  # e.g. https://cctv.corp8.cloud
    grid_email: str = ""
    grid_password: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
