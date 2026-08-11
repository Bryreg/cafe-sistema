"""Diagnóstico de stock: por qué el motor no avisa y por qué hay negativos.

El dueño preguntó dos cosas —«contá los umbrales» y «por qué tengo inventario
negativo»— y la respuesta correcta no es un .sql que él pegue en una consola de
Postgres una vez: es que el sistema se lo conteste, en la pantalla donde ya está
parado, y para siempre. Este módulo es esa respuesta.

LO QUE MIDE

  1. UMBRALES. `stock_minimo`, `stock_ideal` y `stock_critico` nacen en 0
     (models.py:303-305). Un producto que nadie configuró a mano nace INERTE:
     con el mínimo en 0, `inventario.clasificar_estado` y `pedidos._estado`
     degeneran los dos a «agotado si stock<=0, si no, todo bien». O sea que el
     motor de pedidos no avisa nada hasta que ya te quedaste sin producto.
     La cuenta va sobre TODAS las filas y también sobre el inventario
     GESTIONADO (controla stock + entra al conteo), que es el subconjunto que el
     motor mira de verdad — la fracción sobre el total incluye archivados y
     miente hacia abajo.

  2. CONSUMO. El otro eje del motor es el tiempo: stock / consumo diario. Si
     ningún producto tuvo salidas, ese eje tampoco opera y TODO cae al umbral
     mínimo del punto 1. Sin este número, el número de arriba no se puede leer.

  3. NEGATIVOS, con su causa probable. Un negativo NO es un bug: services/pos.py
     descuenta con `allow_negative=True` a propósito, porque una venta jamás
     puede fallar por un motivo contable. Un negativo es el sistema diciendo que
     se consumió más de lo que se registró que ENTRÓ. Lo que falta es un
     registro, no una corrección de stock.

  4. RECETAS SOSPECHOSAS DE UNIDAD. Si la receta dice «18» pensando en gramos
     pero el insumo se mide en kg, cada venta descuenta 18 kg en vez de 18 g: el
     stock se desploma en horas y ningún conteo lo explica.

LA CAUSA ES UNA SOSPECHA, NO UN VEREDICTO
Mismo principio que la escalera de conciliación: este módulo mide y NUNCA
atribuye. La clasificación se arma con lo poquito que el libro puede ver —si hay
receta, si hubo entradas, cuándo fue la última— y eso alcanza para orientar, no
para sentenciar. Por eso cada frase se declara sospecha en su primera palabra, y
cuando dos causas aplican se dice cuál gana Y que la otra estaba ahí: esconder
la segunda es inventar una certeza que los datos no dan.

READ-ONLY DE PUNTA A PUNTA
No escribe, no corrige stock, no crea movimientos. Solo lee.

PORTABILIDAD Y COSTO
Corre en SQLite (dev) y en Postgres (producción): sin FILTER(WHERE), sin NOW(),
sin INTERVAL, sin ::numeric. Los cortes de fecha se calculan en Python y viajan
como parámetros. Son OCHO consultas fijas (CINCO si no hay ningún negativo:
las tres que describen los negativos ni se lanzan), todas agregadas o con LIMIT:
ninguna depende de la cantidad de productos, y no hay N+1 — los datos por
producto (última entrada, recetas en los dos sentidos) se traen de una sola vez
con un IN sobre los negativos, que ya vienen acotados por el LIMIT.
"""
from datetime import datetime, timedelta

from sqlalchemy import and_, case, distinct, func, or_
from sqlalchemy.orm import Session, aliased

from app.models.models import (Inventario, MovimientoInventario, Producto,
                               ProductoInsumo, Tienda, TipoMovInvEnum)
from app.services.pedidos import DIAS_ANALISIS

# Ventana del diagnóstico de consumo. 30 días es la pregunta «¿este producto se
# movió alguna vez en el último mes?».
DIAS_CONSUMO = 30
# La ventana REAL del motor de pedidos. Se importa, no se copia: si mañana
# cambia DIAS_ANALISIS, este diagnóstico no puede quedar mintiendo.
DIAS_ANALISIS_MOTOR = DIAS_ANALISIS

