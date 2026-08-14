"""Rentabilidad (P&L de caja) del negocio.

Cruza las tres fuentes de dinero del sistema, cada una en su base:
  - VENTAS:  Σ Ticket.total (excluye anulados/reversados) — ingreso real.
  - COMPRAS: Σ FacturaCompra.valor_total por fecha de recibido — mercancía que
    ENTRÓ en el período (base de recepción, no de consumo: un mes donde se
    stockea fuerte se ve peor de lo que fue; se documenta en `nota`).
  - GASTOS:  dos mitades que se suman. (a) Σ MovimientoCaja tipo=egreso EXCLUYENDO
    los ligados a facturas de proveedor (concepto 'Pago proveedor:%' /
    'Ajuste factura%'), que ya están contados dentro de COMPRAS, y EXCLUYENDO los
    ya adoptados por el módulo Costos; (b) Σ Obligacion.monto por fecha_devengo.
    Adoptar un egreso lo pasa de (a) a (b) sin cambiar el total: sin cualquiera de
    las dos exclusiones, la misma plata se contaría dos veces.

margen_bruto = ventas - compras;  margen_neto = margen_bruto - gastos.
"""
import calendar
import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, not_, or_

from app.core.tz import dia_col, hora_col, hoy_col, rango_col_utc
from app.models.models import (
    CajaTurno, Combo, CostoCategoria, FacturaCompra, FacturaCompraItem,
    MovimientoCaja, Obligacion, Pago, Producto,
    ProductoInsumo, ProductoDesechable, Ticket, TicketItem,
    TicketItemComboSeleccion, Tienda, TipoMovCajaEnum,
)
from app.services import nomina as nomina_svc

# Patrones de concepto que crea services/facturas.py para pagos a proveedor.
# Si esos strings cambian allá, hay que actualizarlos acá (no hay FK).
_CONCEPTOS_COMPRA = ("Pago proveedor:%", "Reverso Pago proveedor:%", "Ajuste factura%")

# Categoría de costo PROHIBIDA: la deuda con proveedores ya entra al P&L por
# FacturaCompra (fecha de recibido), así que una obligación cargada acá contaría
# la misma mercadería DOS VECES dentro de `gastos`. services/costos.py rechaza
# esta clave al crear/editar/adoptar; la exclusión de abajo cubre las filas
# LEGACY que la versión anterior sí dejó guardar. Vive en este módulo —y no en
# costos.py— porque costos.py ya importa de acá las constantes anti-doble-conteo
# y la dependencia inversa sería circular.
CLAVE_CATEGORIA_PROVEEDORES = "proveedores"

# Categoría de la nómina en el catálogo de costos (`_seed_categorias_costo`).
# El costo laboral del período ya lo CALCULA services/nomina.py con las horas
# marcadas y los recargos de ley, así que cargarlo además a mano sería la misma
# plata dos veces. La regla de convivencia está en `_nomina_del_periodo`.
CLAVE_CATEGORIA_NOMINA = "nomina"

ESTADOS_ANULADOS = ("anulado", "reversado")

logger = logging.getLogger(__name__)


def _mes(dt) -> str:
    return dia_col(dt).strftime("%Y-%m")


def _nomina_del_periodo(db, desde: date, hasta: date, tienda_id: int | None,
                        oblig_rows: list) -> dict:
    """El costo laboral que entra al P&L, ya resuelto el conflicto con lo manual.

    ═══════════════════════════════════════════════════════════════════════════
    LA REGLA: SI EL MES TIENE NÓMINA CARGADA A MANO, GANA LA MANO.
    ═══════════════════════════════════════════════════════════════════════════
    El costo laboral se puede saber de dos formas y las dos son legítimas:

      (a) CALCULADA — `services/nomina.costo_laboral`: horas realmente marcadas
          × recargos de ley vigentes esa semana. Es lo que este sistema mide.
      (b) MANUAL — una `Obligacion` de categoría 'nomina' que alguien cargó. Es
          lo que de verdad se pagó, con prestaciones, seguridad social y auxilio
          de transporte adentro; cosas que (a) declara explícitamente que NO
          incluye (ver `horas.valorizar`).

    Sumar las dos contaría la misma plata dos veces y hundiría el margen con un
    gasto que no existe. Así que se resuelve MES POR MES: el mes que tiene una
    obligación de nómina devengada usa esa —el número que el contador liquidó es
    mejor que la estimación— y su cálculo se descarta entero; el mes que no la
    tiene usa el calculado.

    Por qué mes por mes y no un interruptor global: es lo que hace que prender
    esto NO cambie ni un peso de la historia ya cargada, y que dejar de cargar la
    nómina a mano baste para que el cálculo tome la posta. La migración es no
    hacer nada.

    LA DECISIÓN SE TOMA POR MES CALENDARIO, NO POR LA VENTANA CONSULTADA.
    `oblig_rows` está recortado por [desde, hasta], y el P&L se consulta casi
    siempre con ventanas PARCIALES: el período por defecto de la pantalla es "del
    1 a hoy". Con una nómina devengada el 31, mirar del 1 al 15 no la vería,
    daría ese mes por calculado y sumaría un costo que el mes completo considera
    cubierto por la carga manual — o sea que dos mitades de un mes sumarían más
    que el mes entero. Todos los demás términos del P&L son aditivos sobre
    ventanas disjuntas y este no puede ser la excepción. Por eso la detección
    consulta los MESES COMPLETOS que toca el rango, en su propia query.

    Y SE DECIDE POR SEDE, NO SOLO POR MES. Una obligación de nómina puede ser
    corporativa (`tienda_id` NULL) o de una sede. La corporativa cubre a todo el
    mundo y apaga el cálculo de ese mes entero; la de una sede apaga SOLO esa.
    Sin esta distinción, cargar la nómina de una sola sede borraba del margen el
    costo calculado de las demás: plata que no aparecía ni calculada ni manual.

    El recorte por sede del scope se respeta igual que en `oblig_rows`: en la
    vista de una sede las corporativas no entran (no se prorratean), y entonces
    esa sede sí ve su costo calculado, que es información que antes no tenía.
    """
    ini_mes = desde.replace(day=1)
    fin_mes = hasta.replace(day=calendar.monthrange(hasta.year, hasta.month)[1])
    q_nom = (
        db.query(Obligacion.fecha_devengo, Obligacion.tienda_id)
        .join(CostoCategoria, CostoCategoria.id == Obligacion.categoria_id)
        .filter(
            Obligacion.anulada.is_(False),
            Obligacion.fecha_devengo >= ini_mes,
            Obligacion.fecha_devengo <= fin_mes,
            CostoCategoria.clave == CLAVE_CATEGORIA_NOMINA,
        )
    )
    if tienda_id is not None:
        q_nom = q_nom.filter(Obligacion.tienda_id == tienda_id)

    meses_todas_las_sedes: set[str] = set()
    pares_manuales: set[tuple[str, int]] = set()
    for devengo, tid in q_nom.all():
        mes = devengo.strftime("%Y-%m")
        if tid is None:
            meses_todas_las_sedes.add(mes)      # corporativa: cubre a todos
        else:
            pares_manuales.add((mes, tid))      # de esa sede y solo esa

    # Las exclusiones se aplican ADENTRO del cálculo y no después: así el total,
    # las horas y la gente contada hablan todos del mismo conjunto de días.
    # Filtrando al final, `nomina_horas` incluiría horas cuyo costo no se sumó.
    calculada = nomina_svc.costo_laboral(db, desde, hasta, tienda_id,
                                         excluir_meses=meses_todas_las_sedes,
                                         excluir_mes_sede=pares_manuales)
    manuales = meses_todas_las_sedes | {mes for mes, _sede in pares_manuales}
    return {
        "pares": calculada["por_mes_sede"],
        "total": calculada["total"],
        "meses_calculados": calculada["meses"],
        "meses_manuales": sorted(manuales),
        # Personas con horas en el período y sin salario cargado: sus horas
        # entran al margen valiendo $0. Se dice, no se esconde.
        "sin_contrato": calculada["sin_contrato"],
        "personas": calculada["personas"],
        "horas": calculada["horas"],
    }


