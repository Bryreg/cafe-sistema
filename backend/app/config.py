import os
from pydantic_settings import BaseSettings
from pydantic import field_validator

# El script de arranque establece ENV_FILE antes de iniciar el proceso
_env_file = os.getenv("ENV_FILE", ".env")

_PLACEHOLDER_PREFIXES = (
    "supersecretkey",
    "changeme",
    "change_in_production",
    "your_secret",
)

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./cafe_sistema.db"
    SECRET_KEY: str  # Required — no default; must be set in environment
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 240  # 4 hours (one full shift)
    ALGORITHM: str = "HS256"
    UPLOAD_DIR: str = "uploads"
    ENV: str = "development"
    CLOUDINARY_URL: str = ""   # cloudinary://api_key:api_secret@cloud_name
    SIIGO_USERNAME: str = ""
    SIIGO_ACCESS_KEY: str = ""
    SIIGO_PARTNER_ID: str = ""

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_be_set(cls, v: str) -> str:
        if not v or any(v.lower().startswith(p) for p in _PLACEHOLDER_PREFIXES):
            raise ValueError(
                "SECRET_KEY must be set in environment variables. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters long."
            )
        return v

    class Config:
        env_file = _env_file

settings = Settings()
