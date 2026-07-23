from typing import List, Optional
from datetime import date
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.deps import get_current_user, require_admin, ensure_tienda_access, get_barista_actor
from app.models.models import Usuario
from app.schemas.pos import (
    TicketCreate, PrecioUpdate, ProductoPOSOut, TicketOut,
    TicketAnularRequest, AnalyticsResumenOut, ProductoTopOut,
    VentaPorHoraOut, VentaPorBaristaOut, MetodoPagoOut, ComboOut,
)
from app.services import pos as svc
from app.services import notas_credito as nc_svc


class NotaCreditoItemIn(BaseModel):
    producto_usado: bool
    # Por LÍNEA del ticket (TicketItemOut.id): dos líneas del mismo combo
    # comparten producto_id (sombra) y se marcan independiente por item_id.
    item_id: Optional[int] = None
    # Compat con payloads viejos: indexado por producto (aplica a sus líneas).
    producto_id: Optional[int] = None


class RevertirRequest(BaseModel):
    motivo: str
    items: List[NotaCreditoItemIn] = []

router = APIRouter(prefix="/pos", tags=["pos"])


@router.get("/productos", response_model=List[ProductoPOSOut])
def productos(categoria: Optional[str] = None, db: Session = Depends(get_db),
              user: Usuario = Depends(get_current_user)):
    return svc.get_productos_pos(db, categoria)


@router.get("/combos", response_model=List[ComboOut])
def combos_disponibles(tienda_id: int, db: Session = Depends(get_db),
                       user: Usuario = Depends(get_current_user)):
    """Combos activos disponibles en la tienda (con grupos, opciones y productos).
    El POS los usa para pintar las pestañas y el selector de combo."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_combos_pos(db, tienda_id)


@router.post("/ticket", response_model=TicketOut, status_code=201)
def crear_ticket(data: TicketCreate, db: Session = Depends(get_db),
                 user: Usuario = Depends(get_current_user),
                 barista: tuple = Depends(get_barista_actor)):
    ensure_tienda_access(user, data.tienda_id)
    ticket = svc.crear_ticket(
        db,
        tienda_id=data.tienda_id,
        usuario_id=user.id,
        items=[i.dict() for i in data.items],
        metodo_pago=data.metodo_pago,
        efectivo_recibido=data.efectivo_recibido,
        monto_efectivo=data.monto_efectivo,
        monto_tarjeta=data.monto_tarjeta,
        barista_id=barista[0], barista_nombre=barista[1],
        combos=[c.dict() for c in data.combos],
    )
    return ticket


@router.get("/ticket/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    ticket = svc.get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    ensure_tienda_access(user, ticket.tienda_id)
    return ticket


@router.get("/tickets", response_model=List[TicketOut])
def tickets_turno(turno_id: int, db: Session = Depends(get_db),
                  user: Usuario = Depends(get_current_user)):
    return svc.get_tickets_turno(db, turno_id)


@router.get("/tickets/recientes", response_model=List[TicketOut])
def tickets_recientes(tienda_id: int, dias: int = 7, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_admin)):
    """Tickets recientes de la tienda para revertir (Nota Crédito). Solo admin."""
    return svc.get_tickets_recientes(db, tienda_id, dias)


@router.get("/tickets/historial", response_model=List[TicketOut])
def tickets_historial(tienda_id: int, fecha_desde: Optional[date] = Query(None),
                      fecha_hasta: Optional[date] = Query(None),
                      db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    """Historial de ventas (tickets individuales) en un rango.

    Accesible para la barista (Historial de Ventas del Panel de Turno), scopeado a SU
    tienda; el admin puede consultar cualquier sede."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_tickets_historial(db, tienda_id, fecha_desde, fecha_hasta)


@router.patch("/productos/{producto_id}/precio", response_model=ProductoPOSOut)
def set_precio(producto_id: int, data: PrecioUpdate, db: Session = Depends(get_db),
               user: Usuario = Depends(require_admin)):
    prod = svc.set_precio(db, producto_id, data.precio_venta)
    return ProductoPOSOut(
        id=prod.id,
        nombre=prod.nombre,
        categoria=prod.categoria.value,
        precio_venta=prod.precio_venta or 0.0,
        controla_stock=prod.controla_stock,
        unidad_medida=prod.unidad_medida,
    )


# ---------------------------------------------------------------------------
# Anulación de ticket
# ---------------------------------------------------------------------------