def _costo_unitario_productos(db) -> dict[int, float]:
    """Costo por unidad de VENTA de cada producto (para el COGS teórico).
    Prioridad: precio_costo oficial > receta (Σ insumos × costo) > costo de
    compra (reventa). Los granel-sin-receta quedan afuera (costo por gr vs
    venta por porción no son comparables)."""
    costo_prom, _ = _costos_insumos(db)
    recetas: dict[int, list] = defaultdict(list)
    for pi in db.query(ProductoInsumo).all():
        recetas[pi.producto_id].append(pi)
    out: dict[int, float] = {}
    for p in db.query(Producto).all():
        if p.precio_costo is not None and float(p.precio_costo) > 0:
            out[p.id] = float(p.precio_costo)
            continue
        ings = recetas.get(p.id)
        if ings:
            c, alguno = 0.0, False
            for pi in ings:
                ci = costo_prom.get(pi.insumo_id)
                if ci is not None:
                    c += float(pi.cantidad) * ci
                    alguno = True
            if alguno:
                out[p.id] = c
            continue
        um = (p.unidad_medida or "").lower()
        if um not in ("gr", "g", "gramos", "ml") and p.id in costo_prom:
            out[p.id] = costo_prom[p.id]
    return out


def get_rentabilidad(db, desde: date, hasta: date, tienda_id: int | None = None) -> dict:
    d_utc, h_utc = rango_col_utc(desde, hasta)
    tiendas = {t.id: t.nombre for t in db.query(Tienda).all()}

    # ── Ventas (tickets no anulados) ──────────────────────────────────────────
    # `descuento` viaja ADITIVO: Ticket.total ya viene NETO de descuento, así que
    # exponerlo cuenta lo que se regaló en mostrador sin volver a restarlo. Hasta
    # ahora el POS lo escribía en cada venta y ningún reporte lo sumaba: un
    # descuento y una venta que no ocurrió se veían exactamente igual.
    q_ventas = db.query(Ticket.fecha, Ticket.total, Ticket.tienda_id,
                        Ticket.descuento).filter(
        Ticket.estado.notin_(ESTADOS_ANULADOS),
        Ticket.fecha >= d_utc,
        Ticket.fecha <= h_utc,
    )
    if tienda_id is not None:
        q_ventas = q_ventas.filter(Ticket.tienda_id == tienda_id)
    ventas_rows = q_ventas.all()

    # ── Compras (facturas de proveedor, por fecha de recibido) ───────────────
    fc_fecha = func.coalesce(FacturaCompra.fecha_recibido, FacturaCompra.fecha_registro)
    q_compras = db.query(fc_fecha, FacturaCompra.valor_total, FacturaCompra.tienda_id).filter(
        fc_fecha >= d_utc, fc_fecha <= h_utc,
    )
    if tienda_id is not None:
        q_compras = q_compras.filter(FacturaCompra.tienda_id == tienda_id)
    compras_rows = q_compras.all()

    # ── Gastos operativos (egresos de caja NO ligados a compras) ─────────────
    # Ligado a compra = tiene factura_id (vínculo estructural) o, para movimientos
    # anteriores a esa columna, el concepto reservado que escribe services/facturas.
    #
    # Y ligado a una obligación = ya fue ADOPTADO (Fase 3): el egreso sigue vivo en
    # caja pero su plata ahora se cuenta abajo, como obligación devengada. Sin esta
    # exclusión el mismo gasto se contaría dos veces. Va como SUBCONSULTA y no como
    # lista de ids: un `IN (...)` explícito revienta el tope de variables de SQLite
    # (mismo patrón deliberado que get_attach_producto).
    adoptados = (
        db.query(Pago.movimiento_caja_id)
        .filter(Pago.movimiento_caja_id.isnot(None), Pago.anulado.is_(False))
        .distinct().subquery()
    )
    q_gastos = (
        db.query(MovimientoCaja.fecha, MovimientoCaja.valor,
                 MovimientoCaja.concepto, CajaTurno.tienda_id)
        .join(CajaTurno, MovimientoCaja.caja_turno_id == CajaTurno.id)
        .filter(
            MovimientoCaja.tipo == TipoMovCajaEnum.egreso,
            MovimientoCaja.fecha >= d_utc,
            MovimientoCaja.fecha <= h_utc,
            MovimientoCaja.factura_id.is_(None),
            not_(or_(*[MovimientoCaja.concepto.like(p) for p in _CONCEPTOS_COMPRA])),
            MovimientoCaja.id.notin_(db.query(adoptados.c.movimiento_caja_id)),
        )
    )
    if tienda_id is not None:
        q_gastos = q_gastos.filter(CajaTurno.tienda_id == tienda_id)
    gastos_rows = q_gastos.all()

    # ── Obligaciones devengadas (módulo Costos) ──────────────────────────────
    # Término NUEVO del gasto, en QUERY SEPARADA a propósito: la de arriba hace
    # `join(CajaTurno)` y filtra sede por `CajaTurno.tienda_id`, y una obligación
    # corporativa (arriendo, nómina) tiene tienda_id NULL y ningún turno — ese join
    # la BORRARÍA. Además `fecha_devengo` es Date, o sea fecha de NEGOCIO ya
    # resuelta: se compara contra desde/hasta y NUNCA contra d_utc/h_utc, que son
    # instantes UTC para columnas de instante.
    #
    # Y se EXCLUYE la categoría 'proveedores': esa mercadería ya está contada
    # arriba, en `compras`, por FacturaCompra según fecha de recibido. Sumarla
    # también acá contaría la misma plata dos veces y hundiría el margen neto con
    # un gasto que no existe. El servicio ya no deja cargar nada ahí; este filtro
    # es por las filas que la versión anterior alcanzó a guardar.
    # `clave` va al final (índice 5) a propósito: el chequeo de costos fijos de más
    # abajo indexa por posición (r[4] == grupo) y agregarla en el medio lo rompería.
    q_oblig = (
        db.query(Obligacion.fecha_devengo, Obligacion.monto,
                 Obligacion.tienda_id, CostoCategoria.nombre, CostoCategoria.grupo,
                 CostoCategoria.clave)
        .join(CostoCategoria, CostoCategoria.id == Obligacion.categoria_id)
        .filter(
            Obligacion.anulada.is_(False),
            Obligacion.fecha_devengo >= desde,
            Obligacion.fecha_devengo <= hasta,
            CostoCategoria.clave != CLAVE_CATEGORIA_PROVEEDORES,
        )
    )
    if tienda_id is not None:
        # Con sede filtrada las corporativas NO se cuelan ni se prorratean: repartirlas
        # las duplicaría y Σ por_sede dejaría de dar el global.
        q_oblig = q_oblig.filter(Obligacion.tienda_id == tienda_id)
    oblig_rows = q_oblig.all()

    # ── COGS teórico: lo VENDIDO × costo de receta (base de consumo, no de
    # recepción). Da el margen bruto real del período sin la distorsión de los
    # días en que se stockea fuerte. Se acompaña de pct_venta_costeada para no
    # leer el número como exacto si hay productos sin costo.
    costo_unit = _costo_unitario_productos(db)
    # Líneas de combo: el producto de la línea es el SOMBRA (Combo.producto_id),
    # sin costo propio — su costo real son los COMPONENTES elegidos
    # (TicketItemComboSeleccion), agregados más abajo.
    sombras_combo = {pid for (pid,) in db.query(Combo.producto_id).all()}
    q_items = (
        db.query(TicketItem.producto_id,
                 func.coalesce(func.sum(TicketItem.cantidad), 0),
                 func.coalesce(func.sum(TicketItem.subtotal), 0.0))
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                Ticket.fecha >= d_utc, Ticket.fecha <= h_utc)
        .group_by(TicketItem.producto_id)
    )
    if tienda_id is not None:
        q_items = q_items.filter(Ticket.tienda_id == tienda_id)
    cogs_teorico = 0.0
    venta_costeada = 0.0
    venta_items = 0.0
    for pid, cant, subtotal in q_items.all():
        venta_items += float(subtotal or 0)
        if pid in sombras_combo:
            # La venta del combo cuenta como costeada con su costo agregado
            # (componentes × costo unitario, sumado abajo).
            venta_costeada += float(subtotal or 0)
            continue
        c = costo_unit.get(pid)
        if c is not None:
            cogs_teorico += float(cant or 0) * c
            venta_costeada += float(subtotal or 0)

    # COGS de combos: consumo real de componentes en el rango × costo unitario
    # (la cantidad de la selección es POR combo → total = cantidad × línea).
    q_sel = (
        db.query(TicketItemComboSeleccion.producto_id,
                 func.coalesce(func.sum(TicketItemComboSeleccion.cantidad * TicketItem.cantidad), 0))
        .join(TicketItem, TicketItem.id == TicketItemComboSeleccion.ticket_item_id)
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                Ticket.fecha >= d_utc, Ticket.fecha <= h_utc)
        .group_by(TicketItemComboSeleccion.producto_id)
    )
    if tienda_id is not None:
        q_sel = q_sel.filter(Ticket.tienda_id == tienda_id)
    for pid, cant in q_sel.all():
        c = costo_unit.get(pid)
        if c is not None:
            cogs_teorico += float(cant or 0) * c

    # ── Agregaciones ──────────────────────────────────────────────────────────
    tot_ventas = round(sum(float(r[1] or 0) for r in ventas_rows), 2)
    tot_compras = round(sum(float(r[1] or 0) for r in compras_rows), 2)
    # El gasto del período son las DOS mitades: lo que sigue suelto en caja y lo ya
    # adoptado como obligación. Adoptar mueve plata de una a la otra sin cambiar el total.
    # ── Costo laboral CALCULADO (services/nomina) ────────────────────────────
    # Tercer término del gasto. Sale de las horas marcadas y los recargos de ley,
    # no de que alguien lo digite: eso era el doble trabajo que había que matar.
    # Los meses que YA tienen nómina cargada a mano quedan afuera del cálculo
    # —ver `_nomina_del_periodo`— así que la misma plata nunca se cuenta dos veces.
    nomina = _nomina_del_periodo(db, desde, hasta, tienda_id, oblig_rows)

    tot_gastos = round(sum(float(r[1] or 0) for r in gastos_rows)
                       + sum(float(r[1] or 0) for r in oblig_rows)
                       + nomina["total"], 2)

    por_mes: dict[str, dict] = defaultdict(lambda: {"ventas": 0.0, "compras": 0.0, "gastos": 0.0})
    # Clave int o None: None = gasto CORPORATIVO (sin sede), no un dato faltante.
    por_sede: dict = defaultdict(lambda: {"ventas": 0.0, "compras": 0.0, "gastos": 0.0})
    for fecha, total, tid, _desc in ventas_rows:
        por_mes[_mes(fecha)]["ventas"] += float(total or 0)
        por_sede[tid]["ventas"] += float(total or 0)
    for fecha, total, tid in compras_rows:
        por_mes[_mes(fecha)]["compras"] += float(total or 0)
        por_sede[tid]["compras"] += float(total or 0)
    gastos_por_concepto: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "n": 0})
    # PARTICIÓN de `gastos` por categoría de costo. `gastos_detalle` mezcla en una
    # sola lista el nombre de la categoría con el texto libre del egreso de caja, o
    # sea que leerlo obliga a adivinar cuál es cuál; acá la categoría es la clave
    # ESTABLE del catálogo y los egresos sueltos van a una bolsa declarada aparte.
    # Es ADITIVO: Σ de este desglose tiene que dar exactamente `resumen.gastos`.
    por_categoria: dict[str, dict] = {}

    def _acum_categoria(clave: str, nombre: str, grupo, monto: float) -> None:
        g = por_categoria.setdefault(
            clave, {"clave": clave, "nombre": nombre, "grupo": grupo, "total": 0.0, "n": 0})
        g["total"] += monto
        g["n"] += 1

    for fecha, valor, concepto, tid in gastos_rows:
        por_mes[_mes(fecha)]["gastos"] += float(valor or 0)
        por_sede[tid]["gastos"] += float(valor or 0)
        g = gastos_por_concepto[(concepto or "(sin concepto)").strip()]
        g["total"] += float(valor or 0)
        g["n"] += 1
        # Bolsa propia, nunca disfrazada de categoría: es exactamente la plata que
        # se vacía adoptando el egreso en Costos, y decir cuánta hay es lo que
        # convierte "el desglose no cuadra" en "falta categorizar esto".
        _acum_categoria("sin_categorizar", "Sin categorizar", None, float(valor or 0))
    # Las obligaciones agrupan por NOMBRE DE CATEGORÍA (no por texto libre): a medida
    # que se adoptan egresos, el bloque de conceptos sueltos se vacía solo.
    # `fecha_devengo` ya es fecha Colombia: se formatea directo, sin pasar por _mes
    # (que convierte de UTC y espera un datetime).
    for devengo, monto, tid, categoria, grupo, clave in oblig_rows:
        por_mes[devengo.strftime("%Y-%m")]["gastos"] += float(monto or 0)
        por_sede[tid]["gastos"] += float(monto or 0)
        g = gastos_por_concepto[(categoria or "(sin categoría)").strip()]
        g["total"] += float(monto or 0)
        g["n"] += 1
        _acum_categoria(clave or "otros", (categoria or "Sin categoría").strip(),
                        grupo, float(monto or 0))

    # La nómina calculada entra a los MISMOS desgloses que cualquier otro gasto:
    # si entrara solo al total, `Σ por_mes`, `Σ por_sede` y `Σ por_categoria`
    # dejarían de dar `resumen.gastos` y el desglose pasaría a mentir. Por eso el
    # cálculo viene abierto por (mes, sede) y no como un número suelto.
    for (mes_nom, sede_nom), monto in nomina["pares"].items():
        por_mes[mes_nom]["gastos"] += monto
        por_sede[sede_nom]["gastos"] += monto
        _acum_categoria(CLAVE_CATEGORIA_NOMINA, "Nómina (calculada)", "fijo", monto)
    if nomina["total"]:
        g = gastos_por_concepto["Nómina calculada (horas × recargos)"]
        g["total"] += nomina["total"]
        g["n"] += nomina["personas"]

    # ── Cobertura de costos FIJOS (arriendo, nómina, servicios, impuestos) ────
    # Campo ADITIVO: no entra en ninguna fórmula, solo declara si el margen neto
    # de este período está mirando los costos fijos o no. Sin esto la pantalla no
    # puede distinguir "el negocio no tiene costos fijos" de "nadie los cargó", y
    # un semáforo en verde sobre el segundo caso es una mentira tranquilizadora.
    fijos_rows = [r for r in oblig_rows if (r[4] or "") == "fijo"]
    # La nómina calculada ES un costo fijo del período, y cuenta como tal: sin
    # esto, un negocio que dejó de cargarla a mano —justamente el objetivo de la
    # integración— aparecía como "no tiene costos fijos cargados" y el semáforo
    # se apagaba solo el día que el dato empezó a ser mejor que antes.
    costos_fijos_devengados = round(sum(float(r[1] or 0) for r in fijos_rows)
                                    + nomina["total"], 2)
    n_costos_fijos = len(fijos_rows) + len(nomina["pares"])

    # ── Descuentos: la plata REGALADA en mostrador ────────────────────────────
    # ADITIVO y fuera de toda fórmula: Ticket.total ya viene neto. El % se mide
    # contra la venta BRUTA (lo que se habría facturado sin regalar nada); contra
    # la neta daría un número inflado que sobreestima el descuento.
    descuentos = round(sum(float(r[3] or 0) for r in ventas_rows), 2)
    n_con_descuento = sum(1 for r in ventas_rows if float(r[3] or 0) > 0)

    def _cerrar(d: dict) -> dict:
        v, c, g = round(d["ventas"], 2), round(d["compras"], 2), round(d["gastos"], 2)
        neto = round(v - c - g, 2)
        return {"ventas": v, "compras": c, "gastos": g,
                "margen_neto": neto,
                "pct_margen_neto": round(neto / v * 100, 1) if v > 0 else None}

    margen_bruto = round(tot_ventas - tot_compras, 2)
    margen_neto = round(margen_bruto - tot_gastos, 2)

    # ── Fuga de inventario MEDIDA por los cierres del período ─────────────────
    # Hasta acá el P&L no sabía que existía: `InventarioMensual` no se importaba
    # en ningún otro servicio, así que la merma real que el conteo físico mide
    # nunca llegaba al estado de resultados y el margen que el dueño mira no
    # incluía la fuga que su propio sistema había medido.
    #
    # LA FUGA NO SE PUEDE RESTAR DE `margen_neto`: YA ESTÁ ADENTRO
    # `compras` es base de RECEPCIÓN (línea 101-107: Σ FacturaCompra.valor_total
    # por fecha_recibido) y `margen_neto = ventas − compras − gastos`. O sea que
    # la mercadería se gasta ENTERA al recibirla, sin capitalizar nada: lo que se
    # compró y después se fugó ya está descontado ahí adentro. Restarle la fuga
    # otra vez subestimaría la utilidad exactamente en el valor de la fuga, todos
    # los meses, en un KPI destacado.
    #
    # El término correcto se calcula contra `margen_bruto_real` (ventas −
    # cogs_teorico), que SÍ es base de CONSUMO: `cogs_teorico` (línea 196-224) es
    # el costo de lo VENDIDO según receta y no contiene la fuga, porque lo que se
    # fugó justamente no se vendió. Ahí el término suma información en vez de
    # descontar dos veces la misma plata.
    #
    # `margen_neto` no cambia de valor ni de nombre: sigue siendo el número que el
    # dueño ya conoce.
    #
    # `None` ≠ 0: cero significa "se contó y no falta nada"; None significa
    # "nadie cerró un conteo completo dentro de este rango, así que no se midió".
    #
    # ADITIVO también en el sentido de la falla: el P&L nunca dependió de
    # `movimientos_inventario` y no puede empezar a caerse por eso. Si la
    # conciliación explota, el estado de resultados se sigue mostrando entero y la
    # fuga viaja como "no medida" — que es la verdad: no se pudo medir.
    from app.services import conciliacion
    try:
        fuga = conciliacion.fuga_medida(db, desde, hasta, tienda_id)
    except Exception:  # noqa: BLE001 — un dato aditivo jamás tumba el P&L entero
        logger.exception("No se pudo medir la fuga de inventario; el P&L sigue sin ella")
        fuga = {"valor": None, "periodos": [], "sin_costo": 0, "estimados": 0,
                "contados": 0, "productos": 0, "cierres": 0, "meses": 0,
                "sedes": 0, "sedes_ids": []}

    # Cuántos meses CALENDARIO toca el rango pedido (el parcial también cuenta).
    # Es el denominador que deja ver que el margen y la fuga NO miden el mismo
    # tramo: ver `fuga_meses` abajo.
    meses_rango = (hasta.year - desde.year) * 12 + (hasta.month - desde.month) + 1
    # El OTRO eje del mismo tramo: las SEDES. Con "Todas las sedes" el margen suma
    # ventas y COGS de todas las que vendieron, y la fuga solo de las que cerraron
    # un conteo. Una sede que nunca cierra se cae del término de fuga sin ninguna
    # señal, y el sesgo va para el mismo lado que el de los meses: subdeclara.
    #
    # El denominador son las sedes que VENDIERON en el rango, no todas las del
    # catálogo: una sede sin operación no aporta margen, así que no falta en la
    # comparación y contarla sería un aviso que nunca se puede apagar.
    #
    # Y se INTERSECAN los conjuntos, no se restan los conteos. Comparar cardinalidades
    # deja pasar el caso cruzado: la sede A cerró su conteo pero no vendió, la sede B
    # vendió y nunca cerró. «1 de 1» y el aviso callado, cuando la realidad es que el
    # margen tiene a B adentro y la fuga no. El numerador es la cobertura REAL: sedes
    # que vendieron Y midieron.
    sedes_vendieron = ({tienda_id} if tienda_id is not None else
                       {tid for tid, v in por_sede.items()
                        if tid is not None and v["ventas"] > 0})
    sedes_rango = len(sedes_vendieron)
    sedes_medidas = len(sedes_vendieron & set(fuga.get("sedes_ids") or []))

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "resumen": {
            "ventas": tot_ventas,
            "compras": tot_compras,
            "gastos": tot_gastos,
            "margen_bruto": margen_bruto,
            "margen_neto": margen_neto,
            "pct_margen_bruto": round(margen_bruto / tot_ventas * 100, 1) if tot_ventas > 0 else None,
            "pct_margen_neto": round(margen_neto / tot_ventas * 100, 1) if tot_ventas > 0 else None,
            "n_tickets": len(ventas_rows),
            "n_facturas": len(compras_rows),
            # Base de CONSUMO (complementa a compras, que es base de recepción):
            "cogs_teorico": round(cogs_teorico, 2),
            "margen_bruto_real": round(tot_ventas - cogs_teorico, 2),
            "pct_margen_bruto_real": round((tot_ventas - cogs_teorico) / tot_ventas * 100, 1) if tot_ventas > 0 else None,
            "brecha_compras": round(tot_compras - cogs_teorico, 2),
            "pct_venta_costeada": round(venta_costeada / venta_items * 100, 1) if venta_items > 0 else None,
            # Cobertura de costos fijos del período (ADITIVO — ya está DENTRO de
            # `gastos` y de `margen_neto`; se expone aparte solo para que la UI
            # sepa si puede emitir un veredicto o tiene que pedir el dato).
            "costos_fijos_devengados": costos_fijos_devengados,
            "n_costos_fijos": n_costos_fijos,
            "tiene_costos_fijos": bool(fijos_rows) or bool(nomina["pares"]),
            # ── Costo laboral: cuánto, de dónde salió y qué le falta ──────────
            # ADITIVO: ya está DENTRO de `gastos` y de `margen_neto`. Se expone
            # aparte para que la pantalla pueda decir de qué meses el número lo
            # calculó el sistema y de cuáles lo puso una persona — leerlo como un
            # solo número escondería que son dos fuentes distintas.
            "nomina_calculada": nomina["total"],
            "nomina_meses_calculados": nomina["meses_calculados"],
            "nomina_meses_manuales": nomina["meses_manuales"],
            "nomina_personas": nomina["personas"],
            "nomina_horas": nomina["horas"],
            # Gente con horas en el período y sin salario cargado en Contratos:
            # sus horas entran al margen valiendo $0 y el costo está subdeclarado.
            "nomina_sin_contrato": nomina["sin_contrato"],
            "nomina_es_estimado": True,
            # Plata regalada en mostrador (ADITIVA: NO se resta de nada, `ventas`
            # ya es neto). Sin este número un descuento y una venta que no ocurrió
            # son indistinguibles.
            "descuentos": descuentos,
            "n_tickets_con_descuento": n_con_descuento,
            "pct_descuento": (round(descuentos / (tot_ventas + descuentos) * 100, 1)
                              if tot_ventas + descuentos > 0 else None),
            # Fuga de inventario medida por el conteo físico. Negativa = plata
            # que se fue sin que ninguna causa registrada la explique.
            #
            # NO se resta de `margen_neto`: `compras` es base de RECEPCIÓN, así
            # que la mercadería fugada ya está gastada ahí adentro y descontarla
            # de nuevo contaría la misma plata dos veces. El término va contra
            # `margen_bruto_real` (ventas − cogs_teorico), que es base de CONSUMO
            # y solo tiene el costo de lo VENDIDO.
            #
            # LOS DOS TÉRMINOS NO SE VALORIZAN CON LA MISMA REGLA, Y SE DICE
            # `cogs_teorico` usa `_costo_unitario_productos` (línea 53), que NO
            # cae al precio de venta: un producto de reventa sin costo cargado
            # aporta $0 al costo de lo vendido. La fuga usa
            # `conciliacion.costo_unitario`, que SÍ cae al precio de venta
            # marcándolo `estimado`. En `ventas − cogs_teorico + fuga` el MISMO
            # producto puede pesar $0 de un lado y 3,3× de costo del otro.
            #
            # No se unifican a propósito. Bajar la fuga al criterio del COGS
            # pondría en $0 la fuga de todos los productos sin costo —justo los
            # que nadie va a investigar— y cambiaría el valor de meses YA
            # cerrados sin avisar; subir el COGS al criterio de la fuga metería
            # precio de venta adentro de un costo. Se deja la asimetría y se
            # DECLARA en la pantalla, con `pct_venta_costeada` de un lado y
            # `fuga_sin_costo` / `fuga_estimados` del otro.
            "fuga_inventario": fuga["valor"],
            "tiene_fuga_medida": fuga["valor"] is not None,
            "margen_bruto_real_con_fuga": (
                round(tot_ventas - cogs_teorico + fuga["valor"], 2)
                if fuga["valor"] is not None else None),
            "pct_margen_bruto_real_con_fuga": (
                round((tot_ventas - cogs_teorico + fuga["valor"]) / tot_ventas * 100, 1)
                if fuga["valor"] is not None and tot_ventas > 0 else None),
            "periodos_con_fuga_medida": fuga["periodos"],
            # De cuánto del inventario habla esa fuga y cuánto de ella no se pudo
            # poner en pesos —o se puso con una estimación gruesa—: un total chico
            # puede ser un conteo chico, y uno grande puede ser precio de venta
            # disfrazado de costo.
            #
            # La cobertura es PRODUCTO-MES, no productos: son las coberturas de
            # cada cierre sumadas a lo largo del rango, así que con 3 cierres de
            # 97 productos el denominador da 291 y ese local no tiene 291
            # productos. El ratio es correcto; el absoluto solo se puede leer
            # dividido por `fuga_cierres`, y por eso viaja al lado.
            "fuga_cobertura_contados": fuga["contados"],
            "fuga_cobertura_productos": fuga["productos"],
            "fuga_cierres": fuga["cierres"],
            # Estos DOS sí son productos distintos: son una instrucción de
            # trabajo ("cargá el costo de estos"), no una medida del período.
            "fuga_sin_costo": fuga["sin_costo"],
            "fuga_estimados": fuga["estimados"],
            # LOS DOS TÉRMINOS DE `margen_bruto_real_con_fuga` NO MIDEN EL MISMO
            # TRAMO. `margen_bruto_real` es de TODO el rango; la fuga solo de los
            # meses calendario COMPLETOS que ya pasaron por un cierre adentro de
            # ese rango. En "Este año" eso son 8 meses de margen contra 6 o 7 de
            # fuga, y el sesgo es optimista: subdeclara la fuga. Se expone el par
            # para que la pantalla pueda decirlo en vez de dejarlo implícito.
            "fuga_meses": fuga["meses"],
            "fuga_meses_rango": meses_rango,
            # Y NO SOLO EL TRAMO DE MESES: TAMBIÉN EL DE SEDES.
            # `fuga_sedes` son las que vendieron Y midieron; `fuga_sedes_rango` las
            # que vendieron. Declarar solo los meses dejaba pasar el caso de la sede
            # que nunca cierra el conteo: su venta y su COGS entran al margen y su
            # fuga no entra a la resta.
            "fuga_sedes": sedes_medidas,
            "fuga_sedes_rango": sedes_rango,
        },
        "por_mes": [
            {"mes": mes, **_cerrar(vals)}
            for mes, vals in sorted(por_mes.items())
        ],
        "por_sede": [
            # tienda_id None es un gasto CORPORATIVO (arriendo, nómina): fila propia
            # "Corporativo", nunca el literal "Sede None". Va primero y ordena aparte
            # porque None no se puede comparar con un int.
            {"tienda_id": tid,
             "tienda": "Corporativo" if tid is None else tiendas.get(tid, f"Sede {tid}"),
             **_cerrar(vals)}
            for tid, vals in sorted(por_sede.items(),
                                    key=lambda kv: (kv[0] is not None, kv[0] or 0))
        ],
        # PARTICIÓN de `resumen.gastos` por categoría — el desglose que el módulo
        # Costos ya sabía hacer y que el P&L tiraba. Σ total == resumen.gastos.
        "gastos_por_categoria": sorted(
            [{**g, "total": round(g["total"], 2)} for g in por_categoria.values()],
            key=lambda g: (-g["total"], g["clave"]),
        ),
        "gastos_detalle": sorted(
            [{"concepto": c, "total": round(v["total"], 2), "n": v["n"]}
             for c, v in gastos_por_concepto.items()],
            key=lambda x: -x["total"],
        )[:20],
        "nota": (
            "Compras = facturas de proveedor RECIBIDAS en el período (no el consumo real): "
            "un mes donde se stockea fuerte se ve con menos margen del real. "
            "Gastos = egresos de caja manuales + obligaciones devengadas (arriendo, "
            "servicios) + el costo laboral CALCULADO con las horas marcadas y los recargos "
            "de ley; los pagos a proveedor por caja se excluyen porque ya están dentro "
            "de Compras, y un egreso adoptado cuenta como obligación, nunca dos veces. "
            "El mes que tenga una obligación de nómina cargada a mano usa ESA y no el "
            "cálculo, para no contar el sueldo dos veces. El costo calculado es el tiempo "
            "trabajado con sus recargos: no incluye prestaciones, seguridad social ni "
            "auxilio de transporte, así que es un piso, no la liquidación del contador."
        ),
    }


