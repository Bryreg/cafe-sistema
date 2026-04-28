from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
import os, uuid
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin
from app.models.models import Usuario
from app.services import consignaciones as svc
from app.config import settings

router = APIRouter(prefix="/consignaciones", tags=["consignaciones"])

@router.post("/")
async def registrar(
    tienda_id: int = Form(...),
    valor: float = Form(...),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user)
):
    ensure_tienda_access(user, tienda_id)
    imagen_url = None
    if imagen and imagen.filename:
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        parts = imagen.filename.rsplit(".", 1)
        ext = parts[1].lower() if len(parts) == 2 else "jpg"
        filename = f"{uuid.uuid4()}.{ext}"
        path = os.path.join(settings.UPLOAD_DIR, filename)
        with open(path, "wb") as f:
            f.write(await imagen.read())
        imagen_url = f"/uploads/{filename}"
    return svc.registrar(db, tienda_id, valor, imagen_url, user.id)

@router.get("/tienda/{tienda_id}")
def listar(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_por_tienda(db, tienda_id)

@router.patch("/{consignacion_id}/confirmar")
def confirmar(consignacion_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    return svc.confirmar(db, consignacion_id)
