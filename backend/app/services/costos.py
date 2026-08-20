"""Costos del negocio: obligaciones (qué se debe) y pagos (qué salió, y cuándo).

Por qué existe este servicio y no se reusa MovimientoCaja: `registrar_movimiento`
(services/caja.py) exige un turno ABIERTO con el cuadre de llegada hecho, y el
movimiento no tiene fecha propia — hereda la del turno. Así, el arriendo que se
paga un sábado por transferencia desde el celular hoy no se puede registrar en
ningún lado. Además el arriendo/nómina corporativa no pertenece a una sede, y todo
MovimientoCaja está atado a un turno y por lo tanto a una sede.

Regla central: el estado de una obligación NO se almacena, se DERIVA de la suma de
sus pagos vivos. Lo único persistido es `anulada`. Es una asimetría deliberada con
FacturaCompra.valor_pagado — esa columna es justamente la que se puede
desincronizar de los movimientos que la originaron.
"""
import calendar
import math
import re
import unicodedata
from datetime import date, timedelta
from statistics import median

from fastapi import HTTPException
from sqlalchemy import func, not_, or_
from sqlalchemy.orm import Session

from app.core.tz import dia_col, hoy_col, inicio_dia_col_utc, rango_col_utc
from app.models.models import (CajaTurno, Configuracion, Consignacion,
                               CostoCategoria, EntregaTurno,
                               EstadoConsignacionEnum, EstadoTurnoEnum,
                               FacturaCompra, MovimientoBanco, MovimientoCaja,
                               Obligacion, Pago, ProductoDesechable,
                               RecogidaEfectivo, Ticket, Tienda,
                               TipoMovCajaEnum)
from app.services import audit
# El LIBRO del banco (ancla + movimientos tecleados) es la única verdad del
# saldo bancario. El flujo lo LEE, no lo recalcula: dos matemáticas para el mismo
# saldo darían dos respuestas según por qué pantalla se entró, y son dos
# pantallas que están a un toque una de la otra. No hay ciclo de importación:
# `services/banco.py` solo depende de los modelos.
from app.services import banco as banco_svc
# El costo laboral lo CALCULA services/nomina.py con las horas marcadas y los
# recargos de ley; acá solo se lo convierte en una Obligacion para que entre a
# la agenda, al flujo y al botón [Pagar]. No hay ciclo: nomina.py no importa
# costos.py, y rentabilidad.py —que este módulo ya importa— también lo usa.
from app.services import nomina as nomina_svc
# La lista de conceptos reservados que services/facturas.py escribe para los pagos
# a proveedor vive en rentabilidad.py y se REUSA, no se copia: si allá cambia, acá
# tiene que cambiar en el mismo commit o el anti-doble-conteo se abre un agujero.
# Misma razón para la clave de categoría prohibida: el P&L la excluye del término
# de obligaciones y este servicio la rechaza en la entrada — las dos mitades tienen
# que hablar de la MISMA constante.
from app.services.rentabilidad import (CLAVE_CATEGORIA_NOMINA,
                                       CLAVE_CATEGORIA_PROVEEDORES,
                                       _CONCEPTOS_COMPRA)
# El piso de venta necesita el P&L entero (para MEDIR las razones de la venta) y
# los costos fijos del MES COMPLETO. Se importa el módulo y no solo unos nombres
# porque son funciones, no constantes: así queda a la vista de dónde salen.
from app.services import rentabilidad as rent_svc

METODOS_PAGO = {"efectivo", "transferencia", "tarjeta", "cheque", "otro"}
RECURRENCIAS = {"mensual", "quincenal", "semanal"}
ESTADOS = {"pendiente", "parcial", "pagada", "anulada"}


# ── Catálogo ────────────────────────────────────────────────────────────────

# Los dos grupos, explicados en el idioma del dueño y no en el del contador.
# La copia vive ACÁ y no en el formulario a propósito: la diferencia entre fijo
# y variable decide qué entra a `costos_fijos_devengados` —el piso que hay que
# cubrir para no perder plata— así que la definición y el número tienen que
# salir del mismo archivo. Escrita en la pantalla, se desincroniza el día que
# alguien cambie la regla acá adentro.
GRUPOS: dict[str, dict] = {
    "fijo": {
        "label": "Fijo",
        "que_es": ("Se paga igual venda mucho o poco. Arriendo, sueldos, "
                   "internet, publicidad, seguros, el contador, el arreglo del "
                   "molino."),
        "advertencia": None,
    },
    "variable": {
        "label": "Variable",
        "que_es": ("Sube y baja con la venta: si vendés el doble, cuesta el "
                   "doble. La comisión del datáfono, la del domicilio."),
        "advertencia": (
            "Ojo: un costo que SUBE CON LA VENTA no es una obligación mensual, "
            "es una tasa — y va contra el margen de cada venta, no contra el "
            "piso del mes. Solo los costos FIJOS arman el «cuánto hay que "
            "vender hoy para no perder»: lo que dejes en variable no entra a "
            "ese número. Si esto se paga todos los meses por un valor parecido "
            "—publicidad, internet, domicilios contratados, seguros, el "
            "contador— es FIJO, aunque el monto cambie un poco."
        ),
    },
}
GRUPO_DEFAULT = "fijo"


def catalogo_grupos() -> list[dict]:
    """Los grupos con su explicación, para que el formulario no invente la copia."""
    return [{"clave": clave, **datos} for clave, datos in GRUPOS.items()]


# Catálogo con el que arranca una base nueva. La `clave` es un slug estable: es
# lo que mata el texto libre al agrupar gastos ('Arriendo local' / 'arriendo' /
# 'ARRIENDO LOCAL' serían tres filas distintas). El `nombre` se puede editar
# después sin romper el agrupamiento.
#
# 'proveedores' NO está y no vuelve: era una trampa de doble conteo. Lo que se le
# debe al proveedor entra al P&L por FacturaCompra (fecha de recibido) y a la
# agenda como factura; cargarlo además como obligación contaba la misma
# mercadería dos veces. `_validar_categoria` rechaza esa clave, `listar_categorias`
# no la ofrece y rentabilidad.py la excluye del término de obligaciones. La FILA
# sembrada en las bases viejas se deja donde está: borrarla dejaría sin categoría
# a las obligaciones que le apuntan.
#
# 'mantenimiento' y 'otros' nacieron en "variable" y era un error de
# clasificación, no una opinión: variable significa que el costo SUBE CON LA
# VENTA, y arreglar el molino o pagarle al contador no sube porque se venda más.
# La consecuencia era muda — `costos_fijos_devengados` suma solo el grupo
# 'fijo', así que esa plata se caía del costo del mes sin que ninguna pantalla
# avisara, y 'otros' es justo donde hoy caen publicidad, internet, domicilios,
# seguros y el contador.
CATEGORIAS_INICIALES: list[dict] = [
    {"clave": "arriendo",      "nombre": "Arriendo",      "grupo": "fijo"},
    {"clave": "nomina",        "nombre": "Nómina",        "grupo": "fijo"},
    {"clave": "servicios",     "nombre": "Servicios",     "grupo": "fijo"},
    {"clave": "mantenimiento", "nombre": "Mantenimiento", "grupo": "fijo"},
    {"clave": "impuestos",     "nombre": "Impuestos",     "grupo": "fijo"},
    {"clave": "otros",         "nombre": "Otros",         "grupo": "fijo"},
]

# Marca en `configuracion` de que la corrección de grupos ya se aplicó.
RECLASIFICACION_GRUPOS_V1 = "migracion_grupo_categorias_v1"
# Las dos que estaban mal clasificadas. Explícitas y no derivadas de
# CATEGORIAS_INICIALES: la corrección es un hecho puntual del pasado y tiene que
# quedar congelada, no seguir a un catálogo que se va a editar.
CLAVES_RECLASIFICADAS_V1 = ("mantenimiento", "otros")


def sembrar_categorias(db: Session) -> int:
    """Inserta las categorías iniciales que falten. Devuelve cuántas creó.

    Idempotente y NO destructivo, como `tasas_laborales.sembrar_tasas`: solo
    inserta lo que no está. Una categoría que el dueño renombró o reclasificó
    sobrevive al deploy siguiente.
    """
    existentes = {c.clave for c in db.query(CostoCategoria).all()}
    creadas = 0
    for i, c in enumerate(CATEGORIAS_INICIALES):
        if c["clave"] in existentes:
            continue
        db.add(CostoCategoria(clave=c["clave"], nombre=c["nombre"],
                              grupo=c["grupo"], orden=i, activa=True))
        creadas += 1
    db.commit()
    return creadas


def reclasificar_grupos_v1(db: Session) -> int:
    """Corrige a "fijo" las dos categorías que nacieron mal clasificadas.

    Sembrarlas bien no alcanza: `sembrar_categorias` solo INSERTA lo que falta, y
    en las bases que ya operan esas filas están creadas desde el primer día con
    el grupo equivocado.

    CORRE UNA SOLA VEZ, marcada en `configuracion`. No es paranoia de migración:
    desde que el catálogo se edita por API, un "arreglo" que se aplicara en cada
    arranque le pisaría al dueño su propia decisión cada vez que se reinicia el
    servidor. Un cambio silencioso y repetido es peor que el error que corrige,
    porque enseña a no confiar en la pantalla.

    Solo toca las filas que siguen en "variable": si alguien ya las movió a mano,
    no hay nada que corregir. La marca se escribe igual —el trabajo está hecho—
    y en la misma transacción que el cambio, o un corte a mitad dejaría las filas
    corregidas y la migración marcada como pendiente para siempre.
    """
    ya = db.query(Configuracion).filter(
        Configuracion.clave == RECLASIFICACION_GRUPOS_V1).first()
    if ya is not None:
        return 0
    filas = db.query(CostoCategoria).filter(
        CostoCategoria.clave.in_(CLAVES_RECLASIFICADAS_V1),
        CostoCategoria.grupo == "variable",
    ).all()
    for fila in filas:
        fila.grupo = "fijo"
    db.add(Configuracion(clave=RECLASIFICACION_GRUPOS_V1, valor=str(len(filas))))
    db.commit()
    return len(filas)


def _validar_grupo(grupo) -> str:
    """`None`/vacío cae en FIJO. El default no es neutral y es a propósito: casi
    todo lo que el dueño va a cargar acá (publicidad, internet, domicilios,
    seguros, el contador) es una obligación del mes, y el error caro es al
    revés — clasificar de más como variable saca esa plata del piso a cubrir y
    el punto de equilibrio queda más bajo de lo que es."""
    if grupo is None or grupo == "":
        return GRUPO_DEFAULT
    limpio = str(grupo).strip().lower()
    if limpio not in GRUPOS:
        raise HTTPException(400, "El grupo tiene que ser «fijo» o «variable»")
    return limpio


def _validar_nombre_categoria(nombre) -> str:
    limpio = (nombre or "").strip()
    if not limpio:
        raise HTTPException(400, "El nombre de la categoría es obligatorio")
    if len(limpio) > 100:
        raise HTTPException(400, "El nombre de la categoría es demasiado largo "
                                 "(máximo 100 caracteres)")
    return limpio


def _slug(nombre: str) -> str:
    """`nombre` legible → clave estable, sin tildes ni espacios.

    La clave la deriva el sistema y NUNCA se edita después: es lo que agrupa los
    gastos en el P&L, así que si se moviera al renombrar la categoría, el
    histórico se partiría en dos filas que el dueño lee como dos costos
    distintos. Renombrar «Servicios» a «Servicios públicos» tiene que dejar la
    plata vieja junta con la nueva.
    """
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", nombre)
        if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")[:40]
    if not slug:
        # Un nombre entero de emojis o de signos: sin letras no hay clave estable
        # posible, y una autogenerada tipo "cat_7" no la reconoce nadie.
        raise HTTPException(400, "El nombre de la categoría tiene que tener al "
                                 "menos una letra o un número")
    return slug


def crear_categoria(db: Session, nombre, grupo=None, usuario_id: int | None = None) -> dict:
    """Crea una categoría de costo. El grupo por defecto es FIJO.

    Existe porque el catálogo eran seis filas quemadas en el arranque, y hoy
    publicidad, internet, domicilios, seguros y el contador caen todos en
    «Otros» — cinco costos distintos en una sola línea del P&L, que es lo mismo
    que no tener desglose.
    """
    limpio = _validar_nombre_categoria(nombre)
    grupo_ok = _validar_grupo(grupo)
    clave = _slug(limpio)
    if clave == CLAVE_CATEGORIA_PROVEEDORES:
        raise HTTPException(
            400, "Esa categoría está reservada: lo que le debés a un proveedor se "
                 "carga como FACTURA en Compras, no como costo fijo — acá se "
                 "contaría dos veces.")
    # La colisión se AVISA, no se resuelve con un sufijo: «otros_2» al lado de
    # «Otros» en el desplegable es exactamente el texto libre que la clave vino
    # a matar. Se nombra la fila que ya está para que el dueño la use o la
    # renombre, y se dice si está apagada — si no, el mensaje parece un bug.
    existente = db.query(CostoCategoria).filter(CostoCategoria.clave == clave).first()
    if existente is not None:
        estado = "" if existente.activa else " (está desactivada)"
        raise HTTPException(
            400, f"Ya existe la categoría «{existente.nombre}»{estado} — usá esa o "
                 f"cambiale el nombre a la nueva.")

    ultimo = db.query(func.max(CostoCategoria.orden)).scalar()
    fila = CostoCategoria(clave=clave, nombre=limpio, grupo=grupo_ok,
                          orden=(ultimo or 0) + 1, activa=True)
    db.add(fila)
    db.flush()
    audit.registrar(
        db, accion="crear_categoria_costo", tabla="costos_categorias",
        registro_id=fila.id, usuario_id=usuario_id,
        datos_despues={"clave": fila.clave, "nombre": fila.nombre, "grupo": fila.grupo},
    )
    db.commit()
    db.refresh(fila)
    return _serializar_categoria(fila)


def editar_categoria(db: Session, categoria_id: int, campos: dict,
                     usuario_id: int | None = None) -> dict:
    """Cambia el nombre o el grupo de una categoría. La CLAVE no se toca nunca.

    Mover una categoría de variable a fijo (o al revés) le cambia el piso del
    mes a TODO el histórico, no solo a lo que se cargue de acá en adelante:
    `costos_fijos_devengados` se recalcula por grupo cada vez que se abre el
    P&L. Es lo que se quiere —una mala clasificación vieja se arregla de una—
    pero por eso queda en auditoría con el antes y el después.
    """
    fila = db.query(CostoCategoria).filter(CostoCategoria.id == categoria_id).first()
    if fila is None:
        raise HTTPException(404, "Categoría no encontrada")
    if fila.clave == CLAVE_CATEGORIA_PROVEEDORES:
        raise HTTPException(
            400, "Esa categoría está reservada y no se edita: la deuda con "
                 "proveedores vive en Compras.")

    antes = {"nombre": fila.nombre, "grupo": fila.grupo}
    if "nombre" in campos and campos["nombre"] is not None:
        # El nombre se puede editar libremente PORQUE la clave no se recalcula:
        # es display, no identidad.
        fila.nombre = _validar_nombre_categoria(campos["nombre"])
    if "grupo" in campos and campos["grupo"] is not None:
        fila.grupo = _validar_grupo(campos["grupo"])

    audit.registrar(
        db, accion="editar_categoria_costo", tabla="costos_categorias",
        registro_id=fila.id, usuario_id=usuario_id,
        datos_antes=antes,
        datos_despues={"nombre": fila.nombre, "grupo": fila.grupo},
    )
    db.commit()
    db.refresh(fila)
    return _serializar_categoria(fila)


def _serializar_categoria(c: CostoCategoria) -> dict:
    """Misma forma que las filas de `listar_categorias`, más la advertencia del
    grupo elegido. Viaja en la respuesta y no solo en el catálogo para que la
    pantalla pueda mostrarla DESPUÉS de guardar, que es cuando el dueño todavía
    está mirando lo que acaba de hacer."""
    return {"id": c.id, "clave": c.clave, "nombre": c.nombre,
            "grupo": c.grupo, "orden": c.orden, "activa": bool(c.activa),
            "advertencia": GRUPOS.get(c.grupo, {}).get("advertencia")}


def listar_categorias(db: Session, incluir_inactivas: bool = False) -> list:
    q = db.query(CostoCategoria)
    if not incluir_inactivas:
        q = q.filter(CostoCategoria.activa == True)  # noqa: E712
    # 'proveedores' NO se ofrece nunca, ni siquiera con incluir_inactivas: una
    # categoría que `_validar_categoria` rechaza no puede estar en el desplegable
    # del formulario. La FILA se conserva (hay obligaciones históricas apuntándole
    # y borrarla las dejaría huérfanas); lo que se corta es la posibilidad de
    # elegirla otra vez.
    q = q.filter(CostoCategoria.clave != CLAVE_CATEGORIA_PROVEEDORES)
    cats = q.order_by(CostoCategoria.orden, CostoCategoria.nombre).all()
    return [{"id": c.id, "clave": c.clave, "nombre": c.nombre,
             "grupo": c.grupo, "orden": c.orden} for c in cats]


# ── Estado derivado ─────────────────────────────────────────────────────────

def _pagos_vivos(db: Session, obligacion_ids: list) -> dict:
    """{obligacion_id: [Pago vivo, ...]} en UNA query — no una por obligación."""
    if not obligacion_ids:
        return {}
    filas = db.query(Pago).filter(
        Pago.obligacion_id.in_(obligacion_ids),
        Pago.anulado == False,  # noqa: E712
    ).order_by(Pago.fecha_pago, Pago.id).all()
    agrupado: dict = {}
    for p in filas:
        agrupado.setdefault(p.obligacion_id, []).append(p)
    return agrupado


def estado_derivado(obligacion: Obligacion, pagado: float) -> str:
    """pendiente (Σ == 0) | parcial (0 < Σ < monto) | pagada (Σ >= monto).
    `anulada` es el único estado ALMACENADO y manda sobre todos los demás."""
    if obligacion.anulada:
        return "anulada"
    monto = float(obligacion.monto or 0)
    if pagado <= 0:
        return "pendiente"
    if pagado + 0.005 < monto:   # tolerancia de centavo: Numeric(12,2)
        return "parcial"
    return "pagada"


