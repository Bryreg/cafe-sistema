from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from app.database import get_db
from app.core.deps import require_admin, ensure_tienda_access
from app.core.storage import upload_imagen
from app.models.models import Usuario
from app.services import mantenimientos as svc

router = APIRouter(prefix="/mantenimientos", tags=["mantenimientos"])


@router.post("/")
async def crear(
    tienda_id: int = Form(...),
    tipo: str = Form(...),
    titulo: str = Form(...),
    fecha_realizado: datetime = Form(...),
    descripcion: Optional[str] = Form(None),
    costo: Optional[float] = Form(None),
    tecnico: Optional[str] = Form(None),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    imagen_url = await upload_imagen(imagen)
    return svc.crear(
        db, tienda_id=tienda_id, usuario_id=user.id, tipo=tipo,
        titulo=titulo, fecha_realizado=fecha_realizado,
        descripcion=descripcion, costo=costo, tecnico=tecnico, imagen_url=imagen_url,
    )


@router.get("/")
def listar(
    tienda_id: int = Query(...),
    tipo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.listar(db, tienda_id, tipo)


@router.delete("/{mantenimiento_id}")
def eliminar(
    mantenimiento_id: int,
    tienda_id: int = Query(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    ensure_tienda_access(user, tienda_id)
    return svc.eliminar(db, mantenimiento_id, tienda_id)
