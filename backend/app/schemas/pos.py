from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TicketItemRequest(BaseModel):
    producto_id: int
    cantidad: int
    descuento: Optional[float] = 0  # descuento libre por producto (linea)


class ComboSeleccionRequest(BaseModel):
    grupo_id: int
    opcion_id: int


class TicketComboRequest(BaseModel):
    combo_id: int
    cantidad: int
    # Una selección por grupo. Los grupos de opción única se auto-seleccionan
    # en el servidor si no vienen (grupos fijos).
    selecciones: List[ComboSeleccionRequest] = []


class TicketCreate(BaseModel):
    tienda_id: int
    items: List[TicketItemRequest] = []
    combos: List[TicketComboRequest] = []
    metodo_pago: str  # 'efectivo' | 'tarjeta' | 'mixto'
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


class TicketItemComboSeleccionOut(BaseModel):
    nombre_grupo: str
    nombre_opcion: str
    producto_id: int
    cantidad: int

    class Config:
        from_attributes = True


class TicketItemOut(BaseModel):
    id: int
    producto_id: int
    nombre_producto: str
    cantidad: int
    precio_unitario: float
    subtotal: float
    descuento: float = 0
    # Solo líneas de combo: la combinación elegida (vacío en items normales).
    combo_selecciones: List[TicketItemComboSeleccionOut] = []

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


# ---------------------------------------------------------------------------
# Combos (precio fijo, grupos de opciones) — catálogo para el POS
# ---------------------------------------------------------------------------

class ComboOpcionProductoOut(BaseModel):
    producto_id: int
    nombre: str
    cantidad: int


class ComboOpcionOut(BaseModel):
    id: int
    nombre: str
    orden: int
    productos: List[ComboOpcionProductoOut] = []


class ComboGrupoOut(BaseModel):
    id: int
    nombre: str
    orden: int
    opciones: List[ComboOpcionOut] = []


class ComboOut(BaseModel):
    id: int
    nombre: str
    precio_venta: float
    orden: int
    grupos: List[ComboGrupoOut] = []
