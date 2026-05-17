import os
from pydantic_settings import BaseSettings

# El script de arranque establece ENV_FILE antes de iniciar el proceso
_env_file = os.getenv("ENV_FILE", ".env")

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./cafe_sistema.db"
    SECRET_KEY: str = "supersecretkey_change_in_production_minimum32chars"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ALGORITHM: str = "HS256"
    UPLOAD_DIR: str = "uploads"
    ENV: str = "development"
    CLOUDINARY_URL: str = ""   # cloudinary://api_key:api_secret@cloud_name
    SIIGO_USERNAME: str = ""
    SIIGO_ACCESS_KEY: str = ""

    class Config:
        env_file = _env_file

settings = Settings()
