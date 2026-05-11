from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class FacturaItemCreate(BaseModel):
    producto_id: int
    cantidad: float
    precio_unitario: Optional[float] = None
    numero_lote: Optional[str] = None
    fecha_vencimiento: Optional[datetime] = None


class FacturaCreate(BaseModel):
    tienda_id: int
    proveedor: str
    numero_factura: Optional[str] = None
    numero_lote: Optional[str] = None  # legacy — per-item takes precedence
    fecha_recibido: datetime
    valor_total: float
    tipo_pago: str  # contado | credito | transferencia
    items: List[FacturaItemCreate]


class FacturaItemOut(BaseModel):
    id: int
    producto_id: int
    producto_nombre: str
    unidad_medida: str
    cantidad: float
    precio_unitario: Optional[float]
    numero_lote: Optional[str]
    fecha_vencimiento: Optional[datetime]

    class Config:
        from_attributes = True


class FacturaOut(BaseModel):
    id: int
    tienda_id: int
    proveedor: str
    numero_factura: Optional[str]
    numero_lote: Optional[str]
    fecha_recibido: datetime
    valor_total: float
    tipo_pago: str
    imagen_url: Optional[str]
    fecha_registro: datetime
    usuario_nombre: str
    items: List[FacturaItemOut]

    class Config:
        from_attributes = True
