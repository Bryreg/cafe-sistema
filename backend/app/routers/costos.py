from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import get_barista_actor, require_admin
from app.database import get_db
from app.models.models import Usuario
from app.schemas.costos import (AdopcionEgresoRequest, ObligacionCreate,
                                ObligacionUpdate, PagoCreate)
from app.services import costos as svc

router = APIRouter(prefix="/costos", tags=["costos"])


@router.get("/categorias")
def listar_categorias(
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Catálogo de categorías activas (clave estable + nombre editable)."""
    return svc.listar_categorias(db)


@router.get("/agenda")
def agenda(
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    tienda_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Qué hay que pagar y cuándo: facturas de proveedor y costos fijos en UNA
    lista. Es la unión de dos consultas —la deuda con proveedores sigue viviendo
    solo en facturas_compra—, con el SALDO de cada ítem, no su total."""
    return svc.get_agenda(db, desde=desde, hasta=hasta, tienda_id=tienda_id)


@router.get("/obligaciones")
def listar_obligaciones(
    tienda_id: Optional[int] = Query(None, ge=1),
    solo_corporativas: bool = Query(False),
    categoria: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    campo_fecha: str = Query("devengo"),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Lo que le cuesta el negocio, con su saldo. Sin `tienda_id` trae TODO —las
    corporativas incluidas—; con `tienda_id` trae solo esa sede."""
    return svc.listar_obligaciones(
        db, tienda_id=tienda_id, solo_corporativas=solo_corporativas,
        categoria=categoria, estado=estado, desde=desde, hasta=hasta,
        campo_fecha=campo_fecha)


@router.post("/obligaciones")
def crear_obligacion(
    data: ObligacionCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Registra un costo. `tienda_id` en null = gasto CORPORATIVO (sin sede)."""
    return svc.crear_obligacion(db, data, admin.id,
                                barista_id=barista[0], barista_nombre=barista[1])


@router.patch("/obligaciones/{obligacion_id}")
def editar_obligacion(
    obligacion_id: int,
    data: ObligacionUpdate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    return svc.editar_obligacion(db, obligacion_id, data, admin.id)


@router.delete("/obligaciones/{obligacion_id}")
def anular_obligacion(
    obligacion_id: int,
    motivo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Baja LÓGICA: la saca de listados y totales sin borrar sus pagos."""
    return svc.anular_obligacion(db, obligacion_id, admin.id, motivo)


@router.get("/pagos")
def listar_pagos(
    obligacion_id: Optional[int] = Query(None, ge=1),
    factura_id: Optional[int] = Query(None, ge=1),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Qué plata salió y qué día — por fecha_pago, no por fecha de registro."""
    return svc.listar_pagos(db, obligacion_id=obligacion_id, factura_id=factura_id,
                            desde=desde, hasta=hasta)


@router.post("/pagos")
def registrar_pago(
    data: PagoCreate,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Un pago apunta a una obligación O a una factura, nunca a las dos.
    `fecha_pago` es obligatoria: es EL DÍA QUE SALIÓ LA PLATA."""
    return svc.registrar_pago(db, data, admin.id,
                              barista_id=barista[0], barista_nombre=barista[1])


@router.get("/egresos-sin-adoptar")
def listar_egresos_sin_adoptar(
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    tienda_id: Optional[int] = Query(None, ge=1),
    limite: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Egresos de caja que el P&L todavía muestra como texto libre. Solo lectura:
    no modifica nada, solo dice qué hay para categorizar. Sin `desde` toma los
    últimos 90 días."""
    return svc.listar_egresos_sin_adoptar(db, desde=desde, hasta=hasta,
                                          tienda_id=tienda_id, limite=limite)


@router.post("/egresos/{movimiento_id}/adoptar")
def adoptar_egreso(
    movimiento_id: int,
    data: AdopcionEgresoRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Convierte un egreso suelto en obligación devengada + pago espejo. El
    MovimientoCaja NO se toca: el turno cuadra igual y el total de gastos del
    período no se mueve — la plata solo cambia de bolsa.

    400 si el egreso es un pago a proveedor (ya está contado en Compras),
    409 si ya fue adoptado."""
    return svc.adoptar_egreso(db, movimiento_id, data.categoria_id, admin.id,
                              fecha_devengo=data.fecha_devengo,
                              concepto=data.concepto,
                              beneficiario=data.beneficiario, nota=data.nota,
                              barista_id=barista[0], barista_nombre=barista[1])


@router.delete("/pagos/{pago_id}")
def anular_pago(
    pago_id: int,
    motivo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Baja lógica del pago: la obligación vuelve sola al estado que corresponda."""
    return svc.anular_pago(db, pago_id, admin.id, motivo)
