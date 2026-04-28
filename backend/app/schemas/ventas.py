from pydantic import BaseModel, validator
from typing import Optional
from datetime import datetime


class RegistrarVentaRequest(BaseModel):
    tienda_id: int
    venta_total: float
    nota_credito: float = 0.0
    vales: float = 0.0
    tarjetas: float = 0.0
    nota: Optional[str] = None

    @validator("venta_total")
    def venta_mayor_cero(cls, v):
        if v <= 0:
            raise ValueError("venta_total debe ser mayor a 0")
        return v


class VentaDiariaOut(BaseModel):
    id: int
    tienda_id: int
    turno_id: int
    venta_total: float
    nota_credito: float
    vales: float
    tarjetas: float
    efectivo_calculado: float
    fecha_registro: datetime
    nota: Optional[str]
    class Config: from_attributes = True
