from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime


class CategoriaOut(BaseModel):
    id: int
    clave: str
    nombre: str
    grupo: str
    orden: Optional[int] = None

    class Config:
        from_attributes = True


class ObligacionCreate(BaseModel):
    categoria_id: int
    concepto: str
    monto: float
    # A qué mes pertenece el costo en el P&L. Obligatoria: una obligación sin
    # devengo no se puede ubicar en el tiempo.
    fecha_devengo: date
    # None = gasto CORPORATIVO (arriendo, nómina): no pertenece a ninguna sede.
    tienda_id: Optional[int] = None
    beneficiario: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
    recurrencia: Optional[str] = None   # mensual | quincenal | semanal (metadata en Fase 1)
    nota: Optional[str] = None
    imagen_url: Optional[str] = None


class ObligacionUpdate(BaseModel):
    """Todos los campos opcionales: el PATCH solo pisa lo que llega.
    tienda_id no se puede distinguir de "no enviado" con Optional a secas, así que
    el servicio usa el conjunto de campos realmente presentes (exclude_unset)."""
    categoria_id: Optional[int] = None
    concepto: Optional[str] = None
    monto: Optional[float] = None
    fecha_devengo: Optional[date] = None
    tienda_id: Optional[int] = None
    beneficiario: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
    recurrencia: Optional[str] = None
    nota: Optional[str] = None
    imagen_url: Optional[str] = None


class PagoCreate(BaseModel):
    monto: float
    # EL DÍA QUE SALIÓ LA PLATA. Obligatoria a nivel schema (falta → 422): es el
    # dato que hace útil a todo el módulo.
    fecha_pago: date
    metodo: str = "transferencia"   # efectivo|transferencia|tarjeta|cheque|otro
    # Exactamente uno de los dos (lo valida el servicio, no el schema, para poder
    # devolver un 400 con un mensaje entendible en vez de un 422 de pydantic).
    obligacion_id: Optional[int] = None
    factura_id: Optional[int] = None
    imagen_soporte_url: Optional[str] = None
    nota: Optional[str] = None


class PagoOut(BaseModel):
    id: int
    obligacion_id: Optional[int]
    factura_id: Optional[int]
    tienda_id: Optional[int]
    monto: float
    fecha_pago: date
    metodo: str
    imagen_soporte_url: Optional[str]
    nota: Optional[str]
    anulado: bool
    fecha_registro: Optional[datetime]

    class Config:
        from_attributes = True


class ObligacionOut(BaseModel):
    id: int
    tienda_id: Optional[int]
    tienda_nombre: Optional[str]
    categoria_id: int
    categoria_clave: str
    categoria_nombre: str
    categoria_grupo: str
    concepto: str
    beneficiario: Optional[str]
    monto: float
    # Derivados de la suma de pagos vivos — NO hay columna valor_pagado.
    pagado: float
    saldo: float
    estado: str            # pendiente | parcial | pagada | anulada
    fecha_devengo: date
    fecha_vencimiento: Optional[date]
    recurrencia: Optional[str]
    nota: Optional[str]
    imagen_url: Optional[str]
    anulada: bool
    fecha_registro: Optional[datetime]
    barista_nombre: Optional[str] = None
    pagos: List[PagoOut] = []


class TotalesOut(BaseModel):
    monto: float
    pagado: float
    saldo: float
    n: int


class ListadoObligacionesOut(BaseModel):
    obligaciones: List[ObligacionOut]
    totales: TotalesOut
