from pydantic import BaseModel
from typing import List

class AlertaItem(BaseModel):
    tipo: str
    mensaje: str
    nivel: str  # critico | advertencia | info

class DashboardOut(BaseModel):
    tienda_id: int
    tienda_nombre: str
    ventas_dia: float
    estado_caja: str  # cuadrado | diferencia | sin_turno
    diferencia_caja: float
    productos_criticos: int
    consignaciones_pendientes: int
    cumplimiento_checklist: float
    alertas: List[AlertaItem]
