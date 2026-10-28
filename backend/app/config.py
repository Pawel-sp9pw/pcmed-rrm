from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PCMED_")

    database_url: str = "postgresql+psycopg://pcmed:invalid@localhost/pcmed"
    oidc_issuer: str = "https://rmm.example.test/realms/pcmed"
    oidc_jwks_url: str = "https://rmm.example.test/realms/pcmed/protocol/openid-connect/certs"
    oidc_audience: str = "pcmed-api"
    artifact_hosts: str = "packages.example.test"
    online_seconds: int = Field(default=90, ge=30, le=600)

    @field_validator("oidc_issuer")
    @classmethod
    def https_issuer(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("OIDC issuer must use HTTPS")
        return value.rstrip("/")


@lru_cache
def settings() -> Settings:
    return Settings()
