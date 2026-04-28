from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class SolicitudPedidoItemRequest(BaseModel):
    producto_id: int
    cantidad_solicitada: float


class CrearSolicitudPedidoRequest(BaseModel):
    tienda_id: int
    nota: Optional[str] = None
    items: List[SolicitudPedidoItemRequest]


class SolicitudPedidoItemOut(BaseModel):
    id: int
    producto_id: int
    cantidad_solicitada: float
    nombre: str = ""
    unidad_medida: str = ""
    class Config: from_attributes = True


class SolicitudPedidoOut(BaseModel):
    id: int
    tienda_id: int
    fecha_solicitud: datetime
    estado: str
    nota: Optional[str]
    items: List[SolicitudPedidoItemOut]
    class Config: from_attributes = True


class AprobarSencillaRequest(BaseModel):
    detalle: Optional[str] = None        # desglose ajustado por el admin
    monto_solicitado: Optional[float] = None  # monto ajustado


class CrearSolicitudSencillaRequest(BaseModel):
    tienda_id: int
    monto_solicitado: float
    motivo: str
    detalle: Optional[str] = None  # JSON serializado desde el frontend


class SolicitudSencillaOut(BaseModel):
    id: int
    tienda_id: int
    fecha_solicitud: datetime
    estado: str
    monto_solicitado: float
    motivo: str
    detalle: Optional[str] = None
    class Config: from_attributes = True
