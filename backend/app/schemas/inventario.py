from pydantic import BaseModel
from typing import Optional, List  # noqa: F401
from datetime import datetime


class MovimientoInvRequest(BaseModel):
    producto_id: int
    tienda_id: int
    tipo: str  # entrada | salida | ajuste
    cantidad: float
    motivo: Optional[str] = None

class ProductoCreate(BaseModel):
    nombre: str
    categoria: str   # pasteleria | bebida | insumo
    unidad_medida: str
    controla_stock: bool = True

class ProductoUpdate(BaseModel):
    nombre: Optional[str] = None
    categoria: Optional[str] = None
    unidad_medida: Optional[str] = None
    controla_stock: Optional[bool] = None
    lead_time_dias: Optional[int] = None
    proveedor: Optional[str] = None
    incluir_en_conteo: Optional[bool] = None
    fraccionable: Optional[bool] = None
    envase: Optional[str] = None  # "" (quitar) | "bolsa" | "botella"
    contenido_por_unidad: Optional[float] = None  # gr por unidad sellada (0 = quitar)
    orden_conteo: Optional[int] = None            # posición fija en el conteo (-1 = quitar)
    grupo_conteo: Optional[str] = None            # "" (normal) | "desechables"
    sustituto_id: Optional[int] = None            # producto de reserva (0 = quitar)
    contenido_por_empaque: Optional[float] = None # gr/ml por empaque comercial (0 = quitar)

class InsumoRecetaItem(BaseModel):
    insumo_id: int
    cantidad: float

class InsumosProductoUpdate(BaseModel):
    items: list[InsumoRecetaItem]

class DesechablesProductoUpdate(BaseModel):
    """Receta de desechables (solo costeo de rentabilidad, no toca inventario)."""
    items: list[InsumoRecetaItem]

class PreparacionRequest(BaseModel):
    producto_id: int
    tienda_id: int
    cantidad: float = 1  # tandas preparadas (0.5 = media tanda)

class StockMinimoUpdate(BaseModel):
    stock_minimo: float

class UmbralesStockUpdate(BaseModel):
    stock_minimo: Optional[float] = None
    stock_ideal: Optional[float] = None
    stock_critico: Optional[float] = None
