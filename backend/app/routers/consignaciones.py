from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin, get_barista_actor
from app.models.models import Usuario
from app.services import consignaciones as svc
from app.core.storage import upload_imagen

router = APIRouter(prefix="/consignaciones", tags=["consignaciones"])

@router.post("/")
async def registrar(
    tienda_id: int = Form(...),
    valor: float = Form(...),
    turno_id: Optional[int] = Form(None),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    ensure_tienda_access(user, tienda_id)
    imagen_url = await upload_imagen(imagen)
    return svc.registrar(db, tienda_id, valor, imagen_url, user.id, turno_id=turno_id,
                         barista_id=barista[0], barista_nombre=barista[1])

@router.get("/pendiente/{tienda_id}")
def pendiente(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_pendiente(db, tienda_id)


@router.get("/tienda/{tienda_id}")
def listar(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_por_tienda(db, tienda_id)

@router.get("/resumen-admin")
def resumen_admin(
    tienda_id: int | None = Query(None),
    desde: date | None = Query(None),
    hasta: date | None = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    if tienda_id:
        ensure_tienda_access(user, tienda_id)
    return svc.get_resumen_admin(db, tienda_id, desde=desde, hasta=hasta)


@router.patch("/{consignacion_id}/confirmar")
def confirmar(consignacion_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    return svc.confirmar(db, consignacion_id)


@router.delete("/{consignacion_id}")
def eliminar(consignacion_id: int, db: Session = Depends(get_db),
             user: Usuario = Depends(require_admin)):
    """Revierte una consignación registrada por error."""
    return svc.eliminar(db, consignacion_id, user.id)
