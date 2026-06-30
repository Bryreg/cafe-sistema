"""
Image upload with compression.
- Resizes to max 1280px on the longest side (never enlarges).
- Converts to JPEG at quality 75 before uploading.
- If CLOUDINARY_URL is set → uploads to Cloudinary and returns public URL.
- Otherwise → saves to local disk (development).
"""
import io
import os
import uuid

from app.config import settings


def _compress(data: bytes, max_side: int = 1280, quality: int = 75) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


async def upload_imagen(file, max_side: int = 1280, quality: int = 75) -> str | None:
    if not file or not file.filename:
        return None

    data = await file.read()
    data = _compress(data, max_side=max_side, quality=quality)

    if settings.CLOUDINARY_URL:
        import cloudinary
        import cloudinary.uploader

        cloudinary.config(cloudinary_url=settings.CLOUDINARY_URL)
        result = cloudinary.uploader.upload(
            data,
            folder="cafe-sistema",
            public_id=str(uuid.uuid4()),
            resource_type="image",
        )
        return result["secure_url"]

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4()}.jpg"
    with open(os.path.join(settings.UPLOAD_DIR, filename), "wb") as f:
        f.write(data)
    return f"/uploads/{filename}"