def _salidas_banco_por_obligacion(db: Session, obligacion_ids: list) -> dict:
    """{obligacion_id: plata que YA SALIÓ del banco por esa obligación}.

    Solo SALIDAS: un movimiento de entrada enlazado sería una devolución, y
    restarla como si fuera un pago diría que debe menos de lo que debe.

    Existe para cerrar el doble conteo que documenta `_saldo_banco_hoy`: el
    dueño teclea el débito del arriendo contra el extracto, el saldo del banco
    baja, y la agenda seguía proyectando ese arriendo como salida futura. La
    misma plata, contada dos veces, y el punto de quiebre antes de lo real.
    Cierra solo el tramo ENLAZADO — la salida tecleada sin `obligacion_id` no
    aparece acá y se sigue contando dos veces (ver `_saldo_banco_hoy`).
    """
    if not obligacion_ids:
        return {}
    filas = db.query(
        MovimientoBanco.obligacion_id, func.sum(MovimientoBanco.monto),
    ).filter(
        MovimientoBanco.obligacion_id.in_(obligacion_ids),
        MovimientoBanco.tipo == "salida",
    ).group_by(MovimientoBanco.obligacion_id).all()
    return {oid: round(float(total or 0), 2) for oid, total in filas}


def cubierto_de(pagado: float, del_banco: float) -> float:
    """Cuánta plata de esta obligación ya salió, sin contarla dos veces.

    MAX Y NO SUMA, y la razón es que NO HAY ENLACE entre un `Pago` y el
    `MovimientoBanco` que lo ejecuta. El camino normal —«Registrar pago» con
    «Y descontalo del banco» tildado— escribe LOS DOS para la misma plata:
    primero el pago, después el movimiento. Sumarlos restaría el arriendo dos
    veces y la obligación desaparecería de la agenda debiendo, que es el lado
    tranquilizador y el peor de los dos errores posibles.

    Con el máximo, cada camino da lo correcto:
      · pago + movimiento (el normal)      -> max(1M, 1M) = 1M
      · solo el movimiento tecleado a mano -> max(0, 1M)  = 1M   ← lo que se arregla
      · solo el pago (pagó en efectivo)    -> max(1M, 0)  = 1M
      · dos pagos parciales con su débito  -> max(1M, 1M) = 1M

    Queda un caso mixto que el máximo no resuelve: pagó una parte en efectivo
    (con `Pago`) y otra desde el banco tecleada aparte (sin `Pago`). Ahí muestra
    MÁS deuda de la real — la dirección prudente, y exactamente lo que muestra
    hoy, así que no es una regresión. Resolverlo de verdad pide un enlace
    explícito `Pago.movimiento_banco_id`; identificarlo por la FORMA (un monto
    que coincide) es el anti-patrón que este módulo ya pagó caro.
    """
    return max(round(pagado, 2), round(del_banco, 2))


def _serializar(obligacion: Obligacion, pagos: list, del_banco: float = 0.0) -> dict:
    """El saldo usa la MISMA cuenta que la agenda, y esto no es un detalle.

    `get_agenda` descuenta lo que ya salió del banco con `cubierto_de`. Si esta
    función no hiciera lo mismo, la MISMA obligación diría dos cosas distintas en
    la MISMA pantalla: la agenda de arriba dejaría de pedir el arriendo y el
    banner de Obligaciones seguiría mostrándolo pendiente por $2.400.000, con su
    botón «Pagar» invitando a pagarlo de nuevo. Dos números para la misma
    pregunta es justo lo que este módulo viene peleando.

    `pagado` NO se toca: sigue siendo la suma de los `Pago` registrados, que es
    lo que el historial de la fila puede mostrar. Lo que salió del banco viaja
    aparte en `salido_del_banco` para que la pantalla pueda explicar por qué el
    saldo es cero sin que haya un solo pago listado — y para que el dueño sepa
    que le falta registrar ese pago.
    """
    pagado = round(sum(float(p.monto or 0) for p in pagos), 2)
    cubierto = cubierto_de(pagado, del_banco)
    monto = float(obligacion.monto or 0)
    cat = obligacion.categoria
    return {
        "id": obligacion.id,
        "tienda_id": obligacion.tienda_id,
        "tienda_nombre": obligacion.tienda.nombre if obligacion.tienda else None,
        "categoria_id": obligacion.categoria_id,
        "categoria_clave": cat.clave if cat else "",
        "categoria_nombre": cat.nombre if cat else "",
        "categoria_grupo": cat.grupo if cat else "",
        "concepto": obligacion.concepto,
        "beneficiario": obligacion.beneficiario,
        "monto": round(monto, 2),
        "pagado": pagado,
        # Lo que ya salió del banco por esta obligación, tecleado en el libro. Va
        # aparte de `pagado` porque no tiene un `Pago` detrás: es la evidencia del
        # extracto, no un registro de pago.
        "salido_del_banco": round(del_banco, 2),
        # Nunca negativo: un pago de más deja la obligación en 'pagada' con saldo 0,
        # no con un saldo negativo que ensuciaría los totales de la lista.
        "saldo": round(max(monto - cubierto, 0), 2),
        "estado": estado_derivado(obligacion, cubierto),
        "fecha_devengo": obligacion.fecha_devengo,
        "fecha_vencimiento": obligacion.fecha_vencimiento,
        "recurrencia": obligacion.recurrencia,
        # Llave de la SERIE mensual (ver `repetir_obligacion`). None = costo suelto.
        "plantilla_id": obligacion.plantilla_id,
        "nota": obligacion.nota,
        "imagen_url": obligacion.imagen_url,
        "anulada": bool(obligacion.anulada),
        "fecha_registro": obligacion.fecha_registro,
        "barista_nombre": obligacion.barista_nombre,
        "pagos": [_serializar_pago(p) for p in pagos],
    }


def _serializar_pago(p: Pago) -> dict:
    return {
        "id": p.id,
        "obligacion_id": p.obligacion_id,
        "factura_id": p.factura_id,
        "tienda_id": p.tienda_id,
        "monto": round(float(p.monto or 0), 2),
        "fecha_pago": p.fecha_pago,
        "metodo": p.metodo,
        # Con valor = el pago es el espejo de un egreso de caja adoptado (Fase 3).
        "movimiento_caja_id": p.movimiento_caja_id,
        "imagen_soporte_url": p.imagen_soporte_url,
        "nota": p.nota,
        "anulado": bool(p.anulado),
        "fecha_registro": p.fecha_registro,
    }


# ── Validaciones compartidas ────────────────────────────────────────────────

def _validar_categoria(db: Session, categoria_id: int) -> CostoCategoria:
    """Puerta ÚNICA de la categoría: la usan crear, editar y adoptar, así que la
    prohibición de 'proveedores' se aplica sola en los tres caminos."""
    cat = db.query(CostoCategoria).filter(CostoCategoria.id == categoria_id).first()
    if not cat:
        raise HTTPException(400, "Categoría de costo inexistente")
    if not cat.activa:
        raise HTTPException(400, f"La categoría «{cat.nombre}» está desactivada — elegí otra")
    # DECISIÓN (opción a de la revisión): la categoría se BLOQUEA en la entrada en
    # vez de marcarse "no computa en el P&L". El doble conteo no era solo del P&L:
    # una obligación de proveedor también aparece en la Agenda y en el Flujo al
    # lado de la factura que representa la MISMA deuda. Excluirla solo del P&L
    # (opción b) dejaba esas dos pantallas mintiendo, y además cuesta una columna
    # nueva. Bloquearla cierra las tres de una y no necesita migración.
    if cat.clave == CLAVE_CATEGORIA_PROVEEDORES:
        raise HTTPException(
            400, "Lo que le debés a un proveedor se carga como FACTURA en Compras, "
                 "no como costo fijo: acá se contaría dos veces (la factura ya entra "
                 "al P&L y a la agenda). Para pagarla, andá a «Pagos proveedores».")
    return cat


def _validar_tienda(db: Session, tienda_id):
    """tienda_id None es VÁLIDO y significativo: gasto corporativo (sin sede)."""
    if tienda_id is None:
        return
    if not db.query(Tienda).filter(Tienda.id == tienda_id).first():
        raise HTTPException(400, "Sede inexistente")


def _validar_monto(monto) -> float:
    try:
        valor = float(monto)
    except (TypeError, ValueError):
        raise HTTPException(400, "El monto debe ser un número")
    if valor <= 0:
        raise HTTPException(400, "El monto debe ser mayor a 0")
    return round(valor, 2)


def _validar_concepto(concepto: str) -> str:
    limpio = (concepto or "").strip()
    if not limpio:
        raise HTTPException(400, "El concepto es obligatorio")
    return limpio


def _validar_recurrencia(recurrencia):
    if recurrencia is None or recurrencia == "":
        return None
    if recurrencia not in RECURRENCIAS:
        raise HTTPException(400, "Recurrencia inválida: mensual | quincenal | semanal")
    return recurrencia


# ── Obligaciones ────────────────────────────────────────────────────────────

