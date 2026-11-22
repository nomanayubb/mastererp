from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="UEOS_", env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str = ""  # app role (non-owner, subject to RLS)
    owner_database_url: str = ""  # migrations only
    jwt_secret: str = "dev-only-change-me-dev-only-change-me"
    access_ttl_minutes: int = 15
    refresh_ttl_days: int = 14
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    min_password_length: int = 12

    def validate_for_runtime(self) -> None:
        if self.env != "dev" and self.jwt_secret.startswith("dev-only"):
            raise RuntimeError("UEOS_JWT_SECRET must be set outside dev")


@lru_cache
def get_settings() -> Settings:
    return Settings()
