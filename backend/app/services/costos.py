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
# LA NORMALIZACIÓN DE NOMBRES SE REUSA, NO SE COPIA. `normalizar_alias` es la
# única respuesta que este repo ya tiene a «¿estos dos textos nombran la misma
# cosa?» (NFKD → ascii → espacios colapsados → MAYÚSCULAS), y la usa el matcheo
# de proveedores. Escribir una segunda acá sería tener dos definiciones de
# «Arriendo Vida» == «arriendo  vida» que se despegan en el primer cambio.
#
# EL RIESGO DE LA COMPARTICIÓN, dicho para que no sorprenda: si alguien la hace
# MÁS agresiva por el lado de los alias, acá empezaría a matchear cuentas que no
# son la misma y este módulo dejaría de ofrecer un costo real — el mes destino
# quedaría corto y el piso saldría BAJO, que es la dirección tranquilizadora.
# Por eso el candado no es este comentario: `LlaveDeCuentaTest` fija desde acá
# QUÉ tiene que matchear y qué NO, así que aflojarla del otro lado rompe un test
# de costos y no una cafetería.
from app.services.producto_alias import normalizar_alias
# La lista de conceptos reservados que services/facturas.py escribe para los pagos
# a proveedor vive en rentabilidad.py y se REUSA, no se copia: si allá cambia, acá
# tiene que cambiar en el mismo commit o el anti-doble-conteo se abre un agujero.
# Misma razón para la clave de categoría prohibida: el P&L la excluye del término
# de obligaciones y este servicio la rechaza en la entrada — las dos mitades tienen
# que hablar de la MISMA constante.
from app.services.rentabilidad import (CLAVE_CATEGORIA_CESANTIAS,
                                       CLAVE_CATEGORIA_IMPOCONSUMO,
                                       CLAVE_CATEGORIA_NOMINA,
                                       CLAVE_CATEGORIA_PRIMA,
                                       CLAVE_CATEGORIA_PROVEEDORES,
                                       CLAVE_CATEGORIA_RETEFUENTE,
                                       CLAVE_CATEGORIA_RETEICA,
                                       CLAVES_FUERA_DEL_GASTO,
                                       ESTADOS_ANULADOS, _CONCEPTOS_COMPRA)
# El piso de venta necesita el P&L entero (para MEDIR las razones de la venta) y
# los costos fijos del MES COMPLETO. Se importa el módulo y no solo unos nombres
# porque son funciones, no constantes: así queda a la vista de dónde salen.
from app.services import rentabilidad as rent_svc
# La tarifa del impoconsumo CON VIGENCIA. Se lee acá para poder decir POR QUE
# no hay monto cuando no lo hay (sin tarifa cargada, o precios que no lo
# llevan adentro) en vez de publicar un cero.
from app.services import parametros_tributarios as ptsvc

METODOS_PAGO = {"efectivo", "transferencia", "tarjeta", "cheque", "otro"}

# Los métodos cuya plata sale de una CUENTA y pueden descontar del libro del
# banco en el mismo pago. El efectivo sale del cajón o de la mano — meterlo al
# libro escribiría una salida que el extracto nunca va a tener. ESPEJADO en el
# front (components/plata/tipos.ts: METODOS_DE_BANCO). SYNC: si cambia acá,
# cambiar allá.
METODOS_BANCO = {"transferencia", "cheque"}
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
#
# 'impoconsumo' SÍ está, y es la única que NO se puede elegir a mano. La siembra
# `sembrar_categorias` porque `agendar_impoconsumo` la necesita existiendo para
# crear la obligación de la declaración; `_validar_categoria` la rechaza y
# `listar_categorias` no la ofrece, igual que a 'proveedores'. La diferencia con
# 'proveedores' es que a esta la usa un botón del sistema, no el formulario.
#
# Y NACE EN 'variable', que es la verdad del negocio: el impoconsumo SUBE CON LA
# VENTA —7,41 centavos de cada peso facturado— y "fijo" quiere decir que se paga
# venda lo que venda. Río abajo el grupo no cambia ningún número (la clave ya la
# saca de `oblig_rows` entera), pero el día que alguien toque esa exclusión el
# grupo es la segunda puerta: en 'fijo' entraría además al numerador del piso y
# lo inflaría $12.447.999 sobre esta base.
CATEGORIAS_INICIALES: list[dict] = [
    {"clave": "arriendo",      "nombre": "Arriendo",      "grupo": "fijo"},
    {"clave": "nomina",        "nombre": "Nómina",        "grupo": "fijo"},
    {"clave": "servicios",     "nombre": "Servicios",     "grupo": "fijo"},
    {"clave": "mantenimiento", "nombre": "Mantenimiento", "grupo": "fijo"},
    {"clave": "impuestos",     "nombre": "Impuestos",     "grupo": "fijo"},
    {"clave": "otros",         "nombre": "Otros",         "grupo": "fijo"},
    {"clave": CLAVE_CATEGORIA_IMPOCONSUMO,
     "nombre": "Impoconsumo (DIAN)", "grupo": "variable"},
    # Lo que sale de la caja y NO es costo del mes (decisión del dueño; el
    # detalle en rentabilidad.py, junto a CLAVES_FUERA_DEL_GASTO). Nacen en
    # 'variable' por la misma razón que el impoconsumo: el grupo es la segunda
    # puerta — si alguien rompiera la exclusión por clave, en 'fijo' además
    # inflarían el numerador del piso. Elegibles a mano (las carga él), con el
    # trato dicho en el catálogo (`fuera_del_gasto`).
    {"clave": CLAVE_CATEGORIA_RETEFUENTE, "nombre": "Retefuente", "grupo": "variable"},
    {"clave": CLAVE_CATEGORIA_RETEICA,    "nombre": "Reteica",    "grupo": "variable"},
    {"clave": CLAVE_CATEGORIA_PRIMA,
     "nombre": "Prima (giro jun/dic)", "grupo": "variable"},
    {"clave": CLAVE_CATEGORIA_CESANTIAS,
     "nombre": "Cesantías (giro feb)", "grupo": "variable"},
    # Los costos del propio banco: solo etiquetan filas del LIBRO (ambito
    # 'banco'), jamás obligaciones. Julio real: $191.196 de GMF y $11.567 de
    # comisión que ningún reporte veía.
    {"clave": "gmf", "nombre": "GMF (4×1000)", "grupo": "variable",
     "ambito": "banco"},
    {"clave": "comision_banco", "nombre": "Comisión bancaria", "grupo": "variable",
     "ambito": "banco"},
]

# Las categorías que el formulario de OBLIGACIONES no puede elegir. Ya no es un
# alias de CLAVES_FUERA_DEL_GASTO: retefuente, reteica, prima y cesantías están
# FUERA del gasto (el P&L no las cuenta) pero las carga el dueño A MANO — están
# en su lista de pagos con fecha («antes del 18»), y bloquearlas lo dejaría sin
# dónde ponerlas. La regla nueva tiene dos partes y un invariante:
#   · NO ELEGIBLE = tiene una puerta del sistema que la carga mejor (el botón
#     del impoconsumo, la factura del proveedor); elegirla a mano duplicaría.
#   · FUERA DEL GASTO pero elegible = el trato viaja DICHO en el catálogo
#     (`fuera_del_gasto` en la serialización) para que la pantalla lo muestre,
#     en vez de esconder la categoría.
#   · INVARIANTE (fijado por test): NO_ELEGIBLES ⊆ FUERA_DEL_GASTO — una
#     categoría con puerta del sistema jamás puede contar en el gasto, o la
#     puerta y el formulario contarían la misma plata dos veces.
CLAVES_NO_ELEGIBLES = (CLAVE_CATEGORIA_PROVEEDORES, CLAVE_CATEGORIA_IMPOCONSUMO)

# Los tres mundos de una categoría. 'cafe' es el único que puede colgar
# obligaciones; 'personal' y 'banco' solo etiquetan filas del libro del banco.
# Cerrado acá y validado en la entrada: un ámbito inventado no es una opinión,
# es un typo.
AMBITOS = ("cafe", "personal", "banco")
AMBITO_DEFAULT = "cafe"

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
                              grupo=c["grupo"],
                              ambito=c.get("ambito", AMBITO_DEFAULT),
                              orden=i, activa=True))
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


def _validar_ambito(ambito) -> str:
    """None cae al café: es el caso de siempre y el de todos los clientes viejos."""
    if ambito is None:
        return AMBITO_DEFAULT
    if ambito == "banco":
        # Las de banco son DOS y las siembra el sistema (gmf, comision_banco):
        # crear una tercera a mano diría que hay otro costo bancario que el
        # extracto conoce y el sistema no — eso se agrega acá, no por API.
        raise HTTPException(400, "Las categorías del banco (GMF, comisión) ya "
                                 "existen: elegilas en el libro en vez de crear "
                                 "una nueva.")
    if ambito not in AMBITOS:
        raise HTTPException(400, "El ámbito tiene que ser «cafe» o «personal».")
    return ambito


def crear_categoria(db: Session, nombre, grupo=None, usuario_id: int | None = None,
                    ambito=None) -> dict:
    """Crea una categoría de costo. El grupo por defecto es FIJO.

    Existe porque el catálogo eran seis filas quemadas en el arranque, y hoy
    publicidad, internet, domicilios, seguros y el contador caen todos en
    «Otros» — cinco costos distintos en una sola línea del P&L, que es lo mismo
    que no tener desglose.

    `ambito="personal"` crea una categoría de la plata del dueño (la cuota del
    carro, la casa): solo etiqueta filas del libro del banco y jamás cuelga
    obligaciones ni toca el resultado o el punto de equilibrio.
    """
    limpio = _validar_nombre_categoria(nombre)
    grupo_ok = _validar_grupo(grupo)
    ambito_ok = _validar_ambito(ambito)
    clave = _slug(limpio)
    if clave == CLAVE_CATEGORIA_PROVEEDORES:
        raise HTTPException(
            400, "Esa categoría está reservada: lo que le debés a un proveedor se "
                 "carga como FACTURA en Compras, no como costo fijo — acá se "
                 "contaría dos veces.")
    if clave == CLAVE_CATEGORIA_IMPOCONSUMO:
        # Sin esto, «Impoconsumo» escrito a mano slugifica justo a la clave
        # reservada y la colisión saldría como «ya existe una categoría» —
        # cierto, pero la fila que nombraría está oculta del catálogo y el
        # mensaje mandaría a buscar algo que no se ve en ninguna pantalla.
        raise HTTPException(
            400, "Esa categoría está reservada: la declaración del impoconsumo se "
                 "agenda con su botón en «Una vez al mes», con el monto medido "
                 "sobre lo que facturaste — a mano entraría con un monto inventado.")
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
                          ambito=ambito_ok, orden=(ultimo or 0) + 1, activa=True)
    db.add(fila)
    db.flush()
    audit.registrar(
        db, accion="crear_categoria_costo", tabla="costos_categorias",
        registro_id=fila.id, usuario_id=usuario_id,
        datos_despues={"clave": fila.clave, "nombre": fila.nombre,
                       "grupo": fila.grupo, "ambito": fila.ambito},
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
            "grupo": c.grupo, "ambito": getattr(c, "ambito", AMBITO_DEFAULT),
            "fuera_del_gasto": c.clave in CLAVES_FUERA_DEL_GASTO,
            "orden": c.orden, "activa": bool(c.activa),
            "advertencia": GRUPOS.get(c.grupo, {}).get("advertencia")}


def listar_categorias(db: Session, incluir_inactivas: bool = False,
                      ambito: str | None = AMBITO_DEFAULT) -> list:
    """El catálogo, filtrado por ámbito. El default es «cafe» A PROPÓSITO: los
    consumidores de siempre son los formularios de obligaciones, y ahí una
    categoría personal o del banco no puede aparecer. `ambito=None` trae todas
    (el libro del banco etiqueta con cualquiera).

    `fuera_del_gasto` viaja en cada fila: retefuente, reteica, prima y cesantías
    SÍ se eligen pero su plata no cuenta como costo del mes, y ese trato tiene
    que estar dicho donde el dueño elige — no descubierto meses después en un
    margen que no cuadra.
    """
    q = db.query(CostoCategoria)
    if not incluir_inactivas:
        q = q.filter(CostoCategoria.activa == True)  # noqa: E712
    if ambito is not None:
        q = q.filter(CostoCategoria.ambito == ambito)
    # NI 'proveedores' NI 'impoconsumo' se ofrecen nunca, ni siquiera con
    # incluir_inactivas: una categoría que `_validar_categoria` rechaza no puede
    # estar en el desplegable del formulario. Las FILAS se conservan (hay
    # obligaciones apuntándoles —históricas las de proveedores, del botón las del
    # impoconsumo— y borrarlas las dejaría huérfanas); lo que se corta es la
    # posibilidad de elegirlas a mano.
    q = q.filter(CostoCategoria.clave.notin_(CLAVES_NO_ELEGIBLES))
    cats = q.order_by(CostoCategoria.orden, CostoCategoria.nombre).all()
    return [{"id": c.id, "clave": c.clave, "nombre": c.nombre,
             "grupo": c.grupo, "ambito": getattr(c, "ambito", AMBITO_DEFAULT),
             "fuera_del_gasto": c.clave in CLAVES_FUERA_DEL_GASTO,
             "orden": c.orden} for c in cats]


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
        # ¿ESTA FILA LA PUEDE TOCAR EL FORMULARIO? Lo contesta el SERVER, con la
        # misma lista que usa `_validar_origen` y con la misma expresión, no con
        # una copia de la regla del lado de la pantalla. La fila del impoconsumo
        # y las viejas de proveedores son del sistema: sus botones Corregir y
        # Repetir invitaban a reinstalar el doble conteo, y ahora el server los
        # rechaza con un 400 — un botón que existe solo para dar error es peor
        # que no tenerlo, porque enseña que la pantalla no sabe lo que puede.
        "editable_a_mano": (cat.clave if cat else "") not in CLAVES_NO_ELEGIBLES,
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
    # El ámbito manda antes que la clave: una categoría personal o del banco no
    # puede colgar obligaciones NUNCA. La personal es plata del dueño como
    # persona natural — si entrara acá, terminaría en la agenda del café y a un
    # grupo de distancia de ensuciarle el punto de equilibrio.
    ambito = getattr(cat, "ambito", AMBITO_DEFAULT) or AMBITO_DEFAULT
    if ambito == "personal":
        raise HTTPException(
            400, f"«{cat.nombre}» es una categoría de plata personal: no entra a "
                 "las cuentas del café. Los gastos personales se anotan directo "
                 "en el libro del banco, y no tocan el resultado ni el punto de "
                 "equilibrio.")
    if ambito == "banco":
        raise HTTPException(
            400, f"«{cat.nombre}» es un costo del propio banco: se anota directo "
                 "en el libro (el sistema lo sugiere al registrar salidas), no "
                 "como una cuenta por pagar.")
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
    # El impoconsumo tiene su propio botón y no un renglón del formulario, por una
    # razón que no es de comodidad: el MONTO lo mide el sistema sobre la venta real
    # del bimestre y el VENCIMIENTO sale del calendario de la DIAN. Tecleado a mano
    # entraría con el monto y el mes que a alguien le parezcan, y esta obligación
    # no entra al P&L —está excluida por clave— así que un monto inventado acá no
    # lo corrige después ningún margen. Se manda al botón, que existe.
    if cat.clave == CLAVE_CATEGORIA_IMPOCONSUMO:
        raise HTTPException(
            400, "El impoconsumo no se carga a mano: el monto lo mide el sistema "
                 "sobre lo que facturaste en el bimestre y la fecha la fija el "
                 "calendario de la DIAN. Agendalo con el botón de «La declaración "
                 "del impoconsumo», en «Una vez al mes».")
    return cat


# El PORQUÉ de cada fila que el formulario no puede TOCAR, indexado por la MISMA
# clave que `CLAVES_NO_ELEGIBLES`. Vive en un dict y no adentro de un `if` para
# que agregar mañana una clave a la lista sin escribirle el motivo NO abra la
# puerta: `_validar_origen` bloquea igual, con el texto genérico. Un candado que
# se rompe tiene que fallar cerrado.
MOTIVO_ORIGEN_INTOCABLE: dict[str, str] = {
    CLAVE_CATEGORIA_IMPOCONSUMO: (
        "es la declaración del impoconsumo y no se corrige a mano: el monto lo "
        "mide el sistema sobre lo que facturaste en el bimestre, la fecha la "
        "fija el calendario de la DIAN y esta cuenta va aparte del P&L a "
        "propósito. Si el número de tu contador es otro, anulala y volvé a "
        "agendarla con esa cifra desde «La declaración del impoconsumo»."),
    CLAVE_CATEGORIA_PROVEEDORES: (
        "es una deuda con un proveedor y no se corrige acá: esa plata ya entra "
        "al P&L y a la agenda por su FACTURA en Compras. Editarla desde este "
        "formulario la movería a una categoría que el P&L SÍ cuenta y la misma "
        "mercadería quedaría contada dos veces. Para pagarla, andá a «Pagos "
        "proveedores»."),
}