# Una entrada más vieja que esto, con el stock en negativo, huele a factura sin
# cargar: el producto se siguió gastando y nadie anotó la reposición.
DIAS_ENTRADA_VIEJA = 60

# Topes. El diagnóstico corre en Render free (el backend duerme y despierta
# lento): una respuesta acotada que avisa que está acotada vale más que una
# completa que tarda.
MAX_NEGATIVOS = 200
MAX_RECETAS_SOSPECHOSAS = 100

# Unidades "grandes" y "chicas" para la sospecha de unidad mal cargada.
UNIDADES_GRANDES = ("kg", "lt", "l", "litro", "litros")
UNIDADES_CHICAS = ("gr", "g", "gramos", "ml")
CANTIDAD_GRANDE = 5.0     # 5 kg por unidad vendida no es una receta, es un error
CANTIDAD_CHICA = 0.5      # 0,2 g por unidad vendida tampoco


# ─── Causas ──────────────────────────────────────────────────────────────────
# Cada frase arranca con «Sospecha». No es un adorno: es la única forma honesta
# de decir esto. El libro no puede distinguir un robo de una tanda sin registrar
# de una factura traspapelada, y ninguna de estas frases pretende poder.

CAUSAS: dict[str, dict[str, str]] = {
    "preparable_sin_registrar": {
        "titulo": "Preparación sin registrar",
        # NO dice «nunca entró»: esta causa cubre también al preparable cuyas
        # tandas se registraron hace mucho y se dejaron de registrar. Un absoluto
        # que el propio payload desmiente («último ingreso: hace 90 días») es la
        # misma clase de mentira que se corrigió en el resto de la pantalla.
        "sospecha_base": (
            "esto se prepara en la barra y hace rato que no se registra una "
            "tanda. Cada venta descuenta la mezcla, y la mezcla no está entrando."
        ),
        "que_hacer": "Registrá la preparación cada vez que se arme una tanda.",
    },
    # El MISMO producto, con las tandas SÍ registradas. `registrar_preparacion`
    # (inventario.py:577) las escribe como `tipo=entrada`, así que una barra que
    # hace bien su trabajo tiene entradas recientes y aun así puede quedar en
    # negativo. Decirle a esa barra «nadie registró la tanda» es exigirle lo que
    # ya está haciendo, y encima al lado de un «última entrada: hace 3 días» que
    # lo desmiente en la misma pantalla. Acá la falla está en cuánto RINDE cada
    # tanda o en cuánto descuenta la receta, no en el registro.
    "preparable_no_alcanza": {
        "titulo": "Las tandas no alcanzan",
        "sospecha_base": (
            "las tandas se están registrando (la última hace {dias} días), pero "
            "no cubren lo que las ventas descuentan. O cada tanda rinde menos de "
            "lo que dice la receta, o la receta descuenta de más."
        ),
        "que_hacer": (
            "Medí una tanda real contra lo que dice la receta. Si rinde menos, "
            "corregí el rendimiento; si coincide, revisá cuánto descuenta la venta."
        ),
    },
    "sin_entrada_registrada": {
        "titulo": "Sin ingreso registrado",
        "sospecha_base": (
            "en esta sede no hay ningún ingreso registrado de este producto —ni "
            "entrada, ni ajuste de conteo—. Llegó a la barra y se gastó, pero "
            "nadie lo cargó."
        ),
        "que_hacer": "Cargá la entrada que falta y el número se acomoda.",
    },
    "entrada_vieja": {
        "titulo": "Factura sin cargar",
        "sospecha_base": (
            "el último ingreso registrado es de hace {dias} días y desde "
            "entonces se siguió gastando. Suena a una factura que quedó sin cargar."
        ),
        "que_hacer": "Buscá la factura de la última compra y cargala.",
    },
    "consumo_sin_registro": {
        "titulo": "Se gastó más de lo que se cargó",
        "sospecha_base": (
            "se consumió más de lo que se registró que entró. No hay ninguna "
            "señal más específica que apunte a otra cosa."
        ),
        "que_hacer": (
            "Contá el producto y cargá lo que falte de entrada. Si el negativo "
            "vuelve, mirá la receta que lo consume."
        ),
    },
}