@router.post("/ticket/{ticket_id}/anular", response_model=TicketOut)
def anular_ticket(ticket_id: int, data: TicketAnularRequest = TicketAnularRequest(),
                  db: Session = Depends(get_db),
                  user: Usuario = Depends(require_admin)):
    ticket = svc.anular_ticket(db, ticket_id, usuario_id=user.id, motivo=data.motivo)
    return ticket


@router.post("/ticket/{ticket_id}/revertir", status_code=201)
def revertir_ticket(ticket_id: int, data: RevertirRequest,
                    db: Session = Depends(get_db),
                    user: Usuario = Depends(require_admin)):
    """Nota Crédito: revierte la venta. Por línea del ticket, producto_usado decide
    si el inventario lo recupera (False = vuelve al conteo) o no (True = se consumió)."""
    items_usado = {i.item_id: i.producto_usado for i in data.items if i.item_id is not None}
    usado_por_producto = {i.producto_id: i.producto_usado
                          for i in data.items if i.item_id is None and i.producto_id is not None}
    nota = nc_svc.revertir_venta(db, ticket_id, user.id, data.motivo,
                                 items_usado, usado_por_producto)
    return {
        "id": nota.id, "ticket_id": nota.ticket_id,
        "valor_revertido": nota.valor_revertido,
        "fecha": nota.fecha.isoformat() if nota.fecha else None,
    }


# ---------------------------------------------------------------------------
# Analytics (read-only, admin) — agregaciones sobre tickets reales del POS.
# Rango de fechas opcional (default = hoy) y tienda_id opcional.
# ---------------------------------------------------------------------------

@router.get("/analytics/resumen", response_model=AnalyticsResumenOut)
def analytics_resumen(fecha_desde: Optional[date] = Query(None),
                      fecha_hasta: Optional[date] = Query(None),
                      tienda_id: Optional[int] = Query(None),
                      db: Session = Depends(get_db),
                      user: Usuario = Depends(require_admin)):
    return svc.get_analytics_resumen(db, fecha_desde, fecha_hasta, tienda_id)


@router.get("/analytics/contador")
def analytics_contador(anio: int = Query(...), mes: int = Query(...),
                       tienda_id: Optional[int] = Query(None),
                       db: Session = Depends(get_db),
                       user: Usuario = Depends(require_admin)):
    """Informe Contador: consolidado contable diario/mensual por método de pago."""
    return svc.get_informe_contador(db, anio, mes, tienda_id)


@router.get("/analytics/productos-top", response_model=List[ProductoTopOut])
def analytics_productos_top(fecha_desde: Optional[date] = Query(None),
                            fecha_hasta: Optional[date] = Query(None),
                            tienda_id: Optional[int] = Query(None),
                            db: Session = Depends(get_db),
                            user: Usuario = Depends(require_admin)):
    return svc.get_analytics_productos_top(db, fecha_desde, fecha_hasta, tienda_id)


@router.get("/analytics/ventas-por-hora", response_model=List[VentaPorHoraOut])
def analytics_ventas_por_hora(fecha_desde: Optional[date] = Query(None),
                              fecha_hasta: Optional[date] = Query(None),
                              tienda_id: Optional[int] = Query(None),
                              db: Session = Depends(get_db),
                              user: Usuario = Depends(require_admin)):
    return svc.get_analytics_ventas_por_hora(db, fecha_desde, fecha_hasta, tienda_id)


@router.get("/analytics/por-barista", response_model=List[VentaPorBaristaOut])
def analytics_por_barista(fecha_desde: Optional[date] = Query(None),
                          fecha_hasta: Optional[date] = Query(None),
                          tienda_id: Optional[int] = Query(None),
                          db: Session = Depends(get_db),
                          user: Usuario = Depends(require_admin)):
    return svc.get_analytics_por_barista(db, fecha_desde, fecha_hasta, tienda_id)


@router.get("/analytics/metodo-pago", response_model=List[MetodoPagoOut])
def analytics_metodo_pago(fecha_desde: Optional[date] = Query(None),
                          fecha_hasta: Optional[date] = Query(None),
                          tienda_id: Optional[int] = Query(None),
                          db: Session = Depends(get_db),
                          user: Usuario = Depends(require_admin)):
    return svc.get_analytics_metodo_pago(db, fecha_desde, fecha_hasta, tienda_id)