def _validar_origen(db: Session, obligacion: Obligacion) -> None:
    """Puerta de la categoría de ORIGEN: qué filas puede TOCAR el formulario.

    `_validar_categoria` mira el DESTINO —a dónde VA la obligación— y esa mitad
    sola deja la puerta abierta por el otro lado. La fila del impoconsumo se
    dibuja en Obligaciones con sus botones como cualquier otra: el dueño le
    cambia la categoría a una de grupo fijo y la misma plata vuelve a contarse.
    MEDIDO sobre la base de siempre ($155,6M facturados en el bimestre), el piso
    del mes del devengo sube $12.447.999,00 y el margen neto cae $11.525.925,93
    — el mundo (B) que la categoría dedicada evitó, reinstalado con dos taps y
    sin que ninguna pantalla lo diga.

    Y NO ALCANZABA CON MIRAR EL `categoria_id` QUE LLEGA. El desplegable no
    ofrece estas claves, así que el select del formulario abría EN BLANCO sobre
    la fila y mandaba el primer renglón de la lista: la fila terminaba en
    'arriendo' —grupo fijo— sin que nadie eligiera nada, con el mismo daño en
    pesos. La guarda tiene que preguntar de dónde SALE la fila, no a dónde va.

    Y SE BLOQUEA LA EDICIÓN COMPLETA, no el campo de la categoría. La fila
    entera es del sistema: el monto lo mide sobre la venta real del bimestre, el
    vencimiento sale del calendario de la DIAN, y el DEVENGO es lo que ata la
    declaración a SU bimestre — corrido afuera de ese rango,
    `_obligacion_de_impoconsumo` deja de encontrarla y el botón de agendar, que
    era idempotente, crea una SEGUNDA fila: la DIAN cobrada dos veces en la
    agenda.

    LA SALIDA SIGUE ABIERTA Y ES `anular`. Si el número del contador es otro, se
    anula esta y se vuelve a agendar con esa cifra. Anular es seguro en la
    dirección contraria —saca plata de la agenda, no la agrega— y se corrige
    solo: sin obligación viva, `_cobertura_impoconsumo` vuelve a avisar que
    falta.

    LA LISTA ES `CLAVES_NO_ELEGIBLES`, la misma de `_validar_categoria` y de
    `listar_categorias`, y no una tercera que se le parezca: una categoría que
    no se puede ELEGIR tampoco se puede seguir EDITANDO a mano. Sin esto la de
    'proveedores' se escapaba por el mismo agujero, y ahí el doble conteo es
    contra la FacturaCompra que representa la misma deuda.
    """
    cat = db.query(CostoCategoria).filter(
        CostoCategoria.id == obligacion.categoria_id).first()
    clave = cat.clave if cat else ""
    if clave not in CLAVES_NO_ELEGIBLES:
        return
    motivo = MOTIVO_ORIGEN_INTOCABLE.get(clave) or (
        f"está en «{cat.nombre if cat else clave}», una categoría que el P&L no "
        "cuenta como gasto, y no se corrige a mano: editarla la movería a una "
        "que sí cuenta y la misma plata quedaría contada dos veces.")
    raise HTTPException(400, f"«{obligacion.concepto or 'Esta cuenta'}» {motivo}")


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


# ── Obligaciones ────────────────────────────────────────────────────────────

def crear_obligacion(db: Session, data, usuario_id: int,
                     barista_id: int | None = None,
                     barista_nombre: str | None = None) -> dict:
    _validar_categoria(db, data.categoria_id)
    _validar_tienda(db, data.tienda_id)
    monto = _validar_monto(data.monto)
    _validar_nomina_a_mano(db, data.categoria_id, monto, data.fecha_devengo)
    obligacion = Obligacion(
        tienda_id=data.tienda_id,
        categoria_id=data.categoria_id,
        concepto=_validar_concepto(data.concepto),
        beneficiario=(data.beneficiario or "").strip() or None,
        monto=monto,
        fecha_devengo=data.fecha_devengo,
        fecha_vencimiento=data.fecha_vencimiento,
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
    # LA CATEGORÍA DE DONDE SALE LA FILA, ANTES DE MIRAR UN SOLO CAMPO. Es la
    # mitad que faltaba: validar solo el destino dejaba que la declaración del
    # impoconsumo se editara hacia una categoría contada, y ahí el piso y el
    # margen se movían los millones que la categoría dedicada había dejado
    # quietos. Va arriba de todo porque la respuesta no depende de qué se manda.
    _validar_origen(db, obligacion)

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
    if "beneficiario" in campos:
        obligacion.beneficiario = (campos["beneficiario"] or "").strip() or None
    if "nota" in campos:
        obligacion.nota = campos["nota"]
    if "imagen_url" in campos:
        obligacion.imagen_url = campos["imagen_url"]

    # Con los campos ya aplicados y ANTES del commit: la edición también puede
    # convertir una fila en «la nómina del mes» (cambiando la categoría, el
    # devengo o bajando el monto a una quincena), y esa fila apaga el cálculo
    # igual que una creada de cero. Solo se recalcula si se tocó algo que pesa:
    # liquidar el mes por editar una nota sería castigar la edición inocente.
    if {"monto", "categoria_id", "fecha_devengo"} & campos.keys():
        _validar_nomina_a_mano(db, obligacion.categoria_id,
                               float(obligacion.monto), obligacion.fecha_devengo)

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


def _corrido(d: date, meses: int) -> date:
    """La misma fecha corrida `meses` meses, con el día recortado al último real.

    Sin el recorte, el arriendo del 31 de enero pediría un 31 de febrero y
    reventaría; y usar +30 días correría la fecha un poco cada mes hasta que el
    "arriendo de agosto" quedara devengado en septiembre.

    UNA SOLA definición de "correr una fecha de mes", porque ahora hay DOS
    caminos que la usan: el botón de repetir de a una (+1) y el lote que arma un
    mes entero (que puede tener que correr +2 si el dueño se saltó un mes). Dos
    aritméticas del calendario se despegan en el primer 31 y nadie se entera.
    """
    total = (d.year * 12 + (d.month - 1)) + int(meses)
    anio, mes = divmod(total, 12)
    mes += 1
    ultimo = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(d.day, ultimo))


def _mes_siguiente(d: date) -> date:
    """Mismo día del mes que viene. El caso de `_corrido` que usa `repetir`."""
    return _corrido(d, 1)


def _lockear_serie(db: Session, serie_id: int) -> None:
    """Cierra la puerta de la serie ANTES de preguntar si la copia del mes existe.

    ═══════════════════════════════════════════════════════════════════════════
    LA CARRERA QUE CIERRA
    ═══════════════════════════════════════════════════════════════════════════
    `_copia_viva_del_mes` es un SELECT pelado, y entre que contesta «no hay» y el
    INSERT que viene después hay una ventana abierta. Dos requests simultáneas
    —el dueño toca «Crear las 14» dos veces, o son dos tablets, una por sede— ven
    LAS DOS el mes vacío y las dos insertan: el arriendo y la nómina quedan
    DUPLICADOS. Ser idempotente contra dos toques SEGUIDOS no dice nada sobre dos
    toques SIMULTÁNEOS; son dos problemas distintos y este módulo solo tenía
    resuelto el primero.

    La dirección del error acá es al revés de la habitual en este módulo: un
    costo fijo duplicado INFLA el piso de venta. El dueño no queda tranquilo de
    más — sale a vender más de lo que necesita, con un número que no es.

    ═══════════════════════════════════════════════════════════════════════════
    POR QUÉ SE LOCKEA LA CABEZA Y NO «LA COPIA DEL MES»
    ═══════════════════════════════════════════════════════════════════════════
    Porque la copia del mes es justamente la fila que TODAVÍA NO EXISTE: no hay
    fantasma que se pueda lockear. La cabeza sí existe siempre (`serie_id` es
    `plantilla_id or id`, y de `obligaciones` no se borra nunca ninguna: la baja
    es lógica con `anulada`), así que sirve de cerrojo de la serie entera. Se
    busca SIN filtrar por `anulada`: una cabeza anulada sigue siendo la fila que
    ordena la fila de espera, y filtrarla dejaría la serie sin cerrojo justo
    cuando la cabeza vieja se dio de baja.

    Postgres (Render) respeta el `FOR UPDATE`: la segunda request espera al
    commit de la primera, y cuando entra su `_copia_viva_del_mes` YA VE la copia
    y contesta «ya estaba». SQLite lo ignora al compilar —no emite la cláusula—
    así que los tests no se traban ni cambian de comportamiento; tampoco tienen
    concurrencia real que reproducir.

    Si la cabeza no apareciera (una serie con `plantilla_id` colgado, que hoy no
    puede pasar), no hay nada que lockear y el camino queda como estaba: degrada
    a la carrera vieja, nunca a un error.

    ═══════════════════════════════════════════════════════════════════════════
    LO QUE FALTA, Y POR QUÉ NO ESTÁ ACÁ
    ═══════════════════════════════════════════════════════════════════════════
    El arreglo de raíz sería un ÍNDICE ÚNICO PARCIAL sobre (plantilla_id, mes de
    `fecha_devengo`) `WHERE anulada = false` —el patrón de
    `ConteoFisico.uq_conteo_turno_tipo` y `Pago.uq_pago_movimiento_caja`—, y
    hay tres razones para no meterlo en el mismo movimiento:

    1. La llave es el MES y `fecha_devengo` es un Date, así que es un índice por
       EXPRESIÓN, y la expresión se escribe distinto en cada motor
       (`date_trunc('month', ...)` en Postgres, `strftime('%Y-%m', ...)` en
       SQLite). Deja de ser un `Index` del modelo y pasa a ser SQL a mano por
       dialecto en el loop de migración.
    2. En producción ya puede haber duplicados históricos de esta misma carrera.
       El loop de `main.py` traga cada excepción y sigue, así que un CREATE que
       falle NO tumba el arranque — pero deja el índice sin crear y en silencio:
       el sistema creería tener una garantía que no tiene, que es exactamente el
       error de esta familia. Antes hay que medir y limpiar los duplicados.
    3. Con el índice puesto hay que atrapar el IntegrityError y traducirlo a
       «ya estaba», o el perdedor de la carrera se lleva un 500. En el lote eso
       aborta las catorce.

    El lock no depende de nada de eso y no puede dejar la cafetería sin sistema
    un lunes a las 6 de la mañana. El índice queda como el paso siguiente, con
    la limpieza de duplicados adelante.
    """
    db.query(Obligacion).filter(Obligacion.id == serie_id).with_for_update().first()


def _copia_viva_del_mes(db: Session, serie_id: int, anio: int, mes: int):
    """La obligación VIVA de esa serie devengada en ese mes, si existe.

    LA LLAVE DE IDEMPOTENCIA DE TODO ESTE MÓDULO, en un solo lugar. Se compara
    por MES y no por fecha exacta: si alguien le corrigió el día a la copia,
    sigue siendo la del mes y armarla otra vez no puede duplicarla.

    La serie se busca por los DOS lados —`plantilla_id == serie` para las copias
    y `id == serie` para el primer eslabón, que no tiene plantilla_id— porque la
    llave es siempre el primer eslabón y él mismo cuenta como miembro.

    NO ALCANZA SOLA CONTRA DOS REQUESTS SIMULTÁNEAS: es un SELECT, y lo que ve
    puede quedar viejo antes del INSERT. Todo camino que vaya a ESCRIBIR tiene
    que pasar antes por `_lockear_serie`; el que solo mira (la vista previa)
    puede llamarla pelada.
    """
    inicio = date(int(anio), int(mes), 1)
    fin = date(int(anio), int(mes), calendar.monthrange(int(anio), int(mes))[1])
    return db.query(Obligacion).filter(
        or_(Obligacion.plantilla_id == serie_id, Obligacion.id == serie_id),
        Obligacion.anulada == False,  # noqa: E712
        Obligacion.fecha_devengo >= inicio,
        Obligacion.fecha_devengo <= fin,
    ).order_by(Obligacion.id).first()