# Prioridad: de la causa que más dice a la que menos. La primera que aplica gana.
_PRIORIDAD = ("preparable_sin_registrar", "preparable_no_alcanza",
              "sin_entrada_registrada", "entrada_vieja", "consumo_sin_registro")

# Por qué gana la primera cuando hay dos. Se escribe por PAR: un texto genérico
# («gana la más específica») no le dice nada a nadie.
_POR_QUE_GANA = {
    ("preparable_sin_registrar", "sin_entrada_registrada"): (
        "Las dos aplican. Gana la preparación porque acá la entrada que falta ES "
        "la tanda: este producto no se compra hecho, se arma en la barra."
    ),
    ("preparable_sin_registrar", "entrada_vieja"): (
        "Las dos aplican. Gana la preparación porque lo que falta registrar es la "
        "tanda, no una factura del proveedor: este producto no se compra hecho."
    ),
}


def clasificar_causa_negativo(*, controla_stock: bool, precio_venta: float,
                              tiene_receta_propia: bool,
                              ultima_entrada: datetime | None,
                              ahora: datetime,
                              dias_entrada_vieja: int = DIAS_ENTRADA_VIEJA) -> dict:
    """Convierte un puñado de hechos del libro en una SOSPECHA sobre por qué
    este producto quedó en negativo. Función pura: sin sesión, sin efectos.

    `controla_stock` + `precio_venta == 0` + receta propia = PREPARABLE: un
    intermedio que se arma en la barra y no se vende (la mezcla del granizado).
    Un producto CON precio y receta es una bebida del POS, no un preparable: su
    receta describe qué descuenta, no cómo se produce.

    Devuelve siempre una causa —`consumo_sin_registro` es el cajón de sastre y
    no puede fallar— más las OTRAS causas específicas que también aplicaban y el
    motivo por el que ganó la elegida.
    """
    dias_sin_entrada: int | None = None
    if ultima_entrada is not None:
        dias_sin_entrada = (ahora - ultima_entrada).days

    es_preparable = bool(controla_stock) and (precio_venta or 0) <= 0 and tiene_receta_propia
    sin_entrada = ultima_entrada is None
    entrada_vieja = dias_sin_entrada is not None and dias_sin_entrada > dias_entrada_vieja

    aplican = []
    if es_preparable:
        # La entrada RECIENTE es la que decide: si la hay, las tandas se están
        # registrando y el problema es otro. Sin este corte, el diagnóstico se
        # contradecía a sí mismo dentro del mismo bloque de pantalla.
        hay_entrada_reciente = ultima_entrada is not None and not entrada_vieja
        aplican.append("preparable_no_alcanza" if hay_entrada_reciente
                       else "preparable_sin_registrar")
    if sin_entrada:
        aplican.append("sin_entrada_registrada")
    if entrada_vieja:
        aplican.append("entrada_vieja")
    if not aplican:
        aplican.append("consumo_sin_registro")

    aplican.sort(key=_PRIORIDAD.index)
    causa, *tambien = aplican

    por_que_gana = None
    if tambien:
        por_que_gana = _POR_QUE_GANA.get((causa, tambien[0]))

    txt = CAUSAS[causa]
    return {
        "causa": causa,
        "titulo": txt["titulo"],
        "sospecha": "Sospecha: " + txt["sospecha_base"].format(dias=dias_sin_entrada),
        "que_hacer": txt["que_hacer"],
        "tambien_aplica": tambien,
        "por_que_gana": por_que_gana,
        "dias_sin_entrada": dias_sin_entrada,
    }


# ─── El diagnóstico ──────────────────────────────────────────────────────────