def crear_obligacion(db: Session, data, usuario_id: int,
                     barista_id: int | None = None,
                     barista_nombre: str | None = None) -> dict:
    _validar_categoria(db, data.categoria_id)
    _validar_tienda(db, data.tienda_id)
    obligacion = Obligacion(
        tienda_id=data.tienda_id,
        categoria_id=data.categoria_id,
        concepto=_validar_concepto(data.concepto),
        beneficiario=(data.beneficiario or "").strip() or None,
        monto=_validar_monto(data.monto),
        fecha_devengo=data.fecha_devengo,
        fecha_vencimiento=data.fecha_vencimiento,
        recurrencia=_validar_recurrencia(data.recurrencia),
        nota=data.nota,
        imagen_url=data.imagen_url,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(obligacion)
    db.flush()
    audit.registrar(
        db, accion="crear_obligacion", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=obligacion.tienda_id,
        datos_despues={"concepto": obligacion.concepto, "monto": float(obligacion.monto),
                       "fecha_devengo": obligacion.fecha_devengo},
    )
    db.commit()
    db.refresh(obligacion)
    return _serializar(obligacion, [])


def editar_obligacion(db: Session, obligacion_id: int, data, usuario_id: int) -> dict:
    obligacion = db.query(Obligacion).filter(Obligacion.id == obligacion_id).first()
    if not obligacion:
        raise HTTPException(404, "Obligación no encontrada")
    if obligacion.anulada:
        raise HTTPException(400, "La obligación está anulada — no se puede editar")

    # exclude_unset: distingue "no lo mandaron" de "lo mandaron en null". Sin esto,
    # tienda_id=None (corporativo) sería indistinguible de omitir el campo.
    campos = data.model_dump(exclude_unset=True)
    if "categoria_id" in campos and campos["categoria_id"] is not None:
        _validar_categoria(db, campos["categoria_id"])
        obligacion.categoria_id = campos["categoria_id"]
    if "tienda_id" in campos:
        _validar_tienda(db, campos["tienda_id"])
        obligacion.tienda_id = campos["tienda_id"]
    if "concepto" in campos and campos["concepto"] is not None:
        obligacion.concepto = _validar_concepto(campos["concepto"])
    if "monto" in campos and campos["monto"] is not None:
        obligacion.monto = _validar_monto(campos["monto"])
    if "fecha_devengo" in campos and campos["fecha_devengo"] is not None:
        obligacion.fecha_devengo = campos["fecha_devengo"]
    if "fecha_vencimiento" in campos:
        obligacion.fecha_vencimiento = campos["fecha_vencimiento"]
    if "recurrencia" in campos:
        obligacion.recurrencia = _validar_recurrencia(campos["recurrencia"])
    if "beneficiario" in campos:
        obligacion.beneficiario = (campos["beneficiario"] or "").strip() or None
    if "nota" in campos:
        obligacion.nota = campos["nota"]
    if "imagen_url" in campos:
        obligacion.imagen_url = campos["imagen_url"]

    audit.registrar(
        db, accion="editar_obligacion", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=obligacion.tienda_id,
        datos_despues=campos,
    )
    db.commit()
    db.refresh(obligacion)
    return _serializar(obligacion, _pagos_vivos(db, [obligacion.id]).get(obligacion.id, []),
                       _salidas_banco_por_obligacion(db, [obligacion.id]).get(obligacion.id, 0.0))


def anular_obligacion(db: Session, obligacion_id: int, usuario_id: int,
                      motivo: str | None = None) -> dict:
    """Baja LÓGICA. Nunca un DELETE: dejaría los pagos huérfanos y sin traza."""
    obligacion = db.query(Obligacion).filter(Obligacion.id == obligacion_id).first()
    if not obligacion:
        raise HTTPException(404, "Obligación no encontrada")
    if obligacion.anulada:
        return _serializar(obligacion, [])
    obligacion.anulada = True
    if motivo:
        obligacion.nota = f"{obligacion.nota + ' — ' if obligacion.nota else ''}Anulada: {motivo}"
    audit.registrar(
        db, accion="anular_obligacion", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=obligacion.tienda_id,
        datos_antes={"concepto": obligacion.concepto, "monto": float(obligacion.monto or 0)},
        datos_despues={"motivo": motivo},
    )
    db.commit()
    db.refresh(obligacion)
    return _serializar(obligacion, [])


def _mes_siguiente(d: date) -> date:
    """Mismo día del mes que viene, recortado al último día real de ese mes.

    Sin el recorte, el arriendo del 31 de enero pediría un 31 de febrero y
    reventaría; y usar +30 días correría la fecha un poco cada mes hasta que el
    "arriendo de agosto" quedara devengado en septiembre.
    """
    anio, mes = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    # Último día del mes destino: el día 1 del siguiente, menos uno.
    sig_anio, sig_mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    ultimo = (date(sig_anio, sig_mes, 1) - timedelta(days=1)).day
    return date(anio, mes, min(d.day, ultimo))


def repetir_obligacion(db: Session, obligacion_id: int, usuario_id: int,
                       barista_id: int | None = None,
                       barista_nombre: str | None = None) -> dict:
    """Crea la copia del MES SIGUIENTE de un costo, en un tap.

    `recurrencia` y `plantilla_id` existían como columnas muertas: nadie generaba
    nunca la obligación del mes que viene. Con dos sedes eso son 12-18 cargas
    manuales por mes retecleando lo mismo, que es el camino más corto a que el
    módulo se abandone.

    Deliberadamente NO es un scheduler: no hay job que cree costos solo. El dueño
    aprieta el botón cuando quiere, ve la copia y puede ajustarle el monto (la
    energía no vale igual todos los meses). Un generador automático llenaría el
    P&L de costos que nadie confirmó.

    IDEMPOTENTE por (serie, mes de devengo): un doble tap no cobra el arriendo dos
    veces. La respuesta trae `ya_existia` para que la pantalla lo diga en vez de
    fingir que acaba de crear algo.
    """
    origen = db.query(Obligacion).filter(Obligacion.id == obligacion_id).first()
    if not origen:
        raise HTTPException(404, "Obligación no encontrada")
    if origen.anulada:
        raise HTTPException(400, "La obligación está anulada — no se puede repetir")

    # Repetir CREA una obligación nueva, así que pasa por la misma puerta que
    # crear y editar. Copiar `categoria_id` del origen sin validarlo esquivaba la
    # única guarda que bloquea 'proveedores' (y las categorías desactivadas): una
    # obligación legacy de proveedor se replicaba mes a mes hacia la Agenda y el
    # Flujo, reinstalando por botón el doble conteo que la validación cerró en el
    # formulario. El mensaje base ya dice qué hacer en su lugar (cargarla como
    # factura en Compras); acá solo se le antepone POR QUÉ apareció ahora.
    try:
        _validar_categoria(db, origen.categoria_id)
    except HTTPException as e:
        raise HTTPException(
            e.status_code,
            f"No se puede repetir «{origen.concepto}» — {e.detail}") from e

    # La llave de la serie es SIEMPRE el primer eslabón, no el padre inmediato:
    # encadenando agosto→septiembre→octubre los tres comparten una sola llave y
    # la búsqueda de duplicados es una igualdad, no un recorrido.
    serie_id = origen.plantilla_id or origen.id
    devengo = _mes_siguiente(origen.fecha_devengo)
    vencimiento = (_mes_siguiente(origen.fecha_vencimiento)
                   if origen.fecha_vencimiento else None)

    # ¿Ya hay una copia viva de esta serie devengada en ese mes? Se compara por MES
    # y no por fecha exacta: si alguien le corrigió el día a la copia, sigue siendo
    # la del mes y repetir otra vez no puede duplicarla.
    inicio_mes = devengo.replace(day=1)
    fin_mes = _mes_siguiente(inicio_mes) - timedelta(days=1)
    ya = db.query(Obligacion).filter(
        or_(Obligacion.plantilla_id == serie_id, Obligacion.id == serie_id),
        Obligacion.anulada == False,  # noqa: E712
        Obligacion.fecha_devengo >= inicio_mes,
        Obligacion.fecha_devengo <= fin_mes,
    ).order_by(Obligacion.id).first()
    if ya is not None:
        return {**_serializar(ya, _pagos_vivos(db, [ya.id]).get(ya.id, []),
                              _salidas_banco_por_obligacion(db, [ya.id]).get(ya.id, 0.0)),
                "ya_existia": True}

    copia = Obligacion(
        tienda_id=origen.tienda_id,
        categoria_id=origen.categoria_id,
        concepto=origen.concepto,
        beneficiario=origen.beneficiario,
        monto=origen.monto,
        fecha_devengo=devengo,
        # Si el original no tenía fecha de pago, la copia tampoco: inventarle una
        # sería exactamente el error que la sección "sin fecha" de la agenda evita.
        fecha_vencimiento=vencimiento,
        recurrencia=origen.recurrencia,
        plantilla_id=serie_id,
        nota=origen.nota,
        # La imagen del soporte NO se copia: es el recibo del mes pasado, y
        # arrastrarlo haría pasar un comprobante viejo por el del mes nuevo.
        imagen_url=None,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(copia)
    db.flush()
    audit.registrar(
        db, accion="repetir_obligacion", tabla="obligaciones",
        registro_id=copia.id, usuario_id=usuario_id, tienda_id=copia.tienda_id,
        datos_antes={"origen_id": origen.id, "fecha_devengo": origen.fecha_devengo},
        datos_despues={"serie_id": serie_id, "concepto": copia.concepto,
                       "monto": float(copia.monto), "fecha_devengo": devengo,
                       "fecha_vencimiento": vencimiento},
    )
    db.commit()
    db.refresh(copia)
    # Nace sin pagos: el estado derivado le da 'pendiente' solo.
    return {**_serializar(copia, []), "ya_existia": False}


def listar_obligaciones(db: Session, *, tienda_id: int | None = None,
                        solo_corporativas: bool = False,
                        categoria: str | None = None,
                        estado: str | None = None,
                        desde: date | None = None, hasta: date | None = None,
                        campo_fecha: str = "devengo") -> dict:
    """Listado + totales. Reglas de los filtros:

    - sin `tienda_id` y sin `solo_corporativas` → TODO, corporativas incluidas (son
      el gasto más grande: esconderlas del "todas" sería mentir en el total);
    - con `tienda_id` → SOLO esa sede (las corporativas quedan distinguidas aparte);
    - `solo_corporativas` → SOLO las que no tienen sede.

    Por defecto las anuladas no aparecen ni suman; se piden explícitamente con
    estado='anulada'.
    """
    if estado is not None and estado not in ESTADOS:
        raise HTTPException(400, "Estado inválido: pendiente | parcial | pagada | anulada")
    if campo_fecha not in ("devengo", "vencimiento"):
        raise HTTPException(400, "campo_fecha inválido: devengo | vencimiento")

    q = db.query(Obligacion)
    if solo_corporativas:
        q = q.filter(Obligacion.tienda_id.is_(None))
    elif tienda_id is not None:
        q = q.filter(Obligacion.tienda_id == tienda_id)
    if categoria:
        q = q.join(CostoCategoria, Obligacion.categoria_id == CostoCategoria.id)
        q = q.filter(CostoCategoria.clave == categoria)
    columna = (Obligacion.fecha_devengo if campo_fecha == "devengo"
               else Obligacion.fecha_vencimiento)
    if desde is not None:
        q = q.filter(columna >= desde)
    if hasta is not None:
        q = q.filter(columna <= hasta)
    # anulada == True solo se muestra si se pide ese estado explícitamente.
    q = q.filter(Obligacion.anulada == (estado == "anulada"))

    filas = q.order_by(Obligacion.fecha_devengo.desc(), Obligacion.id.desc()).all()
    ids = [o.id for o in filas]
    pagos_por_obligacion = _pagos_vivos(db, ids)
    banco_por_obligacion = _salidas_banco_por_obligacion(db, ids)

    obligaciones = []
    total_monto = total_pagado = 0.0
    for o in filas:
        item = _serializar(o, pagos_por_obligacion.get(o.id, []),
                           banco_por_obligacion.get(o.id, 0.0))
        # El estado se DERIVA, así que el filtro por estado se aplica acá y no en SQL.
        if estado is not None and item["estado"] != estado:
            continue
        obligaciones.append(item)
        total_monto += item["monto"]
        total_pagado += item["pagado"]

    return {
        "obligaciones": obligaciones,
        "totales": {
            "monto": round(total_monto, 2),
            "pagado": round(total_pagado, 2),
            "saldo": round(max(total_monto - total_pagado, 0), 2),
            "n": len(obligaciones),
        },
    }


# ── La nómina, agendada como obligación de verdad ───────────────────────────
#
# El costo laboral de MEDIUM CAFÉ —hoy más de $20.000.000 al mes entre las dos
# sedes y las siete personas— existía como cálculo (services/nomina.py) y como
# pantalla, pero no como PLATA QUE HAY QUE PAGAR: no era una Obligacion, así que
# no entraba a la agenda, no entraba al flujo proyectado, no tenía botón
# [Pagar] y no bajaba ningún saldo. El punto de quiebre, el piso de venta y el
# colchón para activaciones se calculaban todos sin el gasto más grande del
# negocio, y todos daban de más.
#
# Meterla acá no es una pantalla nueva: es hacer que la nómina sea la misma
# clase de cosa que el arriendo, y con eso hereda toda la cañería que ya existe.

# EL DÍA DE PAGO, en `configuracion` y no en el código. Mismo patrón que
# `saldo_banco`: es un dato del negocio, y un negocio que mañana pague el 5 y el
# 20 no tiene por qué esperar un deploy.
#
# UN SOLO PAGO Y A PROPÓSITO. El dueño confirmó que la nómina se paga ENTERA el
# último día del mes: no hay quincena ni reparto. Acá no se construye el reparto
# «por si acaso» —una segunda fecha que nadie usa se llena de casos raros y de
# tests que fijan un comportamiento que nunca ocurrió—. El día que cambie, se
# agrega entonces, y lo que hay que tocar es esta clave y `fecha_de_pago_nomina`.
CLAVE_NOMINA_DIA_PAGO = "nomina_dia_pago"
# El valor por defecto y el único que hoy existe en la base. Es una PALABRA y no
# un 31: guardar 31 para decir «el último» funciona por accidente (el recorte al
# último día real lo convierte en 28 o 30 cuando toca) pero deja el dato
# diciendo algo que no es, y el día que alguien lea la fila no va a poder
# distinguir «el último» de «el 31 y recórtalo».
DIA_PAGO_ULTIMO = "ultimo"

MESES_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def leer_dia_pago_nomina(db: Session) -> str:
    """Qué día del mes se paga la nómina: `'ultimo'` o un día 1..31 como texto.

    Tolera basura guardada por el mismo motivo que `_leer_saldo_banco`: la fila
    es TEXTO y un valor podrido de otra versión no puede tumbar el agendado. Ante
    cualquier duda devuelve el último día del mes, que es lo que el negocio hace
    hoy — y errar hacia el final del mes es la dirección prudente: adelantar la
    fecha haría aparecer la salida antes de tiempo y correría el punto de quiebre
    hacia atrás sin que nadie lo pidiera.
    """
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_NOMINA_DIA_PAGO).first()
    crudo = (fila.valor if fila is not None else None) or ""
    crudo = crudo.strip().lower()
    if not crudo or crudo == DIA_PAGO_ULTIMO:
        return DIA_PAGO_ULTIMO
    try:
        dia = int(crudo)
    except (TypeError, ValueError):
        return DIA_PAGO_ULTIMO
    if not 1 <= dia <= 31:
        return DIA_PAGO_ULTIMO
    return str(dia)


def fecha_de_pago_nomina(db: Session, anio: int, mes: int) -> date:
    """El día del mes DEVENGADO en que sale la plata de la nómina.

    El día configurado se RECORTA al último real del mes, igual que
    `_mes_siguiente`: sin el recorte, un día 31 pediría un 31 de febrero y
    reventaría.
    """
    ultimo = calendar.monthrange(int(anio), int(mes))[1]
    dia = leer_dia_pago_nomina(db)
    if dia == DIA_PAGO_ULTIMO:
        return date(int(anio), int(mes), ultimo)
    return date(int(anio), int(mes), min(int(dia), ultimo))


def _obligacion_de_nomina_del_mes(db: Session, desde: date, hasta: date):
    """La obligación VIVA de nómina devengada en ese mes, si hay alguna.

    No se filtra por sede A PROPÓSITO, y la que no está es la restricción que
    parecía obvia (`tienda_id IS NULL`, o sea «solo las corporativas»). La razón
    es `rentabilidad._nomina_del_periodo`: ahí una obligación de nómina de UNA
    sede apaga el cálculo de esa sede y una corporativa lo apaga en todas, pero
    las DOS entran a `gastos`. Si el agendado corporativo ignorara una de sede ya
    cargada, el P&L del mes sumaría las dos y contaría la misma nómina dos veces.
    Cualquier fila de nómina viva devengada en el mes bloquea, y se devuelve para
    que la pantalla pueda decir cuál es.
    """
    return (
        db.query(Obligacion)
        .join(CostoCategoria, CostoCategoria.id == Obligacion.categoria_id)
        .filter(
            Obligacion.anulada == False,  # noqa: E712
            Obligacion.fecha_devengo >= desde,
            Obligacion.fecha_devengo <= hasta,
            CostoCategoria.clave == CLAVE_CATEGORIA_NOMINA,
        )
        .order_by(Obligacion.id)
        .first()
    )


def _con_pagos(db: Session, obligacion: Obligacion) -> dict:
    """Serializa una obligación con sus pagos vivos y lo ya salido del banco.
    Tres líneas que se repetían en cada retorno de este módulo."""
    return _serializar(
        obligacion,
        _pagos_vivos(db, [obligacion.id]).get(obligacion.id, []),
        _salidas_banco_por_obligacion(db, [obligacion.id]).get(obligacion.id, 0.0))


def agendar_nomina(db: Session, anio: int, mes: int, usuario_id: int,
                   monto: float | None = None,
                   barista_id: int | None = None,
                   barista_nombre: str | None = None) -> dict:
    """Crea LA obligación corporativa de la nómina de un mes.

    ═══════════════════════════════════════════════════════════════════════════
    EL MES DE **DEVENGO** DECIDE DE QUÉ FUENTE SALE EL NÚMERO; LA FECHA DE
    **VENCIMIENTO** DECIDE EN QUÉ DÍA DEL FLUJO SE DIBUJA.
    ═══════════════════════════════════════════════════════════════════════════
    Con el pago a fin de mes las dos coinciden al día, y por eso hay que
    escribirlo: son la misma fecha por casualidad, no por definición. El devengo
    dice A QUÉ MES pertenece el costo —es lo que lee el P&L, y lo que decide si
    el número sale de las horas ya trabajadas o del contrato— y el vencimiento
    dice CUÁNDO sale la plata —es lo que lee la agenda y el flujo proyectado—.
    El día que el negocio pase a quincena, o que la nómina de agosto se pague el
    5 de septiembre, confundirlas contaría un mes dos veces: el costo se movería
    de mes en el margen al mover la fecha de pago, o al revés, la salida de plata
    se dibujaría en el mes equivocado del flujo.

    DE DÓNDE SALE EL MONTO, entonces, según el mes DEVENGADO:

      · mes ya terminado → `nomina.consolidada`: horas realmente marcadas más las
        acreditadas por novedad, liquidadas persona por persona.
      · mes en curso o futuro → `nomina.proyectada`: desde el CONTRATO. Un mes
        que no terminó no tiene todas sus marcaciones, y pedirle el número a las
        horas devolvería la parte trabajada hasta hoy como si fuera el mes
        entero — que es la mitad del sueldo dicha con cara de total.

    EL MONTO ES `costo_empleador`, NO EL NETO. Es lo que sale del negocio:
    devengado + auxilio + aportes + prestaciones, ~1,55 a 1,69 veces el sueldo.
    Es también el número que reemplaza al calculado en el P&L, que solo tiene el
    devengado (ver `rentabilidad._nomina_del_periodo`: lo cargado a mano gana
    justamente porque trae adentro lo que el cálculo declara que no tiene).

    LÍMITE DECLARADO DEL FLUJO: la obligación entera vence el día de pago, pero
    en la realidad ese día sale el NETO y los aportes de PILA se giran en los
    primeros días del mes siguiente. O sea que el flujo proyectado ve salir la
    plata unos días ANTES de lo que sale. Es la dirección prudente para un punto
    de quiebre y por eso se deja así; la apertura viaja en la respuesta
    (`detalle`) para que la pantalla pueda decirlo. Partirla en dos obligaciones
    sería inventar una fecha de PILA que nadie declaró.

    IDEMPOTENTE Y ATÓMICA sobre el mes de devengo: si ya hay una obligación viva
    de nómina devengada en ese mes —corporativa o de una sede— se devuelve la que
    hay con `ya_existia: true` y no se crea nada. Dos taps no pagan la nómina dos
    veces. La comprobación y el alta viajan en la MISMA transacción, sin commit
    en el medio; queda una ventana teórica si dos admins aprietan el botón en el
    mismo instante, que se cerraría con un índice único parcial en la tabla —no
    se agrega acá porque `create_all` no toca tablas que ya existen y en
    producción no llegaría nunca.
    """
    desde, hasta = nomina_svc.rango_mes(anio, mes)

    ya = _obligacion_de_nomina_del_mes(db, desde, hasta)
    if ya is not None:
        return {**_con_pagos(db, ya), "ya_existia": True,
                "fuente": None, "detalle": None}

    cat = db.query(CostoCategoria).filter(
        CostoCategoria.clave == CLAVE_CATEGORIA_NOMINA).first()
    if cat is None:
        # El catálogo se siembra al arrancar; llegar acá es una base a la que le
        # falta la siembra, no un error del dueño. Se le dice qué falta.
        raise HTTPException(
            400, "No existe la categoría «Nómina» en el catálogo de costos. "
                 "Creala en Costos → Categorías antes de agendar la nómina.")
    if not cat.activa:
        raise HTTPException(
            400, f"La categoría «{cat.nombre}» está desactivada — reactivala para "
                 "poder agendar la nómina.")

    # LA FUENTE LA DECIDE EL MES DEVENGADO, no la fecha de pago ni el mes de hoy.
    mes_terminado = hasta < hoy_col()
    fuente = "real" if mes_terminado else "contrato"
    calculo = (nomina_svc.consolidada(db, anio, mes) if mes_terminado
               else nomina_svc.proyectada(db, anio, mes))
    totales = calculo["totales"]
    # EDITABLE ANTES DE CONFIRMAR: si la pantalla manda un monto, manda ese. El
    # cálculo es un estimado declarado (no tiene retención en la fuente, embargos
    # ni el redondeo de PILA) y el dueño tiene la liquidación del contador; que
    # el sistema le imponga su número sería confiar más en la estimación que en
    # el papel.
    valor = (_validar_monto(monto) if monto is not None
             else round(float(totales["total_costo_empleador"]), 2))
    if valor <= 0:
        # Un cero acá es «nadie cargó los sueldos», no «la nómina no cuesta».
        # Crear la obligación en $0 la dejaría marcada como cargada y APAGARÍA el
        # cálculo de ese mes en el P&L (ver `_nomina_del_periodo`): el costo
        # laboral pasaría a valer cero por haber apretado un botón.
        raise HTTPException(
            400, "El cálculo de la nómina da $0: no hay sueldos cargados en "
                 "Contratos. Cargalos primero, o escribí el monto a mano — "
                 "agendar $0 apagaría el costo laboral de ese mes en el P&L.")

    devengo = hasta                                    # último día del mes devengado
    vencimiento = fecha_de_pago_nomina(db, anio, mes)  # el día que sale la plata
    concepto = f"Nómina {MESES_ES[int(mes) - 1]} {int(anio)}"

    obligacion = Obligacion(
        # CORPORATIVA (tienda_id NULL), igual que el arriendo. La nómina de una
        # persona no se parte entre las sedes en las que cubrió —se probó y el
        # redondeo no cerraba— y además una corporativa apaga el cálculo del mes
        # en TODAS las sedes, que es lo que corresponde a un pago que cubre a
        # todo el mundo.
        tienda_id=None,
        categoria_id=cat.id,
        concepto=_validar_concepto(concepto),
        beneficiario=None,
        monto=valor,
        fecha_devengo=devengo,
        fecha_vencimiento=vencimiento,
        # Mensual como METADATA, igual que el arriendo: `repetir_obligacion` es
        # lo que crea la del mes que viene, y lo aprieta el dueño.
        recurrencia="mensual",
        nota=(f"Agendada desde nómina ({'lo trabajado' if mes_terminado else 'proyección del contrato'}): "
              f"{len(calculo['personas'])} personas, "
              f"neto ${totales['total_neto']:,.0f} + aportes y prestaciones."),
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(obligacion)
    db.flush()
    audit.registrar(
        db, accion="agendar_nomina", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=None,
        datos_despues={"anio": int(anio), "mes": int(mes), "fuente": fuente,
                       "monto": valor, "monto_calculado": totales["total_costo_empleador"],
                       "monto_editado": monto is not None,
                       "fecha_devengo": devengo, "fecha_vencimiento": vencimiento,
                       "personas": len(calculo["personas"])},
    )
    db.commit()
    db.refresh(obligacion)
    return {
        **_serializar(obligacion, []),
        "ya_existia": False,
        "fuente": fuente,
        # La apertura del monto, para que la pantalla pueda explicar por qué el
        # costo es tanto más grande que la suma de los sueldos —y para que se vea
        # que lo que sale el día de pago es el NETO, no el total.
        "detalle": {
            "personas": len(calculo["personas"]),
            "sin_sueldo": totales["sin_sueldo"],
            "total_devengado": totales["total_devengado"],
            "total_auxilio": totales["total_auxilio"],
            "total_deducciones": totales["total_deducciones"],
            "total_neto": totales["total_neto"],
            "total_costo_empleador": totales["total_costo_empleador"],
            "monto_calculado": round(float(totales["total_costo_empleador"]), 2),
            "monto_editado": monto is not None,
            "advertencias": calculo["advertencias"],
        },
    }


# ── Agenda unificada (Fase 2) ───────────────────────────────────────────────
#
# La única lista de "qué hay que pagar esta semana", mezclando el proveedor de
# leche con el arriendo. Es la UNIÓN DE DOS CONSULTAS, jamás una tabla copiada:
# FacturaCompra sigue siendo la ÚNICA verdad de la deuda con proveedores y NO se
# crean obligaciones espejo. Copiar esa deuda acá daría dos verdades sobre la
# misma plata — exactamente lo que este diseño evita.

def _fecha_proyectada(f: FacturaCompra) -> tuple:
    """(día Colombia en que toca pagar la factura, de dónde salió esa fecha).

    Precedencia = COALESCE(fecha_programada, fecha_vencimiento,
    fecha_recibido + plazo_dias): lo que el dueño DECIDIÓ manda sobre lo que el
    proveedor exige, y lo exigido manda sobre lo derivado del plazo.

    Sin ninguna de las tres devuelve (None, ''): la factura NO se agenda. No se
    inventa un vencimiento — no hay tabla maestra de proveedores de donde sacar un
    plazo (FacturaCompra.proveedor es un String suelto), así que las históricas
    entran a la agenda recién cuando alguien les carga el plazo a mano.
    """
    if f.fecha_programada is not None:
        return dia_col(f.fecha_programada), "programada"
    if f.fecha_vencimiento is not None:
        return dia_col(f.fecha_vencimiento), "vencimiento"
    if f.plazo_dias is not None and f.fecha_recibido is not None:
        return dia_col(f.fecha_recibido) + timedelta(days=int(f.plazo_dias)), "plazo"
    return None, ""


CLAVE_GRUPO_FACTURAS = "facturas"


def get_agenda(db: Session, desde: date | None = None, hasta: date | None = None,
               tienda_id: int | None = None) -> dict:
    """Facturas con saldo + obligaciones con saldo, ordenadas por fecha de pago.

    El monto de cada ítem es el SALDO, nunca el total: la agenda responde "cuánta
    plata falta", no "cuánto se facturó".

    Filtro de sede, con la misma regla que `listar_obligaciones`: sin `tienda_id`
    entra TODO —las obligaciones corporativas (tienda_id NULL) incluidas, una sola
    vez—; con `tienda_id` entra SOLO esa sede. Repartir las corporativas entre las
    sedes las duplicaría y el total de la agenda dejaría de cuadrar.

    Devuelve TRES cosas y no una:

    - `items`: lo agendado, con fecha. Es lo único que la proyección consume.
    - `sin_fecha`: las obligaciones con saldo y SIN fecha de vencimiento. "Vence"
      es opcional en el formulario, así que el caso normal —cargar lo obligatorio
      y nada más— producía una pantalla vacía y la conclusión de que el módulo no
      guarda nada. No se les inventa un vencimiento (no hay de dónde sacarlo) ni
      entran al total ni a la proyección: se muestran aparte, para que se les
      pueda poner fecha. El rango desde/hasta NO se les aplica: no tienen fecha
      contra la cual filtrar, y esconderlas por un rango sería volver al mismo bug.
    - `por_categoria`: cuánta plata hay de nómina, de arriendo, de servicios. La
      agenda rotula cada fila por TIPO ('Proveedor' / 'Costo fijo'), así que sin
      esto las palabras que el dueño busca no aparecen en ninguna pantalla.
    """
    hoy = hoy_col()
    items: list = []

    # 1) Facturas de proveedor. El rango se filtra en Python y no en SQL porque la
    #    fecha proyectada puede ser derivada (fecha_recibido + plazo_dias) y esa
    #    suma no es portable entre SQLite y Postgres.
    q = db.query(FacturaCompra).filter(
        FacturaCompra.valor_total - func.coalesce(FacturaCompra.valor_pagado, 0) > 0)
    if tienda_id is not None:
        q = q.filter(FacturaCompra.tienda_id == tienda_id)
    for f in q.all():
        fecha, origen = _fecha_proyectada(f)
        if fecha is None:
            continue
        if (desde is not None and fecha < desde) or (hasta is not None and fecha > hasta):
            continue
        items.append({
            "tipo": "factura",
            "id": f.id,
            "concepto": f.proveedor,
            "beneficiario": f.proveedor,
            "referencia": f.numero_factura,
            "tienda_id": f.tienda_id,
            "tienda_nombre": f.tienda.nombre if f.tienda else None,
            "monto": round(float(f.valor_total) - float(f.valor_pagado or 0), 2),
            "fecha": fecha,
            "origen_fecha": origen,
            "vencida": fecha < hoy,
            "categoria": None,   # las facturas no pasan por el catálogo de costos
            "categoria_nombre": None,
        })

    # 2) Obligaciones (arriendo, nómina, servicios). Se piden TODAS las vivas de la
    #    sede en UNA query y se parten en Python entre agendadas y sin fecha: dos
    #    queries casi iguales se desincronizarían en el primer filtro que cambie.
    qo = db.query(Obligacion).filter(Obligacion.anulada == False)  # noqa: E712
    if tienda_id is not None:
        qo = qo.filter(Obligacion.tienda_id == tienda_id)
    filas = qo.all()
    ids = [o.id for o in filas]
    pagos_por_obligacion = _pagos_vivos(db, ids)
    # LO QUE YA SALIÓ DEL BANCO TAMBIÉN CUENTA COMO PAGADO, y este es EL lugar
    # donde importa: `items` es lo único que consume la proyección. Sin esto, el
    # débito que el dueño teclea contra el extracto baja el saldo y la obligación
    # sigue proyectada como salida futura — la misma plata dos veces, y el día en
    # que se queda sin plata sale antes de lo real.
    banco_por_obligacion = _salidas_banco_por_obligacion(db, ids)
    sin_fecha: list = []
    for o in filas:
        pagado = sum(float(p.monto or 0) for p in pagos_por_obligacion.get(o.id, []))
        cubierto = cubierto_de(pagado, banco_por_obligacion.get(o.id, 0.0))
        saldo = round(float(o.monto or 0) - cubierto, 2)
        if saldo <= 0:   # ya pagada: no es algo que pagar
            continue
        fecha = o.fecha_vencimiento
        comun = {
            "tipo": "obligacion",
            "id": o.id,
            "concepto": o.concepto,
            "beneficiario": o.beneficiario,
            "referencia": None,
            "tienda_id": o.tienda_id,
            "tienda_nombre": o.tienda.nombre if o.tienda else None,
            "monto": saldo,
            "categoria": o.categoria.clave if o.categoria else None,
            "categoria_nombre": o.categoria.nombre if o.categoria else None,
        }
        if fecha is None:
            # Sin fecha de pago no se puede AGENDAR, pero tampoco puede desaparecer:
            # el devengo es lo único que ubica el costo en el tiempo y se manda para
            # que la pantalla ofrezca ponerle la fecha que falta.
            sin_fecha.append({**comun, "fecha": None, "origen_fecha": "",
                              "vencida": False,
                              "fecha_devengo": o.fecha_devengo})
            continue
        if (desde is not None and fecha < desde) or (hasta is not None and fecha > hasta):
            continue
        items.append({**comun, "fecha": fecha, "origen_fecha": "vencimiento",
                      "vencida": fecha < hoy})

    # tipo+id como desempate: dos cosas que vencen el mismo día tienen que salir
    # siempre en el mismo orden (si no, la lista "salta" entre cargas).
    items.sort(key=lambda i: (i["fecha"], i["tipo"], i["id"]))
    # Lo más viejo primero: es lo que lleva más tiempo sin que nadie lo feche.
    sin_fecha.sort(key=lambda i: (i["fecha_devengo"], i["id"]))
    total = round(sum(i["monto"] for i in items), 2)
    vencido = round(sum(i["monto"] for i in items if i["vencida"]), 2)
    total_sin_fecha = round(sum(i["monto"] for i in sin_fecha), 2)
    return {
        "items": items,
        # Fuera de `items` a propósito: `_salidas_por_dia` (la proyección) consume
        # `items` y nada más, así que lo sin fechar no puede inventar ni esconder
        # un punto de quiebre.
        "sin_fecha": sin_fecha,
        "por_categoria": _agenda_por_categoria(items),
        "totales": {
            "monto": total, "vencido": vencido, "n": len(items),
            # Aparte del total, nunca sumado: si entrara, el dueño leería como
            # "agendado para este período" plata que no tiene día de pago.
            "sin_fecha": total_sin_fecha, "n_sin_fecha": len(sin_fecha),
        },
    }


def _agenda_por_categoria(items: list) -> list:
    """Cuánta plata hay por categoría en lo AGENDADO. Las facturas no pasan por el
    catálogo de costos, así que van a su propio grupo en vez de caer en un
    "(sin categoría)" que se leería como un costo fijo mal cargado."""
    acc: dict = {}
    for i in items:
        if i["tipo"] == "factura":
            clave, nombre = CLAVE_GRUPO_FACTURAS, "Facturas de proveedor"
        else:
            clave = i.get("categoria") or "otros"
            nombre = i.get("categoria_nombre") or "Sin categoría"
        g = acc.setdefault(clave, {"clave": clave, "nombre": nombre, "monto": 0.0, "n": 0})
        g["monto"] += i["monto"]
        g["n"] += 1
    for g in acc.values():
        g["monto"] = round(g["monto"], 2)
    # Por plata, que es como se lee: "qué me está costando más este mes".
    return sorted(acc.values(), key=lambda g: (-g["monto"], g["clave"]))


# ── Pagos ───────────────────────────────────────────────────────────────────

def registrar_pago(db: Session, data, usuario_id: int,
                   barista_id: int | None = None,
                   barista_nombre: str | None = None) -> dict:
    """El pago es lo que hace útil todo el módulo: fecha_pago es EL DÍA QUE SALIÓ
    LA PLATA, un dato que hoy no existe en ninguna tabla del sistema."""
    tiene_obligacion = data.obligacion_id is not None
    tiene_factura = data.factura_id is not None
    if tiene_obligacion and tiene_factura:
        raise HTTPException(400, "El pago apunta a una obligación O a una factura, no a las dos")
    if not tiene_obligacion and not tiene_factura:
        raise HTTPException(400, "El pago debe apuntar a una obligación o a una factura")
    if data.metodo not in METODOS_PAGO:
        raise HTTPException(400, "Método inválido: efectivo | transferencia | tarjeta | cheque | otro")
    monto = _validar_monto(data.monto)

    tienda_id = None
    if tiene_obligacion:
        obligacion = db.query(Obligacion).filter(Obligacion.id == data.obligacion_id).first()
        if not obligacion:
            raise HTTPException(404, "Obligación no encontrada")
        if obligacion.anulada:
            raise HTTPException(400, "La obligación está anulada — no admite pagos")
        tienda_id = obligacion.tienda_id   # snapshot copiado del padre

    pago = Pago(
        obligacion_id=data.obligacion_id,
        factura_id=data.factura_id,
        tienda_id=tienda_id,
        monto=monto,
        fecha_pago=data.fecha_pago,
        metodo=data.metodo,
        imagen_soporte_url=data.imagen_soporte_url,
        nota=data.nota,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(pago)
    db.flush()
    audit.registrar(
        db, accion="registrar_pago_costo", tabla="pagos",
        registro_id=pago.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"obligacion_id": pago.obligacion_id, "factura_id": pago.factura_id,
                       "monto": monto, "fecha_pago": pago.fecha_pago, "metodo": pago.metodo},
    )
    db.commit()
    db.refresh(pago)
    return _serializar_pago(pago)


def anular_pago(db: Session, pago_id: int, usuario_id: int, motivo: str | None = None) -> dict:
    """Baja lógica del pago. Al dejar de contar, la obligación vuelve sola al
    estado que corresponda (de 'pagada' a 'parcial', por ejemplo): el estado se
    deriva, así que no hay ningún contador que corregir a mano."""
    pago = db.query(Pago).filter(Pago.id == pago_id).first()
    if not pago:
        raise HTTPException(404, "Pago no encontrado")
    if not pago.anulado:
        pago.anulado = True
        if motivo:
            pago.nota = f"{pago.nota + ' — ' if pago.nota else ''}Anulado: {motivo}"
        audit.registrar(
            db, accion="anular_pago_costo", tabla="pagos",
            registro_id=pago.id, usuario_id=usuario_id, tienda_id=pago.tienda_id,
            datos_antes={"monto": float(pago.monto or 0), "fecha_pago": pago.fecha_pago},
            datos_despues={"motivo": motivo},
        )
        db.commit()
        db.refresh(pago)
    return _serializar_pago(pago)


# ── Adopción de egresos históricos (Fase 3) ─────────────────────────────────
#
# Los gastos fijos que YA se registraron como egreso suelto de caja ("Arriendo
# local", texto libre) se pueden ADOPTAR: nace una Obligacion devengada y un Pago
# espejo con `movimiento_caja_id`. El MovimientoCaja NO SE TOCA NI SE BORRA — el
# cuadre del turno tiene que seguir dando exactamente lo mismo.
#
# La plata cambia de bolsa, no de tamaño: el P&L excluye los movimientos adoptados
# de la query de gastos y suma las obligaciones devengadas. Las dos mitades son
# inseparables; con una sola, el total de gastos se movería.


def _es_egreso_de_compra(db: Session, movimiento_id: int) -> bool:
    """¿El concepto matchea un patrón reservado de pago a proveedor? Se evalúa con
    el MISMO `LIKE` en SQL que usa el P&L, no con una reimplementación en Python:
    dos motores de match distintos se desincronizan en el primer caso raro."""
    return db.query(MovimientoCaja.id).filter(
        MovimientoCaja.id == movimiento_id,
        or_(*[MovimientoCaja.concepto.like(p) for p in _CONCEPTOS_COMPRA]),
    ).first() is not None


def _query_egresos_adoptables(db: Session):
    """Egresos de caja que PODRÍAN adoptarse: los mismos que el P&L cuenta hoy como
    gasto de texto libre. Excluye lo ligado a compras por las dos vías (factura_id
    estructural + concepto reservado histórico)."""
    return (
        db.query(MovimientoCaja, CajaTurno.tienda_id)
        .join(CajaTurno, MovimientoCaja.caja_turno_id == CajaTurno.id)
        .filter(
            MovimientoCaja.tipo == TipoMovCajaEnum.egreso,
            MovimientoCaja.factura_id.is_(None),
            not_(or_(*[MovimientoCaja.concepto.like(p) for p in _CONCEPTOS_COMPRA])),
        )
    )


def _subquery_adoptados(db: Session):
    """movimiento_caja_id de los pagos VIVOS. Se usa como SUBCONSULTA y nunca como
    lista de ids: en una caja con años de movimientos, un `IN (...)` explícito
    revienta el tope de variables de SQLite."""
    return (db.query(Pago.movimiento_caja_id)
              .filter(Pago.movimiento_caja_id.isnot(None), Pago.anulado.is_(False))
              .distinct().subquery())


def listar_egresos_sin_adoptar(db: Session, *, desde: date | None = None,
                               hasta: date | None = None,
                               tienda_id: int | None = None,
                               limite: int = 200) -> dict:
    """Bandeja de "egresos sin categorizar": lo que el P&L todavía muestra como texto
    libre. Solo lectura — adoptar es una acción aparte y explícita."""
    d_utc, h_utc = rango_col_utc(desde or (hoy_col() - timedelta(days=90)), hasta)
    adoptados = _subquery_adoptados(db)
    q = _query_egresos_adoptables(db).filter(
        MovimientoCaja.fecha >= d_utc,
        MovimientoCaja.fecha <= h_utc,
        MovimientoCaja.id.notin_(db.query(adoptados.c.movimiento_caja_id)),
    )
    if tienda_id is not None:
        q = q.filter(CajaTurno.tienda_id == tienda_id)
    filas = q.order_by(MovimientoCaja.fecha.desc(), MovimientoCaja.id.desc()).limit(
        max(1, min(int(limite or 200), 500))).all()

    tiendas = {t.id: t.nombre for t in db.query(Tienda).all()}
    egresos = [{
        "id": mov.id,
        "concepto": mov.concepto,
        "valor": round(float(mov.valor or 0), 2),
        # El día de NEGOCIO en que se tecleó. Es el devengo por defecto y también lo
        # que la UI muestra para que el admin decida si hay que corregirlo.
        "fecha": dia_col(mov.fecha) if mov.fecha else None,
        "tienda_id": tid,
        "tienda_nombre": tiendas.get(tid),
        "barista_nombre": mov.barista_nombre,
    } for mov, tid in filas]
    return {
        "egresos": egresos,
        "totales": {"monto": round(sum(e["valor"] for e in egresos), 2), "n": len(egresos)},
    }


def adoptar_egreso(db: Session, movimiento_id: int, categoria_id: int, usuario_id: int,
                   fecha_devengo: date | None = None, concepto: str | None = None,
                   beneficiario: str | None = None, nota: str | None = None,
                   barista_id: int | None = None,
                   barista_nombre: str | None = None) -> dict:
    """Convierte un egreso suelto de caja en obligación devengada + pago espejo.

    NO cambia ningún total: el MovimientoCaja queda intacto (el turno cuadra igual)
    y el P&L lo deja de contar como gasto de texto libre justo cuando empieza a
    contar la obligación. Lo único que cambia es dónde aparece la plata.

    `fecha_devengo` es un OVERRIDE EXPLÍCITO y nunca silencioso. Por defecto vale
    `dia_col(mov.fecha)`, pero `mov.fecha` es cuándo se TECLEÓ el egreso, no cuándo
    salió la plata: `MovimientoCajaRequest` (schemas/caja.py) no acepta fecha y el
    modelo la fija con `default=datetime.utcnow`, así que registrar un pago de un
    día pasado es imposible por cualquier camino. Si el arriendo de julio se tecleó
    en agosto, corregir esta fecha MUEVE EL COSTO DE MES en el P&L — por eso la UI
    lo muestra editable y avisa, en vez de decidirlo sola.

    `fecha_pago` del espejo, en cambio, siempre es `dia_col(mov.fecha)`: la plata
    salió de ESA caja ese día, y eso no se corrige desde acá.
    """
    mov = db.query(MovimientoCaja).filter(MovimientoCaja.id == movimiento_id).first()
    if not mov:
        raise HTTPException(404, "Movimiento de caja no encontrado")

    tipo = getattr(mov.tipo, "value", mov.tipo)
    if tipo != "egreso":
        raise HTTPException(400, "Solo se adoptan egresos — un ingreso no es un costo")

    # Guarda 1: vínculo ESTRUCTURAL con una compra. La deuda ya vive en
    # FacturaCompra y adoptarla crearía una obligación espejo de esa misma plata.
    if mov.factura_id is not None:
        raise HTTPException(
            400, "Este egreso es el pago de una factura de proveedor — ya está contado "
                 "en Compras. Manejalo desde Pagos a Proveedores.")

    # Guarda 2: filas ANTERIORES a la columna factura_id, donde el único vínculo con
    # la compra es el concepto reservado que escribe services/facturas.py.
    if _es_egreso_de_compra(db, mov.id):
        raise HTTPException(
            400, "El concepto de este egreso es de pago a proveedor — ya está contado "
                 "en Compras y adoptarlo lo contaría dos veces.")

    # Guarda 3: se adopta UNA sola vez. El servicio responde 409 en vez de dejar que
    # reviente el índice único parcial de la DB (que es la garantía final, no esta).
    ya = db.query(Pago).filter(Pago.movimiento_caja_id == mov.id).order_by(
        Pago.anulado, Pago.id).first()
    if ya is not None:
        if ya.anulado:
            raise HTTPException(
                409, "Este egreso ya se adoptó una vez y su pago fue anulado — la "
                     "adopción no se puede rehacer. Editá la obligación existente.")
        raise HTTPException(409, "Este egreso ya fue adoptado")

    cat = _validar_categoria(db, categoria_id)
    # La sede sale del turno del movimiento: así el P&L por sede no se mueve un peso.
    turno = db.query(CajaTurno).filter(CajaTurno.id == mov.caja_turno_id).first()
    tienda_id = turno.tienda_id if turno else None

    dia_mov = dia_col(mov.fecha) if mov.fecha else hoy_col()
    obligacion = Obligacion(
        tienda_id=tienda_id,
        categoria_id=cat.id,
        concepto=_validar_concepto(concepto or mov.concepto),
        beneficiario=(beneficiario or "").strip() or None,
        monto=_validar_monto(mov.valor),
        fecha_devengo=fecha_devengo or dia_mov,
        # Ya está pagada: no hay nada que agendar, así que no lleva vencimiento.
        fecha_vencimiento=None,
        nota=nota,
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(obligacion)
    db.flush()

    pago = Pago(
        obligacion_id=obligacion.id,
        factura_id=None,
        tienda_id=tienda_id,
        monto=float(obligacion.monto),
        fecha_pago=dia_mov,
        # Un egreso de caja es plata que salió del cajón, siempre.
        metodo="efectivo",
        movimiento_caja_id=mov.id,   # la llave anti-doble-conteo
        nota="Adopción del egreso de caja",
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(pago)
    db.flush()

    audit.registrar(
        db, accion="adoptar_egreso_caja", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_antes={"movimiento_caja_id": mov.id, "concepto": mov.concepto,
                     "valor": float(mov.valor or 0), "dia_movimiento": dia_mov},
        datos_despues={"categoria": cat.clave, "monto": float(obligacion.monto),
                       "fecha_devengo": obligacion.fecha_devengo,
                       "devengo_corregido": bool(fecha_devengo and fecha_devengo != dia_mov),
                       "pago_id": pago.id},
    )
    db.commit()
    db.refresh(obligacion)
    db.refresh(pago)
    return _serializar(obligacion, [pago],
                       _salidas_banco_por_obligacion(db, [obligacion.id]).get(obligacion.id, 0.0))


def listar_pagos(db: Session, *, obligacion_id: int | None = None,
                 factura_id: int | None = None,
                 desde: date | None = None, hasta: date | None = None,
                 incluir_anulados: bool = False) -> list:
    """Pagos por fecha_pago — la vista de "qué plata salió" en un rango."""
    q = db.query(Pago)
    if obligacion_id is not None:
        q = q.filter(Pago.obligacion_id == obligacion_id)
    if factura_id is not None:
        q = q.filter(Pago.factura_id == factura_id)
    if desde is not None:
        q = q.filter(Pago.fecha_pago >= desde)
    if hasta is not None:
        q = q.filter(Pago.fecha_pago <= hasta)
    if not incluir_anulados:
        q = q.filter(Pago.anulado == False)  # noqa: E712
    return [_serializar_pago(p) for p in q.order_by(Pago.fecha_pago.desc(), Pago.id.desc()).all()]


# ── Flujo de caja proyectado (Fase 4) ───────────────────────────────────────
#
# El único número que ningún otro reporte del sistema puede producir: EL DÍA EN
# QUE SE ACABA LA PLATA. Ventas, P&L y agenda miran para atrás o miran una sola
# dimensión; esto cruza lo que hay con lo que entra y lo que sale.
#
#   saldo_proyectado(D) = caja_hoy + Σ entradas(d) − Σ salidas(d),  d en (hoy, D]
#
# Las tres reglas anti-doble-conteo que sostienen la fórmula:
#
#   1. las consignaciones NO son entrada — mueven plata del cajón al banco: no se
#      suman como entrada Y se restan del efectivo del turno, porque si no la
#      misma plata quedaría contada en la registradora y otra vez en el banco;
#   2. los MovimientoCaja egreso YA registrados NO se restan como salida futura
#      — son pasado y ya están descontados dentro del efectivo de la registradora;
#   3. la deuda con proveedores se lee de la agenda (unión de dos consultas) y
#      nunca de una copia: FacturaCompra sigue siendo su única verdad.
#
# Y una cuarta, del mismo tipo, para la plata que YA está en el banco:
#
#   4. el saldo bancario se lee del LIBRO (services/banco.py: ancla + los
#      movimientos que el dueño teclea), nunca del ancla cruda de `configuracion`
#      ni de una suma propia. El libro es la única matemática del saldo, y estas
#      dos pantallas están a un toque una de la otra: con el ancla sola, una
#      salida de 3.000.000 ya tecleada bajaba el libro y no bajaba la proyección,
#      así que el punto de quiebre se calculaba con plata que ya no estaba.

# EL HORIZONTE POR DEFECTO SE ANCLA A FIN DE MES, no a 30 días fijos.
#
# Los 30 días eran un número redondo que no coincide con ningún mes: parado en
# el 19 de agosto la serie terminaba el 18 de septiembre, mientras el piso de
# venta hablaba del 31 de agosto. El colchón —el mínimo de esa serie— miraba
# entonces una ventana distinta a la del piso, y las dos cifras de la MISMA
# pantalla contestaban preguntas de períodos diferentes sin decirlo.
#
# Ya no hay `HORIZONTE_DEFAULT`: un default constante es justamente lo que no
# puede existir acá, porque el horizonte correcto depende del día en que se
# pregunta. Lo calcula `dias_hasta_fin_de_mes`.
HORIZONTE_MAX = 180
SEMANAS_HISTORIA = 8          # 56 días = exactamente 8 muestras de cada día de semana
DIAS_SALDO_BANCO_VIGENTE = 7  # más viejo que esto y la respuesta se marca desactualizada
SALDO_BANCO_MAX = 1e12
CLAVE_RECOGIDAS_DESDE = "recogidas_desde"
CLAVE_SALDO_BANCO = "saldo_banco"
CLAVE_SALDO_BANCO_FECHA = "saldo_banco_fecha"
# La plata con la que el negocio no puede quedarse sin. Ver `leer_reserva_minima_caja`.
CLAVE_RESERVA_MINIMA_CAJA = "reserva_minima_caja"
# Lo que se queda el datáfono de cada venta con tarjeta, como fracción (0,025 =
# 2,5%). En `configuracion` y no quemada: es una tasa negociada con el
# adquirente, cambia sin deploy y hoy NADIE la cargó — ver `_leer_comision_datafono`.
CLAVE_COMISION_DATAFONO = "comision_datafono"


def _efectivo_en_registradora(db: Session, tienda_id: int) -> tuple:
    """(efectivo que hay AHORA en el cajón de la sede, de dónde salió el dato).

    Con turno abierto es la fórmula del cuadre —base_real + total_efectivo +
    ingresos − egresos, ver `registrar_cuadre_llegada` en services/caja.py—
    MENOS lo ya consignado, que es plata que salió del cajón y hoy está en el
    banco. La reserva de la caja fuerte NO entra: se declara aparte al abrir el
    turno (`CajaTurno.caja_fuerte`) justamente para que no se mezcle con el
    efectivo operativo. Se replica acá porque
    allá vive inline dentro de `registrar_cuadre_llegada` y no hay función que
    extraer sin tocar caja.py: si esa fórmula cambia, esta línea cambia en el
    mismo commit.

    Sin turno abierto manda el `efectivo_final_real` del ÚLTIMO TURNO CERRADO: el
    conteo físico del cierre. `cerrar_caja` NO crea ningún EntregaTurno —guarda el
    conteo en la columna del turno (services/caja.py:518)— y el único cierre que
    deja EntregaTurno es el del kiosko, y solo si hay imagen. Leer "el último
    EntregaTurno de cualquier tipo" devolvía entonces el cuadre de LLEGADA: la
    base de la mañana. De noche, con la sede cerrada —justo cuando el dueño mira—
    una sede que abrió con 100.000 y cerró con 1.000.000 volvía a 100.000 e
    inventaba un punto de quiebre con alerta roja en el Dashboard.

    El EntregaTurno queda solo como respaldo, para el turno que cerró sin conteo
    (efectivo_final_real NULL) y para los cierres viejos anteriores a la columna.
    Ahí no se descuentan consignaciones: el número es un CONTEO FÍSICO y lo que ya
    se depositó no estaba en el cajón cuando se contó. Restarlo otra vez subestima
    la caja, que es el error que fabrica quiebres falsos.

    Y desde agosto hay una TERCERA salida del cajón que no es ni un egreso ni una
    consignación: el dueño pasa y RECOGE el efectivo (`RecogidaEfectivo`). Esa
    plata se va a su mano —de ahí sale a pagar proveedores de contado, que nunca
    tocan el banco— y el cajón seguía contándola como si estuviera. Se resta en
    las dos ramas que sí tienen un instante contra el cual acotarla, y con el
    criterio OPUESTO en cada una: en `turno_abierto` desde la apertura (la fórmula
    del cuadre no sabe nada de la recogida), y en `ultimo_cierre` solo lo POSTERIOR
    al cierre, porque el conteo físico del cierre ya la refleja.
    """
    turno = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()
    if turno is not None:
        ingresos = db.query(func.sum(MovimientoCaja.valor)).filter(
            MovimientoCaja.caja_turno_id == turno.id,
            MovimientoCaja.tipo == "ingreso",
        ).scalar() or 0.0
        egresos = db.query(func.sum(MovimientoCaja.valor)).filter(
            MovimientoCaja.caja_turno_id == turno.id,
            MovimientoCaja.tipo == "egreso",
        ).scalar() or 0.0
        # Deliberado, y la razón es el doble conteo: `Consignacion` no genera
        # MovimientoCaja, así que la plata ya depositada seguiría contando en la
        # registradora Y otra vez dentro del `saldo_banco` que declara el dueño.
        # Solo las REALIZADAS, mismo criterio que abrir_caja (caja.py:257-260).
        consignado = db.query(func.sum(Consignacion.valor)).filter(
            Consignacion.caja_turno_id == turno.id,
            Consignacion.estado == EstadoConsignacionEnum.realizada,
        ).scalar() or 0.0
        # LO QUE EL DUEÑO YA SE LLEVÓ de este turno. No se pisa con `consignado` y
        # la razón está en de dónde sale cada plata: la consignación de la BARISTA
        # cuelga de su `caja_turno_id` y sí salió del cajón; la que hace ÉL sale de
        # su MANO —ya recogida— y no tiene turno, así que no entra en esa suma. Sin
        # esta resta el cajón mostraba la venta entera del día aunque la plata ya
        # se hubiera ido: $1.000.000 en pantalla donde había $600.000.
        #
        # Se acota por `creado_en` (instante) y no por `fecha` (día): un turno
        # abierto de madrugada y una recogida del mismo día calendario anterior a
        # la apertura pertenecen a la caja de AYER, y `fecha >= ...` no sabe
        # distinguirlas. `fecha_apertura` la llena el default de la columna en todo
        # camino de apertura; si aun así llegara NULL el filtro no matchea y no se
        # resta nada — el único caso en que esto queda del lado optimista.
        recogido = db.query(func.sum(RecogidaEfectivo.monto)).filter(
            RecogidaEfectivo.tienda_id == tienda_id,
            RecogidaEfectivo.creado_en >= turno.fecha_apertura,
        ).scalar() or 0.0
        # La reserva de la caja fuerte NO entra: se declara al abrir
        # (`CajaTurno.caja_fuerte`) y queda guardada aparte, no pasa por la
        # registradora. Misma fórmula que el cuadre de services/caja.py.
        esperado = (float(turno.base_real or 0) + float(turno.total_efectivo or 0)
                    + float(ingresos) - float(egresos)
                    - float(consignado) - float(recogido))
        return round(esperado, 2), "turno_abierto"

    # `fecha_cierre.isnot(None)` no es cosmético: SQLite y Postgres ordenan los
    # NULL al revés en un ORDER BY DESC, así que un turno cerrado sin fecha
    # (legacy) se colaría como "el último" en un motor y no en el otro.
    cerrado = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.cerrado,
        CajaTurno.fecha_cierre.isnot(None),
    ).order_by(CajaTurno.fecha_cierre.desc(), CajaTurno.id.desc()).first()
    if cerrado is not None and cerrado.efectivo_final_real is not None:
        # ESTRICTAMENTE mayor, y no es un detalle de borde: `efectivo_final_real`
        # es un CONTEO FÍSICO. Lo que el dueño se llevó ANTES de que la barista
        # contara ya no estaba sobre la mesa cuando ella contó, así que restarlo
        # otra vez subestima la caja y fabrica el quiebre falso contra el que
        # advierte el docstring de arriba. Lo único que el conteo no puede saber
        # es lo que él recogió DESPUÉS de cerrar —sede cerrada, plata quieta, él
        # pasa a la noche— y eso es exactamente lo que se descuenta acá.
        # `fecha_cierre` nunca es NULL en esta rama: la consulta ya lo exige.
        recogido = db.query(func.sum(RecogidaEfectivo.monto)).filter(
            RecogidaEfectivo.tienda_id == tienda_id,
            RecogidaEfectivo.creado_en > cerrado.fecha_cierre,
        ).scalar() or 0.0
        return round(float(cerrado.efectivo_final_real) - float(recogido), 2), "ultimo_cierre"

    ultima = db.query(EntregaTurno).filter(
        EntregaTurno.tienda_id == tienda_id,
    ).order_by(EntregaTurno.fecha_hora.desc(), EntregaTurno.id.desc()).first()
    if ultima is not None:
        return round(float(ultima.efectivo_real or 0), 2), "ultimo_cuadre"
    return 0.0, "sin_datos"


def desde_recogidas(db: Session) -> date | None:
    """EL DÍA EN QUE ARRANCÓ EL RÉGIMEN NUEVO, y por qué NO se deriva de las filas.

    La primera versión sacaba esta fecha de `MIN(RecogidaEfectivo.fecha)`, y eso
    tenía un agujero que dos lectores independientes encontraron por separado:
    las recogidas se pueden BORRAR. Con la ventana derivada de las filas vivas,
    borrar la más vieja la corría hacia adelante y los pagos en efectivo que
    quedaban adentro DEJABAN de restarse. Medido: recogida de $1.000 el 1-ago,
    pago de $400.000 el 2-ago, recogida de $500.000 el 5-ago. En mano: $101.000.
    El dueño borra la de $1.000 para corregirla y la pantalla salta a $500.000 —
    aparecen $399.000 que nunca existieron, hacia el lado tranquilizador.

    El espejo era igual de caro: cargar una recogida retroactiva corría la ventana
    hacia ATRÁS y arrastraba pagos en efectivo del mundo viejo, cuando la barista
    consignaba y esta bolsa no existía. Una recogida de $10.000 mal fechada podía
    hundir la mano un millón en rojo.

    Así que el ancla vive en `configuracion`, igual que el saldo del banco: se
    escribe UNA vez, con la primera recogida, y no se mueve porque alguien borre
    o agregue una fila. Es una fecha de RÉGIMEN, no un mínimo.

    Tolera basura guardada por la misma razón que `_leer_saldo_banco`: la fila es
    TEXTO y un valor de otra versión no puede tumbar la pantalla del dueño.

    Devuelve None cuando el régimen todavía no arrancó — y eso es lo que hace que
    el bucket entero sea None y no 0.0.
    """
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_RECOGIDAS_DESDE).first()
    if fila is None or not (fila.valor or "").strip():
        return None
    try:
        return date.fromisoformat(fila.valor.strip())
    except (TypeError, ValueError):
        return None


def fijar_desde_recogidas(db: Session, fecha: date) -> date:
    """Deja el ancla puesta, y la mueve SOLO HACIA ATRÁS. Devuelve la vigente.

    El ancla es un trinquete de una sola dirección, y cada dirección tiene su
    razón:

    · HACIA ATRÁS SÍ. Él carga la pasada de hoy y mañana se acuerda de la de
      ayer: esa recogida es real y el período que se sigue empieza antes. Negarlo
      dejaría plata suya afuera de la cuenta.
    · HACIA ADELANTE NUNCA. Ahí estaba el agujero: con la ventana derivada del
      mínimo de las filas, BORRAR la recogida más vieja la corría hacia adelante
      y los pagos en efectivo que quedaban adentro dejaban de restarse. Medido:
      recogida de $1.000 el 1-ago, pago de $400.000 el 2-ago, recogida de
      $500.000 el 5-ago. En mano $101.000; borra la de $1.000 para corregirla y
      la pantalla salta a $500.000. Aparecen $399.000 que no existen, hacia el
      lado tranquilizador.

    Que solo baje corta ese salto de raíz: borrar no puede achicar el período.
    Lo que sí hay que cuidar del lado de atrás —una recogida mal fechada meses
    antes, que arrastraría los pagos del mundo viejo— lo mira el handler con
    `arrastre_al_mover_desde` antes de aceptar.
    """
    vigente = desde_recogidas(db)
    if vigente is not None and vigente <= fecha:
        return vigente

    arranque = fecha if vigente is None else min(vigente, fecha)
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_RECOGIDAS_DESDE).first()
    if fila is None:
        db.add(Configuracion(clave=CLAVE_RECOGIDAS_DESDE, valor=arranque.isoformat()))
    else:
        fila.valor = arranque.isoformat()
    return arranque


def arrastre_al_mover_desde(db: Session, nueva: date, actual: date) -> dict:
    """Qué se metería en la cuenta si el régimen arrancara en `nueva` y no en `actual`.

    Correr el arranque hacia atrás no es gratis: los pagos en efectivo y las
    consignaciones que caen en el tramo que se abre pasan a restarse de la mano.
    Si ese tramo es de unos días, no hay nada — es el olvido normal de cargar la
    pasada de ayer. Si es de meses, lo que entra son pagos del MUNDO VIEJO, de
    cuando la barista consignaba y esta bolsa no existía. Medido: una recogida de
    $10.000 mal fechada seis meses atrás arrastraba un pago de $2.000.000 y
    hundía la mano en −$990.000.

    Devuelve el conteo y el monto de lo que entraría, para que el handler pueda
    decirle al dueño CONTRA QUÉ está chocando en vez de un «no se pudo».
    """
    pagos = db.query(func.count(Pago.id), func.sum(Pago.monto)).filter(
        Pago.metodo == "efectivo",
        Pago.movimiento_caja_id.is_(None),
        Pago.anulado == False,  # noqa: E712
        Pago.fecha_pago >= nueva,
        Pago.fecha_pago < actual,
    ).first()
    cons = db.query(func.count(Consignacion.id), func.sum(Consignacion.valor)).filter(
        Consignacion.estado == EstadoConsignacionEnum.realizada,
        Consignacion.caja_turno_id.is_(None),
        Consignacion.fecha >= inicio_dia_col_utc(nueva),
        Consignacion.fecha < inicio_dia_col_utc(actual),
    ).first()
    n = int(pagos[0] or 0) + int(cons[0] or 0)
    return {"n": n, "monto": round(float(pagos[1] or 0) + float(cons[1] or 0), 2)}


def _efectivo_en_mano(db: Session) -> dict:
    """LA TERCERA BOLSA: la plata que el dueño tiene EN LA MANO, ni en el cajón ni
    en el banco. Devuelve {"monto": float|None, "desde": date|None}.

    Desde agosto él recoge el efectivo de las sedes y desde ahí lo reparte: le paga
    a los proveedores que aceptan contado (esa plata NUNCA pasa por el banco) y
    consigna el resto. El sistema conocía las dos puntas del viaje y no el tramo
    del medio, así que la plata desaparecía de la vista entre que salía del cajón
    y entraba al banco. Lo que queda en ese tramo es:

        en_mano = Σ recogidas − Σ pagos en efectivo de su mano − Σ consignaciones suyas

    LAS DOS CONDICIONES DE EXCLUSIÓN SON EL CORAZÓN DE LA FÓRMULA:

      · `Pago.movimiento_caja_id IS NULL` — el pago NO salió de la registradora, o
        sea salió de su mano. Un egreso de caja adoptado ya está descontado dentro
        del efectivo del turno, y restarlo también acá sería contar la misma salida
        dos veces. NO ES UN FILTRO PREVENTIVO: `adoptar_egreso` (más arriba, en
        este mismo archivo) escribe esa columna en cada adopción, y escribe el pago
        con `metodo="efectivo"` — o sea que cae de lleno en los otros dos filtros.
        Sacar esta condición deja la mano corta por todo lo adoptado. El índice
        único parcial `uq_pago_movimiento_caja` existe justamente porque la columna
        se llena.
      · `Consignacion.caja_turno_id IS NULL` — la consignación la hizo ÉL desde su
        mano; la de la barista cuelga de su turno y ya bajó el cajón. Sin esta
        condición la misma plata se restaría de las dos bolsas.

    `anulado == False` en los pagos por la misma razón de fondo: un pago anulado no
    sacó plata de ninguna parte, así que ese efectivo sigue en su mano. Sin el
    filtro el bucket queda subestimado (dirección prudente, pero igual falso).

    `desde` es la fecha de la PRIMERA recogida registrada, y acota los tres
    términos: los pagos en efectivo y las consignaciones del dueño anteriores a
    esa fecha pertenecen al mundo viejo —cuando la barista consignaba y la plata
    iba directo del cajón al banco— y restarlos inventaría una mano en rojo.

    SIN NINGUNA RECOGIDA EL BUCKET NO EXISTE: `monto` vuelve None, NUNCA 0.0. Cero
    dice "él pasó y no le queda nada"; None dice "todavía no se registró ninguna
    pasada". Confundirlos es literalmente la familia de error que este módulo viene
    arrastrando —decidir con un dato que está CERCA del correcto— y acá el que
    decide es el dueño mirando si le alcanza la plata.
    """
    # ORDER BY + LIMIT 1 en vez de func.min(): sobre una columna Date, el mínimo
    # vuelve como string en SQLite y como `date` en Postgres según cómo el dialecto
    # tipe la función. La primera fila trae un `date` de verdad en los dos motores,
    # que es lo que después se compara contra `Pago.fecha_pago`.
    desde = desde_recogidas(db)
    if desde is None:
        return {"monto": None, "desde": None}

    # SIN NINGUNA RECOGIDA VIVA EL BUCKET NO EXISTE, aunque el ancla siga puesta.
    # El ancla resuelve que la VENTANA no se mueva al borrar una de varias; no
    # convierte en cero un bolsillo que nadie midió. Si borró la única que había
    # —un monto mal tecleado, el caso normal— volvemos a «no se sabe», que es la
    # verdad. Un 0.0 acá diría «pasó y no le quedó nada».
    if db.query(RecogidaEfectivo.id).first() is None:
        return {"monto": None, "desde": None}

    # Las TRES sumas se acotan con la MISMA ventana. Antes esta iba sin filtro
    # —«`desde` es la primera, así que ya está acotada por construcción»— y era
    # cierto solo mientras `desde` saliera del mínimo de estas mismas filas. Con
    # el ancla fija, una recogida anterior al régimen entraría acá y no en las
    # otras dos: sumaría de un lado sin restar del otro, que es la asimetría que
    # infla la bolsa. El handler igual las rechaza; esto es el cinturón.
    recogido = db.query(func.sum(RecogidaEfectivo.monto)).filter(
        RecogidaEfectivo.fecha >= desde).scalar() or 0.0

    pagado = db.query(func.sum(Pago.monto)).filter(
        Pago.metodo == "efectivo",
        Pago.movimiento_caja_id.is_(None),
        Pago.anulado == False,  # noqa: E712
        Pago.fecha_pago >= desde,
    ).scalar() or 0.0

    # `Consignacion.fecha` es un DateTime UTC y `desde` un día COLOMBIA: se
    # convierte el día al instante UTC en que empieza, en vez de comparar un
    # timestamp contra una fecha pelada. Sin esto se perderían (o se colarían) las
    # consignaciones de las primeras 5 horas del día, que es justo cuando el
    # sistema graba con el offset a favor.
    consignado = db.query(func.sum(Consignacion.valor)).filter(
        Consignacion.estado == EstadoConsignacionEnum.realizada,
        Consignacion.caja_turno_id.is_(None),
        Consignacion.fecha >= inicio_dia_col_utc(desde),
    ).scalar() or 0.0

    # Sin piso en cero: si da negativo es que se registró más salida que recogida
    # (una consignación suya sin la pasada que la originó, típicamente) y ese
    # número tiene que verse. Taparlo con un max(0, ..) convertiría un dato mal
    # cargado en un cero tranquilizador.
    return {
        "monto": round(float(recogido) - float(pagado) - float(consignado), 2),
        "desde": desde,
    }


def _leer_saldo_banco(db: Session) -> tuple:
    """(saldo declarado, fecha de la declaración) desde `configuracion`.

    Tolera basura guardada: la fila es TEXTO y un 'inf' o una fecha inválida de
    otra versión no puede tumbar la pantalla entera del dueño. Ante cualquier
    duda devuelve 0 / None, que además deja la respuesta marcada desactualizada.
    """
    filas = {c.clave: c.valor for c in db.query(Configuracion).filter(
        Configuracion.clave.in_((CLAVE_SALDO_BANCO, CLAVE_SALDO_BANCO_FECHA))).all()}
    try:
        saldo = float(filas.get(CLAVE_SALDO_BANCO) or 0)
    except (TypeError, ValueError):
        saldo = 0.0
    if not math.isfinite(saldo) or saldo < 0 or saldo > SALDO_BANCO_MAX:
        saldo = 0.0
    fecha = None
    crudo = (filas.get(CLAVE_SALDO_BANCO_FECHA) or "").strip()
    if crudo:
        try:
            fecha = date.fromisoformat(crudo)
        except ValueError:
            fecha = None
    return round(saldo, 2), fecha


def leer_reserva_minima_caja(db: Session) -> tuple:
    """(reserva mínima de caja, si ese valor es el default y nadie lo decidió).

    LA PLATA CON LA QUE EL NEGOCIO NO PUEDE QUEDARSE SIN. Es lo que convierte
    «cuánto puedo gastar» en una decisión de negocio en vez de «cuánto puedo
    gastar hasta quedar en cero»: nadie opera una cafetería con la cuenta vacía
    —hay un domicilio que pagar, una devolución, un turno extra— y un colchón
    medido contra cero se lee como permiso para gastarlo todo.

    Mismo patrón que `_leer_saldo_banco`, y por la misma razón: la fila es TEXTO
    y un valor podrido de otra versión no puede tumbar la pantalla del dueño.
    Ante cualquier duda vuelve 0, que es el comportamiento de siempre — el
    colchón queda igual que antes de que esta clave existiera.

    EL DEFAULT ES 0 Y SE DICE. Un 0 silencioso es indistinguible de «el dueño
    decidió que no necesita reserva», y esas dos cosas piden pantallas distintas:
    la primera es una invitación a poner el número, la segunda es una decisión
    tomada. Este repo ya se quemó con un default en cero que dejó todo un motor
    de pedidos inerte sin que nadie lo notara.
    """
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_RESERVA_MINIMA_CAJA).first()
    crudo = (fila.valor if fila is not None else None) or ""
    if not crudo.strip():
        return 0.0, True
    try:
        reserva = float(crudo.strip())
    except (TypeError, ValueError):
        return 0.0, True
    if not math.isfinite(reserva) or reserva < 0 or reserva > SALDO_BANCO_MAX:
        return 0.0, True
    return round(reserva, 2), False


