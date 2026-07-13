from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.tz import hoy_col
from app.database import get_db
from app.models.models import Usuario
from app.services import rentabilidad as svc

router = APIRouter(prefix="/rentabilidad", tags=["rentabilidad"])


@router.get("/")
def rentabilidad(
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    tienda_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """P&L de caja: ventas vs compras de proveedor vs gastos operativos.
    Default: mes actual (Colombia)."""
    hoy = hoy_col()
    if not desde:
        desde = hoy.replace(day=1)
    if not hasta:
        hasta = hoy
    return svc.get_rentabilidad(db, desde, hasta, tienda_id)
