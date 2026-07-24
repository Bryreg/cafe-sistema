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
    # Escaneo de facturas (vision). Proveedor preferido: Gemini (schema
    # estructurado, imagen a resolución completa y free tier que sí aguanta una
    # lectura de visión). Groq quedó de RESPALDO: su tier gratis `on_demand`
    # limita a 8.000 tokens POR MINUTO (TPM) y una sola request de visión
    # (imagen + catálogo) supera ese tope → 429 garantizado aunque el modelo
    # exista (visto en producción 2026-07 con el primer escaneo real).
    # Orden de preferencia: Gemini → Groq → Claude, según qué key esté puesta.
    # Sin ninguna key el endpoint responde 503 y el form sigue funcionando manual.
    GROQ_API_KEY: str = ""
    # Único modelo de visión vigente en Groq (2026-07; llama-4-scout fue
    # retirado). Es PREVIEW: si desaparece, el código prueba solo una cadena de
    # modelos alternativos (ver factura_ocr._modelos_groq).
    GROQ_MODEL: str = "qwen/qwen3.6-27b"
    GEMINI_API_KEY: str = ""
    # Si este modelo no tiene cuota gratis, el código prueba solo una cadena
    # CORTA de modelos verificados vivos (ver factura_ocr._modelos_gemini; los
    # nombres se verifican contra v1beta ListModels — un nombre muerto da 404).
    # 2026-07-23: default bajado de gemini-3.5-flash a 3.6-flash — el 3.5
    # respondió 503 "high demand" PERSISTENTE (toda una noche y una mañana,
    # no un pico) y gemini-2.5-flash murió con 404 "no longer available to
    # new users". 3.6-flash es el flash más nuevo con generateContent en el
    # ListModels de la key de producción.
    GEMINI_MODEL: str = "gemini-3.6-flash"
    ANTHROPIC_API_KEY: str = ""
    # 2026-07-24: default bajado de claude-opus-4-8 a Haiku (el económico):
    # para extraer renglones de facturas con schema alcanza de sobra y cuesta
    # centavos por foto. Claude es el RESCATE pago de la cascada (Gemini gratis
    # va primero); con ANTHROPIC_API_KEY en Render se activa solo. Para más
    # calidad: OCR_MODEL=claude-sonnet-5 como env var, sin tocar código.
    OCR_MODEL: str = "claude-haiku-4-5-20251001"

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
