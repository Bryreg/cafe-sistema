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
    # None = CAFÉ (costo del negocio, lo de siempre). «personal» crea una
    # categoría de la plata del dueño: solo etiqueta filas del libro del banco
    # y jamás toca el resultado ni el punto de equilibrio. Lo valida el
    # servicio con 400 legible, no pydantic.
    ambito: Optional[str] = None


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
    # `recurrencia` se sacó: se validaba, se guardaba y nadie la leía. El porqué
    # completo está en el modelo `Obligacion`.
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
    nota: Optional[str] = None
    imagen_url: Optional[str] = None


class NominaAgendarRequest(BaseModel):
    """Agenda la nómina de un mes como obligación corporativa.

    SIN restricciones de pydantic (nada de Field(ge=1, le=12) en `mes`), mismo
    criterio que `CategoriaCreate` y `SaldoBancoRequest`: lo que rechaza el
    schema vuelve como 422 y el `detail` de un 422 es una LISTA de errores — el
    cliente solo sabe leer strings. El mes y el año los valida `nomina.rango_mes`
    con un 400 que se puede mostrar; el monto, `_validar_monto`.
    """
    anio: int
    mes: int
    # EDITABLE ANTES DE CONFIRMAR. None = usar el cálculo. El dueño puede tener
    # la liquidación del contador, que trae retención en la fuente, embargos y el
    # redondeo de PILA — cosas que el cálculo declara que no incluye.
    monto: Optional[float] = None


class PagoCreate(BaseModel):
    monto: float
    # EL DÍA QUE SALIÓ LA PLATA. Obligatoria a nivel schema (falta → 422): es el
    # dato que hace útil a todo el módulo.
    fecha_pago: date
    metodo: str = "transferencia"   # efectivo|transferencia|tarjeta|cheque|otro
    obligacion_id: Optional[int] = None
    # PUERTA CERRADA: un pago con factura_id contesta 400 SIEMPRE (el servicio
    # explica por qué). El campo se conserva en el schema a propósito — sin él,
    # un cliente viejo que lo mande recibiría el 422-lista de pydantic en vez
    # del motivo legible.
    factura_id: Optional[int] = None
    imagen_soporte_url: Optional[str] = None
    nota: Optional[str] = None
    # La salida del banco EN el mismo pago (una transacción). Con esto marcado,
    # `cuenta_id` dice de qué cuenta salió. El backend responde con
    # `movimiento_banco_id`: un cliente que lo pidió y no ve esa clave está
    # hablando con un servidor de antes de este campo — ausente no es «no lo
    # hizo a propósito», es «no pude preguntar».
    descontar_banco: bool = False
    cuenta_id: Optional[int] = None


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


class ArmarMesRequest(BaseModel):
    """Armar todos los costos fijos de un mes de una.

    `confirmar` en False es la VISTA PREVIA: no escribe nada y devuelve la lista
    exacta de lo que crearia con sus montos. Va como campo del body y no como dos
    endpoints distintos porque las dos mitades tienen que calcular la misma lista
    con el mismo codigo — si la previa y el commit fueran dos caminos, el dueno
    aprobaria una lista y se le crearia otra.

    SIN restricciones de pydantic sobre anio/mes, mismo criterio que
    `NominaAgendarRequest`: lo que rechaza el schema vuelve como 422 y el
    `detail` de un 422 es una LISTA de errores — el cliente solo sabe leer
    strings. Los rangos los valida el handler con un 400 que se puede mostrar.
    """
    anio: int
    mes: int
    confirmar: bool = False
    # LAS CUENTAS SUELTAS QUE EL DUENO ELIGIO llevar al mes: ids de las que el
    # server ofrecio en `candidatas`. Vacio = solo las series ya marcadas como
    # repetibles, que es el comportamiento de siempre.
    #
    # Existe porque el lote nacia inerte en este negocio: los fijos se cargan a
    # mano todos los meses, nadie apreto nunca «Repetir mes que viene», y sin
    # una sola serie el lote no encontraba nada que copiar. Que sea una lista
    # EXPLICITA y no un «copia todo» es deliberado: una reparacion del molino
    # copiada al mes siguiente inventa un costo y sube el piso de mas.
    #
    # Sin restricciones de pydantic, misma razon que anio/mes: lo que rechaza el
    # schema vuelve como 422 y el `detail` de un 422 es una LISTA de errores, y
    # el cliente solo sabe leer strings.
    incluir: List[int] = []


class ImpoconsumoDeclaradoRequest(BaseModel):
    """«Esa ya la declare»: apaga el recordatorio de ese bimestre y los de antes.

    Se manda el bimestre EXPLICITO y no «el ultimo»: el dueno puede tener la
    pantalla abierta desde ayer, y si el server dedujera cual es por su cuenta
    podria apagar uno distinto del que el vio. Los rangos y el «todavia no cerro»
    los valida el servicio con 400.
    """
    anio: int
    bimestre: int


class ImpoconsumoAgendarRequest(BaseModel):
    """Mete la declaracion de un bimestre en la agenda y en el flujo proyectado.

    Se manda el bimestre EXPLICITO por la misma razon que
    `ImpoconsumoDeclaradoRequest`: el dueno aprieta el boton viendo un monto y un
    periodo en pantalla, y si el server dedujera cual es por su cuenta podria
    agendar uno distinto del que el vio.

    SIN restricciones de pydantic, mismo criterio que `NominaAgendarRequest`: lo
    que rechaza el schema vuelve como 422 y el `detail` de un 422 es una LISTA de
    errores — el cliente solo sabe leer strings. Los rangos, el «todavia no
    cerro» y el monto los valida el servicio con 400.
    """
    anio: int
    bimestre: int
    # None = usar el monto MEDIDO sobre la venta real del bimestre. Con valor,
    # manda el dueno: lo que el sistema mide es lo COBRADO, y la declaracion que
    # arma el contador trae exclusiones y correcciones que el sistema no ve.
    monto: Optional[float] = None


class ComisionDatafonoRequest(BaseModel):
    """Lo que cobra el datafono, EN PORCENTAJE — 2.5 quiere decir 2,5%.

    Se recibe como el dueño lo escribe y el handler lo convierte a fraccion antes
    de guardar, para que nadie tenga que acordarse de en que unidad quedo. SIN
    restricciones de pydantic, por el mismo motivo que `ReservaMinimaRequest`.
    """
    porcentaje: float


class ReservaMinimaRequest(BaseModel):
    """La plata con la que el negocio no puede quedarse sin.

    SIN restricciones de pydantic, por el mismo motivo exacto que
    `SaldoBancoRequest`: un `inf` rechazado por el schema vuelve dentro del
    cuerpo del 422 y revienta al serializar. La validación vive en el handler.
    """
    reserva: float


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