# ─── Margen por producto ──────────────────────────────────────────────────────

def _costos_insumos(db) -> tuple[dict, dict]:
    """Costo por unidad de inventario de cada producto. Prioridad:
      1) Producto.precio_costo (costo OFICIAL fijado a mano) — si existe, MANDA.
      2) promedio ponderado de FacturaCompraItem (lo llena el escaneo / backfill).
    Devuelve (costo por producto, último costo de factura conocido)."""
    # fecha_recibido puede ser NULL (columna agregada por ALTER) → caer a
    # fecha_registro, igual que get_rentabilidad, para no perder esas filas al
    # buscar el "último precio".
    fc_fecha = func.coalesce(FacturaCompra.fecha_recibido, FacturaCompra.fecha_registro)
    rows = (
        db.query(FacturaCompraItem.producto_id, FacturaCompraItem.cantidad,
                 FacturaCompraItem.precio_unitario, fc_fecha, FacturaCompraItem.id)
        .join(FacturaCompra, FacturaCompra.id == FacturaCompraItem.factura_id)
        .filter(FacturaCompraItem.precio_unitario.isnot(None),
                FacturaCompraItem.precio_unitario > 0,
                FacturaCompraItem.cantidad > 0)
        .all()
    )
    acum: dict[int, dict] = defaultdict(lambda: {"plata": 0.0, "cant": 0.0, "ultimo": None, "ultima_clave": None})
    for pid, cant, precio, fecha, item_id in rows:
        a = acum[pid]
        a["plata"] += float(cant) * float(precio)
        a["cant"] += float(cant)
        # Último precio = factura más reciente; desempate ESTABLE por id de ítem
        # (dos facturas del mismo día no dependen del orden arbitrario del SELECT).
        clave = (fecha or datetime.min, item_id or 0)
        if a["ultima_clave"] is None or clave > a["ultima_clave"]:
            a["ultima_clave"], a["ultimo"] = clave, float(precio)
    costo = {pid: a["plata"] / a["cant"] for pid, a in acum.items() if a["cant"] > 0}
    ultimo = {pid: a["ultimo"] for pid, a in acum.items() if a["ultimo"] is not None}
    # El costo oficial a mano pisa el promedio de facturas (lecturas con ruido).
    for pid, pc in db.query(Producto.id, Producto.precio_costo).filter(
            Producto.precio_costo.isnot(None), Producto.precio_costo > 0).all():
        costo[pid] = float(pc)
    return costo, ultimo


