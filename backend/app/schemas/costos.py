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


class CategoriaCreate(BaseModel):
    """Alta de categoría de costo.

    SIN restricciones de pydantic (nada de Field(min_length=..) ni Literal en
    `grupo`), mismo criterio que SaldoBancoRequest: lo que rechaza el schema
    vuelve como 422, y el `detail` de un 422 es una LISTA de errores — el
    cliente solo sabe leer strings, así que el dueño vería «error» pelado en vez
    de qué escribir. Las tres validaciones (nombre vacío, grupo inválido, clave
    repetida) viven en el servicio y contestan 400 con un texto.

    `clave` no está y no va a estar: la deriva el sistema del nombre y no se
    edita nunca, porque es lo que mantiene junto el histórico del P&L.
    """
    nombre: str
    # None = FIJO. El default no es neutral: casi todo lo que falta cargar
    # (publicidad, internet, domicilios, seguros, el contador) es del mes.
    grupo: Optional[str] = None


class CategoriaUpdate(BaseModel):
    """PATCH: solo pisa lo que llega. Se editan el nombre y el grupo — la clave
    es la identidad de la categoría en el P&L y no se toca."""
    nombre: Optional[str] = None
    grupo: Optional[str] = None


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
    # Con valor = el pago es el espejo de un egreso de caja adoptado (Fase 3).
    movimiento_caja_id: Optional[int] = None
    imagen_soporte_url: Optional[str]
    nota: Optional[str]
    anulado: bool
    fecha_registro: Optional[datetime]

    class Config:
        from_attributes = True


class AdopcionEgresoRequest(BaseModel):
    """Adopta un egreso de caja ya registrado como obligación devengada + pago espejo.
    El MovimientoCaja no se toca: ningún total del P&L ni del turno cambia."""
    categoria_id: int
    # OVERRIDE explícito. Por defecto = el día en que se TECLEÓ el egreso, que no
    # siempre es el mes al que pertenece el costo (MovimientoCaja no admite fecha
    # pasada por ningún camino). Corregirla MUEVE el costo de mes en el P&L.
    fecha_devengo: Optional[date] = None
    concepto: Optional[str] = None       # None = se conserva el del movimiento
    beneficiario: Optional[str] = None
    nota: Optional[str] = None


class EgresoSinAdoptarOut(BaseModel):
    id: int
    concepto: str
    valor: float
    fecha: Optional[date]                # día Colombia en que se tecleó
    tienda_id: Optional[int]
    tienda_nombre: Optional[str]
    barista_nombre: Optional[str] = None


class ListadoEgresosSinAdoptarOut(BaseModel):
    egresos: List[EgresoSinAdoptarOut]
    totales: dict


class SaldoBancoRequest(BaseModel):
    """Saldo bancario declarado por el dueño (Fase 4).

    Es un INPUT, no un cálculo: el sistema registra Consignacion (depósitos) pero
    nunca un saldo bancario, así que no puede derivarlo.

    SIN restricciones de pydantic a propósito (nada de Field(ge=0) ni
    allow_inf_nan=False): un valor rechazado por el schema vuelve DENTRO del
    cuerpo del 422, y un `inf` no es serializable a JSON — la propia respuesta de
    error revienta. La validación vive en el handler y responde 400 con un texto.
    """
    saldo: float
    # Cuándo se miró ese saldo. None = hoy. Sirve para declarar el saldo del
    # extracto del viernes un lunes, sin que el dato aparente ser de hoy.
    fecha: Optional[date] = None


class SaldoBancoOut(BaseModel):
    saldo_banco: float
    saldo_banco_fecha: Optional[date]
    # True = la declaración tiene más de una semana. Se dice en vez de mentir.
    saldo_banco_desactualizado: bool


class PuntoFlujoOut(BaseModel):
    fecha: date
    entradas: float          # venta esperada = MEDIANA del mismo día de semana
    salidas: float           # saldo de facturas + obligaciones que vencen ese día
    saldo: float             # acumulado desde caja_hoy


class FlujoProyectadoOut(BaseModel):
    hoy: date
    dias: int
    tienda_id: Optional[int]
    caja_hoy: dict
    serie: List[PuntoFlujoOut]
    # El día en que se acaba la plata. None = la serie nunca cruza cero.
    punto_de_quiebre: Optional[date]
    dias_hasta_quiebre: Optional[int]
    # Lo que la serie NO sabe: sin salidas cargadas, sin historia de ventas, saldo
    # del banco viejo o corporativas fuera de una vista por sede. Sin esto, la
    # ausencia de punto de quiebre se leería como "estás bien" y no lo dice nadie.
    advertencias: dict
    totales: dict


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
    # Llave de la serie mensual (el id del PRIMER eslabón). La escribe `repetir`.
    plantilla_id: Optional[int] = None
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
