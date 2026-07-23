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
    KIOSK_PIN: str = ""        # PIN para activar modo kiosko; vacío = deshabilitado
    # Escaneo de facturas (vision). Proveedor preferido: Groq (gratis DE VERDAD,
    # sin tarjeta ni proyecto con facturación — no tiene la trampa de Gemini).
    # Orden de preferencia: Groq → Gemini → Claude, según qué key esté puesta.
    # Sin ninguna key el endpoint responde 503 y el form sigue funcionando manual.
    GROQ_API_KEY: str = ""
    # Único modelo de visión vigente en Groq (2026-07; llama-4-scout fue
    # retirado). Es PREVIEW: si desaparece, el código prueba solo una cadena de
    # modelos alternativos (ver factura_ocr._modelos_groq).
    GROQ_MODEL: str = "qwen/qwen3.6-27b"
    GEMINI_API_KEY: str = ""
    # Si este modelo no tiene cuota gratis, el código prueba solo una cadena de
    # modelos Flash alternativos (ver factura_ocr._modelos_gemini).
    GEMINI_MODEL: str = "gemini-3.5-flash"
    ANTHROPIC_API_KEY: str = ""
    OCR_MODEL: str = "claude-opus-4-8"

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
        extra = "ignore"  # ignora variables de entorno sobrantes (ej. SIIGO_* viejas) sin tumbar el arranque

settings = Settings()