def get_rentabilidad_productos(db) -> dict:
    """Margen por producto de venta: precio_venta vs costo de sus insumos.
    - Producto con receta (ProductoInsumo): costo = Σ cantidad_insumo × costo_insumo.
    - Producto sin receta (reventa): costo = su propio costo de compra.
    Los costos salen de las facturas escaneadas; lo que falte se reporta."""
    costo_prom, costo_ult = _costos_insumos(db)
    productos = db.query(Producto).all()
    por_id = {p.id: p for p in productos}

    recetas: dict[int, list] = defaultdict(list)
    for pi in db.query(ProductoInsumo).all():
        recetas[pi.producto_id].append(pi)

    # Desechables (capa de costo aparte, NO descuenta inventario). Se suman al
    # costo de receta para dar el "costo completo" del producto para llevar.
    desechables: dict[int, list] = defaultdict(list)
    for pd in db.query(ProductoDesechable).all():
        desechables[pd.producto_id].append(pd)

    # Ventas últimos 30 días (Colombia) para ordenar por relevancia real.
    d_utc, h_utc = rango_col_utc(hoy_col() - timedelta(days=29), hoy_col())
    ventas_rows = (
        db.query(TicketItem.producto_id,
                 func.coalesce(func.sum(TicketItem.cantidad), 0),
                 func.coalesce(func.sum(TicketItem.subtotal), 0.0))
        .join(Ticket, Ticket.id == TicketItem.ticket_id)
        .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                Ticket.fecha >= d_utc, Ticket.fecha <= h_utc)
        .group_by(TicketItem.producto_id)
        .all()
    )
    ventas_30d = {pid: {"unidades": int(u or 0), "plata": float(pl or 0)}
                  for pid, u, pl in ventas_rows}

    out = []
    for p in productos:
        precio_venta = float(p.precio_venta or 0)
        if precio_venta <= 0:
            continue  # no se vende en el POS: es insumo puro
        ingredientes = recetas.get(p.id)
        faltantes: list[str] = []
        if ingredientes:
            tipo = "receta"
            costo = 0.0
            alguno = False
            for pi in ingredientes:
                c = costo_prom.get(pi.insumo_id)
                if c is None:
                    ins = por_id.get(pi.insumo_id)
                    faltantes.append(ins.nombre if ins else f"insumo {pi.insumo_id}")
                else:
                    costo += float(pi.cantidad) * c
                    alguno = True
            if not alguno:
                costo = None
        else:
            tipo = "reventa"
            um = (p.unidad_medida or "").lower()
            if um in ("gr", "g", "gramos", "ml"):
                # Se vende a granel sin receta: el costo guardado es POR GR/ML y
                # el precio de venta es por porción — compararlos daría un margen
                # sin sentido. Necesita receta para costearse.
                costo = None
                faltantes.append("definí la receta (producto a granel)")
            else:
                costo = costo_prom.get(p.id)
                if costo is None:
                    faltantes.append(p.nombre)

        # Costo OFICIAL del producto (Producto.precio_costo, fijado a mano) MANDA sobre
        # la receta y el promedio de facturas. Sirve para productos COMPRADOS hechos que
        # están mal cargados como receta (ej. omelettes con una receta errónea de "1
        # almojábana"): así el margen sale real sin tener que tocar la receta del POS.
        if p.precio_costo is not None and float(p.precio_costo) > 0:
            costo = float(p.precio_costo)
            faltantes = []

        # Desechables: capa de costo aparte (vaso/tapa/servilleta/azúcar…) que NO
        # descuenta inventario. Se suma al costo de receta para el "costo completo"
        # del producto para llevar. Solo aplica a lo que tenga desechables cargados.
        lista_desech = desechables.get(p.id, [])
        costo_desech = 0.0
        desech_faltan: list[str] = []
        for pd in lista_desech:
            c = costo_prom.get(pd.insumo_id)
            if c is None:
                ins = por_id.get(pd.insumo_id)
                desech_faltan.append(ins.nombre if ins else f"insumo {pd.insumo_id}")
            else:
                costo_desech += float(pd.cantidad) * c
        tiene_desech = bool(lista_desech)
        if costo is not None and tiene_desech:
            costo_full = round(costo + costo_desech, 2)
            margen_full = round(precio_venta - costo_full, 2)
        else:
            costo_full = round(costo, 2) if costo is not None else None
            margen_full = round(precio_venta - costo, 2) if costo is not None else None

        v = ventas_30d.get(p.id, {"unidades": 0, "plata": 0.0})
        completo = costo is not None and not faltantes
        margen = round(precio_venta - costo, 2) if costo is not None else None
        out.append({
            "producto_id": p.id,
            "nombre": p.nombre,
            "categoria": getattr(p.categoria, "value", None) or str(p.categoria or ""),
            "tipo": tipo,
            "precio_venta": round(precio_venta, 2),
            "costo": round(costo, 2) if costo is not None else None,
            "costo_completo": completo,
            "insumos_sin_costo": faltantes,
            "margen": margen,
            "pct_margen": round(margen / precio_venta * 100, 1) if margen is not None else None,
            # Costo completo (receta + desechables para llevar). costo_desechables
            # es None si al producto no se le cargó ningún desechable todavía.
            "costo_desechables": round(costo_desech, 2) if tiene_desech else None,
            "costo_con_desechables": costo_full,
            "desechables_sin_costo": desech_faltan,
            "margen_con_desechables": margen_full,
            "pct_margen_con_desechables": round(margen_full / precio_venta * 100, 1) if margen_full is not None else None,
            "unidades_30d": v["unidades"],
            "venta_30d": round(v["plata"], 2),
        })

    out.sort(key=lambda x: -x["venta_30d"])

    # ── Alertas de costo: el ÚLTIMO precio de factura de un insumo supera en
    # >10% al costo con el que hoy se calculan los márgenes (promedio u oficial).
    # Es la señal temprana de "este insumo está subiendo" — palanca central de
    # la estrategia de ganar por costo. Se dimensiona por la venta afectada.
    usa_insumo: dict[int, set] = defaultdict(set)
    for prod_id, ings in recetas.items():
        for pi in ings:
            usa_insumo[pi.insumo_id].add(prod_id)
    alertas_costo = []
    for iid, ultimo in costo_ult.items():
        usado = costo_prom.get(iid)
        if not usado or usado <= 0 or ultimo <= usado * 1.10:
            continue
        afectados = set(usa_insumo.get(iid, set()))
        ins = por_id.get(iid)
        if ins is not None and float(ins.precio_venta or 0) > 0:
            afectados.add(iid)  # el insumo también se vende directo (reventa)
        if not afectados:
            continue
        venta_afectada = sum(ventas_30d.get(pid, {}).get("plata", 0.0) for pid in afectados)
        alertas_costo.append({
            "insumo_id": iid,
            "nombre": ins.nombre if ins else f"insumo {iid}",
            "unidad_medida": ins.unidad_medida if ins else None,
            "costo_usado": round(usado, 2),
            "costo_ultimo": round(ultimo, 2),
            "pct_suba": round((ultimo / usado - 1) * 100, 1),
            "productos_afectados": sorted(
                (por_id[pid].nombre for pid in afectados if pid in por_id))[:6],
            "venta_30d_afectada": round(venta_afectada, 2),
        })
    alertas_costo.sort(key=lambda a: -a["venta_30d_afectada"])

    from app.services.factura_ocr import facturas_pendientes_de_costos
    from app.services.producto_alias import contar_aliases
    return {
        "productos": out,
        "alertas_costo": alertas_costo[:10],
        "facturas_pendientes_de_costos": facturas_pendientes_de_costos(db),
        # Fase 2 del OCR: cuántos aliases proveedor→producto conoce el sistema
        # (visible en "Salud de datos").
        "aliases_conocidos": contar_aliases(db),
        "nota": (
            "Costo = insumos de la receta × costo promedio de compra (de las facturas "
            "leídas). Si a un producto le faltan costos de insumos, el margen que se "
            "muestra es PARCIAL (mayor al real) hasta que se lean más facturas."
        ),
    }


