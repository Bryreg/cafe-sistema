from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.core.tz import hoy_col
from app.database import get_db
from app.models.models import Producto, Usuario
from app.services import factura_ocr
from app.services import rentabilidad as svc

router = APIRouter(prefix="/rentabilidad", tags=["rentabilidad"])


class CostoInsumoIn(BaseModel):
    producto_id: int
    costo: Optional[float] = None  # None = limpiar el costo oficial (vuelve al promedio)


@router.post("/costo-insumo")
def set_costo_insumo(
    data: CostoInsumoIn,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Fija (o limpia) el costo OFICIAL por unidad de un insumo/producto. Este valor
    manda sobre el promedio de facturas en rentabilidad — así el costo confirmado a
    mano en el verificador no se ensucia con lecturas automáticas ruidosas."""
    p = db.query(Producto).filter(Producto.id == data.producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    if data.costo is not None and data.costo < 0:
        raise HTTPException(400, "El costo no puede ser negativo")
    p.precio_costo = data.costo
    db.commit()
    return {"producto_id": p.id, "nombre": p.nombre,
            "unidad_medida": p.unidad_medida, "precio_costo": p.precio_costo}


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
