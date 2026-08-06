import math
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_barista_actor, require_admin
from app.core.tz import hoy_col
from app.database import get_db
from app.models.models import Usuario
from app.schemas.costos import (AdopcionEgresoRequest, ObligacionCreate,
                                ObligacionUpdate, PagoCreate, SaldoBancoRequest)
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


@router.get("/flujo")
def flujo_proyectado(
    dias: int = Query(svc.HORIZONTE_DEFAULT, ge=1, le=svc.HORIZONTE_MAX),
    tienda_id: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """El día en que se acaba la plata, ANTES de que pase.

    Serie diaria de saldo proyectado = efectivo en caja + saldo del banco
    declarado, más la venta esperada (MEDIANA por día de semana) y menos lo que
    hay que pagar. `punto_de_quiebre` es el primer día en negativo, o null.

    Con `tienda_id` la proyección es SOLO de esa sede: el saldo del banco (que es
    de la empresa) no suma y las obligaciones corporativas quedan fuera, declaradas
    en `advertencias`. `advertencias` también dice cuándo faltan datos para que la
    respuesta signifique algo — un null en `punto_de_quiebre` no es un all-clear si
    nadie cargó las salidas."""
    return svc.get_flujo_proyectado(db, dias=dias, tienda_id=tienda_id)


@router.post("/saldo-banco")
def declarar_saldo_banco(
    data: SaldoBancoRequest,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """Declara cuánta plata hay en el banco. Es un dato del dueño: el sistema
    registra consignaciones, nunca un saldo bancario, así que no puede derivarlo.

    La validación va acá y NO en el schema (mismo patrón que la meta de ventas en
    routers/auth.py): con Field(ge=..) el valor rechazado vuelve dentro del cuerpo
    del 422 y un `inf` no es serializable a JSON — la respuesta de error revienta.
    El saldo además se persiste como TEXTO: un inf/NaN guardado rompería toda
    lectura futura, no solo esta escritura.
    """
    if not math.isfinite(data.saldo):
        raise HTTPException(400, "El saldo del banco debe ser un número válido")
    if data.saldo < 0:
        raise HTTPException(400, "El saldo del banco no puede ser negativo")
    if data.saldo > svc.SALDO_BANCO_MAX:
        raise HTTPException(400, "El saldo del banco es demasiado grande")
    fecha = data.fecha or hoy_col()
    if fecha > hoy_col():
        raise HTTPException(400, "La fecha del saldo no puede ser futura")
    return svc.guardar_saldo_banco(db, data.saldo, fecha, admin.id)


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


@router.post("/obligaciones/{obligacion_id}/repetir")
def repetir_obligacion(
    obligacion_id: int,
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
    barista: tuple = Depends(get_barista_actor),
):
    """Crea la copia del MES SIGUIENTE de este costo (devengo y vencimiento +1 mes,
    con el día recortado al último real del mes). No es un scheduler: lo dispara
    el dueño y la copia queda editable.

    Idempotente por serie y mes: repetir dos veces devuelve la misma obligación
    con `ya_existia: true` en vez de cobrar el arriendo dos veces."""
    return svc.repetir_obligacion(db, obligacion_id, admin.id,
                                  barista_id=barista[0], barista_nombre=barista[1])


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
