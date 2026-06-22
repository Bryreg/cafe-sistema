import json
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin, get_barista_actor
from app.models.models import Usuario
from app.schemas.facturas import FacturaCreate
from app.services import facturas as svc
from app.core.storage import upload_imagen

router = APIRouter(prefix="/facturas", tags=["facturas"])


@router.post("/")
async def crear_factura(
    data: str = Form(...),
    imagen: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    barista: tuple = Depends(get_barista_actor),
):
    try:
        payload = FacturaCreate(**json.loads(data))
    except Exception as e:
        raise HTTPException(422, f"Datos inválidos: {e}")

    ensure_tienda_access(user, payload.tienda_id)

    imagen_url = await upload_imagen(imagen)
    return svc.crear_factura(db, payload, imagen_url, user.id,
                             barista_id=barista[0], barista_nombre=barista[1])


# Must be before /{factura_id} to avoid route conflict
@router.get("/proveedores/{tienda_id}")
def listar_proveedores(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    return svc.get_proveedores_tienda(db, tienda_id)


@router.get("/tienda/{tienda_id}")
def listar_facturas(
    tienda_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    ensure_tienda_access(user, tienda_id)
    return svc.get_facturas_tienda(db, tienda_id)


@router.get("/{factura_id}")
def detalle_factura(
    factura_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    factura = svc.get_factura(db, factura_id)
    ensure_tienda_access(user, factura["tienda_id"])
    return factura