def guardar_reserva_minima_caja(db: Session, reserva: float,
                                usuario_id: int) -> dict:
    """Persiste la reserva en `configuracion`. Asume que el handler ya rechazó
    inf/NaN/negativos: se guarda como TEXTO, así que un valor podrido acá
    envenena toda lectura futura y no solo esta escritura (mismo motivo que
    `guardar_saldo_banco`)."""
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_RESERVA_MINIMA_CAJA).first()
    valor = str(round(float(reserva), 2))
    if fila is not None:
        fila.valor = valor
    else:
        db.add(Configuracion(clave=CLAVE_RESERVA_MINIMA_CAJA, valor=valor))
    audit.registrar(
        db, accion="declarar_reserva_minima_caja", tabla="configuracion",
        registro_id=None, usuario_id=usuario_id, tienda_id=None,
        datos_despues={CLAVE_RESERVA_MINIMA_CAJA: round(float(reserva), 2)},
    )
    db.commit()
    guardada, es_default = leer_reserva_minima_caja(db)
    return {"reserva_minima_caja": guardada, "reserva_es_default": es_default}


def guardar_comision_datafono(db: Session, tasa: float, usuario_id: int) -> dict:
    """Persiste la comisión del datáfono en `configuracion`, como FRACCIÓN.

    Sin este dato el término `k` del margen vale 0, y esa es una de las cuatro
    cosas que hacen que el piso salga CORTO: la comisión se cobra de cada venta
    con tarjeta y hoy no la descuenta nadie. Con la mitad de la venta por
    datáfono y una tasa típica de 2,5%, el margen se infla 1,25 puntos y el piso
    baja en proporción — hacia el lado que tranquiliza.

    Se guarda la FRACCIÓN (0,025) y no el porcentaje (2,5): el handler recibe lo
    que el dueño escribe y convierte, para que nadie tenga que acordarse de en
    qué unidad quedó guardado. Asume que el handler ya rechazó inf/NaN/negativos
    y las tasas absurdas — se guarda como TEXTO y un valor podrido envenena toda
    lectura futura, no solo esta escritura.
    """
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_COMISION_DATAFONO).first()
    valor = str(round(float(tasa), 6))
    if fila is not None:
        fila.valor = valor
    else:
        db.add(Configuracion(clave=CLAVE_COMISION_DATAFONO, valor=valor))
    audit.registrar(
        db, accion="declarar_comision_datafono", tabla="configuracion",
        registro_id=None, usuario_id=usuario_id, tienda_id=None,
        datos_despues={CLAVE_COMISION_DATAFONO: round(float(tasa), 6)},
    )
    db.commit()
    guardada, sin_cargar = _leer_comision_datafono(db)
    return {"comision_datafono": guardada, "sin_cargar": sin_cargar}


