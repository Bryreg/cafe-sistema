from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class InformeFilter:
    tienda_id: int
    fecha_desde: date
    fecha_hasta: date
    usuario_id: Optional[int] = None
    categoria: Optional[str] = None
    turno_id: Optional[int] = None
    producto_search: Optional[str] = None
    con_descuento: Optional[bool] = None
