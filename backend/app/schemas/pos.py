from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TicketItemRequest(BaseModel):
    producto_id: int
    cantidad: int


class TicketCreate(BaseModel):
    tienda_id: int
    items: List[TicketItemRequest]
    metodo_pago: str  # 'efectivo' | 'tarjeta' | 'mixto'
    descuento: Optional[float] = 0  # descuento libre por ticket
    efectivo_recibido: Optional[float] = None
    # Solo se usan cuando metodo_pago == 'mixto'
    monto_efectivo: Optional[float] = None
    monto_tarjeta: Optional[float] = None


class PrecioUpdate(BaseModel):
    precio_venta: float


class ProductoPOSOut(BaseModel):
    id: int
    nombre: str
    categoria: str
    precio_venta: float
    controla_stock: bool
    unidad_medida: str
    vendidos_7d: int = 0  # unidades vendidas últimos 7 días (para "Favoritos")


class TicketItemOut(BaseModel):
    id: int
    producto_id: int
    nombre_producto: str
    cantidad: int
    precio_unitario: float
    subtotal: float

    class Config:
        from_attributes = True


class TicketOut(BaseModel):
    id: int
    tienda_id: int
    caja_turno_id: int
    usuario_id: int
    fecha: datetime
    total: float
    descuento: float = 0
    metodo_pago: str
    monto_efectivo: float
    monto_tarjeta: float
    efectivo_recibido: Optional[float] = None
    cambio: Optional[float] = None
    estado: str
    items: List[TicketItemOut] = []

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Anulación de ticket
# ---------------------------------------------------------------------------

class TicketAnularRequest(BaseModel):
    motivo: Optional[str] = None


# ---------------------------------------------------------------------------
# Analytics (read-only, agregaciones sobre tickets reales)
# ---------------------------------------------------------------------------

class AnalyticsResumenOut(BaseModel):
    total_ventas: float
    n_tickets: int
    ticket_promedio: float
    total_efectivo: float
    total_tarjeta: float
    n_items: int


class ProductoTopOut(BaseModel):
    producto_id: int
    nombre_producto: str
    unidades: int
    total: float


class VentaPorHoraOut(BaseModel):
    hora: int          # 0-23
    n_tickets: int
    total: float


class VentaPorBaristaOut(BaseModel):
    usuario_id: int
    nombre: str
    total: float
    n_tickets: int
    ticket_promedio: float


class MetodoPagoOut(BaseModel):
    metodo_pago: str   # 'efectivo' | 'tarjeta' | 'mixto'
    n_tickets: int
    total: float