def _saldo_banco_hoy(db: Session, hoy: date) -> dict:
    """Cuánta plata hay HOY en el banco, según el LIBRO — no según el ancla cruda.

    ═══════════════════════════════════════════════════════════════════════════
    POR QUÉ NO ALCANZA EL ANCLA SOLA
    ═══════════════════════════════════════════════════════════════════════════
    El ancla (`saldo_banco` en `configuracion`) es el saldo que el dueño copió
    del extracto ESE DÍA, y el sistema le pide actualizarlo cada 7 días. Entre
    una carga y la siguiente él sí teclea los movimientos en el libro. Con el
    ancla sola pasaba esto: cargaba una salida de 3.000.000, el libro le decía
    que le quedaban 2.000.000, y el flujo —que está a un toque de ahí— seguía
    proyectando desde 5.000.000 y calculaba el punto de quiebre con plata que ya
    no está. Dos números para la misma pregunta, y el optimista era el que
    decidía si hay que salir a conseguir plata.

    `saldo_al_cierre` es exactamente ancla + Σ(entradas − salidas) hasta hoy, y
    devuelve además si la cadena llega: sin ancla no se conoce el saldo y los
    movimientos sueltos NO lo inventan (un neto de movimientos no es un saldo).
    Ahí se cae al ancla saneada, que es el comportamiento de siempre.

    ANTI-DOBLE-CONTEO (las tres reglas del bloque de arriba siguen en pie):
      1. las consignaciones no se suman acá: la plata depositada ya salió del
         efectivo de la registradora (`_efectivo_en_registradora` la descuenta) y
         entra al banco solo cuando el dueño la teclea como movimiento — la misma
         plata queda contada UNA vez, del lado del banco;
      2. los MovimientoCaja egreso son de la registradora, no del banco: no hay
         intersección con MovimientoBanco, que se teclea contra el extracto;
      3. las salidas FUTURAS siguen saliendo de la agenda, no de una copia.

    EL CAMINO QUE ESTE CAMBIO ABRIÓ, Y CÓMO SE CERRÓ. Este docstring llegó a
    afirmar que el cambio «no agrega un camino nuevo para contar dos veces»: era
    FALSO y una auditoría lo demostró ejecutándolo. Antes, teclear una salida del
    banco no movía la proyección —arrancaba del ancla cruda— así que una
    obligación pagada desde el banco y todavía viva en la agenda se contaba UNA
    vez. Al meter el libro adentro, el saldo baja Y la agenda la seguía
    proyectando como salida futura: la misma plata dos veces, y el punto de
    quiebre antes de lo real.

    Ese agujero HOY ESTÁ CERRADO por el lado del enlace. `get_agenda` descuenta
    de cada obligación lo que ya salió del banco con su `obligacion_id`
    (`_salidas_banco_por_obligacion`) y lo combina con los pagos por MÁXIMO, no
    por suma (`cubierto_de`): el camino normal —«Registrar pago» con «Y
    descontalo del banco»— escribe el `Pago` y el movimiento para la MISMA
    plata, y sumarlos sacaría de la agenda una obligación que todavía se debe,
    que es el error tranquilizador y el peor de los dos.

    LO QUE SIGUE ABIERTO, dicho en vez de negado: el enlace es OPCIONAL y el
    libro se teclea. La salida que el dueño escribe a mano SIN elegir la
    obligación es, para el sistema, indistinguible de un gasto nuevo, y esa
    obligación se cuenta dos veces igual. Eso es inherente al tecleo y no se
    arregla desde acá: emparejar por la FORMA (un monto que coincide) es el
    anti-patrón que este módulo ya pagó caro. Se cierra pidiendo el enlace en el
    momento de teclear, no adivinándolo después.

    El error que queda va en la dirección PRUDENTE (muestra menos plata de la
    que hay, no más), que es la única razón por la que esto no bloquea.
    """
    declarado, fecha_ancla = _leer_saldo_banco(db)
    base_libro, _fecha_libro = banco_svc.ancla(db)
    saldo_libro, hay_cadena = banco_svc.saldo_al_cierre(db, hoy)

    # El libro encadena sobre el ancla CRUDA; `_leer_saldo_banco` la sanea
    # (inf/NaN/negativo/absurdo → 0). Si las dos lecturas no coinciden, la fila de
    # `configuracion` está podrida y el saldo del libro estaría encadenado sobre
    # basura: se cae al valor saneado en vez de propagar el veneno a la
    # proyección. Con datos sanos son idénticas y el número del flujo es, al
    # peso, el mismo que muestra «La plata».
    usa_libro = (hay_cadena
                 and base_libro == declarado
                 and math.isfinite(saldo_libro)
                 and abs(saldo_libro) <= SALDO_BANCO_MAX)
    saldo = round(saldo_libro, 2) if usa_libro else declarado
    return {
        "saldo": saldo,
        "declarado": declarado,
        "fecha": fecha_ancla,
        # Lo que se movió en el banco DESPUÉS del extracto. Es la distancia entre
        # los dos números, y sirve para que la pantalla pueda decir de dónde sale
        # el saldo en vez de mostrar uno que no coincide con lo declarado.
        "movimientos": round(saldo - declarado, 2) if usa_libro else 0.0,
        "origen": "libro" if usa_libro else "ancla",
    }


