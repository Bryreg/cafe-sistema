from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class AbrirCajaRequest(BaseModel):
    tienda_id: int
    base_real: float
    justificacion_apertura: Optional[str] = None


class CerrarCajaRequest(BaseModel):
    efectivo_final_real: float          # total contado en caja (base + ventas efectivo)
    datafono_real: Optional[float] = None  # total datáfono Bold
    justificacion_cierre: Optional[str] = None


class MovimientoCajaRequest(BaseModel):
    tipo: str  # ingreso | egreso
    concepto: str
    valor: float


class MovimientoCajaOut(BaseModel):
    id: int
    tipo: str
    concepto: str
    valor: float
    fecha: datetime
    imagen_url: Optional[str] = None
    class Config: from_attributes = True


class EntregaTurnoOut(BaseModel):
    id: int
    turno_id: int
    tienda_id: int
    usuario_id: int
    fecha_hora: datetime
    efectivo_esperado: float
    efectivo_real: float
    ventas_efectivo_siigo: float
    ventas_tarjeta_bold: float
    diferencia_efectivo: float
    diferencia_tarjeta: float
    imagen_url: Optional[str]
    tipo: str = "entrega"
    class Config: from_attributes = True


class TurnoOut(BaseModel):
    id: int
    tienda_id: int
    fecha_apertura: datetime
    fecha_cierre: Optional[datetime]
    base_sistema: float
    base_real: float
    diferencia_apertura: float
    justificacion_apertura: Optional[str]
    total_ventas: float
    total_efectivo: float
    total_tarjeta: float
    ingresos_movimientos: float = 0.0
    egresos_movimientos: float = 0.0
    efectivo_esperado_actual: float = 0.0
    efectivo_final_real: Optional[float]
    datafono_real: Optional[float]
    diferencia_cierre: Optional[float]
    diferencia_tarjeta: Optional[float]
    justificacion_cierre: Optional[str]
    estado: str
    tiene_conteo_apertura: bool
    tiene_ventas: bool
    tiene_conteo_cierre: bool
    ultima_entrega_fecha: Optional[datetime] = None
    ultima_entrega_diferencia_efectivo: Optional[float] = None
    class Config: from_attributes = True
