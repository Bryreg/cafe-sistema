from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class AbrirCajaRequest(BaseModel):
    tienda_id: int
    # None = cuadre diferido (flujo actual): el efectivo se cuenta después del conteo
    # de inventario vía POST /caja/{id}/cuadre-inicial. Con valor = cuadre al abrir (legacy).
    base_real: Optional[float] = None
    caja_fuerte: Optional[float] = None  # reserva fija aparte, no entra en el cuadre
    tipo_turno: Optional[str] = None
    justificacion_apertura: Optional[str] = None
    barista_ids: Optional[List[int]] = None


class AjustarAperturaRequest(BaseModel):
    base_real: float                      # efectivo real de la registradora al abrir
    caja_fuerte: Optional[float] = None   # reserva fija aparte
    motivo: Optional[str] = None


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
    ventas_tarjeta_bold: float
    diferencia_efectivo: float
    diferencia_tarjeta: float
    base_snapshot: Optional[float] = None
    ventas_efectivo_snapshot: Optional[float] = None
    ingresos_snapshot: Optional[float] = None
    egresos_snapshot: Optional[float] = None
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
    caja_fuerte: Optional[float] = None
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
    tipo_turno: Optional[str] = None
    usuario_apertura_id: Optional[int] = None
    tiene_conteo_apertura: bool
    tiene_cuadre_llegada: bool = False
    tiene_ventas: bool
    tiene_conteo_cierre: bool
    es_operativo: bool = False
    dia_tiene_conteo_apertura: bool = False
    ts_conteo_apertura: Optional[datetime] = None
    ts_conteo_cierre: Optional[datetime] = None
    ultima_entrega_fecha: Optional[datetime] = None
    ultima_entrega_diferencia_efectivo: Optional[float] = None
    consignaciones_turno: float = 0.0
    consignaciones_deducidas: Optional[float] = None
    baristas: List[str] = []
    baristas_salidas: List[str] = []
    class Config: from_attributes = True


class TurnoHistorialItem(BaseModel):
    id: int
    fecha_apertura: datetime
    fecha_cierre: Optional[datetime] = None
    estado: str
    tipo_turno: Optional[str] = None
    total_ventas: float = 0
    total_efectivo: float = 0
    total_tarjeta: float = 0
    base_real: float = 0
    efectivo_final_real: Optional[float] = None
    datafono_real: Optional[float] = None
    diferencia_apertura: float = 0
    diferencia_cierre: Optional[float] = None
    diferencia_tarjeta: Optional[float] = None
    tiene_conteo_cierre: bool = False
    baristas: List[str] = []
    imagen_cierre_url: Optional[str] = None
    class Config: from_attributes = True


class MovimientoFlujoItem(BaseModel):
    tipo: str  # "ingreso" | "egreso"
    concepto: str
    valor: float


class ConsignacionFlujoItem(BaseModel):
    id: int
    valor: float
    fecha: str  # ISO date string


class FlujoCajaOut(BaseModel):
    turno_id: int
    barista: str
    fecha_apertura: str
    base_real: float
    ventas_total: float
    ventas_efectivo: float
    ventas_tarjeta: float
    movimientos: List[MovimientoFlujoItem]
    consignaciones: List[ConsignacionFlujoItem]
    efectivo_esperado: float
    efectivo_final_real: Optional[float]
    diferencia_cierre: Optional[float]