def _caja_hoy(db: Session, hoy: date, tienda_id: int | None) -> dict:
    """Con cuánta plata arranca la proyección. TRES sumandos, y el sistema solo
    derivaba uno:

    - el efectivo de cada registradora, que SÍ se deriva de los datos;
    - el saldo del banco, que arranca en un INPUT DEL DUEÑO. El sistema registra
      Consignacion (depósitos) pero jamás un saldo bancario: no hay de dónde
      derivarlo. Sobre ese ancla el libro suma los movimientos que él teclea
      (`_saldo_banco_hoy`). Si el ancla tiene más de una semana, la respuesta lo
      dice en vez de mentir: los movimientos posteriores mantienen el saldo al
      día, pero NO son una conciliación contra el extracto.
    - el efectivo EN MANO del dueño (`_efectivo_en_mano`), que desde agosto es un
      lugar real donde vive la plata del negocio: él recoge de las sedes, paga
      proveedores de contado y consigna el resto. Antes ese tramo no existía y la
      plata recogida se contaba igual en el cajón, de donde ya se había ido.

    DECISIÓN (opción a de la revisión): con `tienda_id` el saldo del banco NO
    entra al total. La cuenta es de la EMPRESA — una sede no "tiene" el banco— y
    no hay dato para repartirla entre sedes. Sumarla completa mientras `get_agenda`
    excluye las obligaciones corporativas (tienda_id NULL) dejaba la serie de la
    sede SISTEMÁTICAMENTE OPTIMISTA: toda la plata del negocio contra solo una
    parte de sus salidas, o sea un quiebre real convertido en verde tranquilizador
    con solo mover el filtro.

    EL EFECTIVO EN MANO SIGUE LA MISMA REGLA, y por el mismo argumento: la plata
    en su bolsillo es de la EMPRESA. `RecogidaEfectivo` sí sabe de qué sede salió
    cada billete, pero los pagos y las consignaciones que la consumen NO se pueden
    repartir por sede —él le paga al proveedor con la plata junta—, así que una
    vista por sede solo podría sumar el lado de las ENTRADAS. Eso es exactamente el
    sesgo optimista descrito arriba, con otro disfraz.

    Y cuando todavía no hay ninguna recogida, `efectivo_en_mano` vale None y no
    suma nada. None no es 0.0: significa "este bucket todavía no existe", y la
    pantalla necesita poder callarse en vez de mostrar un cero que se lee como
    "no le queda plata en la mano".

    Se descartó la opción (b) —meter las corporativas en la agenda de cada sede—
    porque no hay forma de repartirlas: sumar las dos sedes contaría el arriendo
    dos veces y el total dejaría de cuadrar con la agenda global (la misma razón
    por la que `get_agenda` y `listar_obligaciones` ya las excluyen). Lo que la
    vista por sede ignora se declara aparte, en `advertencias.excluye_corporativas`.

    El saldo declarado se sigue devolviendo aunque no entre al total: es un dato
    real que el dueño tiene que poder ver. `saldo_banco_incluido` dice si suma.
    """
    q = db.query(Tienda).filter(Tienda.activa == True)  # noqa: E712
    if tienda_id is not None:
        q = q.filter(Tienda.id == tienda_id)

    detalle = []
    efectivo = 0.0
    for t in q.order_by(Tienda.id).all():
        monto, origen = _efectivo_en_registradora(db, t.id)
        efectivo += monto
        detalle.append({"tienda_id": t.id, "tienda_nombre": t.nombre,
                        "efectivo": monto, "origen": origen})

    del_banco = _saldo_banco_hoy(db, hoy)
    saldo_banco = del_banco["saldo"]
    fecha_banco = del_banco["fecha"]
    # La vigencia se sigue midiendo contra la FECHA DEL EXTRACTO, no contra el
    # último movimiento tecleado: lo que envejece es la CONCILIACIÓN. Un libro
    # lleno de movimientos sobre un ancla de hace un mes puede estar al día o
    # puede tener un débito automático que nadie tecleó, y nada del sistema
    # sabe cuál de las dos. Mover este criterio al último movimiento apagaría
    # el aviso justo cuando el saldo se está alejando del extracto.
    desactualizado = (fecha_banco is None
                      or (hoy - fecha_banco).days > DIAS_SALDO_BANCO_VIGENTE)
    incluye_banco = tienda_id is None

    # Se calcula SIEMPRE, aunque filtrando por sede no sume: es un dato real que el
    # dueño tiene que poder ver, igual que el saldo del banco. `..._incluido` es el
    # que dice si entró al total, para que la pantalla no tenga que deducirlo.
    en_mano = _efectivo_en_mano(db)
    incluye_en_mano = tienda_id is None and en_mano["monto"] is not None

    return {
        "efectivo_registradora": round(efectivo, 2),
        "por_tienda": detalle,
        # El saldo que de verdad entra al total: ancla + movimientos del libro.
        "saldo_banco": saldo_banco,
        # Lo que el dueño copió del extracto, y lo que se movió después. Los dos
        # se devuelven para que la pantalla pueda explicar el número en vez de
        # rotularlo "declarado" cuando ya no lo es.
        "saldo_banco_declarado": del_banco["declarado"],
        "saldo_banco_movimientos": del_banco["movimientos"],
        "saldo_banco_origen": del_banco["origen"],   # 'libro' | 'ancla'
        "saldo_banco_fecha": fecha_banco,
        "saldo_banco_desactualizado": desactualizado,
        "saldo_banco_incluido": incluye_banco,
        # La tercera bolsa. None = todavía no se registró ninguna recogida, o sea
        # que el bucket NO EXISTE — distinto de que exista y esté en cero.
        "efectivo_en_mano": en_mano["monto"],
        "efectivo_en_mano_desde": en_mano["desde"],
        "efectivo_en_mano_incluido": incluye_en_mano,
        "total": round(efectivo
                       + (saldo_banco if incluye_banco else 0.0)
                       + (en_mano["monto"] if incluye_en_mano else 0.0), 2),
    }


