from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import date
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user
from app.models.models import Usuario
from app.schemas.pasteleria import PasteleriaRequest
from app.services import pasteleria as svc
from typing import Optional

router = APIRouter(prefix="/pasteleria", tags=["pasteleria"])

@router.post("/")
def registrar(data: PasteleriaRequest, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    return svc.registrar(db, data.tienda_id, data.producto_id, data.cantidad, data.fecha_frescura, user.id)

@router.get("/tienda/{tienda_id}/activos")
def activos(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_activos(db, tienda_id)

@router.patch("/{lote_id}/cerrar")
def cerrar(lote_id: int, tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.cerrar_lote(db, lote_id, tienda_id)

@router.get("/tienda/{tienda_id}")
def por_fecha(tienda_id: int, fecha: Optional[date] = None, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    from datetime import date as d
    ensure_tienda_access(user, tienda_id)
    return svc.get_por_fecha(db, tienda_id, fecha or d.today())
