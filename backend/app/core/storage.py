"""
Abstracción de almacenamiento de imágenes.
- Si CLOUDINARY_URL está configurado → sube a Cloudinary y devuelve URL pública.
- Si no → guarda en disco local (desarrollo) y devuelve ruta /uploads/<filename>.
"""
import os, uuid
from app.config import settings


async def upload_imagen(file) -> str | None:
    """Recibe un UploadFile de FastAPI y retorna la URL de la imagen guardada."""
    if not file or not file.filename:
        return None

    contenido = await file.read()
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"

    if settings.CLOUDINARY_URL:
        import cloudinary
        import cloudinary.uploader
        cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)
        result = cloudinary.uploader.upload(
            contenido,
            folder="cafe-sistema",
            public_id=str(uuid.uuid4()),
            resource_type="image",
        )
        return result["secure_url"]
    else:
        # Fallback local (desarrollo)
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        filename = f"{uuid.uuid4()}.{ext}"
        path = os.path.join(settings.UPLOAD_DIR, filename)
        with open(path, "wb") as f:
            f.write(contenido)
        return f"/uploads/{filename}"