def _gestionado():
    """Inventario que el motor de pedidos mira de verdad. Misma regla que
    get_alertas / sugerencia_pedido: controla stock y entra al conteo."""
    return and_(Producto.controla_stock.is_(True),
                Producto.incluir_en_conteo.isnot(False))


def _cuenta(cond):
    """SUM(CASE WHEN … THEN 1 ELSE 0 END) — el equivalente portable de
    COUNT(*) FILTER (WHERE …), que es sintaxis solo-Postgres."""
    return func.sum(case((cond, 1), else_=0))


def _umbrales(db: Session, tienda_id: int | None) -> dict:
    """Consulta 1 de 8. Agregada y agrupada por sede: devuelve una fila por
    tienda, nunca una por producto."""
    con_min = func.coalesce(Inventario.stock_minimo, 0) > 0
    q = (
        db.query(
            Inventario.tienda_id,
            Tienda.nombre,
            func.count(Inventario.id),
            _cuenta(con_min),
            _cuenta(func.coalesce(Inventario.stock_critico, 0) > 0),
            _cuenta(func.coalesce(Inventario.stock_ideal, 0) > 0),
            _cuenta(_gestionado()),
            _cuenta(and_(_gestionado(), con_min)),
        )
        .join(Producto, Producto.id == Inventario.producto_id)
        .join(Tienda, Tienda.id == Inventario.tienda_id)
        .group_by(Inventario.tienda_id, Tienda.nombre)
        .order_by(Tienda.nombre)
    )
    if tienda_id is not None:
        q = q.filter(Inventario.tienda_id == tienda_id)

    por_sede = [{
        "tienda_id": r[0], "tienda": r[1], "filas": int(r[2] or 0),
        "con_minimo": int(r[3] or 0), "con_critico": int(r[4] or 0),
        "con_ideal": int(r[5] or 0), "filas_gestionadas": int(r[6] or 0),
        "con_minimo_gestionadas": int(r[7] or 0),
    } for r in q.all()]

    claves = ("filas", "con_minimo", "con_critico", "con_ideal",
              "filas_gestionadas", "con_minimo_gestionadas")
    # El total es la suma de las sedes: cada fila de inventario pertenece a UNA
    # sede, así que acá no hay doble conteo posible.
    total = {k: sum(s[k] for s in por_sede) for k in claves}
    return {"total": total, "por_sede": por_sede}


def _consumo(db: Session, tienda_id: int | None, ahora: datetime) -> dict:
    """Consultas 2 y 3 de 8. La total va aparte de la agrupada a propósito: un
    producto que se movió en las DOS sedes cuenta una vez en el total y una vez
    en cada sede, y sumar las sedes lo contaría dos veces."""
    corte_30 = ahora - timedelta(days=DIAS_CONSUMO)
    corte_motor = ahora - timedelta(days=DIAS_ANALISIS_MOTOR)
    reciente = case((MovimientoInventario.fecha >= corte_motor,
                     MovimientoInventario.producto_id))

    def base(q):
        q = q.filter(MovimientoInventario.tipo == TipoMovInvEnum.salida,
                     MovimientoInventario.fecha >= corte_30)
        if tienda_id is not None:
            q = q.filter(MovimientoInventario.tienda_id == tienda_id)
        return q

    n30, n_motor = base(db.query(
        func.count(distinct(MovimientoInventario.producto_id)),
        func.count(distinct(reciente)),
    )).one()

    por_sede = [{
        "tienda_id": r[0],
        "productos_con_salidas_30d": int(r[1] or 0),
        "productos_con_salidas_14d": int(r[2] or 0),
    } for r in base(db.query(
        MovimientoInventario.tienda_id,
        func.count(distinct(MovimientoInventario.producto_id)),
        func.count(distinct(reciente)),
    )).group_by(MovimientoInventario.tienda_id).all()]

    return {
        "dias_ventana": DIAS_CONSUMO,
        "dias_analisis_motor": DIAS_ANALISIS_MOTOR,
        "productos_con_salidas_30d": int(n30 or 0),
        "productos_con_salidas_14d": int(n_motor or 0),
        # Sin salidas medidas, `pedidos._estado` no puede calcular «días que me
        # quedan» y todo el motor cae al umbral mínimo — que además está en 0.
        "motor_sin_datos": int(n_motor or 0) == 0,
        "por_sede": por_sede,
    }


