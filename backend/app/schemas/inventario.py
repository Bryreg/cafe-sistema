from pydantic import BaseModel
from typing import Optional, List  # noqa: F401
from datetime import datetime


class SiigoMapeoCreate(BaseModel):
    codigo_siigo: str
    descripcion_siigo: str = ""
    producto_id: int
    factor_conversion: float = 1.0
    activo: bool = True


class SiigoMapeoUpdate(BaseModel):
    factor_conversion: Optional[float] = None
    activo: Optional[bool] = None
    descripcion_siigo: Optional[str] = None


class SiigoMapeoOut(BaseModel):
    id: int
    codigo_siigo: str
    descripcion_siigo: str
    producto_id: int
    factor_conversion: float
    activo: bool
    producto_nombre: Optional[str] = None

    class Config:
        from_attributes = True


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

class StockMinimoUpdate(BaseModel):
    stock_minimo: float
