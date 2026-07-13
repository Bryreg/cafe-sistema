from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.tz import hoy_col
from app.database import get_db
from app.models.models import Usuario
from app.services import factura_ocr
from app.services import rentabilidad as svc

router = APIRouter(prefix="/rentabilidad", tags=["rentabilidad"])


@router.get("/por-producto")
def rentabilidad_por_producto(
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Margen por producto: precio de venta vs costo de insumos (receta) o de
    compra (reventa), con las ventas de los últimos 30 días para priorizar."""
    return svc.get_rentabilidad_productos(db)


@router.post("/backfill-costos")
async def backfill_costos(
    limite: int = Query(2, ge=1, le=5),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Lee un lote de fotos de facturas YA registradas y rellena los costos por
    ítem que estén vacíos. Se llama repetidas veces hasta que no queden pendientes."""
    return await run_in_threadpool(
        factura_ocr.backfill_costos_facturas, db, admin.id, limite)


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