def repetir_obligacion(db: Session, obligacion_id: int, usuario_id: int,
                       barista_id: int | None = None,
                       barista_nombre: str | None = None) -> dict:
    """Crea la copia del MES SIGUIENTE de un costo, en un tap.

    `plantilla_id` era una columna muerta: nadie generaba nunca la obligación del
    mes que viene. Con dos sedes eso son 12-18 cargas manuales por mes
    retecleando lo mismo, que es el camino más corto a que el módulo se abandone.
    (La otra columna muerta, `recurrencia`, se sacó: ver el modelo `Obligacion`.)

    Deliberadamente NO es un scheduler: no hay job que cree costos solo. El dueño
    aprieta el botón cuando quiere, ve la copia y puede ajustarle el monto (la
    energía no vale igual todos los meses). Un generador automático llenaría el
    P&L de costos que nadie confirmó.

    IDEMPOTENTE por (serie, mes de devengo): un doble tap no cobra el arriendo dos
    veces. La respuesta trae `ya_existia` para que la pantalla lo diga en vez de
    fingir que acaba de crear algo.

    Y también contra dos requests SIMULTÁNEAS, que es un problema distinto: el
    cerrojo de `_lockear_serie` va antes de mirar si la copia existe. Lo toma
    por la MISMA llave que el lote de `armar_mes`, así que las dos puertas de
    este módulo son una sola.
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

    # El cerrojo va ANTES de mirar si ya está, y no después: mirar y después
    # lockear deja la ventana igual de abierta. Es la MISMA llave que usa el
    # lote, y tiene que ser la misma puerta — dejar cerrada una sola de las dos
    # no sirve de nada: el dueño repite de a una desde Obligaciones mientras la
    # otra tablet arma el mes entero, y las dos crean la copia de septiembre.
    _lockear_serie(db, serie_id)

    ya = _copia_viva_del_mes(db, serie_id, devengo.year, devengo.month)
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


def _series_y_sueltas(db: Session, antes_de: date) -> tuple[dict[int, Obligacion],
                                                            list[Obligacion]]:
    """Los DOS montones que salen del mismo barrido, y por qué son dos y no uno.

    ═══════════════════════════════════════════════════════════════════════════
    LOS DOS CEROS QUE ERAN EL MISMO CERO
    ═══════════════════════════════════════════════════════════════════════════
    Esta función devolvía SOLO el primer montón y `armar_mes` publicaba su tamaño
    como si fuera «no falta nada». Con los datos reales del negocio —cinco fijos
    cargados a mano todos los meses, $27.620.000, y NADIE apretó nunca «Repetir
    mes que viene»— ninguna obligación tiene `plantilla_id`, el montón sale
    VACÍO, y la pantalla afirmaba dos veces que el mes que viene ya estaba.

    Medido con sonda sobre este negocio, ANTES: agosto $27.620.000 de fijos y un
    piso de $29.829.597,61; septiembre $0,00 de fijos y sin piso, con la pantalla
    diciendo «ya tienen su copia». «Ninguna serie repetible que copiar» se
    publicaba como «nada falta en septiembre» — otro cero completamente distinto,
    del lado tranquilizador y con la firma del server encima.

    Ahora salen los dos montones por separado, y `armar_mes` los nombra por
    separado:

      · `probadas` — las series que alguien YA declaró repetibles apretando el
        botón al menos una vez. Solo estas se copian SOLAS.
      · `sueltas` — las cuentas vivas que todavía no son serie. No se copian
        solas NUNCA: se OFRECEN con su concepto y su plata a la vista para que el
        dueño elija cuáles van. La copia nace con `plantilla_id`, o sea que de ahí
        en más ya son serie y el lote las agarra solo. Elige una vez, no todos
        los meses.

    ═══════════════════════════════════════════════════════════════════════════
    POR QUÉ LAS SUELTAS NO SE COPIAN SOLAS, AUNQUE SEA MÁS CÓMODO
    ═══════════════════════════════════════════════════════════════════════════
    Porque no toda obligación se repite. Arreglar el molino, un anticipo, una
    compra de una sola vez: copiarlas al mes siguiente inventa un costo que nadie
    va a pagar, y eso INFLA el piso. Es el error en la dirección contraria y
    cuesta igual de caro — el dueño sale a vender de más contra un número que no
    es. Y el catálogo NO las separa: «arreglar el molino» es 'mantenimiento',
    grupo FIJO desde `reclasificar_grupos_v1`, o sea que entra al numerador del
    piso igual que el arriendo. Ninguna regla automática puede distinguir un
    arriendo de una reparación. El dueño sí, y le toma un tap.

    ═══════════════════════════════════════════════════════════════════════════
    SOLO SE OFRECEN LAS DEL MES MÁS RECIENTE QUE TENGA ALGUNA
    ═══════════════════════════════════════════════════════════════════════════
    Y no todas las sueltas de la historia. Con dos años de costos sueltos la lista
    sería de cincuenta renglones, y una lista que nadie lee es exactamente cómo
    se termina tildando la de al lado. Acotada a UN mes son cinco o seis.

    Se toma el mes MÁS RECIENTE con sueltas y no «el mes anterior» a secas: si el
    dueño se saltó un mes, «el anterior» está vacío y la oferta desaparecería
    entera — o sea el mes que viene arrancando en cero otra vez, que es el error
    que este arreglo persigue. De qué mes son viaja en `candidatas_de`, porque la
    pantalla tiene que poder nombrarlo y no dar por hecho que es el mes pasado.

    LO QUE ESTA REGLA NO ARREGLA, dicho para que nadie lo lea como que sí: una
    suelta que el dueño decidió NO repetir se le sigue ofreciendo hasta que
    aparezca un mes más nuevo con sueltas. Es molesto y es a propósito — el
    remedio (una marca de «esta no va nunca») es una columna nueva, y equivocarse
    hacia «te lo vuelvo a preguntar» cuesta un tap, mientras que equivocarse
    hacia «no te lo pregunto más» cuesta un costo fijo que no entra al piso.

    Las de más plata primero. El arriendo y la nómina son las que no se pueden
    olvidar, así que son las que van arriba de todo.

    De las series se toma el miembro MÁS NUEVO y no el del mes pasado a secas: si
    el dueño se saltó un mes, el arriendo de septiembre tiene que salir del de
    julio y no perderse.
    """
    filas = (
        db.query(Obligacion)
        .filter(Obligacion.anulada == False,  # noqa: E712
                Obligacion.fecha_devengo < antes_de)
        .order_by(Obligacion.fecha_devengo.asc(), Obligacion.id.asc())
        .all()
    )
    series: dict[int, Obligacion] = {}
    con_copia: set[int] = set()
    for o in filas:
        serie = o.plantilla_id or o.id
        # El orden del query ya deja el más nuevo al final, así que pisar es
        # quedarse con el último. El desempate por id es explícito porque
        # `fecha_devengo` sola no ordena dos costos del mismo día.
        series[serie] = o
        if o.plantilla_id is not None:
            con_copia.add(serie)

    # Las PROBADAS: las que tienen al menos una copia hecha a mano.
    probadas = {sid: o for sid, o in series.items() if sid in con_copia}
    sin_serie = [o for sid, o in series.items() if sid not in con_copia]
    if not sin_serie:
        return probadas, []
    # El mes más reciente que tenga alguna, medido sobre (año, mes) y no sobre la
    # fecha: dos sueltas del mismo mes con días distintos son las dos del mismo
    # mes, y comparar fechas dejaría afuera la del 3 cuando hay una del 28.
    ultimo_mes = max((o.fecha_devengo.year, o.fecha_devengo.month)
                     for o in sin_serie)
    sueltas = sorted(
        (o for o in sin_serie
         if (o.fecha_devengo.year, o.fecha_devengo.month) == ultimo_mes),
        # De más plata a menos. El id desempata para que dos cuentas del mismo
        # monto no se cambien de lugar entre dos lecturas: una lista que baila es
        # una lista en la que se tilda la de al lado.
        key=lambda o: (-float(o.monto or 0), o.id))
    return probadas, sueltas


def _serializar_candidata(o: Obligacion, parecidas: list[Obligacion]) -> dict:
    """Una cuenta suelta OFRECIDA, con lo que hace falta para decidir por ella.

    Concepto, plata, sede, categoría y de qué día es. Sin eso la pantalla pide
    una decisión sobre una lista de nombres pelados, y el dueño tilda todas o no
    tilda ninguna — las dos son justo la decisión que este paso existe para NO
    tomar por él.

    NO se filtran acá las que no se pueden copiar (categoría desactivada, o la
    vieja 'proveedores'). Sacarlas de la oferta en silencio sería esconder una
    cuenta que el dueño está buscando; si la tilda, pasa por la MISMA puerta que
    todo lo demás y vuelve en `no_se_pueden` con el porqué escrito.

    ═══════════════════════════════════════════════════════════════════════════
    `parecidas`: LO QUE EL MES DESTINO YA TIENE Y SE LE PARECE
    ═══════════════════════════════════════════════════════════════════════════
    La llave de cobertura (`_llave_de_cuenta`) es concepto normalizado + sede.
    Cuando matchea, la cuenta NO se ofrece y se va a `ya_en_el_mes`. Pero
    matchear es una igualdad, y dos escrituras distintas del mismo costo
    —«Arriendo Vida» contra «Arriendo local Vida»— no son iguales: esa cuenta
    SE SIGUE OFRECIENDO, y tildarla duplica el arriendo.

    Acá viaja lo que quedó SIN EMPAREJAR en el mes destino con la misma sede y
    la misma categoría. No decide nada —la cuenta se ofrece igual— pero le pone
    el aviso EN EL RENGLÓN, antes del tilde y no después: «septiembre ya tiene
    "Arriendo local Vida" por $8.500.000». Una llave más floja habría escondido
    la cuenta sola, y esconder un costo real deja el mes corto y el piso BAJO.
    """
    cat = o.categoria
    return {
        "obligacion_id": o.id,
        "concepto": o.concepto,
        "beneficiario": o.beneficiario,
        "monto": round(float(o.monto or 0), 2),
        "tienda_id": o.tienda_id,
        "tienda_nombre": o.tienda.nombre if o.tienda else None,
        "categoria_clave": cat.clave if cat else "",
        "categoria_nombre": cat.nombre if cat else "",
        "fecha_devengo": o.fecha_devengo,
        "fecha_vencimiento": o.fecha_vencimiento,
        "parecidas": [_serializar_la_del_destino(p) for p in parecidas],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LO QUE EL MES DESTINO YA TIENE
# ═══════════════════════════════════════════════════════════════════════════════
# EL BLOQUEANTE QUE ESTO CIERRA, MEDIDO
# ─────────────────────────────────────────────────────────────────────────────
# Este negocio carga los cinco fijos A MANO todos los meses desde hace siete.
# `armar_mes` armaba su oferta mirando SOLO el mes origen: septiembre ya tenía
# sus $27.620.000 cargados a mano y el lote ofrecía igual los cinco de agosto,
# porque una cuenta suelta no tiene `plantilla_id` y `_copia_viva_del_mes` —que
# compara por SERIE— no tenía con qué reconocerla. El dueño tildaba los cinco:
#
#     costos_fijos_devengados  $27.620.000 (n=5)  →  $55.240.000 (n=10)
#     piso_mes                 $29.829.597,61     →  $59.659.195,23
#
# El piso pidiéndole $59,7M cuando necesita $29,8M, y $27.620.000 de deuda
# inventada en la agenda y en la proyección de caja.
#
# Y HABÍA UN SEGUNDO, PEOR, QUE NO NECESITA QUE NADIE TILDE NADA: una cuenta que
# YA es serie se copia SOLA. Con el arriendo como serie y septiembre cargado a
# mano, `van_a_crearse` traía el arriendo igual —$8.500.000 → $17.000.000 en el
# numerador del piso— sin un solo tap. Ese es el mes que viene del arreglo de la
# ronda pasada: en cuanto el dueño tilde los cinco YA SON serie, y el 1 de
# octubre a las 6 vuelve a cargarlos a mano como hace siete meses.
#
# Por eso la cobertura se mide contra el mes DESTINO y se aplica a los DOS
# montones: el que se copia solo y el que se ofrece.

def _llave_de_cuenta(o: Obligacion) -> tuple[str, int | None]:
    """CONCEPTO NORMALIZADO + SEDE. Por qué esos dos, y por qué NO la categoría.

    · CONCEPTO NORMALIZADO y no el texto pelado: «Arriendo Vida» y
      «arriendo  vida» son la misma cuenta escrita dos veces, y comparando
      strings crudos las dos entraban al mes. La normalización se reusa de
      `producto_alias` — ver el import.

    · SEDE, y es OBLIGATORIA. Medido: «Arriendo» vale $8.500.000 en Vida y
      $7.200.000 en Centro, con el MISMO concepto. Sin la sede en la llave, el
      arriendo de Vida ya cargado taparía al de Centro, Centro nunca entraría al
      mes y el piso saldría $7.200.000 CORTO — la dirección tranquilizadora, que
      es la cara del error que este módulo persigue.

    · LA CATEGORÍA QUEDA AFUERA, A PROPÓSITO. Meterla haría la llave más
      ESTRICTA, y una llave estricta falla hacia «no reconozco que ya está» →
      duplicar. El caso real: el dueño carga septiembre a mano y le pone a
      «Arriendo Vida» la categoría equivocada; con la categoría adentro, la
      llave no matchea y la serie copia un segundo arriendo. Sin ella, matchea.
      Lo que la categoría protegía —dos costos distintos que comparten concepto
      y sede— ya lo cubre el conteo por MULTIPLICIDAD de abajo, así que sacarla
      no abre nada. Igual viaja en `parecidas` para que se vea si difiere.
    """
    return (normalizar_alias(o.concepto), o.tienda_id)


def _serializar_la_del_destino(o: Obligacion) -> dict:
    """La fila del MES DESTINO que tapa (o se parece a) una del origen.

    Va con su plata y su fecha porque la pregunta que contesta no es «¿existe?»
    sino «¿es la misma?»: $8.500.000 del 5/9 se reconoce, $150.000 del 5/9 no."""
    cat = o.categoria
    return {
        "obligacion_id": o.id,
        "concepto": o.concepto,
        "monto": round(float(o.monto or 0), 2),
        "fecha_devengo": o.fecha_devengo,
        "categoria_nombre": cat.nombre if cat else "",
        "tienda_nombre": o.tienda.nombre if o.tienda else None,
    }


class _LoQueElMesYaTiene:
    """Las cuentas VIVAS ya devengadas en el mes destino, como PRESUPUESTO.

    ═══════════════════════════════════════════════════════════════════════════
    POR QUÉ SE REPARTE Y NO SE PREGUNTA «¿EXISTE?»
    ═══════════════════════════════════════════════════════════════════════════
    Preguntar «¿el destino tiene alguna con esta llave?» alcanza mientras haya
    una sola. Con dos —agua y luz, las dos tecleadas «Servicios públicos» en la
    misma sede— la presencia de UNA taparía a las DOS, y el mes destino se
    quedaría sin la segunda: un costo real que no entra al piso, o sea el piso
    BAJO. Contra eso el único remedio es contar.

    Así que cada fila del destino se GASTA una sola vez. Si el origen trae dos
    con la misma llave y el destino tiene una, se tapa una y se ofrece la otra.

    ═══════════════════════════════════════════════════════════════════════════
    EL ORDEN EN QUE SE GASTA ES PARTE DEL CONTRATO
    ═══════════════════════════════════════════════════════════════════════════
    Primero por IDENTIDAD (`sacar_miembro_de`), que es la llave fuerte: una fila
    del destino que ya pertenece a esa serie es ESA cuenta, no una parecida.
    Recién después por llave, y en un orden fijo (series por `serie_id`, sueltas
    por -monto/id). Sin orden fijo, dos lecturas seguidas ofrecerían listas
    distintas y la vista previa dejaría de valer para el commit.

    `sacar_miembro_de` repite la condición de `_copia_viva_del_mes` en memoria y
    SOLO para repartir este presupuesto. La que decide si se ESCRIBE sigue siendo
    `_copia_viva_del_mes` después del cerrojo: acá no hay decisión de escritura,
    así que una divergencia no puede crear una fila — como mucho reparte un cupo
    de más. `MismaCondicionQueLaLlaveTest` las mantiene pegadas igual.
    """

    def __init__(self, filas: list[Obligacion]):
        self.filas = filas
        self.n = len(filas)
        self.total = round(sum(float(o.monto or 0) for o in filas), 2)
        # ── LO QUE DE ESTO ENTRA AL PISO, aparte ─────────────────────────────
        # La cobertura se mide sobre TODAS las vivas (una cuenta variable ya
        # cargada tampoco se puede duplicar), pero la PANTALLA habla del piso, y
        # publicar el total de todo como si fuera el numerador daría un número
        # CERCA del correcto y del lado tranquilizador: una declaración del
        # impoconsumo de $12M haría leer como cubierto un mes sin un peso de
        # costos fijos. Mismo filtro que `rentabilidad._cuenta_costos_fijos`
        # (grupo 'fijo') más las claves que el P&L saca del gasto.
        #
        # NO INCLUYE LA NÓMINA CALCULADA, que `costos_fijos_del_mes` sí suma:
        # esta clase solo ve obligaciones. La diferencia va para el lado seguro
        # —el mes se ve MENOS cubierto de lo que está, o sea que el aviso suena
        # de más y nunca de menos— y por eso no se disfraza de otra cosa: el
        # campo se llama `fijos` y la pantalla lo nombra como costos fijos
        # CARGADOS, no como el piso.
        entran = [o for o in filas
                  if o.categoria is not None
                  and (o.categoria.grupo or "") == "fijo"
                  and o.categoria.clave not in CLAVES_FUERA_DEL_GASTO]
        self.n_fijos = len(entran)
        self.fijos = round(sum(float(o.monto or 0) for o in entran), 2)
        self._por_llave: dict[tuple, list[Obligacion]] = {}
        for o in filas:
            self._por_llave.setdefault(_llave_de_cuenta(o), []).append(o)

    def sacar_miembro_de(self, serie_id: int) -> Obligacion | None:
        """La fila del destino que YA es de esa serie, gastada. Misma condición
        que `_copia_viva_del_mes`: la cabeza cuenta como miembro de sí misma."""
        for lista in self._por_llave.values():
            for i, o in enumerate(lista):
                if o.id == serie_id or o.plantilla_id == serie_id:
                    return lista.pop(i)
        return None

    def sacar_por_llave(self, o: Obligacion) -> Obligacion | None:
        """La primera fila libre del destino con la misma llave, gastada."""
        lista = self._por_llave.get(_llave_de_cuenta(o))
        return lista.pop(0) if lista else None

    def parecidas_a(self, o: Obligacion) -> list[Obligacion]:
        """Lo que quedó SIN EMPAREJAR con la misma sede y categoría.

        Se lee DESPUÉS de repartir: una fila que ya tapó a otra no puede volver
        a aparecer como aviso, o el dueño leería dos veces la misma cuenta."""
        llave = _llave_de_cuenta(o)
        return [x for lista in self._por_llave.values() for x in lista
                if x.tienda_id == o.tienda_id
                and x.categoria_id == o.categoria_id
                and _llave_de_cuenta(x) != llave]


def _vivas_del_mes(db: Session, anio: int, mes: int) -> list[Obligacion]:
    """Las obligaciones VIVAS devengadas en ese mes. La misma ventana y el mismo
    filtro de `anulada` que `_copia_viva_del_mes`, sin el filtro de serie.

    Las ANULADAS quedan afuera y es deliberado: una cuenta que el dueño dio de
    baja en septiembre NO cubre nada, y seguir tapándola con ella dejaría el mes
    sin ese costo. Se vuelve a ofrecer, que es la dirección segura."""
    inicio = date(int(anio), int(mes), 1)
    fin = date(int(anio), int(mes), calendar.monthrange(int(anio), int(mes))[1])
    return (db.query(Obligacion)
            .filter(Obligacion.anulada == False,  # noqa: E712
                    Obligacion.fecha_devengo >= inicio,
                    Obligacion.fecha_devengo <= fin)
            .order_by(Obligacion.id)
            .all())


def _serializar_tapada(origen: Obligacion, ya: Obligacion,
                       automatica: bool) -> dict:
    """Una cuenta que NO va al mes porque el mes ya la tiene, con las dos filas.

    NO ES UN SILENCIO Y NO PUEDE SERLO. Que el server decida no copiar algo es
    exactamente la clase de decisión que, callada, se lee como «no había nada».
    Van las dos: la del origen que se iba a copiar y la del destino que la tapa,
    con concepto, plata y fecha, para que el dueño pueda decir «esa no es la
    misma» si la llave se equivocó.

    `automatica` separa las dos procedencias, que se cuentan distinto: True es
    una SERIE que se habría copiado sola (nadie iba a tildar nada), False es una
    cuenta suelta que ni siquiera se ofrece.
    """
    cat = origen.categoria
    return {
        "obligacion_id": origen.id,
        "concepto": origen.concepto,
        "monto": round(float(origen.monto or 0), 2),
        "tienda_nombre": origen.tienda.nombre if origen.tienda else None,
        "categoria_nombre": cat.nombre if cat else "",
        "fecha_devengo": origen.fecha_devengo,
        "automatica": bool(automatica),
        "ya": _serializar_la_del_destino(ya),
    }


def armar_mes(db: Session, anio: int, mes: int, *, confirmar: bool,
              usuario_id: int, barista_id: int | None = None,
              barista_nombre: str | None = None,
              incluir: list[int] | None = None) -> dict:
    """ARMAR TODOS LOS COSTOS FIJOS DE UN MES DE UNA, o mostrar antes qué haría.

    ═══════════════════════════════════════════════════════════════════════════
    POR QUÉ EXISTE, SI EL BOTÓN DE A UNA YA FUNCIONA
    ═══════════════════════════════════════════════════════════════════════════
    La pantalla hacía N requests en un `for`, una por obligación. Es idempotente,
    así que reintentar no duplica nada — pero si la tablet pierde señal en la
    séptima de catorce, el mes queda armado A LA MITAD y las siete que faltan no
    están en ningún lado. La proyección del mes siguiente sale con la mitad de
    los costos y por lo tanto TRANQUILIZADORA, que es la dirección en la que este
    módulo se equivoca siempre.

    Acá son un solo viaje y un solo `commit`: o entran las catorce o no entra
    ninguna. Y con `confirmar=False` no escribe nada y devuelve la lista exacta
    de lo que va a crear, con la plata que le va a agregar al mes — el dueño ve
    los montos ANTES de que existan, que es cuando todavía puede decir «ese
    arriendo subió».

    ═══════════════════════════════════════════════════════════════════════════
    LOS DOS CEROS, Y POR QUÉ ESTE LOTE NACÍA INERTE
    ═══════════════════════════════════════════════════════════════════════════
    Solo se copian solas las series PROBADAS (las que tienen al menos una copia
    hecha a mano). En este negocio los fijos se cargan a mano todos los meses y
    nadie apretó nunca «Repetir mes que viene», así que no hay NINGUNA serie: el
    lote encontraba cero, y la respuesta —`van_a_crearse: 0`, `ya_estaban: 0`—
    se leía en la pantalla como «ya está todo armado». Medido: agosto
    $27.620.000 de fijos con un piso de $29.829.597,61, septiembre $0,00 y sin
    piso, y el 1 de septiembre el dueño arrancando el mes creyendo que cada peso
    que entra es margen.

    Son DOS ceros distintos y ahora se devuelven distintos:

      · `series_repetibles` — cuántas series marcadas como repetibles hay. En
        cero, «no falta ninguna copia» NO quiere decir que el mes esté armado.
      · `candidatas` — las cuentas vivas que todavía no son serie, ofrecidas con
        su concepto y su plata para que el dueño elija cuáles van (y de qué mes
        son, en `candidatas_de`). NO se copian solas: copiar una reparación del
        molino inventa un costo y eso INFLA el piso, que es el mismo error
        mirado del otro lado. El porqué completo está en `_series_y_sueltas`.

    Lo que el dueño elige llega en `incluir` y entra POR LA MISMA PUERTA que las
    series: mismo cerrojo, misma llave de idempotencia, mismo `no_se_pueden`. La
    copia nace con `plantilla_id`, así que a partir del mes siguiente esa cuenta
    YA es serie y el lote la agarra sola. Elige una vez, no todos los meses.

    ═══════════════════════════════════════════════════════════════════════════
    NADA DE ESTO SE DECIDE SIN ABRIR EL MES DESTINO
    ═══════════════════════════════════════════════════════════════════════════
    Los dos montones se miden contra lo que el mes destino YA TIENE, y el porqué
    con los números medidos está arriba de `_llave_de_cuenta`. En dos frases:
    este dueño carga los cinco fijos a mano todos los meses, así que el mes
    destino casi nunca está vacío, y hasta acá el lote ofrecía (y las series
    copiaban) sin mirarlo — septiembre pasaba de $27.620.000 a $55.240.000 y el
    piso de $29.829.597,61 a $59.659.195,23.

    · una SERIE cuya cuenta ya está en el mes NO se copia (`ya_en_el_mes`, con
      `automatica: true`): esa es la que no necesita que nadie tilde nada;
    · una SUELTA que ya está en el mes NI SE OFRECE (`ya_en_el_mes`);
    · lo que igual se ofrece viaja con `parecidas`: lo que el mes destino tiene
      en la misma sede y categoría y NO matcheó, para que el aviso esté en el
      renglón ANTES del tilde;
    · y `mes_destino` dice cuántas cuentas y cuánta plata hay ya en el mes, que
      es el número sobre el que la pantalla venía afirmando sin haberlo pedido.

    Tapar NO ES BORRAR NI ES CALLARSE: todo lo tapado vuelve nombrado, con la
    fila del origen y la del destino, sus montos y sus fechas. Si la llave se
    equivocó, se ve.

    ═══════════════════════════════════════════════════════════════════════════
    LO QUE NO PUEDE ENTRAR NO ABORTA EL MES
    ═══════════════════════════════════════════════════════════════════════════
    Una serie con la categoría desactivada, o con la vieja categoría 'proveedores'
    que ya no se acepta, no se puede copiar. Si eso tumbara la transacción entera,
    UNA fila legacy dejaría el mes sin armar para siempre y sin explicación. Van a
    `no_se_pueden` CON EL PORQUÉ, y el resto se arma. La atomicidad es sobre lo
    que la vista previa prometió, no sobre lo que era imposible desde el vamos.

    ═══════════════════════════════════════════════════════════════════════════
    DOS TABLETS ARMANDO EL MISMO MES
    ═══════════════════════════════════════════════════════════════════════════
    Ser idempotente contra dos toques SEGUIDOS no dice nada sobre dos toques
    SIMULTÁNEOS. Con `confirmar=True` cada serie pasa por `_lockear_serie` antes
    de que se le pregunte si ya tiene copia; el porqué completo está allá. Sin
    eso, dos requests a la vez veían las dos el mes vacío y duplicaban el
    arriendo y la nómina — y un costo fijo duplicado INFLA el piso de venta.
    """
    anio, mes = int(anio), int(mes)
    primero = date(anio, mes, 1)
    series, sueltas = _series_y_sueltas(db, primero)

    # ── LO QUE EL MES DESTINO YA TIENE ───────────────────────────────────────
    # Se lee ANTES de decidir nada, y es la mitad que faltaba: hasta acá el lote
    # armaba su oferta mirando solo el mes ORIGEN y afirmaba sobre el destino sin
    # haberlo abierto. El porqué completo, con los números medidos, está arriba
    # de `_llave_de_cuenta`.
    destino = _LoQueElMesYaTiene(_vivas_del_mes(db, anio, mes))
    tapadas: list[dict] = []
    # Se declaran acá arriba porque las pasadas de cobertura ya llenan
    # `ya_estaban`: una suelta cuya copia vive DENTRO del mes destino no la ve
    # `_series_y_sueltas` (esa mira solo lo anterior), así que la reconoce la
    # pasada 2 y no el loop de escritura.
    van: list[dict] = []
    ya_estaban: list[dict] = []
    no_se_pueden: list[dict] = []
    a_crear: list[tuple[Obligacion, int, date, date | None]] = []

    # ── PASADA 1: LAS SERIES, que son las que se copian SOLAS ────────────────
    # Van primero porque son las que no necesitan que nadie tilde nada: si una
    # cuenta del destino puede tapar a una serie o a una suelta, tiene que
    # gastarla la serie. Al revés, la suelta se quedaría con el cupo y la serie
    # crearía la copia igual — el duplicado automático, que es el peor de los
    # dos porque no hay ningún tap donde frenarlo.
    #
    # `sorted` por `serie_id`: el mismo orden que el loop de escritura de abajo,
    # así el reparto no depende de por dónde entró el diccionario.
    cubiertas: dict[int, Obligacion] = {}
    for serie_id, origen in sorted(series.items(), key=lambda kv: kv[0]):
        # Por IDENTIDAD primero: si el destino ya tiene un miembro de esta serie,
        # esa fila ES esta cuenta y la gasta. El loop de abajo la va a encontrar
        # con `_copia_viva_del_mes` y la va a poner en `ya_estaban`.
        if destino.sacar_miembro_de(serie_id) is not None:
            continue
        ocupada = destino.sacar_por_llave(origen)
        if ocupada is not None:
            cubiertas[serie_id] = ocupada
            tapadas.append(_serializar_tapada(origen, ocupada, automatica=True))

    # ── PASADA 2: LAS SUELTAS, o sea qué se OFRECE ───────────────────────────
    # Una suelta tapada NO se ofrece: ofrecerla es poner un tilde al lado de un
    # costo que ya está, y el tilde es todo lo que separa al piso de salir el
    # doble. Vuelve nombrada en `ya_en_el_mes`, nunca en silencio.
    ofrecidas: list[Obligacion] = []
    tapadas_por_id: dict[int, Obligacion] = {}
    ya_por_identidad: dict[int, Obligacion] = {}
    for o in sueltas:
        # ── PRIMERO POR IDENTIDAD, Y LA DIFERENCIA NO ES COSMÉTICA ───────────
        # Una suelta puede tener su copia EN el mes destino sin que
        # `_series_y_sueltas` lo sepa: esa función solo mira lo ANTERIOR al mes
        # destino, así que una cabeza cuya única copia vive adentro del destino
        # le parece suelta. Eso pasa SIEMPRE al confirmar dos veces —el camino
        # normal, no un borde—, y ahí la respuesta correcta es «ya estaba», la
        # idempotencia de toda la vida: el id sigue siendo válido en `incluir` y
        # el segundo toque es un no-op silencioso.
        #
        # Taparla por LLAVE es otra cosa: ahí la cuenta del destino es OTRA fila
        # que se le parece, el id deja de ser elegible y `incluir` con ese id
        # tiene que volver 400. Mezclar los dos casos rompía el doble confirmar.
        propia = destino.sacar_miembro_de(o.id)
        if propia is not None:
            ya_por_identidad[o.id] = propia
            ya_estaban.append({
                "serie_id": o.id, "obligacion_id": propia.id,
                "concepto": propia.concepto,
                "monto": round(float(propia.monto or 0), 2),
                "fecha_devengo": propia.fecha_devengo,
            })
            continue
        ocupada = destino.sacar_por_llave(o)
        if ocupada is not None:
            tapadas_por_id[o.id] = ocupada
            tapadas.append(_serializar_tapada(o, ocupada, automatica=False))
        else:
            ofrecidas.append(o)

    # ── LO QUE EL DUEÑO ELIGIÓ ESTA VEZ ──────────────────────────────────────
    # `incluir` son ids de cuentas SUELTAS: las que `candidatas` ofreció. Se
    # normalizan primero —sin repetidos y en el orden en que llegaron— porque la
    # misma cuenta tildada dos veces no puede terminar en dos copias.
    pedidas = list(dict.fromkeys(int(x) for x in (incluir or [])))
    # DE LAS OFRECIDAS Y NO DE TODAS LAS SUELTAS. Es el candado del bloqueante:
    # aunque la pantalla venga vieja y mande el id de una que el destino ya
    # tiene, acá no hay con qué crearla.
    por_id = {o.id: o for o in ofrecidas}
    elegidas: dict[int, Obligacion] = {}
    for oid in pedidas:
        if oid in por_id:
            elegidas[oid] = por_id[oid]
        elif oid in ya_por_identidad:
            # EL CAMINO NORMAL DEL SEGUNDO TOQUE, no un borde: confirmar dos
            # veces manda el mismo `incluir`, y para entonces esas cuentas ya
            # tienen su copia en el mes destino. Es un no-op legítimo —ya está
            # nombrada en `ya_estaban`— y contestar 400 acá dejaría al dueño
            # creyendo que se rompió algo cuando el mes está exactamente como lo
            # pidió.
            continue
        elif oid in tapadas_por_id:
            # EL 400 DICE LA RAZÓN DE VERDAD. El caso real: el dueño mira la
            # previa, se va a Obligaciones, carga esa misma cuenta a mano en el
            # mes destino y vuelve a confirmar. Decirle «se anuló o cambió» lo
            # mandaría a buscar algo que no pasó. Y aborta el lote entero a
            # propósito: crear las otras cinco y callarse esta es «tildaste seis
            # y se crearon cinco», que es la familia de error de esta pantalla.
            ya = tapadas_por_id[oid]
            # El separador de miles se arma aparte y NO con un `.replace` sobre
            # la frase entera: un concepto con coma («Aseo, vigilancia») saldría
            # con la coma cambiada por un punto.
            monto = f"{round(float(ya.monto or 0)):,}".replace(",", ".")
            raise HTTPException(
                400,
                f"«{ya.concepto}» ya está en {MESES_ES[mes - 1]} (${monto} del "
                f"{ya.fecha_devengo.day}/{ya.fecha_devengo.month}) — no se copió "
                "ninguna. Volvé a mirar la lista.")
        elif oid not in series:
            # NO SE IGNORA EN SILENCIO, y es el corazón de este arreglo: el dueño
            # tildó seis, se crearían cinco y arriba diría «listo». Es la familia
            # de error que esta pantalla existe para no cometer.
            #
            # Que YA sea serie (`oid in series`) sí es un no-op legítimo y no un
            # error: pasa cuando confirma dos veces, o cuando la eligió el mes
            # pasado. Ahí el lote ya la trae sola por el camino de las series, y
            # `_copia_viva_del_mes` decide si hay algo para crear.
            raise HTTPException(
                400,
                f"La cuenta #{oid} ya no está en la lista para copiar — se anuló "
                "o cambió desde que la elegiste. Volvé a mirar la lista.")

    # Las elegidas entran por LA MISMA PUERTA que las series. Una cuenta suelta
    # es su propia cabeza de serie (`serie_id == id`), así que las llaves no
    # pueden chocar: en `series` solo hay ids que ya tienen copia y en `elegidas`
    # solo ids que no.
    ultimos = dict(series)
    ultimos.update(elegidas)

    for serie_id, origen in sorted(ultimos.items(), key=lambda kv: kv[0]):
        # SOLO cuando se va a escribir. La vista previa no toma cerrojos: es de
        # solo lectura, y hacer esperar a la otra tablet por MIRAR sería un
        # costo sin contraparte.
        #
        # El `sorted` por `serie_id` de arriba dejó de ser cosmético: dos lotes
        # simultáneos toman los MISMOS cerrojos EN EL MISMO ORDEN, que es lo que
        # evita que se traben en cruz (uno con el arriendo esperando la nómina y
        # el otro al revés). Si algún día se cambia el orden del recorrido, hay
        # que cambiarlo sabiendo esto.
        if confirmar:
            _lockear_serie(db, serie_id)
        ya = _copia_viva_del_mes(db, serie_id, anio, mes)
        if ya is not None:
            ya_estaban.append({
                "serie_id": serie_id, "obligacion_id": ya.id,
                "concepto": ya.concepto, "monto": round(float(ya.monto or 0), 2),
                "fecha_devengo": ya.fecha_devengo,
            })
            continue

        # EL MES DESTINO YA LA TIENE, con otro id y sin `plantilla_id`: la cargó
        # el dueño a mano, que es como carga los cinco fijos desde hace siete
        # meses. `_copia_viva_del_mes` no la puede ver —compara por SERIE— y sin
        # esta rama la serie creaba la SEGUNDA. Ya está nombrada en `tapadas`.
        if serie_id in cubiertas:
            continue

        # MISMA PUERTA QUE CREAR, EDITAR Y REPETIR. Copiar `categoria_id` sin
        # validarlo reinstalaría por lote el doble conteo que la validación cerró
        # en el formulario.
        try:
            cat = _validar_categoria(db, origen.categoria_id)
        except HTTPException as e:
            no_se_pueden.append({"serie_id": serie_id, "origen_id": origen.id,
                                 "concepto": origen.concepto,
                                 "porque": e.detail})
            continue

        # Cuántos meses hay que correr la fecha. Se mide sobre el MES y no sobre
        # los días: el arriendo del 31 de julio y el del 1 de agosto están a un
        # día y a un mes de distancia al mismo tiempo.
        salto = ((anio * 12 + mes) -
                 (origen.fecha_devengo.year * 12 + origen.fecha_devengo.month))
        devengo = _corrido(origen.fecha_devengo, salto)
        # El vencimiento se corre LOS MISMOS meses y no se recalcula: el arriendo
        # que se devenga el 31 y se paga el 5 del mes siguiente tiene que seguir
        # pagándose el 5 del mes siguiente. Y si el original no tenía fecha de
        # pago, la copia tampoco: inventarle una la metería a la agenda con un
        # vencimiento que nadie pactó.
        vencimiento = (_corrido(origen.fecha_vencimiento, salto)
                       if origen.fecha_vencimiento else None)

        van.append({
            "serie_id": serie_id,
            "origen_id": origen.id,
            "concepto": origen.concepto,
            "beneficiario": origen.beneficiario,
            "monto": round(float(origen.monto or 0), 2),
            "tienda_id": origen.tienda_id,
            "tienda_nombre": origen.tienda.nombre if origen.tienda else None,
            "categoria_clave": cat.clave,
            "categoria_nombre": cat.nombre,
            "categoria_grupo": cat.grupo,
            "fecha_devengo": devengo,
            "fecha_vencimiento": vencimiento,
            # De qué mes se copió. Con un mes saltado esto NO es el mes anterior,
            # y el dueño tiene derecho a ver que el monto es viejo.
            "copiado_de": origen.fecha_devengo,
        })
        a_crear.append((origen, serie_id, devengo, vencimiento))

    total = round(sum(v["monto"] for v in van), 2)
    resp = {
        "anio": anio, "mes": mes, "nombre_mes": MESES_ES[mes - 1],
        "confirmado": bool(confirmar),
        "van_a_crearse": van,
        "total": total,
        "ya_estaban": ya_estaban,
        "no_se_pueden": no_se_pueden,
        # ── LOS DOS CEROS, SEPARADOS ─────────────────────────────────────────
        # `van_a_crearse` vacío no dice POR QUÉ está vacío, y las dos razones son
        # opuestas: «las series ya tienen su copia» (el mes está armado) y «no
        # hay ninguna serie marcada como repetible» (el mes arranca en cero). La
        # pantalla no puede afirmar la primera cuando pasa la segunda, así que la
        # respuesta trae con qué distinguirlas en vez de dejarla deducir.
        "series_repetibles": len(series),
        # Las cuentas vivas que todavía no son serie Y QUE EL MES DESTINO NO
        # TIENE, para elegir cuáles van. Nunca se copian solas: llegan de vuelta
        # en `incluir`. Las que el destino ya tiene salieron de acá y están
        # nombradas en `ya_en_el_mes`.
        "candidatas": [_serializar_candidata(o, destino.parecidas_a(o))
                       for o in ofrecidas],
        # DE QUÉ MES son las candidatas. Con un mes saltado NO es el mes anterior
        # y la pantalla no lo puede dar por hecho. Sale de `sueltas` y no de
        # `ofrecidas`: el mes de la oferta es el mismo aunque el destino tape
        # todas, y la pantalla lo necesita para nombrarlo igual.
        "candidatas_de": (date(sueltas[0].fecha_devengo.year,
                               sueltas[0].fecha_devengo.month, 1)
                          if sueltas else None),
        # ── LO QUE EL MES DESTINO YA TIENE ───────────────────────────────────
        # LOS DOS NÚMEROS QUE LA PANTALLA NO PODÍA MIRAR, y por eso afirmaba
        # «el mes que viene arrancaría sin costos fijos y el piso en cero» sobre
        # un mes que ya tenía sus $27.620.000. Van SIEMPRE, estén o no en cero:
        # `n: 0` es «lo miré y está vacío», que es una afirmación distinta de no
        # haber mirado y es la única que autoriza el aviso fuerte.
        # `n`/`total` = TODAS las vivas del mes (lo que la cobertura mira).
        # `n_fijos`/`fijos` = solo las que entran al numerador del piso, que es
        # de lo que la pantalla habla. Van los dos porque son dos preguntas.
        "mes_destino": {"n": destino.n, "total": destino.total,
                        "n_fijos": destino.n_fijos, "fijos": destino.fijos},
        # Las que NO van al mes porque el mes ya las tiene, con las dos filas a
        # la vista. `automatica: true` = era una serie y se habría copiado sola.
        "ya_en_el_mes": tapadas,
        # Cuántas de las elegidas van a quedar marcadas como serie con este lote.
        "n_elegidas": len(elegidas),
        "creadas": [],
        "n_creadas": 0,
    }
    if not confirmar or not a_crear:
        return resp

    # ── UN SOLO COMMIT ───────────────────────────────────────────────────────
    copias = []
    for origen, serie_id, devengo, vencimiento in a_crear:
        copia = Obligacion(
            tienda_id=origen.tienda_id,
            categoria_id=origen.categoria_id,
            concepto=origen.concepto,
            beneficiario=origen.beneficiario,
            monto=origen.monto,
            fecha_devengo=devengo,
            fecha_vencimiento=vencimiento,
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
        copias.append((copia, origen, serie_id))
    db.flush()
    for copia, origen, serie_id in copias:
        audit.registrar(
            db, accion="armar_mes_obligacion", tabla="obligaciones",
            registro_id=copia.id, usuario_id=usuario_id, tienda_id=copia.tienda_id,
            datos_antes={"origen_id": origen.id,
                         "fecha_devengo": origen.fecha_devengo},
            datos_despues={"serie_id": serie_id, "concepto": copia.concepto,
                           "monto": float(copia.monto),
                           "fecha_devengo": copia.fecha_devengo,
                           "fecha_vencimiento": copia.fecha_vencimiento,
                           "lote": f"{anio}-{mes:02d}"},
        )
    db.commit()
    # Nacen sin pagos: el estado derivado les da 'pendiente' solo.
    resp["creadas"] = [_serializar(c, []) for c, _o, _s in copias]
    resp["n_creadas"] = len(copias)
    return resp


def dejar_de_repetir(db: Session, obligacion_id: int, usuario_id: int,
                     barista_nombre: str | None = None) -> dict:
    """DESHACER que una cuenta sea serie. El botón que faltaba.

    ═══════════════════════════════════════════════════════════════════════════
    EL AGUJERO QUE CIERRA
    ═══════════════════════════════════════════════════════════════════════════
    Tildar una cuenta en «elegir qué va al mes que viene» la vuelve serie PARA
    SIEMPRE, y hasta acá no había forma de salir. Medido: el dueño tilda una vez
    la «Reparación del molino» de $3.000.000 en septiembre; en octubre el lote la
    copia SOLA, y en noviembre otra vez. Un costo de una sola vez convertido en
    fijo mensual infla el piso todos los meses.

    Y lo que había que hacer para salir era impracticable en una tablet, porque
    la marca de serie no vive en una fila sino en TODAS las copias vivas —está
    medido: anular la copia de octubre no alcanza (la de septiembre sigue con
    `plantilla_id` y noviembre se vuelve a copiar), y anular la CABEZA tampoco.
    Había que anularlas todas, una por una, sabiendo cuáles son.

    ═══════════════════════════════════════════════════════════════════════════
    QUÉ HACE, Y POR QUÉ ES BARATO DE VERDAD
    ═══════════════════════════════════════════════════════════════════════════
    Le pone `plantilla_id = NULL` a todos los miembros VIVOS de la serie. Eso las
    devuelve a ser cuentas sueltas: dejan de copiarse solas y vuelven a
    OFRECERSE, que es donde el dueño decide de nuevo.

    NO TOCA UN PESO, y se verificó antes de escribirlo: `Obligacion.plantilla_id`
    no lo lee nadie fuera de la lógica de series de este módulo —ni el P&L, ni el
    piso, ni la agenda, ni el flujo de caja—, así que romper la cadena no mueve
    ningún número. Las obligaciones creadas siguen existiendo, con su plata y sus
    pagos: se pagaron o se van a pagar igual. Lo único que cambia es si el mes
    que viene se copian solas.

    NO ANULA NADA, y es deliberado: anular la copia de octubre y desmarcar la
    serie son dos decisiones distintas —«esta no la debo» y «esta no se repite»—
    y hacerlas juntas le borraría al dueño un costo que a lo mejor sí debe. Si
    además quiere que la de octubre no exista, la anula desde Obligaciones.

    LAS ANULADAS SE DEJAN COMO ESTÁN. `_series_y_sueltas` filtra `anulada`, así
    que una copia muerta con `plantilla_id` no marca nada; borrárselo sería
    perder de qué serie venía sin comprar nada a cambio.

    Toma el MISMO cerrojo que las dos puertas que escriben (`_lockear_serie`):
    sin él, desmarcar mientras la otra tablet arma el mes deja la mitad de la
    serie rota y la otra mitad copiándose.
    """
    o = db.query(Obligacion).filter(Obligacion.id == obligacion_id).first()
    if not o:
        raise HTTPException(404, "Obligación no encontrada")

    # La llave de la serie es SIEMPRE el primer eslabón, igual que en `repetir` y
    # en el lote: así desmarcar desde cualquier mes de la cadena desmarca la
    # cadena entera y no solo de ahí para adelante.
    serie_id = o.plantilla_id or o.id
    _lockear_serie(db, serie_id)

    miembros = db.query(Obligacion).filter(
        or_(Obligacion.plantilla_id == serie_id, Obligacion.id == serie_id),
        Obligacion.anulada == False,  # noqa: E712
        Obligacion.plantilla_id.isnot(None),
    ).order_by(Obligacion.id).all()

    if not miembros:
        # NO ES UN ERROR: la cuenta ya no era serie (nunca lo fue, o alguien la
        # desmarcó desde la otra tablet). Se contesta el estado, no un 400 — un
        # error acá mandaría al dueño a buscar un problema que no existe.
        return {"serie_id": serie_id, "concepto": o.concepto,
                "n_desmarcadas": 0, "ya_estaba": True}

    for m in miembros:
        m.plantilla_id = None
    db.flush()
    audit.registrar(
        db, accion="dejar_de_repetir", tabla="obligaciones",
        registro_id=serie_id, usuario_id=usuario_id, tienda_id=o.tienda_id,
        datos_antes={"serie_id": serie_id,
                     "miembros": [m.id for m in miembros]},
        datos_despues={"concepto": o.concepto,
                       "n_desmarcadas": len(miembros),
                       # Quién lo tocó DE VERDAD en el kiosko compartido: el
                       # `usuario_id` es el de la tablet, no el de la persona.
                       "barista": barista_nombre},
    )
    db.commit()
    return {"serie_id": serie_id, "concepto": o.concepto,
            "n_desmarcadas": len(miembros), "ya_estaba": False}


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


# Una quincena es la MITAD del mes, y la liquidación real del contador difiere
# del cálculo por puntos (retención en la fuente, embargos, el redondeo de
# PILA), no por mitades: el corte en 3/5 deja pasar cualquier liquidación
# completa y rebota la quincena. Más alta que el cálculo entra siempre — el
# mismo criterio asimétrico que el quinto del impoconsumo.
FRACCION_MINIMA_NOMINA = 0.6


def _nomina_calculada_del_mes(db: Session, anio: int, mes: int) -> float:
    """El costo laboral que el sistema calcula para ese mes, con la MISMA regla
    de fuente que el agendado: mes terminado → horas reales (consolidada); en
    curso o futuro → contratos (proyectada)."""
    _desde, hasta = nomina_svc.rango_mes(anio, mes)
    calculo = (nomina_svc.consolidada(db, anio, mes) if hasta < hoy_col()
               else nomina_svc.proyectada(db, anio, mes))
    return round(float(calculo["totales"]["total_costo_empleador"]), 2)


def _validar_nomina_a_mano(db: Session, categoria_id: int, monto: float,
                           fecha_devengo) -> None:
    """El candado de la nómina parcial.

    Una obligación de nómina devengada en un mes APAGA el cálculo del mes
    ENTERO (`rentabilidad._nomina_del_periodo`: «si el mes tiene nómina cargada
    a mano, gana la mano») sin mirar el monto: una «Nómina quincena» de la
    mitad dejaba el costo laboral del mes en la mitad y el margen se veía mejor
    de lo que está, sin ningún aviso. El error es MUDO y tranquilizador — la
    familia entera de este repo.

    Se compara contra el cálculo del mes del DEVENGO. Sin cálculo (>0) no hay
    contra qué comparar y la mano es la única fuente: pasa.
    """
    cat = db.get(CostoCategoria, categoria_id)
    if cat is None or cat.clave != CLAVE_CATEGORIA_NOMINA or fecha_devengo is None:
        return
    calculada = _nomina_calculada_del_mes(db, fecha_devengo.year, fecha_devengo.month)
    if calculada <= 0 or float(monto) >= calculada * FRACCION_MINIMA_NOMINA:
        return
    raise HTTPException(400, _mensaje_nomina_parcial(
        float(monto), calculada,
        f"{MESES_ES[fecha_devengo.month - 1]} {fecha_devengo.year}"))


def _mensaje_nomina_parcial(valor: float, calculada: float, mes_nombre: str) -> str:
    return (
        f"Escribiste ${valor:,.0f} de nómina para {mes_nombre} y el sistema "
        f"calcula ${calculada:,.0f} con los contratos y turnos cargados. Una "
        "nómina cargada a mano apaga el cálculo del mes ENTERO: con esa cifra "
        "el costo laboral del mes quedaría en menos de la mitad y el margen se "
        "vería mejor de lo que está, sin ningún aviso. Si es una quincena, no "
        "va sola: cargá el mes completo (el monto se corrige después si hace "
        "falta). Si es la liquidación completa de tu contador, fijate si no le "
        "falta un dígito — parecida al cálculo entra, y más alta entra siempre."
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
    # El monto a mano del agendado pasa por el MISMO candado que la obligación
    # manual: una quincena entra igual de callada por este botón que por el
    # formulario, y apaga el mismo mes. El cálculo ya está hecho — se compara
    # contra él sin liquidar de nuevo.
    calculada = round(float(totales["total_costo_empleador"]), 2)
    if (monto is not None and calculada > 0
            and valor < calculada * FRACCION_MINIMA_NOMINA):
        raise HTTPException(400, _mensaje_nomina_parcial(
            valor, calculada, f"{MESES_ES[int(mes) - 1]} {int(anio)}"))
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
    LA PLATA, un dato que hoy no existe en ninguna tabla del sistema.

    Con `descontar_banco`, la salida del libro del banco nace EN LA MISMA
    transacción, enlazada por `obligacion_id`. Antes eran dos escrituras del
    frontend (el pago y después el movimiento): si la segunda fallaba, el
    vencimiento quedaba tachado y el saldo del banco no bajaba — la ventana
    exacta que la composición cierra.
    """
    if data.factura_id is not None:
        # PUERTA CERRADA. Este camino creaba la fila Pago pero JAMÁS tocaba
        # FacturaCompra.valor_pagado: la factura seguía debiendo lo mismo en la
        # agenda y en todas las pantallas, con el pago guardado en una tabla que
        # su saldo no lee. Una puerta que registra sin efecto es peor que un
        # error: parece que funcionó.
        raise HTTPException(400, (
            "El pago de una factura de proveedor no va por acá: esta puerta "
            "guardaba el pago en una tabla que el saldo de la factura no lee — "
            "la factura seguía debiendo lo mismo, con tu pago invisible. "
            "Pagala desde su propia fila en «Lo que baja el margen», que sí "
            "mueve el saldo."
        ))
    if data.obligacion_id is None:
        raise HTTPException(400, "El pago debe apuntar a una obligación")
    if data.metodo not in METODOS_PAGO:
        raise HTTPException(400, "Método inválido: efectivo | transferencia | tarjeta | cheque | otro")
    monto = _validar_monto(data.monto)

    obligacion = db.query(Obligacion).filter(Obligacion.id == data.obligacion_id).first()
    if not obligacion:
        raise HTTPException(404, "Obligación no encontrada")
    if obligacion.anulada:
        raise HTTPException(400, "La obligación está anulada — no admite pagos")
    tienda_id = obligacion.tienda_id   # snapshot copiado del padre

    descontar = bool(getattr(data, "descontar_banco", False))
    if descontar:
        # Las mismas cotas que el POST directo al libro (routers/banco.py), con
        # el texto pensado para este gesto: acá el dueño está PAGANDO, y el
        # motivo del rechazo tiene que hablar del pago.
        if data.metodo not in METODOS_BANCO:
            raise HTTPException(400, (
                "«Descontar del banco» va solo con un método que salga de la "
                "cuenta (transferencia o cheque). El efectivo sale del cajón o "
                "de tu mano: meterlo al libro escribiría una salida que el "
                "extracto nunca va a tener."
            ))
        if data.fecha_pago > hoy_col():
            raise HTTPException(400, (
                "El libro del banco es de plata que YA se movió: para "
                "descontar del banco, la fecha del pago no puede ser futura."
            ))
        if data.cuenta_id is None:
            raise HTTPException(400, (
                "Elegí de qué cuenta salió la plata (Occidente o Bold) para "
                "descontarla del banco."
            ))

    pago = Pago(
        obligacion_id=data.obligacion_id,
        factura_id=None,
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

    movimiento_banco_id = None
    if descontar:
        try:
            mov = banco_svc.registrar(
                db, data.fecha_pago, data.cuenta_id, "salida", monto,
                concepto=(obligacion.concepto or "")[:160],
                usuario_id=usuario_id, obligacion_id=data.obligacion_id,
                nota=(data.nota or None), commit=False)
        except ValueError as e:
            # El texto del servicio del banco ya está escrito para el dueño.
            # El raise deshace también el pago: o entran los dos, o ninguno.
            raise HTTPException(400, str(e))
        movimiento_banco_id = mov.id

    audit.registrar(
        db, accion="registrar_pago_costo", tabla="pagos",
        registro_id=pago.id, usuario_id=usuario_id, tienda_id=tienda_id,
        datos_despues={"obligacion_id": pago.obligacion_id, "factura_id": None,
                       "monto": monto, "fecha_pago": pago.fecha_pago,
                       "metodo": pago.metodo,
                       "movimiento_banco_id": movimiento_banco_id},
    )
    db.commit()
    db.refresh(pago)
    # `movimiento_banco_id` viaja SIEMPRE (None cuando no se pidió): un cliente
    # que pidió descontar y no ve la CLAVE está contra un servidor viejo, y esa
    # ausencia es su señal para caer al camino de las dos escrituras.
    return {**_serializar_pago(pago), "movimiento_banco_id": movimiento_banco_id}


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


def _cobertura_impoconsumo(db: Session, hoy: date, tope: date) -> dict | None:
    """La declaración del bimestre cerrado, si NO está agendada. None = cubierta.

    `tope` es el último día que la serie dibuja: una salida que vence después no
    le falta a ESTA proyección y avisarla sería ruido.

    EL VENCIDO SÍ CUENTA, y acá es donde más importa. Una declaración atrasada es
    plata que todavía no salió —a la DIAN no se le paga sola— y `_salidas_por_dia`
    apila todo lo ya debido en hoy+1. O sea que agendarla la mete de lleno en la
    serie: es exactamente el caso en que la proyección está más equivocada.

    ═══════════════════════════════════════════════════════════════════════════
    LA CUBRE UN SOLO HECHO: QUE LA OBLIGACIÓN EXISTA
    ═══════════════════════════════════════════════════════════════════════════
    Acá arrancaba mirando `leer_impoconsumo_declarado` y devolvía «cubierta»
    cuando el bimestre estaba marcado, ANTES de preguntar si la obligación
    existía. O sea que el interruptor de «ya la declaré» apagaba el aviso de la
    CAJA. MEDIDO en un mundo sin nada agendado: antes del tap la proyección
    avisaba que faltaban el impoconsumo y la nómina; después del tap avisaba
    solo por la nómina, y la agenda seguía en el mismo total — cero pesos
    movidos, un aviso menos.

    «YA LA DECLARÉ» Y «LA PLATA ESTÁ RESERVADA» SON DOS HECHOS DISTINTOS, y esa
    es la razón, que es de negocio y no de código. Declarar es un TRÁMITE ante
    la DIAN; pagar es plata que sale del cajón. Se puede declarar y no haber
    pagado —es lo normal, el plazo de pago llega después— y en ese rato la caja
    tiene que seguir viendo la salida. Leer el marcador del trámite como prueba
    de la reserva es exactamente el error de siempre: un dato que está CERCA del
    correcto, y del lado que tranquiliza.

    Así que el marcador de `configuracion` no se mira desde acá: apaga el
    RECORDATORIO del trámite (`get_impoconsumo.hay_que_declarar`) y nada más. La
    cobertura de la caja la decide una sola pregunta —¿hay una obligación viva
    de este bimestre?— y esa pregunta la contesta la base, no una afirmación del
    dueño sobre otra cosa.

    EL QUE YA LA PAGÓ POR AFUERA TAMBIÉN TIENE CAMINO, y es el mismo que para
    cualquier otra plata que salió: agendarla y registrarle el pago. La
    obligación cuenta como cobertura esté pagada o no —`_obligacion_de_impoconsumo`
    no mira el saldo— así que agendarla apaga este aviso para siempre. Lo que no
    hay es una forma de apagarlo sin dejar la salida escrita en algún lado.
    """
    anio, bim = _bimestre_anterior(*_bimestre_de(hoy))
    desde, hasta = _rango_bimestre(anio, bim)

    if _obligacion_de_impoconsumo(db, desde, hasta) is not None:
        return None

    _primero, vencimiento = _mes_de_declaracion(hasta)
    if vencimiento > tope:
        return None

    ventas, medido, tributos = _impoconsumo_medido(db, desde, hasta)
    porque = _porque_no_hay_monto(ventas, tributos)
    return {
        "clave": CLAVE_CATEGORIA_IMPOCONSUMO,
        "nombre": f"Impoconsumo {_nombre_bimestre(anio, bim)}",
        # `None` con el porqué al lado, NUNCA un 0: acá un cero se leería como
        # «no hay nada que reservar», que es la conclusión opuesta a la verdadera.
        "monto": None if porque else medido,
        "sin_monto_porque": porque,
        "vence": vencimiento,
        "vencido": vencimiento < hoy,
    }


def _cobertura_nomina(db: Session, hoy: date, tope: date) -> dict | None:
    """La nómina del mes, si NO está agendada. None = cubierta.

    NO CUENTA LA VENCIDA, al revés que el impoconsumo, y la diferencia no es un
    descuido: una nómina cuyo día de pago YA PASÓ se pagó —la gente no sigue
    viniendo si no— así que esa plata ya salió del cajón y está descontada del
    efectivo de hoy. Anunciarla como salida futura la restaría de nuevo y correría
    el punto de quiebre hacia adelante por plata que no existe. La declaración de
    la DIAN es el caso opuesto y por eso la regla es por concepto y no global.
    """
    desde, hasta = nomina_svc.rango_mes(hoy.year, hoy.month)
    if _obligacion_de_nomina_del_mes(db, desde, hasta) is not None:
        return None

    vence = fecha_de_pago_nomina(db, hoy.year, hoy.month)
    if vence <= hoy or vence > tope:
        return None

    totales = nomina_svc.proyectada(db, hoy.year, hoy.month)["totales"]
    monto = round(float(totales["total_costo_empleador"]), 2)
    return {
        "clave": CLAVE_CATEGORIA_NOMINA,
        "nombre": f"Nómina {MESES_ES[hoy.month - 1]} {hoy.year}",
        # $0 acá es «no hay sueldos cargados en Contratos», no «la nómina no
        # cuesta». Se dice, igual que en `agendar_nomina`.
        "monto": monto if monto > 0 else None,
        "sin_monto_porque": (None if monto > 0 else
                             "no hay sueldos cargados en Contratos, así que el "
                             "sistema no puede decir cuánto va a costar"),
        "vence": vence,
        "vencido": False,
    }


def _conceptos_sin_cargar(db: Session, hoy: date, dias: int) -> list[dict]:
    """LO QUE SE SABE QUE HAY QUE PAGAR Y ESTA PROYECCIÓN NO ESTÁ VIENDO.

    ═══════════════════════════════════════════════════════════════════════════
    POR QUÉ NO ALCANZA CON `sin_salidas_cargadas`
    ═══════════════════════════════════════════════════════════════════════════
    Ese flag es `not salidas_dia`: se prende solo cuando NO HAY NADA cargado. Con
    un solo arriendo adentro se apaga, y el verde sigue viajando aunque falten los
    $11,5 millones de la DIAN. O sea que la única señal que implementaba el
    «la AUSENCIA de un punto de quiebre, sola, no significa nada» del docstring de
    `get_flujo_proyectado` se desarmaba con UNA obligación. Se queda igual —«ni
    una sola salida» es un caso propio y vale nombrarlo— pero deja de ser la única.

    Esto es COBERTURA POR CONCEPTO: para cada gasto grande que el sistema sabe
    medir por su cuenta, dice si está adentro de la serie o no, con su monto y su
    fecha. Un booleano de «hay algo» no se puede convertir en una acción; una
    lista con nombre y plata sí.

    QUÉ ENTRA ACÁ Y QUÉ NO. Solo los conceptos que el sistema puede MEDIR solo:
    el impoconsumo (sale de la venta real del bimestre) y la nómina (sale de los
    contratos). El arriendo, los servicios y el contador NO están y no pueden
    estar — no hay de dónde deducir que existen ni cuánto valen si nadie los
    cargó. Para esos, «ni una sola salida cargada» sigue siendo todo lo que se
    puede afirmar honestamente.

    CADA CONCEPTO TRAE SU PROPIA REGLA SOBRE LO VENCIDO, porque no significan lo
    mismo: una declaración atrasada es plata que todavía va a salir, una nómina
    atrasada es plata que ya salió. Está escrito en cada función.

    LÍMITE DECLARADO: una obligación cargada SIN fecha de vencimiento cuenta como
    cubierta acá aunque la serie tampoco la vea —existe, alguien la cargó— y ese
    hueco lo nombra `agenda.sin_fecha`, que viaja aparte justamente para eso.

    SE MIRA EL NEGOCIO ENTERO, sin filtrar por sede, incluso cuando la proyección
    es de una sola: los dos conceptos son CORPORATIVOS (tienda_id NULL) y en una
    vista de sede están ausentes por diseño, no por falta de carga. Decir «no está
    cargada» ahí sería falso; que la vista de sede no los mire ya lo dice
    `excluye_corporativas`.
    """
    tope = hoy + timedelta(days=dias)
    candidatos = [_cobertura_impoconsumo(db, hoy, tope),
                  _cobertura_nomina(db, hoy, tope)]
    return [c for c in candidatos if c is not None]


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
    las SALIDAS existen únicamente si un humano las tecleó (el costo fijo del mes
    que viene solo existe si alguien apretó «armar el mes», la compra que no llegó
    no está, el costo de mercadería aparece recién cuando alguien registra la
    factura). O sea: la PRESENCIA de un punto de
    quiebre significa algo; su AUSENCIA, sola, no significa nada. Estos flags son
    los que le permiten a la pantalla decir "falta información" en vez de vender
    tranquilidad con un verde.

    Y ESA REGLA LA IMPLEMENTA `conceptos_sin_cargar`, NO `sin_salidas_cargadas`.
    El segundo es `not salidas_dia`: se apaga con UNA obligación cualquiera, así
    que con el arriendo cargado el verde volvía a viajar sin reserva aunque
    faltaran los $11,5M de la DIAN. El primero pregunta por CONCEPTO —¿está el
    impoconsumo?, ¿está la nómina?— y devuelve nombre, plata y fecha de lo que no
    está. Los dos conviven: «ni una sola salida» es un caso propio que vale
    nombrar, pero ya no es la única señal.
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
    # Se mide DESPUÉS de la serie y sobre el mismo horizonte: lo que se pregunta
    # es qué le falta a ESTA proyección, no qué le falta al negocio en abstracto.
    conceptos_sin_cargar = _conceptos_sin_cargar(db, hoy, dias)

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
            # cargó las cuentas por pagar, no que no haya nada que pagar. SIGUE
            # SIENDO ÚTIL pero YA NO ES LA ÚNICA señal de cobertura: se apaga con
            # una sola obligación cargada, y con eso el verde viajaba igual
            # faltando los millones de la DIAN. Ver `conceptos_sin_cargar`.
            "sin_salidas_cargadas": not salidas_dia,
            # LO QUE SE SABE QUE FALTA, CON NOMBRE Y PLATA. Lista, no booleano: es
            # lo que deja decir «faltan $11.525.926 del impoconsumo de may-junio»
            # en vez de «puede que falte algo».
            "conceptos_sin_cargar": conceptos_sin_cargar,
            # El atajo para la pantalla que solo necesita saber si puede publicar
            # un número. Se deriva de la lista y no al revés: un booleano que se
            # pudiera prender por su cuenta volvería a ser la señal que miente.
            "salidas_incompletas": bool(conceptos_sin_cargar),
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

    ── LA MERCADERÍA LLEVA LOS DESECHABLES ADENTRO ──────────────────────────
    `cogs` se mide sobre `cogs_con_desechables` y no sobre `cogs_teorico`: el
    vaso, la tapa y la servilleta son costo de la bebida y dejarlos afuera era
    uno de los cuatro sesgos declarados de este piso. La suma SUBE el costo, BAJA
    el margen y por lo tanto SUBE el piso — si alguna vez este cambio hiciera
    BAJAR el piso, es que se restó donde había que sumar.

    El P&L sigue publicando `cogs_teorico` SIN los desechables, y no es una
    contradicción: allá hay un término de fuga medida por conteo que ya se lleva
    esos vasos (no descuentan inventario al vender), así que sumarlos de los dos
    lados contaría el mismo vaso dos veces. Acá no hay término de fuga. Los dos
    números salen de la MISMA medición y viajan juntos en la respuesta.
    """
    pnl = rent_svc.get_rentabilidad(db, desde, hasta)
    resumen = pnl["resumen"]
    ventas = float(resumen["ventas"] or 0.0)
    if ventas <= 0:
        return None
    tasa_comision, comision_sin_cargar = _leer_comision_datafono(db)
    pct_tarjeta = _parte_con_tarjeta(db, desde, hasta)
    cogs_desech = float(resumen["cogs_desechables"] or 0.0)
    return {
        "desde": desde,
        "hasta": hasta,
        "ventas": round(ventas, 2),
        "impoconsumo": round(float(resumen["impoconsumo"] or 0.0) / ventas, 6),
        "cogs": round(float(resumen["cogs_con_desechables"] or 0.0) / ventas, 6),
        # ADITIVO, ya adentro de `cogs`: se abre para que la pantalla pueda decir
        # cuánto de la mercadería es empaque sin que nadie lo vuelva a restar.
        "cogs_desechables": round(cogs_desech / ventas, 6),
        "cogs_sin_desechables": round(float(resumen["cogs_teorico"] or 0.0) / ventas, 6),
        "comision": round(tasa_comision * pct_tarjeta, 6),
        "tasa_comision": tasa_comision,
        "comision_sin_cargar": comision_sin_cargar,
        "pct_tarjeta": round(pct_tarjeta, 6),
        "pct_venta_costeada": resumen["pct_venta_costeada"],
        "pct_venta_con_desechables": resumen["pct_venta_con_desechables"],
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
    cobertura_desech = razones["pct_venta_con_desechables"]
    # EL TEXTO SALE DEL MISMO PREDICADO QUE DECIDE `activo`, y por eso se calcula
    # acá arriba en vez de en un ternario adentro del dict. Antes el texto se
    # elegía con `not cobertura_desech`, que es otra pregunta: con la cobertura
    # en 100 el sesgo quedaba APAGADO y el texto que viajaba al lado seguía
    # diciendo «solo una parte de la venta tiene sus desechables cargados» —un
    # string afirmando lo contrario del campo con el que viaja—. Hoy no se ve
    # porque la pantalla filtra por `activo`, pero el día que alguien muestre el
    # texto sin mirar la bandera va a publicar la contradicción.
    #
    # Y `not` tampoco distinguía `None` (no se pudo medir) de 0,0 (se midió y no
    # hay nada cubierto): las dos caían en «los desechables no están dentro del
    # costo», que en el caso de `None` es una afirmación que no se puede hacer.
    activo_desech = cobertura_desech is None or cobertura_desech < 100
    if not activo_desech:
        texto_desech = "toda la venta medida tiene sus desechables cargados"
    elif cobertura_desech is None:
        texto_desech = "no se pudo medir cuánta venta tiene sus desechables cargados"
    elif cobertura_desech <= 0:
        texto_desech = "los desechables no están dentro del costo de la bebida"
    else:
        texto_desech = "solo una parte de la venta tiene sus desechables cargados"
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
            # YA NO ES ESTRUCTURAL: el vaso, la tapa y la servilleta entran al
            # `cogs` de este piso por la capa `cogs_desechables` (ver
            # `_razones_de_la_venta`). Lo que queda es un dato que falta —los
            # productos a los que nadie les cargó el empaque— y por eso el sesgo
            # se apaga por COBERTURA y no por decreto: con el 12% de la venta
            # cubierta, el empaque sigue casi todo afuera. `None` = no se pudo
            # medir, que también deja el sesgo vivo.
            "clave": "desechables_fuera_del_costo",
            "activo": activo_desech,
            "texto": texto_desech,
            "detalle": {"productos_con_desechables": n_desechables,
                        "pct_venta_con_desechables": cobertura_desech,
                        "cogs_desechables": razones["cogs_desechables"]},
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
            # ADITIVOS y ya adentro de `cogs`: cuánto de la mercadería es
            # empaque, y cuánto sería sin él. Viajan para que la pantalla pueda
            # nombrar el renglón sin restar nada de nuevo.
            "cogs_desechables": razones["cogs_desechables"],
            "cogs_sin_desechables": razones["cogs_sin_desechables"],
            "comision": razones["comision"],
            "tasa_comision": razones["tasa_comision"],
            "pct_tarjeta": razones["pct_tarjeta"],
            "pct_venta_costeada": razones["pct_venta_costeada"],
            "pct_venta_con_desechables": razones["pct_venta_con_desechables"],
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


# ═══════════════════════════════════════════════════════════════════════════════
# LAS PALANCAS: dónde bajar un costo, no cuánto se gastó
# ═══════════════════════════════════════════════════════════════════════════════
# El sistema ya DETECTABA las subas de precio y las ordenaba bien, pero llegaban
# ANÓNIMAS y en porcentaje. Dos cosas faltaban para poder sentarse a negociar:
#
#   1. EL NOMBRE. «La leche subió 14%» no se puede llevar a una reunión; «Lácteos
#      Andina subió la leche 14%» sí. Viene de `rentabilidad.alertas_de_costo`,
#      que lo lee de la MISMA factura que fijó el precio nuevo.
#   2. LA PLATA, Y EN LA UNIDAD EN QUE EL DUEÑO DECIDE. Un 14% no es una
#      decisión; «te sube el piso $180.000 por día» sí lo es.
#
# ── NO SE CALCULA UN SEGUNDO PISO ──────────────────────────────────────────────
# El impacto es una DIFERENCIA contra el piso ya publicado: se toman los COSTOS
# FIJOS y el MARGEN DE CONTRIBUCIÓN que `get_piso` acaba de devolver, se le mueve
# al margen únicamente el pedacito que ese insumo explica, y se resta contra el
# `piso_mes` de esa misma respuesta. Si el piso se midiera de nuevo acá, las dos
# cifras de la misma pantalla se contradirían el día que una de las dos cambie —
# el error que este módulo ya pagó tres veces.
#
# ── SON DOS NÚMEROS Y NO UNO, Y ESA CONFUSIÓN COSTÓ UN 10× ─────────────────────
# Durante una versión esta pantalla publicó UN solo número —cuánto sube el piso
# si el precio nuevo se queda— y abajo escribió «recuperar el viejo es esa misma
# plata de vuelta». No lo es, y la diferencia no es de detalle. MEDIDO sobre 10
# compras de leche a $2,00 y una a $2,80, con el arriendo y la venta de la base
# de prueba:
#
#     lo que VIENE (si $2,80 se queda)          el piso SUBE   $8.052,95 por día
#     lo que VUELVE (si el proveedor da marcha
#     atrás y vuelve a $2,00)                   el piso BAJA     $798,18 por día
#
# La pantalla prometía 10,1 VECES lo que la decisión devuelve. La razón está en
# `_costos_insumos`: el costo con el que se costea es el promedio ponderado de
# TODA la historia, así que a esa altura ya tenía la suba absorbida en un 9,1% —
# y solo ese 9,1% es lo que la vuelta puede recuperar. El resto de la suba
# todavía no llegó al piso: llega sola, compra a compra, y de eso habla el
# primer número.
#
# ── LOS DOS SON TOPES, Y NINGUNO PASA MAÑANA ───────────────────────────────────
# `costo_usado` no salta el día del acuerdo: es el promedio de todas las facturas
# y solo se mueve cuando llega una nueva. O sea que las DOS cifras son el límite
# al que se llega comprando al precio de destino, no lo que se ve al otro día.
# MEDIDO sobre el mismo escenario, con el proveedor aceptando volver a $2,00:
#
#     el día del acuerdo, sin comprar todavía   el piso baja      $0,00
#     con 1 compra al precio acordado           bajó   $658,99   ( 8,3% del tope)
#     con 5                                     bajó $2.492,71   (31,2%)
#     con 20                                    bajó $5.148,76   (64,5%)
#     con 100                                   bajó $7.189,22   (90,1%)
#     el tope publicado (`piso_mes_si_vuelve`)       $7.978,85
#
# El cálculo está bien y no se toca: lo que tiene que decirlo es el VERBO de la
# pantalla («va bajando hasta $X por día a medida que se le compre a ese
# precio»), porque «baja $X por día» en presente le pone fecha de mañana a una
# plata que tarda decenas de facturas — la misma familia de error de siempre: un
# dato cerca del correcto, del lado que tranquiliza.
#
# Los dos se publican, NOMBRADOS, y ninguno se deduce del otro:
#   · `piso_*_si_se_queda` → mover el costo de `costo_usado` a `costo_ultimo`.
#   · `piso_*_si_vuelve`   → mover el costo de `costo_usado` a `costo_ref` (el
#                            más barato de los últimos 12 meses; ver por qué esa
#                            referencia y no el promedio en `_costos_insumos`).
#   · `piso_*_en_juego`    → la distancia entre los DOS mundos. No se muestra:
#                            es con lo que se ORDENA la lista, y es lo único
#                            estable, porque no se encoge a medida que la suba
#                            se absorbe. Ordenar por «lo que viene» mandaría al
#                            fondo justo a la suba que ya llegó entera y que es
#                            toda oportunidad de recuperación.
#
# EL SIGNO SALE DE LA CUENTA, NO DE UN SUPUESTO. Lo normal es
# `costo_ref <= costo_usado <= costo_ultimo` (viene positivo, vuelve negativo),
# pero con un `precio_costo` fijado a mano `costo_usado` puede caer afuera de
# ese sándwich y dar vuelta cualquiera de los dos. Se publican con su signo real
# y la pantalla elige el verbo; forzar «sube» sería inventar una dirección.


def get_palancas(db: Session, anio: int, mes: int) -> dict:
    """Las subas de precio de ese mes, CON NOMBRE y traducidas a pesos de piso.

    De cada suba salen DOS cifras y las dos se publican, porque no son la misma
    plata mirada de dos formas (el bloque de arriba tiene los números medidos):
    `piso_*_si_se_queda` es lo que TODAVÍA va a subir el piso si el precio nuevo
    se queda, y `piso_*_si_vuelve` es HASTA CUÁNTO baja si el proveedor da marcha
    atrás. Los dos son topes que se alcanzan comprando, no lo que pasa mañana
    (ver el escalón medido en el bloque de arriba: el día del acuerdo, $0,00).
    `piso_*_en_juego` es la distancia entre los dos y ordena la lista.

    Contesta 200 SIEMPRE, igual que el piso: cuando el impacto no se puede
    calcular, la alerta viaja igual con `sin_impacto_porque` en castellano. Una
    suba que desaparece de la lista porque no se le pudo poner precio es una
    suba que nadie va a ir a negociar.
    """
    piso = get_piso(db, anio, mes)
    razones = piso["razones"]
    alertas = rent_svc.alertas_de_costo(db)

    # LA VENTANA ES LA DE LAS RAZONES, no la del mes: el margen de contribución
    # se midió ahí, y repartir el costo sobre otra ventana daría un pedacito que
    # no encaja con el margen contra el que se lo va a comparar.
    reparto = ({} if razones is None else
               rent_svc.cogs_por_insumo(db, razones["desde"], razones["hasta"]))

    cf = piso["costos_fijos"]["total"]
    mc = piso["margen_contribucion"]
    piso_mes = piso["piso_mes"]
    n_dias = piso["dias"]["quedan"]

    def mover_el_costo(costo_en_la_venta: float, usado: float, destino: float):
        """El piso del mes SI el costo con el que se costea fuera `destino`.

        Devuelve `(margen, delta contra el piso publicado)`; el delta es `None`
        cuando con ese costo cada venta pierde plata y ya no hay piso posible.

        LOS TRES COSTOS ENTRAN SIN REDONDEAR, y no es un detalle: este cociente
        se calculaba sobre `round(costo, 2)`, y con un insumo de $0,004545/gr el
        divisor daba 0,00 → ZeroDivisionError → 500 en `/costos/palancas` y el
        bloque entero de la pantalla caído. Aparte, sobre la leche del ejemplo
        el redondeo publicaba $8.094,56 donde la cuenta da $8.052,95: medio
        punto de error metido por la impresora adentro de la cuenta.

        `usado > 0` lo garantiza `alertas_de_costo`, que filtra en el origen.
        """
        extra = costo_en_la_venta * (destino / usado - 1.0)
        mc_n = round(mc - extra / razones["ventas_medidas"], 6)
        return mc_n, (None if mc_n <= 0 else round(cf / mc_n - piso_mes, 2))

    palancas = []
    for a in alertas:
        p = dict(a)
        costo_en_la_venta = reparto.get(a["insumo_id"])
        p["costo_en_la_venta"] = costo_en_la_venta
        p["ventana"] = None if razones is None else {"desde": razones["desde"],
                                                     "hasta": razones["hasta"]}
        for k in ("piso_mes_si_se_queda", "piso_dia_si_se_queda",
                  "piso_mes_si_vuelve", "piso_dia_si_vuelve",
                  "piso_mes_en_juego", "piso_dia_en_juego",
                  "margen_si_se_queda", "margen_si_vuelve"):
            p[k] = None
        p["sin_impacto_porque"] = None

        if razones is None:
            p["sin_impacto_porque"] = (
                "no hubo venta con la que medir el margen, así que no se puede "
                "decir cuánto mueve el piso")
        elif piso_mes is None or mc is None or mc <= 0:
            p["sin_impacto_porque"] = (
                "el piso de resultado de este mes no se pudo calcular, así que "
                "no hay contra qué medir la suba")
        elif not costo_en_la_venta:
            # CERO NO ES «NO IMPORTA». O no se vendió nada que lo use en la
            # ventana, o el producto que lo usa tiene un costo OFICIAL cargado a
            # mano y ese número no se mueve con el precio de este insumo.
            p["sin_impacto_porque"] = (
                "no aparece en el costo de lo que se vendió en la ventana medida "
                "(o el producto que lo usa tiene un costo fijado a mano, que no "
                "se mueve con el precio de compra)")
        else:
            # LOS DOS MUNDOS, cada uno medido aparte contra el MISMO piso
            # publicado. Ninguno se deduce del otro: son movimientos del costo a
            # dos destinos distintos y la división cf/mc no es lineal.
            p["margen_si_se_queda"], p["piso_mes_si_se_queda"] = mover_el_costo(
                costo_en_la_venta, a["costo_usado"], a["costo_ultimo"])
            p["margen_si_vuelve"], p["piso_mes_si_vuelve"] = mover_el_costo(
                costo_en_la_venta, a["costo_usado"], a["costo_ref"])

            if p["piso_mes_si_se_queda"] is None:
                p["sin_impacto_porque"] = (
                    "con ese precio nuevo cada venta pierde plata: no hay piso "
                    "que alcance, hay que mover el precio de venta o el costo")
            if (p["piso_mes_si_se_queda"] is not None
                    and p["piso_mes_si_vuelve"] is not None):
                # La distancia ENTERA entre los dos mundos: la plata que esta
                # negociación pone sobre la mesa. Es la que ordena la lista
                # porque es la única que no se encoge sola mientras la suba se
                # va absorbiendo en el promedio.
                p["piso_mes_en_juego"] = round(
                    p["piso_mes_si_se_queda"] - p["piso_mes_si_vuelve"], 2)

            if n_dias > 0:
                # `k_mes`/`k_dia` y no `mes`/`dia`: `mes` es el parámetro de
                # esta función, y pisarlo acá adentro dejaría un int convertido
                # en string esperando al próximo que lo use más abajo.
                for k_mes, k_dia in (("piso_mes_si_se_queda", "piso_dia_si_se_queda"),
                                     ("piso_mes_si_vuelve", "piso_dia_si_vuelve"),
                                     ("piso_mes_en_juego", "piso_dia_en_juego")):
                    if p[k_mes] is not None:
                        p[k_dia] = round(p[k_mes] / n_dias, 2)
            elif p["piso_mes_si_se_queda"] is not None:
                # Sin días que queden no hay «por día» que repartir (el mes
                # ya cerró, o el local no vuelve a abrir). El del MES sigue
                # siendo válido y se dice, en vez de dejar un hueco mudo que
                # se lee como «esta suba no importa».
                p["sin_impacto_porque"] = (
                    "no quedan días de venta en el mes: el impacto está en "
                    "el total del mes, no hay entre cuántos días repartirlo")
        palancas.append(p)

    # Por PLATA EN JUEGO primero —que es la unidad en que se decide— y recién
    # después por venta tocada, para que las que no se pudieron traducir no se
    # pierdan al fondo en un orden arbitrario.
    #
    # NO se ordena por «lo que viene»: ese número se encoge a medida que la suba
    # se absorbe en el promedio, así que la suba que YA llegó entera —la que es
    # 100% oportunidad de recuperación— caería al fondo de la lista justo cuando
    # más plata hay para ir a buscar.
    palancas.sort(key=lambda x: (-(x["piso_dia_en_juego"] or 0.0), -x["venta_30d_afectada"]))
    return {
        "anio": piso["anio"],
        "mes": piso["mes"],
        # EL PISO CONTRA EL QUE SE MIDIÓ, servido acá para que la pantalla no
        # tenga que cruzarlo con otra lectura que podría ser de otro momento.
        "piso": {
            "puerta": piso["puerta"],
            "piso_mes": piso_mes,
            "piso_hoy": piso["piso_hoy"],
            "margen_contribucion": mc,
            "costos_fijos": cf,
            "dias_quedan": n_dias,
        },
        "palancas": palancas,
        "n_alertas": len(palancas),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# EL IMPOCONSUMO: EL ÚNICO GASTO GRANDE QUE NO SE VE COMO GASTO
# ═══════════════════════════════════════════════════════════════════════════════
# De cada peso facturado, 7,41 centavos son de la DIAN. El sistema ya lo trata
# bien en todos lados —la venta neta lo descuenta, el margen de contribución lo
# resta, el piso ya lo tiene adentro— pero en NINGUNA pantalla aparece como PLATA
# QUE HAY QUE PAGAR EN UNA FECHA. Se ve como menos venta todos los días y después
# aparece de golpe una vez cada dos meses. Con $155,6M facturados en un bimestre
# son millones que nadie vio venir.
#
# ═══════════════════════════════════════════════════════════════════════════════
# SÍ SE AGENDA — PERO EN UNA CATEGORÍA QUE EL P&L NO MIRA
# ═══════════════════════════════════════════════════════════════════════════════
# Durante una versión esto fue un recordatorio y NADA MÁS, con este argumento:
# cargarlo como obligación de 'impuestos' sería doble conteo. El argumento era
# correcto y sigue siéndolo — lo que estaba mal era la conclusión, porque los dos
# mundos que se compararon eran «agendarlo en 'impuestos'» y «no agendarlo», y
# hay un tercero. Los tres, MEDIDOS sobre esta base (impoconsumo $11.525.925,93):
#
#   (B) obligación en una categoría de grupo FIJO ('impuestos'):
#       piso del mes $10.799.999 → $23.247.998 (+$12.447.999, que es exactamente
#       impoconsumo/margen_contribución) y margen neto −$11.525.925,93. El doble
#       conteo es REAL y por los dos caminos a la vez.
#   (C) misma obligación en un grupo NO fijo: el piso queda intacto —parece
#       arreglado— pero `tot_gastos` suma TODAS las obligaciones sin mirar el
#       grupo y el margen neto igual cae −$11.525.925,93. ES EL PEOR: el error es
#       MUDO, porque la pantalla que lo delataría no se movió.
#   (D) misma obligación en una categoría DEDICADA, excluida POR CLAVE del
#       término de obligaciones del P&L: piso delta $0, margen neto delta $0, y
#       la agenda pasa de $10.000.000 a $21.525.926.
#
# (D) es lo que hace este módulo, y el mecanismo NO es nuevo: es el mismo que
# `rentabilidad._obligaciones_del_periodo` ya usaba para 'proveedores'. La
# exclusión es por CLAVE y no por grupo justamente por lo que mide (C).
#
# LO QUE SE GANA, EN LA PANTALLA QUE DECIDE SI SE GASTA O NO: sin la obligación,
# el flujo proyectado no veía esta salida —no había ninguna fila que la
# representara— y sobre esta base el saldo mínimo del mes daba +$1.500.000 sin
# punto de quiebre. Con ella agendada da −$5.025.926 y el quiebre cae el 25 de
# agosto. Son $6.525.926 de diferencia entre «podés gastar» y «te quedás sin
# plata en cinco días».
#
# LO QUE SIGUE SIENDO CIERTO: el monto es MEDIDO, no declarado. Por eso agendarla
# es un botón que el dueño aprieta viendo la cifra, y no algo que pase solo.

# El bimestre YA DECLARADO más reciente, como "ANIO-B" (ej. "2026-3"). Un solo
# marcador monótono y no una fila por bimestre: el recordatorio siempre apunta al
# último bimestre cerrado, así que el dueño nunca marca uno viejo estando parado
# en uno nuevo. Marcar el 3 da por declarados el 1 y el 2, que es la verdad de
# cualquier negocio al día con la DIAN.
CLAVE_IMPOCONSUMO_DECLARADO = "impoconsumo_declarado_hasta"


def _bimestre_de(d: date) -> tuple[int, int]:
    """(año, número de bimestre 1..6) de una fecha.

    Los períodos del impuesto nacional al consumo son ene-feb, mar-abr, may-jun,
    jul-ago, sep-oct y nov-dic. No salen de una constante configurable porque no
    son una decisión del negocio: son el calendario de la DIAN.
    """
    return int(d.year), (int(d.month) + 1) // 2


def _rango_bimestre(anio: int, bimestre: int) -> tuple[date, date]:
    """El primer y el último día del bimestre, como fechas de negocio."""
    mes_ini = bimestre * 2 - 1
    mes_fin = bimestre * 2
    return (date(anio, mes_ini, 1),
            date(anio, mes_fin, calendar.monthrange(anio, mes_fin)[1]))


def _bimestre_anterior(anio: int, bimestre: int) -> tuple[int, int]:
    return (anio - 1, 6) if bimestre == 1 else (anio, bimestre - 1)


def _nombre_bimestre(anio: int, bimestre: int) -> str:
    """«julio-agosto 2026». En el idioma del dueño, no «bimestre 4»."""
    return f"{MESES_ES[bimestre * 2 - 2]}-{MESES_ES[bimestre * 2 - 1]} {anio}"


def _mes_de_declaracion(hasta: date) -> tuple[date, date]:
    """(primer día del mes en que se declara, último día de ese mes).

    El plazo cae en el mes SIGUIENTE al cierre del bimestre. El DÍA exacto lo fija
    la DIAN según el último dígito del NIT y el sistema no lo conoce, así que se
    usa el último día del mes: es lo único que se puede afirmar sin el NIT, y es
    el lado prudente para una FECHA DE VENCIMIENTO —adelantarla inventaría una
    mora que no existe; atrasarla escondería la salida del flujo de ese mes.
    """
    primero = hasta + timedelta(days=1)
    ultimo = date(primero.year, primero.month,
                  calendar.monthrange(primero.year, primero.month)[1])
    return primero, ultimo


def _impoconsumo_medido(db: Session, desde: date, hasta: date) -> tuple[float, float, object]:
    """(venta cobrada del bimestre, impoconsumo MEDIDO adentro, tarifas vigentes).

    UNA SOLA CUENTA PARA LOS TRES CONSUMIDORES —el recordatorio, el botón que
    agenda y la cobertura del flujo—, por el mismo motivo por el que
    `_obligaciones_del_periodo` vive afuera de `get_rentabilidad`: si el monto que
    el dueño VE fuera de una fórmula y el que se AGENDA de otra, la obligación
    creada podría no coincidir con la cifra que aprobó.

    Es la misma aritmética que `get_rentabilidad` hace con las ventas del período
    (Σ Ticket.total de los no anulados → `Tributos.separar`), pero como UNA
    agregación en vez del P&L entero: esta cuenta la paga la página que se abre
    todos los días antes de abrir el local, y ahora también el flujo proyectado.

    NO se calcula como tasa nominal: `Tributos.separar` devuelve impuesto CERO
    cuando el precio de la carta no lo lleva adentro, y ahí no hay nada que medir
    —el cociente cubre los dos regímenes sin una rama que se pueda olvidar.
    """
    d_utc, h_utc = rango_col_utc(desde, hasta)
    total = db.query(func.coalesce(func.sum(Ticket.total), 0.0)).filter(
        # La MISMA lista de estados que usa el P&L, importada y no copiada: este
        # monto tiene que dar igual que `resumen.impoconsumo` o el dueño vería dos
        # cifras distintas del mismo impuesto en dos pantallas vecinas.
        Ticket.estado.notin_(ESTADOS_ANULADOS),
        Ticket.fecha >= d_utc,
        Ticket.fecha <= h_utc,
    ).scalar()
    ventas = round(float(total or 0.0), 2)
    tributos = ptsvc.para(db, desde)
    _neta, medido = tributos.separar(ventas)
    return ventas, round(float(medido or 0.0), 2), tributos


def _porque_no_hay_monto(ventas: float, tributos) -> str | None:
    """El motivo, EN CASTELLANO, por el que no se puede publicar un monto — o None.

    Un $0 en una pantalla de plata se lee como «no tenés que pagar nada», así que
    los tres casos en que la medición no existe se nombran en vez de publicarse
    como cero. Vive en su propia función porque lo consultan el recordatorio, el
    botón que agenda (que se NIEGA a crear una obligación sin monto medido) y la
    cobertura del flujo.
    """
    if ventas <= 0:
        return ("no hay ventas registradas en ese bimestre, así que no hay de "
                "dónde medir el impuesto")
    if tributos.impoconsumo <= 0:
        return ("no hay una tarifa de impoconsumo cargada para ese período: el "
                "sistema no la inventa")
    if not tributos.precio_incluye_impoconsumo:
        return ("los precios de la carta no llevan el impoconsumo adentro, así "
                "que no está en lo que cobró la caja y no se puede medir de ahí")
    return None


def _obligacion_de_impoconsumo(db: Session, desde: date, hasta: date):
    """La obligación VIVA del impoconsumo de ese bimestre, si hay alguna.

    Se busca por FECHA DE DEVENGO adentro del bimestre y por la clave dedicada,
    igual que `_obligacion_de_nomina_del_mes` hace con el mes. El devengo es lo
    que ATA la obligación a su período: el vencimiento cae en el mes siguiente y
    buscar por él haría que la declaración de may-jun y la de jul-ago se pisaran
    en cuanto una se agende tarde.
    """
    return (
        db.query(Obligacion)
        .join(CostoCategoria, CostoCategoria.id == Obligacion.categoria_id)
        .filter(
            Obligacion.anulada == False,  # noqa: E712
            Obligacion.fecha_devengo >= desde,
            Obligacion.fecha_devengo <= hasta,
            CostoCategoria.clave == CLAVE_CATEGORIA_IMPOCONSUMO,
        )
        .order_by(Obligacion.id)
        .first()
    )


def leer_impoconsumo_declarado(db: Session) -> tuple[int, int] | None:
    """El último bimestre marcado como declarado, o None si nunca se marcó ninguno.

    Un valor corrupto (alguien tocó la tabla a mano) se lee como None y NO como
    «todo declarado»: ante la duda el recordatorio aparece, que es el lado
    incómodo. Apagarlo por un string que no se entiende sería exactamente el
    error tranquilizador de siempre.
    """
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_IMPOCONSUMO_DECLARADO).first()
    if fila is None or not (fila.valor or "").strip():
        return None
    try:
        anio_txt, bim_txt = str(fila.valor).split("-", 1)
        anio, bim = int(anio_txt), int(bim_txt)
    except (ValueError, TypeError):
        return None
    if not (1 <= bim <= 6) or not (2000 <= anio <= 2100):
        return None
    return anio, bim


def marcar_impoconsumo_declarado(db: Session, anio: int, bimestre: int,
                                 usuario_id: int) -> dict:
    """«Esa ya la declaré»: el interruptor del recordatorio.

    NO SE PUEDE MARCAR UN BIMESTRE QUE TODAVÍA NO CERRÓ. Sería apagar por
    adelantado un aviso sobre plata que ni siquiera terminó de cobrarse — y como
    el marcador es monótono, apagaría de paso todos los anteriores.

    Tampoco RETROCEDE: marcar may-jun teniendo jul-ago marcado no reabre nada.
    """
    anio, bimestre = int(anio), int(bimestre)
    if not (2000 <= anio <= 2100):
        raise HTTPException(400, "Año fuera de rango")
    if not (1 <= bimestre <= 6):
        raise HTTPException(400, "El bimestre va de 1 a 6")
    _desde, hasta = _rango_bimestre(anio, bimestre)
    hoy = hoy_col()
    if hasta >= hoy:
        raise HTTPException(
            400, f"El bimestre {_nombre_bimestre(anio, bimestre)} todavía no "
                 f"cerró (termina el {hasta.isoformat()}): no se puede marcar "
                 "como declarado.")

    ya = leer_impoconsumo_declarado(db)
    if ya is not None and ya >= (anio, bimestre):
        return {"declarado_hasta": {"anio": ya[0], "bimestre": ya[1],
                                    "nombre": _nombre_bimestre(*ya)},
                "ya_estaba": True}

    valor = f"{anio}-{bimestre}"
    fila = db.query(Configuracion).filter(
        Configuracion.clave == CLAVE_IMPOCONSUMO_DECLARADO).first()
    if fila is None:
        db.add(Configuracion(clave=CLAVE_IMPOCONSUMO_DECLARADO, valor=valor))
    else:
        fila.valor = valor
    audit.registrar(
        db, accion="marcar_impoconsumo_declarado", tabla="configuracion",
        registro_id=None, usuario_id=usuario_id, tienda_id=None,
        datos_antes={"declarado_hasta": f"{ya[0]}-{ya[1]}" if ya else None},
        datos_despues={"declarado_hasta": valor},
    )
    db.commit()
    return {"declarado_hasta": {"anio": anio, "bimestre": bimestre,
                                "nombre": _nombre_bimestre(anio, bimestre)},
            "ya_estaba": False}


def get_impoconsumo(db: Session) -> dict:
    """LA DECLARACIÓN DEL IMPOCONSUMO QUE VIENE, con el monto MEDIDO o sin él.

    Apunta SIEMPRE al último bimestre CERRADO: es el único que se puede declarar.
    El que está corriendo no se declara, y ponerlo acá haría creer que hay que
    pagar hoy una plata que todavía se está cobrando.

    ── EL MONTO NO SE INVENTA ────────────────────────────────────────────────
    Lo que se publica es lo que el sistema MIDIÓ cobrado de impoconsumo en ese
    bimestre, con la misma cuenta que usa el piso (`Tributos.separar` sobre la
    venta real, no la tarifa nominal). Eso NO es la declaración: el contador
    tiene exclusiones, correcciones y ajustes que el sistema no ve. Por eso viaja
    como `monto_medido` y no como «lo que hay que pagar», y por eso vuelve en
    None con el porqué escrito en tres casos: sin ventas registradas, sin tarifa
    cargada, y con precios que no llevan el impuesto adentro (ahí no está en
    `Ticket.total` y no hay de dónde medirlo). Un monto inventado en una pantalla
    de plata es peor que un recordatorio sin monto.

    ── LA MEDICIÓN SOLO SE PAGA SI HAY ALGO QUE OFRECER ─────────────────────
    Con el bimestre declarado Y la obligación ya creada la respuesta sale sin
    tocar las ventas. Esta página se abre todos los días antes de abrir el local
    y ya paga varias lecturas caras; una más que no va a mostrar nada no se gana
    el viaje.

    PERO «DECLARADO» SOLO NO ES «NADA QUE MOSTRAR», y el atajo estaba puesto ahí.
    Declarado sin agendar es justamente el hueco que el flujo denuncia —la plata
    sigue sin estar en la agenda— y la pantalla necesita el monto para poder
    ofrecer el botón que lo tapa. Devolviendo `monto_medido: None` ahí, el aviso
    del flujo mandaba al dueño a un renglón que decía «al día» y no tenía ningún
    botón: una acción que se evapora. La condición ahora es la que de verdad
    quiere decir «no queda nada que hacer»: declarado Y agendado.

    ── Y SE DICE SI YA ESTÁ AGENDADA ────────────────────────────────────────
    `agendada` es lo que le permite a la pantalla ofrecer el botón una sola vez y
    después mostrar la obligación que existe. Sin este campo el botón no sabría
    si crear o no, y la única forma de averiguarlo sería apretarlo.
    """
    hoy = hoy_col()
    # El bimestre de HOY todavía corre: el que se declara es el anterior.
    anio, bim = _bimestre_anterior(*_bimestre_de(hoy))
    desde, hasta = _rango_bimestre(anio, bim)

    # EL MES EN QUE SE DECLARA: el siguiente al cierre del bimestre. La FECHA
    # exacta la fija la DIAN según el último dígito del NIT y el sistema no lo
    # conoce, así que se nombra el mes y no se inventa un día. Pasado ese mes
    # entero, sí se puede afirmar que está tarde sin saber el NIT.
    mes_dec, fin_plazo = _mes_de_declaracion(hasta)

    ya = leer_impoconsumo_declarado(db)
    declarado = ya is not None and ya >= (anio, bim)

    # LA OBLIGACIÓN SE MIRA SIEMPRE, incluso con el bimestre ya declarado: marcar
    # «ya la declaré» apaga el recordatorio pero NO paga la obligación, y la
    # pantalla tiene que poder mostrar que esa plata sigue en la agenda.
    obl = _obligacion_de_impoconsumo(db, desde, hasta)

    base = {
        "hoy": hoy,
        "bimestre": {
            "anio": anio, "numero": bim, "nombre": _nombre_bimestre(anio, bim),
            "desde": desde, "hasta": hasta,
        },
        "declara_en": {"anio": mes_dec.year, "mes": mes_dec.month,
                       "nombre": MESES_ES[mes_dec.month - 1],
                       "hasta": fin_plazo},
        "declarado": declarado,
        "declarado_hasta": (None if ya is None else
                            {"anio": ya[0], "bimestre": ya[1],
                             "nombre": _nombre_bimestre(*ya)}),
        # Ya pasó el mes ENTERO en que la DIAN lo pide: esto es tarde para
        # cualquier NIT, y por eso se puede afirmar sin saber cuál es.
        "vencido": (not declarado) and hoy > fin_plazo,
        "hay_que_declarar": not declarado,
        "agendada": (None if obl is None else
                     {"obligacion_id": obl.id, "monto": round(float(obl.monto or 0), 2),
                      "fecha_vencimiento": obl.fecha_vencimiento,
                      "concepto": obl.concepto}),
    }

    # El atajo pide LAS DOS COSAS: el trámite hecho y la plata reservada. Con una
    # sola —declarada pero sin agendar— todavía hay un botón que ofrecer, y sin
    # monto ese botón no se puede rotular.
    if declarado and obl is not None:
        return {**base, "monto_medido": None, "ventas": None,
                "sin_monto_porque": None, "tasa": None,
                "confirmar_contador": False}

    ventas, medido, tributos = _impoconsumo_medido(db, desde, hasta)
    porque = _porque_no_hay_monto(ventas, tributos)

    return {
        **base,
        # MEDIDO, no «a pagar». La declaración la arma el contador.
        "monto_medido": None if porque else medido,
        "ventas": None if ventas <= 0 else ventas,
        "sin_monto_porque": porque,
        "tasa": tributos.impoconsumo,
        "confirmar_contador": bool(tributos.confirmar_contador),
    }


def agendar_impoconsumo(db: Session, anio: int, bimestre: int, usuario_id: int,
                        monto: float | None = None,
                        barista_id: int | None = None,
                        barista_nombre: str | None = None) -> dict:
    """Convierte la declaración de un bimestre en plata con fecha en la agenda.

    Copia el patrón de `agendar_nomina` —el otro gasto grande que era un cálculo y
    no una obligación— y por las mismas razones: sin una fila que la represente,
    la salida no está en la agenda, no baja el flujo proyectado y no tiene botón
    de [Pagar]. Con $155,6M facturados en un bimestre son $11,5M que la caja no
    veía venir.

    ═══════════════════════════════════════════════════════════════════════════
    EL DEVENGO ES DEL BIMESTRE; EL VENCIMIENTO, DEL MES SIGUIENTE
    ═══════════════════════════════════════════════════════════════════════════
    Acá NO coinciden —a diferencia de la nómina, donde caen el mismo día por
    casualidad— y esa distancia es justamente lo que hace que la obligación sea
    útil sin ensuciar nada:

      · `fecha_devengo` = último día del bimestre. Ata la declaración a SU
        período, que es lo que hace idempotente al botón y lo que impide que
        may-jun y jul-ago se pisen.
      · `fecha_vencimiento` = último día del mes siguiente. Es lo que lee la
        agenda y el flujo, o sea el día en que la plata se dibuja saliendo. El
        día exacto lo fija la DIAN según el último dígito del NIT: se usa el
        último del mes porque es lo único afirmable sin el NIT.

    ═══════════════════════════════════════════════════════════════════════════
    ESTA OBLIGACIÓN NO ENTRA AL P&L NI AL PISO, Y NO ES UN OLVIDO
    ═══════════════════════════════════════════════════════════════════════════
    Va a la categoría dedicada `CLAVE_CATEGORIA_IMPOCONSUMO`, que
    `rentabilidad._obligaciones_del_periodo` excluye POR CLAVE igual que a
    'proveedores'. El margen ya se mide sobre la venta NETA y el piso ya le restó
    el impuesto en el denominador: contarla otra vez como gasto sería cobrar la
    misma plata dos veces (medido: piso +$12.447.999 y margen neto −$11.525.926).
    El porqué completo, con los tres mundos medidos, está en el bloque de arriba.

    SIN MONTO MEDIDO NO SE AGENDA NADA. Los tres casos en que la medición no
    existe —sin ventas, sin tarifa, precios que no lo llevan adentro— vuelven 400
    con el motivo en castellano en vez de crear una obligación en $0. Una fila en
    cero en la agenda se lee como «esto ya está resuelto», que es peor que no
    tenerla: apagaría el aviso de cobertura del flujo sin haber reservado un peso.

    EL MONTO ES EDITABLE, por el mismo motivo que en la nómina: lo que el sistema
    mide es lo COBRADO, y la declaración que arma el contador tiene exclusiones y
    correcciones que el sistema no ve. Manda el papel, no la estimación.

    PERO NO CONTRA LA MEDICIÓN: crear esta fila apaga el aviso de cobertura de la
    caja por el solo hecho de existir, así que un monto escrito muy por DEBAJO del
    medido rebota con las dos cifras y la base a la vista. Escribir de más no
    rebota: reserva de más, que es el lado seguro. El corte y su porqué, abajo.

    IDEMPOTENTE Y ATÓMICA sobre el bimestre: dos taps no pagan la DIAN dos veces.
    Misma ventana teórica que `agendar_nomina` si dos admins aprietan en el mismo
    instante, y por el mismo motivo no se cierra con un índice único acá.
    """
    anio, bimestre = int(anio), int(bimestre)
    if not (2000 <= anio <= 2100):
        raise HTTPException(400, "Año fuera de rango")
    if not (1 <= bimestre <= 6):
        raise HTTPException(400, "El bimestre va de 1 a 6")
    desde, hasta = _rango_bimestre(anio, bimestre)

    # NO SE AGENDA UN BIMESTRE QUE TODAVÍA NO CERRÓ, con el mismo criterio que
    # `marcar_impoconsumo_declarado`: la venta de esos dos meses sigue entrando,
    # así que el monto medido de hoy no es el que se va a declarar. Agendarlo
    # ahora congelaría una cifra incompleta —siempre MENOR que la real— y el
    # flujo reservaría de menos justo en el término que vino a hacer visible.
    if hasta >= hoy_col():
        raise HTTPException(
            400, f"El bimestre {_nombre_bimestre(anio, bimestre)} todavía no cerró "
                 f"(termina el {hasta.isoformat()}): lo que lleva facturado no es "
                 "lo que se va a declarar.")

    ya = _obligacion_de_impoconsumo(db, desde, hasta)
    if ya is not None:
        return {**_con_pagos(db, ya), "ya_existia": True,
                "bimestre": {"anio": anio, "numero": bimestre,
                             "nombre": _nombre_bimestre(anio, bimestre)},
                "detalle": None}

    cat = db.query(CostoCategoria).filter(
        CostoCategoria.clave == CLAVE_CATEGORIA_IMPOCONSUMO).first()
    if cat is None:
        # El catálogo se siembra al arrancar; llegar acá es una base a la que le
        # falta la siembra. NO se crea la categoría al vuelo: nacería sin pasar
        # por `sembrar_categorias` y podría quedar en el grupo equivocado.
        raise HTTPException(
            400, "No existe la categoría «Impoconsumo (DIAN)» en el catálogo de "
                 "costos. Reiniciá el sistema para que se siembre y volvé a "
                 "intentarlo.")
    if not cat.activa:
        raise HTTPException(
            400, f"La categoría «{cat.nombre}» está desactivada — reactivala para "
                 "poder agendar la declaración.")

    ventas, medido, tributos = _impoconsumo_medido(db, desde, hasta)
    porque = _porque_no_hay_monto(ventas, tributos)
    if monto is None and porque is not None:
        raise HTTPException(
            400, f"No se puede agendar el impoconsumo de "
                 f"{_nombre_bimestre(anio, bimestre)}: {porque}. Si tenés la cifra "
                 "de tu contador, escribila a mano.")
    valor = _validar_monto(monto) if monto is not None else medido
    if valor <= 0:
        raise HTTPException(
            400, "El impoconsumo medido da $0: agendarlo así pondría en la agenda "
                 "una cuenta que se lee como resuelta sin haber reservado un peso.")

    # ═══════════════════════════════════════════════════════════════════════════
    # EL MONTO A MANO MANDA, PERO NO CONTRA LA MEDICIÓN Y SIN QUE NADIE MIRE
    # ═══════════════════════════════════════════════════════════════════════════
    # Crear esta obligación APAGA `_cobertura_impoconsumo`, que cubre por un solo
    # hecho —que la obligación exista— y no mira ni el saldo ni el monto. O sea
    # que un $1 escrito acá apaga el aviso de que faltan $11,5M por reservar, y
    # deja la proyección de caja exactamente igual de equivocada que antes pero
    # ahora con un renglón verde encima. Es la familia de error de siempre —una
    # cifra CERCA de la correcta, del lado que tranquiliza— con la firma del dueño.
    #
    # SE REBOTA EN UN SOLO SENTIDO, Y LA ASIMETRÍA ES A PROPÓSITO. Escribir de MÁS
    # reserva de más: es incómodo y es seguro, así que pasa sin preguntar. Escribir
    # de MENOS es lo que apaga un aviso sin haber reservado la plata, y ahí sí se
    # frena. Un dígito que falta es un factor de diez exacto, así que el corte va
    # en un QUINTO del medido: atrapa el dígito perdido y todavía deja entrar una
    # declaración legítimamente más baja (el contador tiene exclusiones y
    # correcciones que el sistema no ve — sobre este local, un quinto ya pediría
    # que el 80% de lo que cobró la caja quedara afuera de la base).
    #
    # NO SE COMPARA CUANDO NO HAY CONTRA QUÉ: sin ventas, sin tarifa o con precios
    # que no llevan el impuesto adentro (`porque`), el medido no mide nada y
    # rebotar contra él sería rebotar contra un cero inventado.
    if monto is not None and porque is None and medido > 0 and valor * 5 < medido:
        raise HTTPException(
            400,
            f"Escribiste ${valor:,.0f} y el sistema midió ${medido:,.0f} de "
            f"impoconsumo sobre ${ventas:,.0f} facturados en "
            f"{_nombre_bimestre(anio, bimestre)}: lo que escribiste es menos de "
            "la quinta parte de lo medido. Agendarla por esa cifra apagaría el "
            "aviso de que esa plata todavía no está reservada, sin haber "
            "reservado un peso, así que no se crea. Fijate si no le falta un "
            "dígito. Si el número de tu contador es más bajo que el medido pero "
            "parecido, ese sí entra — y si es más alto, entra siempre.")

    _desde_mes, vencimiento = _mes_de_declaracion(hasta)
    concepto = f"Impoconsumo {_nombre_bimestre(anio, bimestre)}"

    obligacion = Obligacion(
        # CORPORATIVA (tienda_id NULL): la declaración es UNA sola para el NIT del
        # negocio, no una por sede. Partirla entre sedes inventaría una
        # repartición que la DIAN no hace, y además el impuesto ya se midió sobre
        # la venta de todas juntas.
        tienda_id=None,
        categoria_id=cat.id,
        concepto=_validar_concepto(concepto),
        beneficiario="DIAN",
        monto=valor,
        fecha_devengo=hasta,
        fecha_vencimiento=vencimiento,
        nota=(f"Agendada desde el recordatorio del impoconsumo. Medido sobre "
              f"${ventas:,.0f} facturados en el bimestre. El día exacto lo fija "
              f"la DIAN según el último dígito del NIT: acá va el último del mes."),
        usuario_id=usuario_id,
        barista_id=barista_id,
        barista_nombre=barista_nombre,
    )
    db.add(obligacion)
    db.flush()
    audit.registrar(
        db, accion="agendar_impoconsumo", tabla="obligaciones",
        registro_id=obligacion.id, usuario_id=usuario_id, tienda_id=None,
        datos_despues={"anio": anio, "bimestre": bimestre, "monto": valor,
                       "monto_medido": medido, "monto_editado": monto is not None,
                       "ventas_bimestre": ventas,
                       "fecha_devengo": hasta, "fecha_vencimiento": vencimiento},
    )
    db.commit()
    db.refresh(obligacion)
    return {
        **_serializar(obligacion, []),
        "ya_existia": False,
        "bimestre": {"anio": anio, "numero": bimestre,
                     "nombre": _nombre_bimestre(anio, bimestre)},
        # La apertura, para que la pantalla pueda explicar de dónde salió la cifra
        # sin volver a pedirla — y para que se vea que es MEDIDA y no declarada.
        "detalle": {
            "ventas_bimestre": ventas,
            "monto_medido": medido,
            "monto_editado": monto is not None,
            "tasa": tributos.impoconsumo,
            "confirmar_contador": bool(tributos.confirmar_contador),
        },
    }
