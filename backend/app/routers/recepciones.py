"""Router de recepción de mercancía — borrador, items, confirmar (escribe stock)."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user, ensure_tienda_access
from app.models.models import Usuario
from app.services import recepciones as svc

router = APIRouter(prefix="/recepciones", tags=["recepciones"])


class RecepcionCreate(BaseModel):
    tienda_id: int
    proveedor: Optional[str] = None
    nota: Optional[str] = None


class ItemCreate(BaseModel):
    producto_id: int
    cantidad_recibida: float
    cantidad_factura: Optional[float] = None
    numero_lote: Optional[str] = None
    fecha_vencimiento: Optional[datetime] = None
    precio_unitario: Optional[float] = None


def _out(r):
    return {
        "id": r.id, "tienda_id": r.tienda_id, "proveedor": r.proveedor,
        "estado": r.estado.value if hasattr(r.estado, "value") else r.estado,
        "nota": r.nota, "fecha": r.fecha.isoformat() if r.fecha else None,
        "items": [
            {"id": i.id, "producto_id": i.producto_id,
             "cantidad_recibida": i.cantidad_recibida, "numero_lote": i.numero_lote}
            for i in r.items
        ],
    }


@router.post("", status_code=201)
def crear(data: RecepcionCreate, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    return _out(svc.crear(db, data.tienda_id, user.id, data.proveedor, data.nota))


@router.post("/{recepcion_id}/items", status_code=201)
def agregar_item(recepcion_id: int, data: ItemCreate,
                 db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    it = svc.agregar_item(db, recepcion_id, data.producto_id, data.cantidad_recibida,
                          data.cantidad_factura, data.numero_lote, data.fecha_vencimiento, data.precio_unitario)
    return {"id": it.id, "producto_id": it.producto_id, "cantidad_recibida": it.cantidad_recibida}


@router.post("/{recepcion_id}/confirmar")
def confirmar(recepcion_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return _out(svc.confirmar(db, recepcion_id, user.id))


@router.get("/sugerencias")
def sugerencias(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.sugerencias(db, tienda_id)


@router.get("")
def listar(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return [_out(r) for r in svc.listar(db, tienda_id)]
