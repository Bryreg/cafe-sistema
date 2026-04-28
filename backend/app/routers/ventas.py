from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import ensure_turno_access, ensure_tienda_access, get_current_user
from app.models.models import Usuario
from app.schemas.ventas import RegistrarVentaRequest, VentaDiariaOut
from app.services import ventas as svc
from typing import List

router = APIRouter(prefix="/ventas", tags=["ventas"])


@router.post("/", response_model=VentaDiariaOut)
def registrar(data: RegistrarVentaRequest, db: Session = Depends(get_db),
              user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, data.tienda_id)
    return svc.registrar_venta(
        db, data.tienda_id, data.venta_total, data.nota_credito,
        data.vales, data.tarjetas, data.nota, user.id
    )


@router.get("/turno/{turno_id}", response_model=List[VentaDiariaOut])
def ventas_turno(turno_id: int, db: Session = Depends(get_db),
                 user: Usuario = Depends(get_current_user)):
    ensure_turno_access(db, user, turno_id)
    return svc.get_ventas_turno(db, turno_id)
