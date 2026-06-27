"""Router del Dashboard Ejecutivo (Módulo 7).

Solo expone los 3 agregados que no existen en otros endpoints.
El resto del dashboard (ventas, ranking productos, compras, alertas, etc.)
consume directamente los endpoints ya existentes desde el frontend.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import require_admin
from app.models.models import Usuario
from app.services import dashboard_ejecutivo as svc

router = APIRouter(prefix="/dashboard-ejecutivo", tags=["dashboard-ejecutivo"])


@router.get("/ventas-por-sede")
def ventas_por_sede(
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Σ ventas y n_tickets por tienda activa en el rango (default = hoy)."""
    return svc.ventas_por_sede(db, fecha_desde, fecha_hasta)


@router.get("/ventas-por-categoria")
def ventas_por_categoria(
    fecha_desde: Optional[date] = Query(None),
    fecha_hasta: Optional[date] = Query(None),
    tienda_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Σ importe y unidades por categoría de producto. tienda_id opcional."""
    return svc.ventas_por_categoria(db, fecha_desde, fecha_hasta, tienda_id)


@router.get("/inventario-valorizado")
def inventario_valorizado(
    tienda_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Valor del inventario a precio de venta, por sede y por categoría. tienda_id opcional."""
    return svc.inventario_valorizado(db, tienda_id)