def _negativos(db: Session, tienda_id: int | None, ahora: datetime) -> tuple[list, bool]:
    """Consultas 5 a 8 de 8. La primera trae los negativos con LIMIT; las otras
    tres traen de UNA sola vez los datos por producto de ese conjunto ya
    acotado. Cero N+1: el costo no crece con el catálogo."""
    q = (
        db.query(
            Inventario.producto_id, Inventario.tienda_id, Inventario.stock_actual,
            Producto.nombre, Producto.unidad_medida, Producto.controla_stock,
            Producto.precio_venta, Tienda.nombre,
        )
        .join(Producto, Producto.id == Inventario.producto_id)
        .join(Tienda, Tienda.id == Inventario.tienda_id)
        .filter(Inventario.stock_actual < 0)
    )
    if tienda_id is not None:
        q = q.filter(Inventario.tienda_id == tienda_id)
    # El LIMIT va ÚLTIMO: SQLAlchemy prohíbe filtrar una query ya acotada, y si
    # se pudiera sería peor —el tope se aplicaría antes que el filtro de sede.
    filas = (q.order_by(Inventario.stock_actual.asc())
              .limit(MAX_NEGATIVOS + 1)      # +1 para saber si quedó recortado
              .all())

    truncado = len(filas) > MAX_NEGATIVOS
    filas = filas[:MAX_NEGATIVOS]
    if not filas:
        return [], False

    pids = list({f[0] for f in filas})
    tids = list({f[1] for f in filas})

    # Último INGRESO por (producto, sede). El par importa: una entrada en
    # Palmetto no explica el negativo de Vida.
    #
    # Cuenta la `entrada` Y el `ajuste`, porque el ajuste TAMBIÉN sube stock y es
    # un camino real en este repo: aplicar un conteo físico (conteos.py:41),
    # aprobar una verificación (conteos.py:346), el conteo de compras
    # (compras.py:65) y el cierre mensual (inventario_mensual.py:497) escriben
    # ajustes. Mirando solo `entrada`, un producto cuya reposición se registró
    # por conteo aplicado salía como «nadie lo cargó» — una afirmación falsa
    # sobre el trabajo de una persona que sí lo registró.
    ultimas = {
        (r[0], r[1]): r[2]
        for r in db.query(
            MovimientoInventario.producto_id, MovimientoInventario.tienda_id,
            func.max(MovimientoInventario.fecha),
        ).filter(
            MovimientoInventario.tipo.in_((TipoMovInvEnum.entrada,
                                           TipoMovInvEnum.ajuste)),
            MovimientoInventario.producto_id.in_(pids),
            MovimientoInventario.tienda_id.in_(tids),
        ).group_by(MovimientoInventario.producto_id,
                   MovimientoInventario.tienda_id).all()
    }

    # ¿Tiene receta PROPIA? (es algo que se arma) — y ¿cuántas recetas lo
    # consumen? (es insumo de otra cosa). Son los dos sentidos de la receta.
    con_receta_propia = {
        r[0] for r in db.query(ProductoInsumo.producto_id)
        .filter(ProductoInsumo.producto_id.in_(pids)).distinct().all()
    }
    lo_consumen = {
        r[0]: int(r[1]) for r in db.query(
            ProductoInsumo.insumo_id, func.count(ProductoInsumo.id)
        ).filter(ProductoInsumo.insumo_id.in_(pids))
        .group_by(ProductoInsumo.insumo_id).all()
    }

    out = []
    for pid, tid, stock, nombre, unidad, controla, precio, sede in filas:
        ultima = ultimas.get((pid, tid))
        causa = clasificar_causa_negativo(
            controla_stock=bool(controla),
            precio_venta=float(precio or 0),
            tiene_receta_propia=pid in con_receta_propia,
            ultima_entrada=ultima,
            ahora=ahora,
        )
        out.append({
            "producto_id": pid,
            "producto": nombre,
            "tienda_id": tid,
            "sede": sede,
            "stock": round(float(stock or 0), 2),
            "unidad": unidad,
            "ultima_entrada": ultima.isoformat() if ultima else None,
            "lo_consumen_n_recetas": lo_consumen.get(pid, 0),
            **causa,
        })
    return out, truncado