def _venta_esperada_por_dia_semana(db: Session, hoy: date,
                                   tienda_id: int | None) -> dict:
    """{día de la semana (0=lunes): venta esperada} — MEDIANA, no promedio.

    Un solo día atípico (un evento, una venta corporativa) movería el promedio y
    con él TODAS las proyecciones de ese día de semana. La mediana lo ignora, que
    es exactamente lo que se quiere de una proyección de caja: ser aburrida.

    Ventana: [hoy-56, hoy-1]. Cualquier ventana de 56 días tiene exactamente 8
    muestras de cada día de la semana. HOY queda fuera a propósito: es un día a
    medio vender y hundiría la mediana de su propio día de semana.

    Solo se promedian días CON ventas: un lunes cerrado no entra como 0 (no es
    "vendimos nada", es "no abrimos"), así que no contamina la mediana.

    Sin rezago de cobro: en el POS toda venta se cobra el mismo día — no hay
    cuentas por cobrar que diferir.
    """
    d_utc, h_utc = rango_col_utc(hoy - timedelta(days=SEMANAS_HISTORIA * 7),
                                 hoy - timedelta(days=1))
    q = db.query(Ticket.fecha, Ticket.total).filter(
        Ticket.fecha >= d_utc,
        Ticket.fecha <= h_utc,
        Ticket.estado.notin_(("anulado", "reversado")),
    )
    if tienda_id is not None:
        q = q.filter(Ticket.tienda_id == tienda_id)

    por_dia: dict = {}
    for fecha, total in q.all():
        if fecha is None:
            continue
        # dia_col es Python puro: agrupar por día COLOMBIA en SQL exigiría
        # funciones de fecha distintas en SQLite y en Postgres.
        d = dia_col(fecha)
        por_dia[d] = por_dia.get(d, 0.0) + float(total or 0)

    muestras: dict = {}
    for d, total in por_dia.items():
        muestras.setdefault(d.weekday(), []).append(total)
    return {dow: round(median(vals), 2) for dow, vals in muestras.items()}


def _salidas_por_dia(db: Session, hoy: date, dias: int,
                     tienda_id: int | None) -> dict:
    """{día: plata que hay que pagar ese día} — REUSA `get_agenda`, no la duplica.

    Así la proyección hereda gratis toda la semántica ya probada de la agenda:
    la precedencia COALESCE(programada, vencimiento, recibido+plazo), el saldo en
    vez del total, las obligaciones anuladas y los pagos anulados que devuelven
    saldo. Una segunda implementación de esas reglas se desincronizaría.

    Todo lo que ya se debe se acumula ENTERO en hoy+1: es plata que se debe AHORA.
    Repartirla en el horizonte o dejarla fuera haría desaparecer la mora de la
    proyección justo cuando más importa.

    Lo que vence HOY entra en ese mismo bloque. La serie arranca en hoy+1, así
    que sin esto un pago de hoy no caería en ningún día y se perdería en silencio.

    Los MovimientoCaja egreso NO se restan acá: son pasado y ya están descontados
    dentro del efectivo de la registradora (`_efectivo_en_registradora`).
    """
    agenda = get_agenda(db, desde=None, hasta=hoy + timedelta(days=dias),
                        tienda_id=tienda_id)
    manana = hoy + timedelta(days=1)
    por_dia: dict = {}
    for item in agenda["items"]:
        fecha = item["fecha"]
        if fecha <= hoy:
            fecha = manana
        por_dia[fecha] = round(por_dia.get(fecha, 0.0) + item["monto"], 2)
    return por_dia


def _corporativas_fuera(db: Session, hoy: date, dias: int) -> float:
    """Plata que la vista de UNA sede no muestra: el saldo de las obligaciones
    CORPORATIVAS (tienda_id NULL — arriendo, nómina) que vencen en el horizonte.

    Reusa `get_agenda` global y filtra en Python, igual que `_salidas_por_dia`: la
    semántica de fechas y saldos se hereda en vez de reimplementarse. Las facturas
    nunca son corporativas (FacturaCompra.tienda_id es NOT NULL), así que este
    total sale entero de obligaciones.
    """
    agenda = get_agenda(db, desde=None, hasta=hoy + timedelta(days=dias),
                        tienda_id=None)
    return round(sum(i["monto"] for i in agenda["items"] if i["tienda_id"] is None), 2)


def dias_hasta_fin_de_mes(hoy: date) -> int:
    """Cuántos días de serie hacen falta para llegar al último día del mes.

    La serie del flujo arranca en hoy+1, así que para que el último punto sea el
    último día del mes el horizonte es exactamente esa diferencia. El 31 da 0 y
    se recorta a 1: una serie vacía no es una respuesta, y un solo día de más al
    mes siguiente es preferible a devolver nada el día que más se mira.
    """
    fin = date(hoy.year, hoy.month, calendar.monthrange(hoy.year, hoy.month)[1])
    return max(1, (fin - hoy).days)


def get_flujo_proyectado(db: Session, dias: int | None = None,
                         tienda_id: int | None = None) -> dict:
    """Serie diaria del saldo proyectado y, sobre todo, el PUNTO DE QUIEBRE: el
    primer día en que el saldo cruza a negativo, o None si nunca cruza.

    El punto de quiebre es el único número que el dueño realmente necesita: le
    dice el día en que se queda sin plata ANTES de que pase.

    SIN `dias`, EL HORIZONTE ES HASTA FIN DE MES y no 30 días fijos: ver el
    bloque de constantes. El colchón que sale de esta serie tiene que mirar la
    MISMA ventana que el piso de venta, o son dos respuestas a dos preguntas
    distintas presentadas como si fueran comparables.

    Con `advertencias` va lo que la serie NO sabe, porque las dos mitades de la
    fórmula no se ganan igual: las ENTRADAS se derivan solas de cada ticket, pero
    las SALIDAS existen únicamente si un humano las tecleó (`recurrencia` todavía
    no genera nada, la compra que no llegó no está, el costo de mercadería aparece
    recién cuando alguien registra la factura). O sea: la PRESENCIA de un punto de
    quiebre significa algo; su AUSENCIA, sola, no significa nada. Estos flags son
    los que le permiten a la pantalla decir "falta información" en vez de vender
    tranquilidad con un verde.
    """
    hoy = hoy_col()
    ancla = dias_hasta_fin_de_mes(hoy)
    try:
        dias = int(dias) if dias is not None else ancla
    except (TypeError, ValueError):
        dias = ancla
    if dias <= 0:
        dias = ancla
    dias = max(1, min(dias, HORIZONTE_MAX))

    caja = _caja_hoy(db, hoy, tienda_id)
    entradas_dow = _venta_esperada_por_dia_semana(db, hoy, tienda_id)
    salidas_dia = _salidas_por_dia(db, hoy, dias, tienda_id)

    serie = []
    saldo = caja["total"]
    quiebre = None
    total_entradas = total_salidas = 0.0
    for n in range(1, dias + 1):
        d = hoy + timedelta(days=n)
        entradas = entradas_dow.get(d.weekday(), 0.0)
        salidas = salidas_dia.get(d, 0.0)
        saldo = round(saldo + entradas - salidas, 2)
        total_entradas += entradas
        total_salidas += salidas
        if quiebre is None and saldo < 0:
            quiebre = d
        serie.append({"fecha": d, "entradas": entradas, "salidas": salidas,
                      "saldo": saldo})

    corporativas_fuera = _corporativas_fuera(db, hoy, dias) if tienda_id else 0.0

    # ── EL COLCHÓN: cuánta plata sobra sobre la reserva, en el peor día ───────
    # `punto_de_quiebre` contesta "¿me quedo sin plata?" — un sí/no. El colchón
    # contesta "¿cuánto puedo gastar?", que es la pregunta que el dueño hace de
    # verdad cuando evalúa una activación o una compra grande.
    #
    # Se mide contra el MÍNIMO de la serie y no contra el saldo final: la plata
    # tiene que alcanzar TODOS los días del horizonte, no solo el último. Un mes
    # que termina bien pero pasa por un lunes en rojo no tiene colchón.
    #
    # Y se le resta la RESERVA. Sin ella el colchón contesta "cuánto puedo gastar
    # hasta quedar en cero", que no es una decisión de negocio: nadie opera una
    # cafetería con la cuenta en $0. Con la reserva en 0 —el default— el número
    # es el de siempre, y `reserva_es_default` lo dice para que la pantalla pueda
    # invitar a ponerla en vez de dejar el cero pasando por una decisión tomada.
    piso_serie = min((p["saldo"] for p in serie), default=caja["total"])
    reserva, reserva_es_default = leer_reserva_minima_caja(db)
    return {
        "hoy": hoy,
        "dias": dias,
        # Si el horizonte pedido coincide con el ancla de fin de mes, el colchón
        # y el piso de venta hablan del mismo período. La pantalla necesita poder
        # decirlo, así que el ancla viaja al lado del horizonte usado.
        "dias_hasta_fin_de_mes": ancla,
        "horizonte_es_fin_de_mes": dias == ancla,
        "tienda_id": tienda_id,
        "caja_hoy": caja,
        "serie": serie,
        "punto_de_quiebre": quiebre,
        "dias_hasta_quiebre": (quiebre - hoy).days if quiebre else None,
        "saldo_minimo": round(piso_serie, 2),
        "reserva_minima_caja": reserva,
        "reserva_es_default": reserva_es_default,
        # Negativo = no hay colchón, falta esa plata para sostener la reserva.
        # No se recorta en cero: un colchón negativo es exactamente el dato que
        # hay que ver antes de gastar.
        "colchon": round(piso_serie - reserva, 2),
        "advertencias": {
            # Solo molesta si el banco de verdad entra al total: filtrando por
            # sede no suma, y avisar de un dato que no se usa es ruido.
            "saldo_banco_desactualizado": bool(caja["saldo_banco_incluido"]
                                               and caja["saldo_banco_desactualizado"]),
            # Ni una sola salida en el horizonte: casi siempre significa que nadie
            # cargó las cuentas por pagar, no que no haya nada que pagar.
            "sin_salidas_cargadas": not salidas_dia,
            # Sin muestras no hay venta esperada: la serie asume que no entra nada.
            "sin_historia_ventas": not entradas_dow,
            # La vista de una sede no ve el arriendo ni la nómina corporativa.
            "excluye_corporativas": bool(tienda_id and corporativas_fuera > 0),
            "corporativas_fuera": corporativas_fuera,
        },
        "totales": {
            "entradas": round(total_entradas, 2),
            "salidas": round(total_salidas, 2),
            "saldo_final": saldo,
        },
    }


def guardar_saldo_banco(db: Session, saldo: float, fecha: date,
                        usuario_id: int) -> dict:
    """Persiste la declaración del dueño en `configuracion` (dos claves).

    OJO: este servicio asume que el handler ya rechazó inf/NaN/negativos. Se
    guarda como TEXTO, así que un valor podrido acá envenena toda lectura futura,
    no solo esta escritura — mismo motivo por el que la meta de ventas se valida
    antes de tocar la fila (routers/auth.py).
    """
    valores = {CLAVE_SALDO_BANCO: str(round(float(saldo), 2)),
               CLAVE_SALDO_BANCO_FECHA: fecha.isoformat()}
    filas = {c.clave: c for c in db.query(Configuracion).filter(
        Configuracion.clave.in_(tuple(valores))).all()}
    for clave, valor in valores.items():
        fila = filas.get(clave)
        if fila is not None:
            fila.valor = valor
        else:
            db.add(Configuracion(clave=clave, valor=valor))

    audit.registrar(
        db, accion="declarar_saldo_banco", tabla="configuracion",
        registro_id=None, usuario_id=usuario_id, tienda_id=None,
        datos_despues={"saldo_banco": round(float(saldo), 2),
                       "saldo_banco_fecha": fecha},
    )
    db.commit()
    saldo_guardado, fecha_guardada = _leer_saldo_banco(db)
    return {
        "saldo_banco": saldo_guardado,
        "saldo_banco_fecha": fecha_guardada,
        "saldo_banco_desactualizado": (
            fecha_guardada is None
            or (hoy_col() - fecha_guardada).days > DIAS_SALDO_BANCO_VIGENTE),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# EL PISO: cuánto hay que vender este mes para no perder plata
# ═══════════════════════════════════════════════════════════════════════════════
#
# La venta cayó 54% de enero a julio y la proyección del dueño cierra agosto en
# negativo. La pregunta que ninguna pantalla contesta hoy es la única que decide
# si gasta o no gasta: CUÁNTO TENGO QUE VENDER PARA NO PERDER.
#
#   PISO_MES = costos fijos del mes / margen de contribución
#   falta    = PISO_MES − lo vendido en el mes a la fecha
#   PISO_HOY = falta / los días que QUEDAN por abrir
#
# TRES DECISIONES QUE HACEN QUE EL NÚMERO SIRVA, y cada una es un error que este
# módulo ya cometió en otra forma:
#
# 1. EL NUMERADOR MIRA EL MES COMPLETO, no "del 1 a hoy". El arriendo y la
#    nómina se devengan a fin de mes y la pantalla pide el P&L con `hasta = hoy`
#    (`mesActualBogota` en Plata.tsx): el 3 de septiembre esa ventana no los
#    contiene y el piso saldría ridículamente bajo justo cuando más se mira.
#    Lo resuelve `rentabilidad.costos_fijos_del_mes`, que fija la ventana adentro.
#
# 2. EL DENOMINADOR SE MIDE, NO SE SUPONE. Las tres razones —impuesto, costo de
#    mercadería, comisión del datáfono— salen de la venta REAL del mes a la
#    fecha, no de tarifas nominales. En particular el impoconsumo NO se calcula
#    como tasa/(1+tasa): `Tributos.separar` devuelve impuesto CERO cuando el
#    precio no incluye el impuesto, y el cociente medido cubre los dos regímenes
#    sin una rama que se pueda olvidar.
#
# 3. EL PISO DEL DÍA NO ES EL DEL MES DIVIDIDO PLANO. Se descuenta lo ya vendido
#    y se reparte entre los días que faltan: si el mes viene atrasado, el piso de
#    los días que quedan SUBE. Un mensual repartido en partes iguales da una
#    cifra tranquilizadora y falsa a mitad de mes.
#
# Y UNA CUARTA, sobre unidades: como el impoconsumo ya está restado del margen,
# PISO_MES queda en pesos COBRADOS —lo mismo que `resumen.ventas`— y NO se le
# vuelve a sumar. Se trabaja en cobrado o en neto, nunca en los dos.

# Las cuatro puertas de honestidad. Son estados de la RESPUESTA, no errores: el
# endpoint contesta 200 en todos los casos y dice cuál se activó.
PUERTA_SIN_COSTOS_FIJOS = "sin_costos_fijos"
PUERTA_SIN_RAZONES = "sin_razones"
PUERTA_MARGEN_NO_POSITIVO = "margen_no_positivo"
PUERTA_RAZONES_DEL_MES_ANTERIOR = "razones_del_mes_anterior"
PUERTA_OK = "ok"


def _leer_comision_datafono(db: Session) -> tuple:
    """(comisión del datáfono como fracción, si nadie la cargó).

    Tolera basura por el mismo motivo que `_leer_saldo_banco`: la fila es TEXTO.
    Ante cualquier duda vuelve 0 — o sea, el margen de contribución sale MÁS ALTO
    y el piso MÁS BAJO. Es un sesgo, va para el lado tranquilizador como todos
    los de este cálculo, y por eso el segundo valor del par existe: la respuesta
    tiene que poder decir «este costo no está adentro» en vez de callarlo.

    Tope en 1: una comisión mayor al 100% de la venta no es un dato, es un error
    de tipeo, y dejarla pasar volvería el margen negativo y dispararía la puerta
    del veredicto («cada venta pierde plata») por una tecla mal apretada.
    """
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_COMISION_DATAFONO).first()
    crudo = (fila.valor if fila is not None else None) or ""
    if not crudo.strip():
        return 0.0, True
    try:
        tasa = float(crudo.strip())
    except (TypeError, ValueError):
        return 0.0, True
    if not math.isfinite(tasa) or tasa < 0 or tasa > 1:
        return 0.0, True
    return tasa, False