# ─── Pulso: cómo vamos + comportamiento de compra ────────────────────────────

def get_pulso(db) -> dict:
    """El vistazo de 10 segundos + el comportamiento real de compra:
      - mes en curso vs mes anterior EN LA MISMA VENTANA de días (día 1 → hoy),
        para que la comparación a mitad de mes sea justa;
      - ventas diarias del mes (sparkline);
      - attach real y pares por CO-OCURRENCIA de tickets (últimos 30 días);
      - ventas por hora Colombia (daypart) para ubicar pico y valle;
      - top movers: productos subiendo/bajando vs los 30 días anteriores.
    Ventana fija y ambas sedes: es el pulso global del negocio."""
    hoy = hoy_col()
    ini_act = hoy.replace(day=1)
    fin_ant_mes = ini_act - timedelta(days=1)
    ini_ant = fin_ant_mes.replace(day=1)
    fin_ant = ini_ant.replace(day=min(hoy.day, fin_ant_mes.day))

    def _ventana(desde: date, hasta: date) -> tuple[dict, list]:
        d, h = rango_col_utc(desde, hasta)
        rows = (db.query(Ticket.fecha, Ticket.total)
                .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                        Ticket.fecha >= d, Ticket.fecha <= h).all())
        ventas = sum(float(r[1] or 0) for r in rows)
        n = len(rows)
        return ({"ventas": round(ventas, 2), "tickets": n,
                 "ticket_promedio": round(ventas / n, 0) if n else None}, rows)

    actual, rows_act = _ventana(ini_act, hoy)
    anterior, _ = _ventana(ini_ant, fin_ant)

    por_dia: dict = defaultdict(float)
    for f, t in rows_act:
        por_dia[dia_col(f)] += float(t or 0)
    ventas_diarias = [{"dia": d.isoformat(), "ventas": round(v, 2)}
                      for d, v in sorted(por_dia.items())]

    # ── Comportamiento (30 días): attach y pares reales ──────────────────────
    d30, h30 = rango_col_utc(hoy - timedelta(days=29), hoy)
    info_prod = {p.id: (p.nombre, getattr(p.categoria, "value", None) or str(p.categoria or ""))
                 for p in db.query(Producto).all()}
    items = (db.query(TicketItem.ticket_id, TicketItem.producto_id)
             .join(Ticket, Ticket.id == TicketItem.ticket_id)
             .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                     Ticket.fecha >= d30, Ticket.fecha <= h30).all())
    por_ticket: dict = defaultdict(set)
    for tid, pid in items:
        por_ticket[tid].add(pid)
    # Tickets con combo: la línea apunta al SOMBRA (Combo.producto_id), de
    # categoría inerte. Todo combo incluye bebida + acompañamiento/torta, así
    # que para el attach cuenta como bebida CON pastelería.
    sombras_combo = {pid for (pid,) in db.query(Combo.producto_id).all()}
    con_bebida = con_beb_pasteleria = con_beb_addon = 0
    pares: Counter = Counter()
    for pids in por_ticket.values():
        cats = {info_prod.get(p, ("", ""))[1] for p in pids}
        if pids & sombras_combo:
            cats |= {"bebida", "pasteleria"}
        if "bebida" in cats:
            con_bebida += 1
            if "pasteleria" in cats:
                con_beb_pasteleria += 1
            if "porciones" in cats:
                con_beb_addon += 1
        lp = sorted(pids)
        for i in range(len(lp)):
            for j in range(i + 1, len(lp)):
                pares[(lp[i], lp[j])] += 1
    top_pares = []
    for (a, b), c in pares.most_common(40):
        if c < 3:
            break
        na, ca = info_prod.get(a, (f"#{a}", ""))
        nb, cb = info_prod.get(b, (f"#{b}", ""))
        top_pares.append({"a": na, "a_id": a, "a_cat": ca,
                          "b": nb, "b_id": b, "b_cat": cb, "veces": c})
        if len(top_pares) >= 12:
            break
    attach = {
        "tickets_con_bebida": con_bebida,
        "pct_bebida_con_pasteleria": round(con_beb_pasteleria / con_bebida * 100, 1) if con_bebida else None,
        "pct_bebida_con_addon": round(con_beb_addon / con_bebida * 100, 1) if con_bebida else None,
    }

    # ── Daypart: por hora Colombia (30 días) ─────────────────────────────────
    rows30 = (db.query(Ticket.fecha, Ticket.total)
              .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                      Ticket.fecha >= d30, Ticket.fecha <= h30).all())
    horas: dict = defaultdict(lambda: {"tickets": 0, "ventas": 0.0})
    for f, t in rows30:
        e = horas[hora_col(f)]
        e["tickets"] += 1
        e["ventas"] += float(t or 0)
    daypart = [{"hora": h, "tickets": v["tickets"], "ventas": round(v["ventas"], 2)}
               for h, v in sorted(horas.items())]

    # ── Top movers: 30 días vs los 30 anteriores ─────────────────────────────
    def _ventas_prod(desde: date, hasta: date) -> dict:
        d, h = rango_col_utc(desde, hasta)
        rows = (db.query(TicketItem.producto_id,
                         func.coalesce(func.sum(TicketItem.cantidad), 0),
                         func.coalesce(func.sum(TicketItem.subtotal), 0.0))
                .join(Ticket, Ticket.id == TicketItem.ticket_id)
                .filter(Ticket.estado.notin_(ESTADOS_ANULADOS),
                        Ticket.fecha >= d, Ticket.fecha <= h)
                .group_by(TicketItem.producto_id).all())
        return {pid: (int(u or 0), float(v or 0)) for pid, u, v in rows}

    act30 = _ventas_prod(hoy - timedelta(days=29), hoy)
    ant30 = _ventas_prod(hoy - timedelta(days=59), hoy - timedelta(days=30))
    movers = []
    for pid in set(act30) | set(ant30):
        ua, va = act30.get(pid, (0, 0.0))
        ub, vb = ant30.get(pid, (0, 0.0))
        dv = va - vb
        if abs(dv) < 30000:  # ruido: cambios menores a $30k/mes no son señal
            continue
        movers.append({"producto_id": pid,
                       "nombre": info_prod.get(pid, (f"#{pid}", ""))[0],
                       "unidades": ua, "unidades_prev": ub,
                       "venta": round(va, 2), "venta_prev": round(vb, 2),
                       "delta_venta": round(dv, 2)})
    subiendo = sorted((m for m in movers if m["delta_venta"] > 0),
                      key=lambda m: -m["delta_venta"])[:5]
    bajando = sorted((m for m in movers if m["delta_venta"] < 0),
                     key=lambda m: m["delta_venta"])[:5]

    return {
        "mes_actual": {**actual, "desde": ini_act.isoformat(), "hasta": hoy.isoformat()},
        "mes_anterior": {**anterior, "desde": ini_ant.isoformat(), "hasta": fin_ant.isoformat()},
        "ventas_diarias": ventas_diarias,
        "attach": attach,
        "top_pares": top_pares,
        "daypart": daypart,
        "top_movers": {"subiendo": subiendo, "bajando": bajando},
        "nota": ("Comparación mes en curso vs mes anterior en la MISMA ventana de días. "
                 "Attach, pares, daypart y movers usan los últimos 30 días, ambas sedes."),
    }