def _num(x: float) -> str:
    """18.0 → «18», 0.2 → «0,2». Un número que se lee en voz alta dentro de una
    frase no puede arrastrar el .0 del float."""
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return (s or "0").replace(".", ",")


def _recetas_sospechosas(db: Session) -> list:
    """Consulta 8 de 8. La receta no tiene sede: la sospecha es global.

    Dos formas del mismo error, simétricas: cantidad grande sobre insumo medido
    en unidad grande (18 «kg» donde se quiso decir 18 g descuenta 1000 veces de
    más por cada venta), y cantidad minúscula sobre insumo medido en unidad
    chica (0,2 «g» donde se quiso decir 0,2 kg descuenta 1000 veces de menos)."""
    Pr = aliased(Producto)
    Ins = aliased(Producto)
    unidad = func.lower(Ins.unidad_medida)
    grande = and_(unidad.in_(UNIDADES_GRANDES), ProductoInsumo.cantidad >= CANTIDAD_GRANDE)
    chica = and_(unidad.in_(UNIDADES_CHICAS), ProductoInsumo.cantidad < CANTIDAD_CHICA)

    filas = (
        db.query(Pr.nombre, Ins.id, Ins.nombre, ProductoInsumo.cantidad,
                 Ins.unidad_medida, Pr.id)
        .join(Pr, Pr.id == ProductoInsumo.producto_id)
        .join(Ins, Ins.id == ProductoInsumo.insumo_id)
        .filter(or_(grande, chica))
        .order_by(ProductoInsumo.cantidad.desc())
        .limit(MAX_RECETAS_SOSPECHOSAS)
        .all()
    )
    out = []
    for pr_nombre, ins_id, ins_nombre, cantidad, ins_unidad, pr_id in filas:
        cant = round(float(cantidad or 0), 4)
        de_mas = cant >= CANTIDAD_GRANDE
        out.append({
            "producto_vendido": pr_nombre,
            "producto_id": pr_id,
            "insumo": ins_nombre,
            "insumo_id": ins_id,
            "dice_la_receta": cant,
            "unidad_del_insumo": ins_unidad,
            "sospecha": (
                f"Sospecha: la receta de {pr_nombre} descuenta {_num(cant)} "
                f"{ins_unidad} de {ins_nombre} por unidad vendida. "
                + ("Si en realidad eran gramos, cada venta está descontando mil veces de más."
                   if de_mas else
                   "Si en realidad eran kilos o litros, cada venta está descontando mil veces de menos.")
            ),
        })
    return out


def diagnostico(db: Session, tienda_id: int | None = None) -> dict:
    """Lectura completa. Solo LEE: no escribe, no corrige stock, no crea
    movimientos. `tienda_id` acota umbrales, consumo y negativos; las recetas
    son globales porque no tienen sede."""
    ahora = datetime.utcnow()
    negativos, truncado = _negativos(db, tienda_id, ahora)
    return {
        "generado": ahora.isoformat(),
        "tienda_id": tienda_id,
        "umbrales": _umbrales(db, tienda_id),
        "consumo": _consumo(db, tienda_id, ahora),
        "negativos": negativos,
        "negativos_truncado": truncado,
        "negativos_tope": MAX_NEGATIVOS,
        "recetas_sospechosas": _recetas_sospechosas(db),
    }
