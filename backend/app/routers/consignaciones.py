from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin
from app.models.models import Usuario
from app.services import consignaciones as svc
from app.core.storage import upload_imagen

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
    imagen_url = await upload_imagen(imagen)
    return svc.registrar(db, tienda_id, valor, imagen_url, user.id)

@router.get("/pendiente/{tienda_id}")
def pendiente(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_pendiente(db, tienda_id)


@router.get("/tienda/{tienda_id}")
def listar(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_por_tienda(db, tienda_id)

@router.get("/resumen-admin")
def resumen_admin(db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    return svc.get_resumen_admin(db)


@router.patch("/{consignacion_id}/confirmar")
def confirmar(consignacion_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    return svc.confirmar(db, consignacion_id)