def get_attach_producto(db, producto_id: int, dias: int = 30) -> dict:
    """Attach REAL de un producto: en cuántos tickets aparece, con qué se vende
    junto y en qué proporción sale acompañado de bebida.

    Existe porque el `top_pares` del pulso se queda con las 12 combinaciones más
    frecuentes de TODA la carta: un par poco frecuente (croissant + americano)
    queda invisible aunque el sistema sí lo calcule. Para decidir un combo hace
    falta el número exacto de ESE par, no el ranking general.

    `tickets_multiples` (2+ unidades del mismo producto en un ticket) es clave para
    combos que venden de a dos: si mucha gente ya se lleva dos, un combo que las
    empaqueta con descuento canibaliza en vez de sumar.
    """
    dias = max(1, min(int(dias or 30), 365))
    hoy = hoy_col()
    d_utc, h_utc = rango_col_utc(hoy - timedelta(days=dias - 1), hoy)

    prod = db.query(Producto).filter_by(id=producto_id).first()
    if not prod:
        from fastapi import HTTPException
        raise HTTPException(404, "Producto no encontrado")

    # Los tickets que contienen el producto, como SUBCONSULTA (no como lista de IDs):
    # un producto muy vendido en una ventana larga da miles de tickets y una lista
    # enlazada revienta el tope de variables de SQLite.
    sub = (db.query(TicketItem.ticket_id)
           .join(Ticket, Ticket.id == TicketItem.ticket_id)
           .filter(TicketItem.producto_id == producto_id,
                   Ticket.estado.notin_(ESTADOS_ANULADOS),
                   Ticket.fecha >= d_utc, Ticket.fecha <= h_utc)
           .distinct().subquery())

    filas = (db.query(TicketItem.ticket_id, TicketItem.producto_id, TicketItem.cantidad)
             .filter(TicketItem.ticket_id.in_(db.query(sub.c.ticket_id))).all())
    por_ticket: dict = defaultdict(lambda: defaultdict(float))
    for tid, pid, cant in filas:
        por_ticket[tid][pid] += float(cant or 0)

    if not por_ticket:
        return {"producto": {"id": prod.id, "nombre": prod.nombre,
                             "categoria": getattr(prod.categoria, "value", None) or str(prod.categoria or "")},
                "dias": dias, "tickets": 0, "unidades": 0, "tickets_multiples": 0,
                "con_bebida": 0, "pct_con_bebida": None, "sin_bebida": 0,
                "por_categoria": {}, "pares": []}

    info = {p.id: (p.nombre, getattr(p.categoria, "value", None) or str(p.categoria or ""))
            for p in db.query(Producto).all()}

    unidades = 0.0
    multiples = 0
    con_bebida = 0
    cats: Counter = Counter()
    pares: Counter = Counter()
    for pids in por_ticket.values():
        propia = pids.get(producto_id, 0)
        unidades += propia
        if propia >= 2:
            multiples += 1
        acompanantes = [p for p in pids if p != producto_id]
        cats_ticket = {info.get(p, ("", ""))[1] for p in acompanantes}
        if "bebida" in cats_ticket:
            con_bebida += 1
        for c in cats_ticket:
            if c:
                cats[c] += 1
        for p in acompanantes:
            pares[p] += 1

    n = len(por_ticket)
    return {
        "producto": {"id": prod.id, "nombre": prod.nombre,
                     "categoria": getattr(prod.categoria, "value", None) or str(prod.categoria or "")},
        "dias": dias,
        "tickets": n,
        "unidades": round(unidades, 2),
        "tickets_multiples": multiples,
        "con_bebida": con_bebida,
        "pct_con_bebida": round(con_bebida / n * 100, 1) if n else None,
        "sin_bebida": n - con_bebida,
        "por_categoria": {c: v for c, v in cats.most_common()},
        "pares": [{"producto_id": p, "nombre": info.get(p, (f"#{p}", ""))[0],
                   "categoria": info.get(p, ("", ""))[1], "veces": v,
                   "pct": round(v / n * 100, 1)}
                  for p, v in pares.most_common()],
    }