def _parte_con_tarjeta(db: Session, desde: date, hasta: date) -> float:
    """Qué fracción de lo cobrado entró por el datáfono, en esa ventana.

    Se mide sobre `Ticket.monto_tarjeta`, que el POS llena también en los tickets
    MIXTOS: contar por `metodo_pago == 'tarjeta'` dejaría afuera la parte con
    tarjeta de cada venta mixta y subestimaría la comisión — otra vez hacia el
    lado tranquilizador.

    Sin venta en la ventana devuelve 0: no hay de dónde medir y no se inventa.
    """
    d_utc, h_utc = rango_col_utc(desde, hasta)
    total, tarjeta = db.query(
        func.coalesce(func.sum(Ticket.total), 0.0),
        func.coalesce(func.sum(Ticket.monto_tarjeta), 0.0),
    ).filter(
        Ticket.estado.notin_(("anulado", "reversado")),
        Ticket.fecha >= d_utc,
        Ticket.fecha <= h_utc,
    ).first()
    total = float(total or 0.0)
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, float(tarjeta or 0.0) / total))


def dias_que_abre(db: Session, desde: date, hasta: date,
                  tienda_id: int | None = None) -> dict:
    """Cuántos días entre `desde` y `hasta` (los dos incluidos) ABRE el local.

    NO SE PREGUNTA, SE DERIVA. `_venta_esperada_por_dia_semana` ya devuelve la
    mediana de venta de cada día de la semana sobre las últimas 8 semanas
    contando SOLO los días con venta: un día de la semana con mediana > 0 es un
    día que el local abre, y uno con mediana 0 —o ausente— es uno que no. Contar
    cuántos de esos caen en el rango es aritmética de calendario.

    HOY CUENTA COMO DÍA QUE QUEDA, y no es un detalle de borde: la venta del mes
    "a la fecha" que se le resta al piso ya incluye lo que se lleva vendido hoy,
    así que las horas que quedan de hoy son horas en las que todavía se puede
    vender el resto. Dejar hoy afuera repartiría el faltante entre menos días y
    daría un piso diario más alto que el real.

    SIN HISTORIA NO SE DERIVA NADA y se cuentan todos los días del calendario.
    Es el único punto de esta función que empuja el piso hacia abajo (más días,
    menos por día), así que `derivados` viaja en la respuesta para que la
    pantalla lo pueda decir en vez de dejarlo implícito.
    """
    esperada = _venta_esperada_por_dia_semana(db, hoy_col(), tienda_id)
    dows = {dow for dow, valor in esperada.items() if valor > 0}
    calendario = ([desde + timedelta(days=n) for n in range((hasta - desde).days + 1)]
                  if hasta >= desde else [])
    if not dows:
        return {"dias": len(calendario), "dias_calendario": len(calendario),
                "dias_semana": [], "derivados": False}
    abre = [d for d in calendario if d.weekday() in dows]
    return {"dias": len(abre), "dias_calendario": len(calendario),
            "dias_semana": sorted(dows), "derivados": True}


def _razones_de_la_venta(db: Session, desde: date, hasta: date):
    """Los tres términos que se comen cada peso COBRADO, medidos en esa ventana.

    Devuelve None cuando no hubo venta: sin denominador no hay cociente, y
    devolver ceros diría que de cada peso queda el peso entero — el error más
    caro posible en este cálculo.

    El impoconsumo sale de `resumen.impoconsumo / resumen.ventas` y NO de la
    tarifa. Con el precio con impuesto adentro y tarifa 8% el cociente da 0,0741
    y no 0,08; y con `precio_incluye_impoconsumo` en False, `Tributos.separar`
    devuelve impuesto 0 y el cociente da 0 solo, sin una rama aparte que alguien
    pueda olvidar de actualizar el día que cambie el régimen.
    """
    pnl = rent_svc.get_rentabilidad(db, desde, hasta)
    resumen = pnl["resumen"]
    ventas = float(resumen["ventas"] or 0.0)
    if ventas <= 0:
        return None
    tasa_comision, comision_sin_cargar = _leer_comision_datafono(db)
    pct_tarjeta = _parte_con_tarjeta(db, desde, hasta)
    return {
        "desde": desde,
        "hasta": hasta,
        "ventas": round(ventas, 2),
        "impoconsumo": round(float(resumen["impoconsumo"] or 0.0) / ventas, 6),
        "cogs": round(float(resumen["cogs_teorico"] or 0.0) / ventas, 6),
        "comision": round(tasa_comision * pct_tarjeta, 6),
        "tasa_comision": tasa_comision,
        "comision_sin_cargar": comision_sin_cargar,
        "pct_tarjeta": round(pct_tarjeta, 6),
        "pct_venta_costeada": resumen["pct_venta_costeada"],
    }


def _sesgos_del_piso(razones: dict, n_desechables: int) -> list:
    """LOS CUATRO SESGOS, TODOS PARA EL MISMO LADO: el piso sale CORTO.

    Los cuatro INFLAN lo que queda de cada peso —o sea, agrandan el denominador
    de la división— y por lo tanto BAJAN el piso. Ninguno lo sube. Por eso el
    número se publica rotulado «AL MENOS» y por eso esta lista viaja en la
    respuesta: la pantalla tiene que poder nombrar cuáles están vivos, no adornar
    el número con un asterisco genérico.

    Los dos primeros son la MISMA medición vista de dos formas —cuánta venta
    quedó sin costear— y se separan a propósito: uno es la instrucción de trabajo
    («cargá el costo de lo que falta») y el otro es cuánto creerle al número. Se
    dice acá para que nadie los lea después como dos evidencias independientes.
    """
    pct = razones["pct_venta_costeada"]
    sin_costear = pct is None or pct < 100
    plata_sin_costear = (round(razones["ventas"] * (100.0 - pct) / 100.0, 2)
                         if pct is not None else razones["ventas"])
    return [
        {
            "clave": "productos_sin_costo",
            "activo": bool(sin_costear),
            "texto": "los productos sin costo cargado aportan $0 al costo de la venta",
            "detalle": {"venta_sin_costear": plata_sin_costear if sin_costear else 0.0},
        },
        {
            "clave": "costeo_parcial",
            "activo": bool(sin_costear),
            "texto": "el costeo cubre solo una parte de la venta",
            "detalle": {"pct_venta_costeada": pct},
        },
        {
            # ESTRUCTURAL, no un dato que falte: `_costo_unitario_productos` —el
            # que arma `cogs_teorico`— resuelve por precio_costo, receta o costo
            # de compra, y ProductoDesechable no entra por ninguno de los tres.
            # El vaso, la tapa y la servilleta de cada bebida para llevar están
            # afuera del costo SIEMPRE, se hayan cargado o no.
            "clave": "desechables_fuera_del_costo",
            "activo": True,
            "texto": "los desechables no están dentro del costo de la bebida",
            "detalle": {"productos_con_desechables": n_desechables},
        },
        {
            "clave": "comision_datafono_sin_cargar",
            "activo": bool(razones["comision_sin_cargar"]),
            "texto": "la comisión del datáfono no está cargada",
            "detalle": {"pct_tarjeta": razones["pct_tarjeta"],
                        "tasa_comision": razones["tasa_comision"]},
        },
    ]


def get_piso(db: Session, anio: int, mes: int) -> dict:
    """CUÁNTO HAY QUE VENDER ESTE MES PARA NO PERDER, y cuánto por día.

    La fórmula y sus cuatro decisiones están en el bloque de arriba. Acá va lo
    que la respuesta DEVUELVE y por qué, que es la mitad del trabajo: una
    pantalla que recibe solo el resultado no lo puede explicar ni auditar, y este
    número es el que decide si el dueño gasta o no gasta.

    ═══════════════════════════════════════════════════════════════════════════
    EL TITULAR Y EL PISO DEL DÍA SALEN DE LOS MISMOS DOS NÚMEROS
    ═══════════════════════════════════════════════════════════════════════════
    «Para no perder en agosto faltan $14.500.000» es `falta`; «$1.208.000 más por
    día» es `falta / días que quedan`. Los dos van juntos en `titular`
    justamente para que no se puedan calcular por separado: dos cuentas distintas
    se contradicen en la misma pantalla el día que una de ellas cambie.

    ═══════════════════════════════════════════════════════════════════════════
    LAS CUATRO PUERTAS
    ═══════════════════════════════════════════════════════════════════════════
    1. SIN COSTOS FIJOS cargados: no hay piso de resultado. Va el hueco CON
       NOMBRE y el piso de caja, si se puede calcular.
    2. SIN VENTA todavía en el mes: no hay cociente. Se usan las razones del mes
       anterior y se ROTULA (`razones.de`). Sin mes anterior tampoco, solo caja.
    3. MARGEN <= 0: no es falta de datos, es un VEREDICTO, y se dice plano.
    4. TODO LO DEMÁS: el número SIEMPRE se publica, rotulado «AL MENOS».

    NO HAY UN PORTÓN EN `pct_venta_costeada`. La pantalla se llama EL PISO y su
    columna vertebral no puede desaparecer porque el costeo esté al 58% en vez de
    al 62%. Ese porcentaje decide las PALABRAS de la banda —cuánto creerle— y
    nunca si el número existe. Lo que la regla de la casa prohíbe es un VERDE
    fuera del dato resuelto, no un número.

    EL PISO DE CAJA es la columna de repuesto: salidas agendadas + reserva −
    plata que hay, sobre los días que quedan. No necesita costeo de producto ni
    margen, así que sobrevive al negocio que todavía no cargó ni una receta. NO
    es un atajo para saltarse la nómina: la necesita EN LA AGENDA igual que el
    otro (`POST /costos/nomina/agendar`). Cuando existen los dos, MANDA EL MÁS
    ALTO y el de abajo se nombra.
    """
    hoy = hoy_col()
    anio, mes = int(anio), int(mes)
    desde = date(anio, mes, 1)
    fin_mes = date(anio, mes, calendar.monthrange(anio, mes)[1])

    # ── NUMERADOR: el mes COMPLETO, siempre ──────────────────────────────────
    cf = rent_svc.costos_fijos_del_mes(db, anio, mes)
    costos_fijos = cf["costos_fijos_devengados"]

    # ── DENOMINADOR: la ventana simétrica con la venta real ──────────────────
    # Del 1 a HOY para el mes en curso; del 1 al último día para un mes cerrado
    # (ahí "hasta hoy" ya es el mes entero, y recortarlo sería mirar el futuro).
    hasta_venta = min(hoy, fin_mes)
    razones = (_razones_de_la_venta(db, desde, hasta_venta)
               if hasta_venta >= desde else None)
    # «mes_pedido» y no «mes_actual»: el endpoint también contesta por meses
    # cerrados, y una pantalla que lea «actual» escribiría «este mes» sobre
    # el resultado de julio.
    razones_de = "mes_pedido"
    if razones is None:
        # PUERTA 2. El mes anterior COMPLETO, recortado a hoy por las dudas: un
        # mes que todavía no terminó no se puede leer entero.
        prev_fin = desde - timedelta(days=1)
        prev_desde = date(prev_fin.year, prev_fin.month, 1)
        razones = _razones_de_la_venta(db, prev_desde, min(prev_fin, hoy))
        razones_de = "mes_anterior" if razones is not None else None

    # LO VENDIDO EN EL MES PEDIDO, que es lo único que se le puede restar al
    # piso. Con las razones prestadas del mes anterior esto vale 0 a propósito:
    # restarle al piso de agosto la venta de julio sería la doble contabilidad
    # más cara de la pantalla.
    ventas_mes = (round(float(razones["ventas"]), 2)
                  if razones is not None and razones_de == "mes_pedido" else 0.0)
    margen_contribucion = (round(1.0 - razones["impoconsumo"] - razones["cogs"]
                                 - razones["comision"], 6)
                           if razones is not None else None)

    # ── LOS DÍAS QUE QUEDAN POR ABRIR ────────────────────────────────────────
    dias = dias_que_abre(db, max(hoy, desde), fin_mes)
    n_dias = dias["dias"]

    # ── PISO DE RESULTADO ────────────────────────────────────────────────────
    puerta = PUERTA_OK
    piso_mes = falta = piso_hoy = None
    if not cf["tiene_costos_fijos"] or cf["n_costos_fijos"] == 0:
        puerta = PUERTA_SIN_COSTOS_FIJOS
    elif razones is None:
        puerta = PUERTA_SIN_RAZONES
    elif margen_contribucion <= 0:
        puerta = PUERTA_MARGEN_NO_POSITIVO
    else:
        piso_mes = round(costos_fijos / margen_contribucion, 2)
        falta = round(piso_mes - ventas_mes, 2)
        # Sin días que queden no hay "por día" que calcular: el mes ya cerró, o
        # el local no vuelve a abrir antes de fin de mes. `falta` sigue siendo
        # válido y se devuelve; `piso_hoy` vuelve None, que es la verdad.
        piso_hoy = round(falta / n_dias, 2) if n_dias > 0 else None
        if razones_de == "mes_anterior":
            puerta = PUERTA_RAZONES_DEL_MES_ANTERIOR

    # ── PISO DE CAJA: la columna de repuesto ─────────────────────────────────
    # `desde=None` a propósito: lo VENCIDO también hay que pagarlo, y arrancar la
    # ventana hoy lo dejaría afuera. Es la misma regla que `_salidas_por_dia`.
    agenda = get_agenda(db, desde=None, hasta=fin_mes, tienda_id=None)
    salidas = round(sum(i["monto"] for i in agenda["items"]), 2)
    reserva, reserva_es_default = leer_reserva_minima_caja(db)
    caja = _caja_hoy(db, hoy, None)
    piso_caja_mes = round(salidas + reserva - caja["total"], 2)
    piso_caja = round(piso_caja_mes / n_dias, 2) if n_dias > 0 else None

    # ── MANDA EL MÁS ALTO ────────────────────────────────────────────────────
    # Los dos son plata COBRADA por día, así que se comparan de frente. Con los
    # dos vivos manda el más exigente: cubrir el más chico y creer que alcanza es
    # exactamente el error tranquilizador que esta pantalla existe para evitar.
    candidatos = {k: v for k, v in (("resultado", piso_hoy), ("caja", piso_caja))
                  if v is not None}
    manda = max(candidatos, key=candidatos.get) if candidatos else None
    otro = next((k for k in candidatos if k != manda), None)

    n_desechables = db.query(func.count(func.distinct(
        ProductoDesechable.producto_id))).scalar() or 0

    return {
        "anio": anio,
        "mes": mes,
        "hoy": hoy,
        "desde": desde,
        "hasta": fin_mes,
        # CUÁL DE LAS CUATRO PUERTAS SE ACTIVÓ. La pantalla no tiene que deducirla
        # de qué campos vinieron en None.
        "puerta": puerta,
        # ── El numerador, abierto ────────────────────────────────────────────
        "costos_fijos": {
            "total": costos_fijos,
            "n": cf["n_costos_fijos"],
            "hay": cf["tiene_costos_fijos"],
            # LA VENTANA, explícita: es el bug más fácil de reintroducir y tiene
            # que poder verificarse leyendo la respuesta.
            "desde": cf["desde"],
            "hasta": cf["hasta"],
            "nomina_calculada": cf["nomina_calculada"],
            "nomina_manual_en_ventana": cf["nomina_manual_en_ventana"],
            "nomina_sin_contrato": cf["nomina_sin_contrato"],
            "por_categoria": cf["por_categoria"],
        },
        # ── El denominador, término por término ──────────────────────────────
        # Sin esto la pantalla recibe un margen de 0,41 y no puede decir de dónde
        # sale ni qué habría que mover para subirlo.
        "margen_contribucion": margen_contribucion,
        "razones": None if razones is None else {
            "de": razones_de,               # 'mes_pedido' | 'mes_anterior'
            "desde": razones["desde"],
            "hasta": razones["hasta"],
            "ventas_medidas": razones["ventas"],
            "impoconsumo": razones["impoconsumo"],
            "cogs": razones["cogs"],
            "comision": razones["comision"],
            "tasa_comision": razones["tasa_comision"],
            "pct_tarjeta": razones["pct_tarjeta"],
            "pct_venta_costeada": razones["pct_venta_costeada"],
        },
        # ── El resultado ─────────────────────────────────────────────────────
        "ventas_mes": ventas_mes,
        "piso_mes": piso_mes,
        "piso_hoy": piso_hoy,
        # Negativo = el piso del mes ya está cubierto. No se recorta en cero: el
        # dueño tiene derecho a ver por cuánto lo pasó.
        "falta": falta,
        "cubierto": bool(falta is not None and falta <= 0),
        # LOS MISMOS DOS NÚMEROS que el titular de la pantalla, servidos juntos
        # para que no se puedan calcular por separado y contradecirse.
        "titular": {"falta": falta, "por_dia": piso_hoy},
        # ── Los días ─────────────────────────────────────────────────────────
        "dias": {
            "quedan": n_dias,
            "calendario": dias["dias_calendario"],
            "dias_semana": dias["dias_semana"],
            "derivados": dias["derivados"],
            "incluye_hoy": bool(desde <= hoy <= fin_mes),
        },
        # ── El piso de caja, y quién manda ───────────────────────────────────
        "piso_caja": {
            "por_dia": piso_caja,
            "del_mes": piso_caja_mes,
            "salidas_agendadas": salidas,
            "vencido": agenda["totales"]["vencido"],
            "reserva": reserva,
            "reserva_es_default": reserva_es_default,
            "caja_hoy": caja["total"],
            # Lo agendado SIN fecha no entra a `salidas` (misma regla que la
            # proyección), y por eso se declara: es plata que se debe y que este
            # piso todavía no está mirando.
            "sin_fecha": agenda["totales"]["sin_fecha"],
        },
        "manda": manda,                     # 'resultado' | 'caja' | None
        "el_otro": otro,
        # ── Lo que el número NO sabe ─────────────────────────────────────────
        "sesgos": (_sesgos_del_piso(razones, int(n_desechables))
                   if razones is not None else []),
        # Los cuatro empujan para el mismo lado, así que el rótulo es uno solo y
        # sale del backend: la pantalla no tiene que inferirlo de la lista.
        "rotulo": "al_menos",
    }
