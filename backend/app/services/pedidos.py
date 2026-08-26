import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from app.models.models import (
    Inventario, MovimientoInventario, TipoMovInvEnum,
    SolicitudPedido, SolicitudPedidoItem, EstadoSolicitudEnum,
    FacturaCompra, FacturaCompraItem, Producto,
    ORIGEN_ADMIN, ORIGEN_KIOSKO,
)
from app.services import preparables as preparables_svc
from app.services import consumo_ventas
from app.services.producto_alias import normalizar_alias
from app.core.tz import fin_dia_col_utc, hoy_col, inicio_dia_col_utc


def _proveedores_por_compras(db: Session) -> dict[int, str]:
    """Último proveedor que facturó cada producto — lo que las baristas registran
    al Recibir. Sirve de fallback cuando el producto no tiene proveedor asignado
    a mano: los pedidos se agrupan con los MISMOS proveedores de las compras."""
    rows = (
        db.query(FacturaCompraItem.producto_id, FacturaCompra.proveedor)
        .join(FacturaCompra, FacturaCompra.id == FacturaCompraItem.factura_id)
        .order_by(FacturaCompra.fecha_recibido.asc(), FacturaCompra.id.asc())
        .all()
    )
    out: dict[int, str] = {}
    for pid, prov in rows:      # asc: la última escritura = la compra más reciente
        if prov and prov.strip():
            out[pid] = prov.strip()
    return out

# Días de historial para calcular consumo promedio
DIAS_ANALISIS = 14

# Urgencia, de peor a mejor. Una sola tabla para ordenar items y grupos.
_ORDEN_ESTADO = {"agotado": 0, "urgente": 1, "pronto": 2, "bajo": 3, "ok": 4}

# Colchón de días de stock según velocidad de entrega
_COLCHON = {1: 4, 2: 7}   # lead_time -> días extra
_COLCHON_DEFAULT = 14       # para lead_time >= 3


def _dias_objetivo(lead_time: int) -> int:
    return lead_time + _COLCHON.get(lead_time, _COLCHON_DEFAULT)


def _estado(stock: float, consumo_diario: float, lead_time: int,
            stock_minimo: float) -> str:
    if stock <= 0:
        return "agotado"
    if consumo_diario > 0:
        dias_rest = stock / consumo_diario
        if dias_rest <= lead_time:
            return "urgente"
        if dias_rest <= lead_time * 3:
            return "pronto"
    # Sin datos de consumo → usar stock_minimo como fallback
    if stock <= stock_minimo:
        return "bajo"
    return "ok"


def _items_base(db: Session, tienda_id: int) -> tuple[list[dict], dict[int, float]]:
    """UNA sola fórmula para todo el módulo: el inventario GESTIONADO de la sede
    con su consumo, su estado y su `cantidad_sugerida`.

    La extracción no es cosmética: `sugerencia_pedido` y `catalogo_proveedores`
    tienen que decir el MISMO número para el mismo producto. Cuando la cuenta
    vive dos veces, el día que una cambia la otra empieza a mentir — que es
    exactamente la clase de bug (dos números para lo mismo) que este módulo ya
    tenía en la cabecera de sus grupos.

    Devuelve (items ordenados por urgencia, rendimiento de los preparables).
    """
    cutoff = datetime.utcnow() - timedelta(days=DIAS_ANALISIS)

    # Salidas de los últimos DIAS_ANALISIS días
    salidas = (
        db.query(MovimientoInventario)
        .filter(
            MovimientoInventario.tienda_id == tienda_id,
            MovimientoInventario.tipo == TipoMovInvEnum.salida,
            MovimientoInventario.fecha >= cutoff,
        )
        .all()
    )
    salidas_por_prod: dict[int, float] = defaultdict(float)
    for s in salidas:
        salidas_por_prod[s.producto_id] += s.cantidad

    # El consumo aprendido de las VENTAS reales (histórico por día de semana). Se
    # calcula una sola vez para toda la sede; el llamado por-producto es un lookup.
    # Ver `consumo_ventas`: por qué venta y no solo salidas, y por qué la mediana.
    ventas_rate = consumo_ventas.tasa_diaria_por_producto(db, tienda_id, hoy_col())

    # Productos que el barista marcó como urgentes (solicitudes pendientes).
    # El filtro por origen es redundante HOY —el pedido del dueño nace aprobado y
    # nunca está pendiente— y está igual: el campo se llama «barista_alertó» y
    # tiene que seguir siendo cierto aunque mañana alguien cambie el estado con
    # el que nace un pedido del dueño.
    barista_alerto: set[int] = set(
        item.producto_id
        for item in db.query(SolicitudPedidoItem)
        .join(SolicitudPedido)
        .filter(
            SolicitudPedido.tienda_id == tienda_id,
            SolicitudPedido.estado == EstadoSolicitudEnum.pendiente,
            func.coalesce(SolicitudPedido.origen, ORIGEN_KIOSKO) != ORIGEN_ADMIN,
        )
        .all()
    )

    inventarios = (
        db.query(Inventario)
        .options(joinedload(Inventario.producto))   # evita N+1 al leer inv.producto en el loop
        .filter(Inventario.tienda_id == tienda_id)
        .all()
    )

    # Lo que se PREPARA en la barra (mezcla de granizado, almíbar) no se compra:
    # su necesidad es igual de real y la cuenta de consumo sirve igual, pero el
    # verbo es otro. Ver `services/preparables.py`. La tabla de rendimientos tiene
    # una entrada por preparable (0.0 si no está cargado), así que sus claves SON
    # el conjunto de preparables: una sola consulta, no dos.
    rendimientos = preparables_svc.rendimiento_por_tanda(db)

    items = []
    for inv in inventarios:
        p = inv.producto
        # Solo inventario GESTIONADO: controla stock Y está en el conteo. Si no se
        # cuenta, su stock no es confiable y sugerir pedidos/urgencias con él es ruido
        # (84 filas viejas fuera del conteo inflaban la alarma de "urgente").
        if not p.controla_stock or p.incluir_en_conteo is False:
            continue

        stock = inv.stock_actual
        lead_time = p.lead_time_dias or 2
        # El consumo es lo que dice la VENTA real (histórico por día de semana),
        # pero NUNCA por debajo de lo que físicamente salió del estante en 14 días
        # —mermas, preparación, correcciones—: así no se subestima ni se queda sin
        # stock. Sin ventas en la ventana, `ventas_rate` no lo trae y manda la salida
        # (comportamiento idéntico al de antes para un producto que no se vende por POS).
        consumo_salidas = salidas_por_prod.get(p.id, 0.0) / DIAS_ANALISIS
        consumo_diario = round(max(ventas_rate.get(p.id, 0.0), consumo_salidas), 3)

        dias_restantes: float | None = None
        if consumo_diario > 0:
            dias_restantes = round(stock / consumo_diario, 1)

        estado = _estado(stock, consumo_diario, lead_time, inv.stock_minimo)

        # Cantidad sugerida: cubrir dias_objetivo desde hoy
        if consumo_diario > 0:
            objetivo = consumo_diario * _dias_objetivo(lead_time)
            cantidad_sugerida = max(0, math.ceil(objetivo - stock))
        else:
            # Fallback: reponer hasta el doble del mínimo
            cantidad_sugerida = max(0, math.ceil(inv.stock_minimo * 2 - stock))

        # La CANTIDAD no cambia por ser preparable: la misma matemática de consumo
        # dice cuánto falta reponer. Lo que cambia es la acción y la unidad en que
        # se lee — «reponer 51.000 gr» y, si el rendimiento está cargado, cuántas
        # TANDAS son. Sin rendimiento no hay factor de conversión y no se inventa:
        # los gramos por sí solos ya son honestos.
        es_preparable = p.id in rendimientos
        rinde = rendimientos.get(p.id, 0.0)
        tandas_sugeridas = None
        if es_preparable and rinde > 0 and cantidad_sugerida > 0:
            tandas_sugeridas = math.ceil(cantidad_sugerida / rinde)

        items.append({
            "producto_id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "unidad": p.unidad_medida,
            # Lo que el dueño asignó A MANO, crudo. La fusión con lo aprendido de
            # las facturas la hace cada consumidor: `sugerencia_pedido` con un
            # fallback plano, `catalogo_proveedores` con jerarquía explícita.
            "proveedor_manual": (p.proveedor or "").strip() or None,
            # Gr/ml que trae UN empaque comercial. None cuando nadie lo cargó:
            # sin este número no hay forma honesta de hablar en «bolsas».
            "contenido_por_empaque": (
                float(p.contenido_por_empaque) if p.contenido_por_empaque else None
            ),
            "lead_time_dias": lead_time,
            "stock_actual": round(stock, 1),
            "stock_minimo": round(inv.stock_minimo, 1),
            "stock_ideal": round(inv.stock_ideal or 0, 1),
            "stock_critico": round(inv.stock_critico or 0, 1),
            "consumo_diario": consumo_diario,
            "dias_restantes": dias_restantes,
            "estado": estado,
            "cantidad_sugerida": cantidad_sugerida,
            # Qué hacer con esa cantidad. "comprar" es lo de siempre; "preparar"
            # es el producto que se arma con receta y que ningún proveedor vende.
            "accion": "preparar" if es_preparable else "comprar",
            "tandas_sugeridas": tandas_sugeridas,
            "rendimiento_tanda": rinde if (es_preparable and rinde > 0) else None,
            "barista_alerto": p.id in barista_alerto,
            "fraccionable": bool(p.fraccionable),
            "envase": p.envase,
        })

    # Orden global: agotado → urgente → pronto → bajo → ok, luego alfabético
    items.sort(key=lambda x: (_ORDEN_ESTADO.get(x["estado"], 9), x["nombre"]))
    return items, rendimientos


def sugerencia_pedido(db: Session, tienda_id: int) -> dict:
    items, _ = _items_base(db, tienda_id)

    # Proveedor por historial de compras: fallback cuando no hay asignación manual
    prov_compras = _proveedores_por_compras(db)
    for item in items:
        # Manual manda; si no hay, el proveedor de la última compra (Recibir)
        item["proveedor"] = item["proveedor_manual"] or prov_compras.get(item["producto_id"])

    # Agrupar proveedores fijos vs. insumos generales
    grupos: dict[str, dict] = {}
    generales: list[dict] = []

    for item in items:
        # Un grupo de proveedor ES una lista de compra: se abre por teléfono y se
        # copia a WhatsApp. Un preparable no entra ahí ni con proveedor cargado.
        # Puede tener uno por dos caminos —el campo `Producto.proveedor` escrito a
        # mano y el fallback `_proveedores_por_compras`, que lo toma de la última
        # factura que lo incluyó— y ninguno de los dos lo vuelve comprable.
        prov = item["proveedor"] if item["accion"] == "comprar" else None
        if prov:
            if prov not in grupos:
                grupos[prov] = {
                    "proveedor": prov,
                    "lead_time_dias": item["lead_time_dias"],
                    "alerta_mediodia": item["lead_time_dias"] <= 1,
                    "productos": [],
                    "estado_resumen": "ok",
                }
            grupos[prov]["productos"].append(item)
        else:
            generales.append(item)

    # Estado resumen por grupo proveedor
    for g in grupos.values():
        peor = min(g["productos"], key=lambda x: _ORDEN_ESTADO.get(x["estado"], 9))
        g["estado_resumen"] = peor["estado"]

    grupos_lista = sorted(
        grupos.values(),
        key=lambda g: _ORDEN_ESTADO.get(g["estado_resumen"], 9),
    )

    return {
        "grupos_fijos": grupos_lista,
        "insumos_generales": generales,
        "total_urgentes": sum(1 for i in items if i["estado"] in ("agotado", "urgente")),
        "total_pronto": sum(1 for i in items if i["estado"] == "pronto"),
        "total_bajo": sum(1 for i in items if i["estado"] == "bajo"),
        "total_ok": sum(1 for i in items if i["estado"] == "ok"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# El catálogo APRENDIDO de proveedores
# ═══════════════════════════════════════════════════════════════════════════════
#
# Cada factura que entra por el escáner enseña quién trajo qué, cuándo y a cuánto.
# Ese saber vivía enterrado en `facturas_compra_items` y salía por un solo agujero:
# un dict producto→último proveedor. Acá se lee entero.
#
# DOS FUENTES, UNA JERARQUÍA:
#
#   1. `Producto.proveedor` — la palabra del dueño. Marca al TITULAR: a quién se
#      le pide ese producto por defecto. Es GLOBAL (la columna no tiene sede).
#   2. historial de facturas — lo que el sistema aprendió solo. Mete al producto
#      en el catálogo del proveedor que lo trajo, con precio, fecha y frecuencia.
#
# Las dos suman: un producto que vino de dos proveedores aparece en los DOS
# catálogos con SUS números, y solo uno lo tiene como titular. La asignación
# manual gana siempre; sin ella, gana la factura más reciente.
#
# POR QUÉ EL APRENDIZAJE ES POR SEDE: una factura se registra en una sede y es la
# única evidencia de que ese proveedor le entrega ahí. Colgarle a Vida el
# proveedor de una factura de Palmetto era un bug confirmado del módulo viejo.
# Pero el saber no se tira: el producto huérfano viaja con `visto_en_otra_sede`,
# que la pantalla ofrece como asignación de un toque. La asignación manual, en
# cambio, sí cruza sedes — es una decisión, no una inferencia.


def _clave_proveedor(nombre) -> str:
    """«Lacteos Andina», «LÁCTEOS ANDINA» y «lacteos  andina» son el mismo
    teléfono. Se agrupan por la MISMA normalización que usan los aliases de
    factura (NFKD sin tildes, espacios colapsados, MAYÚSCULAS) — reusada, no
    copiada: el día que cambie, cambia en un solo lugar."""
    return normalizar_alias(nombre)


def _historial_compras(db: Session, tienda_id: int) -> dict:
    """Todo lo que las facturas enseñaron, en UNA consulta (el backend corre en
    Render free: nada de N+1). Devuelve, ya agregado en memoria:

      pares      (clave_prov, producto_id) → veces, último precio, última compra
      grafias    clave_prov → cómo se escribió el nombre y cuántas veces
      fechas     clave_prov → fechas de sus facturas EN ESTA SEDE (cadencia)
      demora     clave_prov → [días entre registrar y recibir], cuando los hay
      otra_sede  producto_id → clave del último proveedor que lo trajo en OTRA sede
    """
    # fecha_recibido es nullable (columna agregada por ALTER). En Postgres un
    # ORDER BY con NULLs los manda al final y una factura vieja sin fecha ganaba
    # como «la más reciente». Se cae a fecha_registro, igual que rentabilidad.
    fc_fecha = func.coalesce(FacturaCompra.fecha_recibido, FacturaCompra.fecha_registro)
    rows = (
        db.query(
            FacturaCompra.tienda_id, FacturaCompra.proveedor, fc_fecha,
            FacturaCompra.fecha_recibido, FacturaCompra.fecha_registro,
            FacturaCompraItem.producto_id, FacturaCompraItem.precio_unitario,
            FacturaCompraItem.id,
        )
        .join(FacturaCompraItem, FacturaCompra.id == FacturaCompraItem.factura_id)
        .all()
    )

    pares: dict[tuple[str, int], dict] = {}
    grafias: dict[str, Counter] = defaultdict(Counter)
    fechas: dict[str, set] = defaultdict(set)
    demora: dict[str, list] = defaultdict(list)
    otra_sede: dict[int, tuple] = {}
    facturas_vistas: set[tuple[str, int]] = set()

    for (t_id, prov, fecha, recibido, registro, pid, precio, item_id) in rows:
        if not prov or not prov.strip():
            continue
        clave = _clave_proveedor(prov)
        if not clave:
            continue
        grafias[clave][prov.strip()] += 1
        # Desempate ESTABLE por id de ítem: dos facturas del mismo día no pueden
        # depender del orden arbitrario en que el motor devuelva las filas.
        orden = (fecha or datetime.min, item_id or 0)

        if t_id == tienda_id:
            a = pares.setdefault((clave, pid), {
                "veces": 0, "ultimo_precio": None, "ultima_compra": None, "_orden": None,
            })
            a["veces"] += 1
            if a["_orden"] is None or orden > a["_orden"]:
                a["_orden"] = orden
                a["ultima_compra"] = fecha
                a["ultimo_precio"] = float(precio) if precio is not None else None
            if fecha:
                fechas[clave].add(fecha.date())
            # Demora observada: solo cuando la factura se registró ANTES de
            # recibirla (el pedido quedó anotado y después llegó). Registrar al
            # recibir da 0 o negativo y no dice nada del proveedor: no se cuenta.
            marca = (clave, item_id)
            if recibido and registro and recibido > registro and marca not in facturas_vistas:
                facturas_vistas.add(marca)
                demora[clave].append((recibido - registro).total_seconds() / 86400)
        else:
            previo = otra_sede.get(pid)
            if previo is None or orden > previo[1]:
                otra_sede[pid] = (clave, orden)

    return {"pares": pares, "grafias": grafias, "fechas": fechas,
            "demora": demora, "otra_sede": {p: c for p, (c, _) in otra_sede.items()}}


def _promedio_dias_entre(fechas: set) -> float | None:
    """Cada cuánto entrega este proveedor. Con una sola factura no hay cadencia
    que medir y se devuelve None: un promedio de un dato es un invento."""
    if len(fechas) < 2:
        return None
    ordenadas = sorted(fechas)
    saltos = [(b - a).days for a, b in zip(ordenadas, ordenadas[1:])]
    return round(sum(saltos) / len(saltos), 1) if saltos else None


def catalogo_proveedores(db: Session, tienda_id: int) -> dict:
    """Los proveedores REALES de esta sede, cada uno con el catálogo de lo que
    trae, listo para armar el pedido del día."""
    items, rendimientos = _items_base(db, tienda_id)
    base: dict[int, dict] = {i["producto_id"]: i for i in items}
    # Ser preparable es una propiedad del catálogo, no del inventario de la sede:
    # un preparable que no se cuenta acá tampoco se le compra a nadie.
    ids_preparables = set(rendimientos)

    hist = _historial_compras(db, tienda_id)
    pares, grafias = hist["pares"], hist["grafias"]

    # Asignación manual: global, cruda, de TODO el catálogo (no solo del
    # inventario gestionado de esta sede — la columna no tiene sede).
    manual: dict[int, str] = {}
    for pid, prov in (db.query(Producto.id, Producto.proveedor)
                        .filter(Producto.proveedor.isnot(None)).all()):
        if prov and prov.strip():
            manual[pid] = prov.strip()
    for pid, prov in manual.items():
        clave = _clave_proveedor(prov)
        if clave:
            grafias[clave][prov] += 0   # registra la clave sin votar la grafía

    # ── Qué pares (proveedor, producto) existen ──────────────────────────────
    #    De las facturas de ESTA sede + de la asignación manual (que sí cruza).
    #    Un par puede existir por los DOS caminos a la vez (el dueño lo asignó Y
    #    ese proveedor lo facturó): se guardan ambos, no uno pisando al otro.
    miembros: dict[str, set[int]] = defaultdict(set)
    fuentes_par: dict[tuple[str, int], set] = defaultdict(set)
    for (clave, pid) in pares:
        if pid in ids_preparables:
            continue
        miembros[clave].add(pid)
        fuentes_par[(clave, pid)].add("compras")
    for pid, prov in manual.items():
        if pid in ids_preparables:
            continue
        clave = _clave_proveedor(prov)
        if not clave:
            continue
        miembros[clave].add(pid)
        fuentes_par[(clave, pid)].add("manual")

    # ── Quién es el TITULAR de cada producto ─────────────────────────────────
    titular: dict[int, str] = {}
    for pid, prov in manual.items():          # 1) la palabra del dueño manda
        clave = _clave_proveedor(prov)
        if clave and pid not in ids_preparables:
            titular[pid] = clave
    mejor_compra: dict[int, tuple] = {}       # 2) si no, la factura más reciente
    for (clave, pid), a in pares.items():
        if pid in titular or pid in ids_preparables:
            continue
        if pid not in mejor_compra or a["_orden"] > mejor_compra[pid][1]:
            mejor_compra[pid] = (clave, a["_orden"])
    for pid, (clave, _) in mejor_compra.items():
        titular[pid] = clave

    # ── Metadata de los productos que NO están en el inventario de esta sede ──
    faltantes = {pid for pids in miembros.values() for pid in pids} - set(base)
    extra: dict[int, Producto] = {}
    if faltantes:
        for p in db.query(Producto).filter(Producto.id.in_(faltantes)).all():
            # Archivados fuera (misma firma que el listado de inventario): no
            # controla stock + fuera del conteo + sin precio de venta.
            if not p.controla_stock and p.incluir_en_conteo is False and not (p.precio_venta or 0):
                continue
            extra[p.id] = p

    # Grafías escritas a mano por clave, indexadas UNA vez: se consultan por
    # cada proveedor, por cada huérfano y por cada nombre conocido.
    manuales_por_clave: dict[str, set] = defaultdict(set)
    for _pid, _prov in manual.items():
        _c = _clave_proveedor(_prov)
        if _c:
            manuales_por_clave[_c].add(_prov)

    def _nombre_display(clave: str) -> str:
        """La grafía del dueño manda; si no asignó ninguna, la más repetida en
        las facturas. Desempate alfabético para que no baile entre recargas."""
        manuales = sorted(manuales_por_clave.get(clave, ()))
        if manuales:
            return manuales[0]
        votos = grafias.get(clave)
        if votos:
            return sorted(votos.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        return clave

    def _armar_item(clave: str, pid: int) -> dict | None:
        b = base.get(pid)
        p = extra.get(pid)
        if b is None and p is None:
            return None
        compra = pares.get((clave, pid))
        prov_manual = manual.get(pid)
        return {
            "producto_id": pid,
            "nombre": b["nombre"] if b else p.nombre,
            "categoria": b["categoria"] if b else p.categoria.value,
            "unidad": b["unidad"] if b else p.unidad_medida,
            "contenido_por_empaque": (
                b["contenido_por_empaque"] if b else
                (float(p.contenido_por_empaque) if p.contenido_por_empaque else None)
            ),
            # ¿Este producto se cuenta en esta sede? Si no, su stock es None —
            # no cero, que sería afirmar algo que nadie midió.
            "gestionado": b is not None,
            "titular": titular.get(pid) == clave,
            # Con qué autoridad está acá. Si el dueño lo asignó, esa es la que
            # cuenta: manda sobre lo aprendido aunque también lo haya facturado.
            "fuente": "manual" if "manual" in fuentes_par[(clave, pid)] else "compras",
            "proveedor_manual": prov_manual,
            "ultimo_precio": compra["ultimo_precio"] if compra else None,
            "ultima_compra": compra["ultima_compra"] if compra else None,
            "veces_comprado": compra["veces"] if compra else 0,
            "stock_actual": b["stock_actual"] if b else None,
            "stock_minimo": b["stock_minimo"] if b else None,
            "consumo_diario": b["consumo_diario"] if b else 0.0,
            "dias_restantes": b["dias_restantes"] if b else None,
            "estado": b["estado"] if b else None,
            "cantidad_sugerida": b["cantidad_sugerida"] if b else 0,
            "lead_time_dias": b["lead_time_dias"] if b else (p.lead_time_dias or 2),
            "barista_alerto": b["barista_alerto"] if b else False,
            # El único criterio de «va precargado en el pedido». La pantalla
            # cuenta ESTO y manda ESTO: un botón que dice N manda N.
            "necesita": bool(b and b["cantidad_sugerida"] > 0),
            # Está AGOTADO o urgente pero la fórmula dio 0 porque nadie cargó
            # `stock_minimo` ni hay consumo registrado. La cuenta no se toca —es
            # contrato— pero el producto tampoco se esconde: la pantalla lo
            # muestra con el input en cero para que el dueño escriba cuánto.
            # Sin esto, un catálogo entero de tortas en cero se ve como «todo OK».
            "en_alerta_sin_sugerencia": bool(
                b and b["cantidad_sugerida"] <= 0
                and b["estado"] in ("agotado", "urgente")
            ),
        }

    ahora = datetime.utcnow()
    # Lo que YA se le pidió hoy a cada proveedor. Viaja con el catálogo —y no en
    # una segunda llamada— para que la pantalla nunca se dibuje un instante
    # ofreciendo pedir algo que ya se pidió.
    ya_pedido = pedido_del_dia_por_proveedor(db, tienda_id)
    proveedores = []
    for clave, pids in miembros.items():
        productos = [it for it in (_armar_item(clave, pid) for pid in pids) if it]
        if not productos:
            continue
        productos.sort(key=lambda it: (
            not it["necesita"], _ORDEN_ESTADO.get(it["estado"], 9), it["nombre"]))
        # Los contadores del card cuentan lo que el card va a MOSTRAR: solo lo
        # del TITULAR. Un producto que dos proveedores trajeron se precarga en el
        # card de uno —el que manda— y en el otro queda disponible para agregar;
        # contarlo en los dos daría un número que el cuerpo del card no respalda,
        # que es justo la mentira de dos números que este módulo ya tenía.
        necesitan = [it for it in productos if it["necesita"] and it["titular"]]
        # Lo que la pantalla DESTACA: lo que se pide + lo que está en rojo aunque
        # la cuenta haya dado cero. El resumen del card se calcula sobre esto,
        # porque un card que dice OK con un producto agotado adentro miente.
        destacados = necesitan + [
            it for it in productos if it["en_alerta_sin_sugerencia"] and it["titular"]]

        fuentes = set().union(*(fuentes_par[(clave, it["producto_id"])] for it in productos))
        ultimas = [it["ultima_compra"] for it in productos if it["ultima_compra"]]
        ultima = max(ultimas) if ultimas else None
        demoras = hist["demora"].get(clave) or []
        # Lead time del GRUPO: el más corto de sus productos. Es el que aprieta —
        # si algo de este proveedor llega al día siguiente, la llamada tiene hora.
        # (El módulo viejo heredaba el del primer producto que caía en el grupo:
        # con productos mezclados, el chip «antes del mediodía» era lotería.)
        leads = [it["lead_time_dias"] for it in productos] or [2]

        proveedores.append({
            "proveedor": _nombre_display(clave),
            "clave": clave,
            "origen": "ambos" if fuentes == {"manual", "compras"} else fuentes.pop(),
            "productos": productos,
            "n_necesita": len(necesitan),
            "n_en_alerta": len(destacados) - len(necesitan),
            "estado_resumen": min(
                (it["estado"] for it in destacados if it["estado"]),
                key=lambda e: _ORDEN_ESTADO.get(e, 9), default="ok"),
            "lead_time_dias": min(leads),
            # Demora REAL medida entre registrar la factura y recibir la
            # mercancía. Casi siempre None: se registra al recibir. Cuando existe,
            # vale más que el `lead_time_dias` tecleado.
            "lead_time_observado": round(sum(demoras) / len(demoras), 1) if demoras else None,
            "ultima_compra": ultima,
            "dias_desde_ultima": (ahora - ultima).days if ultima else None,
            "cada_dias": _promedio_dias_entre(hist["fechas"].get(clave, set())),
            "total_productos": len(productos),
            # Los pedidos que ya salieron HOY para este proveedor, del más viejo
            # al más nuevo. Lista y no un booleano: pedir dos veces en el día es
            # legítimo, y lo que el dueño necesita ver es QUÉ mandó, no cuántas
            # veces. Vacía cuando todavía no le pidió nada hoy.
            "pedidos_hoy": (ya_pedido.get(clave) or {}).get("pedidos", []),
        })

    proveedores.sort(key=lambda g: (
        _ORDEN_ESTADO.get(g["estado_resumen"], 9), -g["n_necesita"], g["proveedor"]))

    # ── Lo que hay que pedir y no se sabe a quién ────────────────────────────
    con_duenio = set(titular)
    sin_proveedor = []
    for it in items:
        pid = it["producto_id"]
        if pid in con_duenio or pid in ids_preparables:
            continue
        # Entra si hay cuánto pedir O si está en rojo. Filtrar solo por
        # `cantidad_sugerida > 0` dejaba el bucket VACÍO en el caso real del
        # negocio —umbrales en cero— justo cuando más falta hace: un producto
        # agotado y sin dueño es lo primero que hay que resolver.
        en_alerta = it["estado"] in ("agotado", "urgente")
        if it["cantidad_sugerida"] <= 0 and not en_alerta:
            continue
        pista = hist["otra_sede"].get(pid)
        sin_proveedor.append({
            **{k: it[k] for k in (
                "producto_id", "nombre", "categoria", "unidad", "stock_actual",
                "stock_minimo", "consumo_diario", "dias_restantes", "estado",
                "cantidad_sugerida", "lead_time_dias", "barista_alerto",
                "contenido_por_empaque", "proveedor_manual")},
            "gestionado": True,
            "necesita": it["cantidad_sugerida"] > 0,
            "en_alerta_sin_sugerencia": it["cantidad_sugerida"] <= 0 and en_alerta,
            "titular": False,
            "fuente": None,
            "ultimo_precio": None,
            "ultima_compra": None,
            "veces_comprado": 0,
            # En esta sede nadie se lo entregó nunca; en la otra sí. Es una pista
            # para asignarlo de un toque, no una afirmación sobre esta sede.
            "visto_en_otra_sede": _nombre_display(pista) if pista else None,
        })

    # Dos listas porque son dos preguntas. `sin_proveedor` es la de TRABAJO: qué
    # hay que pedir hoy y no se sabe a quién. `sin_asignar` es la de
    # CONFIGURACIÓN: todo lo que todavía no tiene dueño, urja o no — es lo que
    # alimenta la pantalla de asignación, que existe justamente para vaciarla.
    sin_asignar = [
        {k: it[k] for k in ("producto_id", "nombre", "categoria", "unidad", "estado")}
        for it in items
        if it["producto_id"] not in con_duenio
        and it["producto_id"] not in ids_preparables
    ]

    # Lo que se ARMA en la barra. No es de ningún proveedor y no entra a ninguna
    # lista de WhatsApp, pero su necesidad es igual de real: sale por su puerta.
    preparables = [
        {k: it[k] for k in (
            "producto_id", "nombre", "unidad", "estado", "cantidad_sugerida",
            "accion", "tandas_sugeridas", "rendimiento_tanda", "barista_alerto")}
        for it in items
        if it["accion"] == "preparar" and it["cantidad_sugerida"] > 0
    ]

    # Nombres para el datalist de asignación rápida: TODOS los conocidos, también
    # los de la otra sede. Asignar es elegir de lo que ya existe, no teclear otro
    # proveedor nuevo que mañana sea un duplicado con otra grafía.
    conocidos = sorted({_nombre_display(c) for c in grafias if c},
                       key=lambda s: s.lower())

    return {
        "proveedores": proveedores,
        "sin_proveedor": sin_proveedor,
        "sin_asignar": sin_asignar,
        "preparables": preparables,
        "proveedores_conocidos": conocidos,
        "total_urgentes": sum(1 for i in items if i["estado"] in ("agotado", "urgente")),
        "total_pronto": sum(1 for i in items if i["estado"] == "pronto"),
        "total_bajo": sum(1 for i in items if i["estado"] == "bajo"),
        "total_ok": sum(1 for i in items if i["estado"] == "ok"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# El pedido que el dueño MANDA queda escrito
# ═══════════════════════════════════════════════════════════════════════════════
#
# Hasta acá, «Armar pedido» calculaba muy bien qué pedir, armaba el texto y lo
# soltaba en el portapapeles. Ahí terminaba: el pedido se iba por WhatsApp y el
# sistema no se enteraba nunca de que había existido. Por eso la ficha del insumo
# tenía un hueco donde debía ir «pedí» y decía, literalmente, que no lo guardaba.
#
# Sin ese dato no hay forma de contestar la única pregunta que importa cuando
# llega la mercadería: ¿trajeron lo que pedí? Se podía comparar lo que llegó
# contra lo que HACÍA FALTA, que no es lo mismo — hacía falta es un cálculo del
# sistema, el pedido es una decisión del dueño, y la diferencia entre los dos es
# justamente donde vive el criterio de quien compra.
#
# DOS COSAS QUE ESTE MÓDULO NO HACE, A PROPÓSITO:
#
#  · No manda el WhatsApp. Guardar es dejar constancia de lo que el dueño decidió
#    mandar; mandarlo lo sigue haciendo él. Un sistema que dijera «pedido enviado»
#    sin haber enviado nada sería peor que uno que no guarda nada.
#  · No aprueba ni espera aprobación. El dueño ES quien aprueba. La fila nace
#    `aprobada` y con `origen='admin'`, y por eso NO dispara la notificación de
#    kiosko: avisarle al dueño de su propio pedido es ruido.

_VENTANA_ANTIDUPLICADO = timedelta(minutes=5)


def _clave_items(items: list[dict]) -> frozenset:
    """Huella de un pedido: qué productos y cuánto de cada uno."""
    return frozenset(
        (int(i["producto_id"]), round(float(i["cantidad"]), 4)) for i in items
    )


def registrar_pedido(db: Session, tienda_id: int, proveedor: str,
                     items: list[dict], usuario_id: int,
                     nota: str | None = None) -> dict:
    """Deja escrito el pedido que el dueño acaba de mandarle a UN proveedor.

    `items`: [{"producto_id": int, "cantidad": float, "unidad": str|None}]. La
    unidad se guarda porque la cantidad sin unidad no se puede restar contra una
    factura; la pantalla manda siempre la del producto, que es en la que están
    hechas las dos cuentas.

    GUARDA ANTI-DOBLE-TOQUE. Esto corre en una tablet, con un dedo, sobre wifi de
    local: el mismo pedido llega dos veces por un doble toque o por un reintento
    del navegador. Si en los últimos minutos ya se registró un pedido IDÉNTICO
    (mismo proveedor, mismos productos, mismas cantidades) se devuelve ese, sin
    crear el gemelo. No es una regla de negocio —dos pedidos iguales al mismo
    proveedor el mismo día son legítimos con horas de por medio—: es la ventana
    en la que un duplicado solo puede ser un accidente. Duplicar acá no rompe
    nada visible, y esa es la trampa: inflaría «pedí» para siempre y el dueño
    creería que le entregaron de menos.
    """
    prov = (proveedor or "").strip()
    if not prov:
        raise HTTPException(status_code=400, detail="Falta a qué proveedor se le pidió")

    limpios = []
    for i in items or []:
        cant = float(i.get("cantidad") or 0)
        if cant <= 0:
            continue          # una línea en cero no es un pedido, es un input vacío
        limpios.append({
            "producto_id": int(i["producto_id"]),
            "cantidad": cant,
            "unidad": (i.get("unidad") or "").strip() or None,
        })
    if not limpios:
        raise HTTPException(status_code=400, detail="El pedido está vacío: ninguna línea tiene cantidad")

    ids = {i["producto_id"] for i in limpios}
    existentes = {p.id: p for p in db.query(Producto).filter(Producto.id.in_(ids)).all()}
    faltan = ids - set(existentes)
    if faltan:
        raise HTTPException(status_code=400,
                            detail=f"Hay productos que ya no existen: {sorted(faltan)}")

    huella = _clave_items(limpios)
    desde = datetime.utcnow() - _VENTANA_ANTIDUPLICADO
    for previo in (
        db.query(SolicitudPedido)
        .options(joinedload(SolicitudPedido.items))
        .filter(SolicitudPedido.tienda_id == tienda_id,
                SolicitudPedido.origen == ORIGEN_ADMIN,
                SolicitudPedido.fecha_solicitud >= desde)
        .all()
    ):
        if _clave_proveedor(previo.proveedor) != _clave_proveedor(prov):
            continue
        gemelo = frozenset(
            (it.producto_id, round(float(it.cantidad_solicitada), 4)) for it in previo.items)
        if gemelo == huella:
            return _pedido_dict(previo, existentes, duplicado=True)

    ahora = datetime.utcnow()
    pedido = SolicitudPedido(
        tienda_id=tienda_id,
        proveedor=prov,
        origen=ORIGEN_ADMIN,
        nota=(nota or "").strip() or None,
        usuario_id=usuario_id,
        # El dueño no se pide permiso a sí mismo: el pedido nace resuelto para no
        # aparecer como pendiente en la bandeja ni contarse como alerta de barista.
        estado=EstadoSolicitudEnum.aprobada,
        usuario_aprobacion_id=usuario_id,
        fecha_aprobacion=ahora,
        fecha_solicitud=ahora,
    )
    db.add(pedido)
    db.flush()
    for i in limpios:
        db.add(SolicitudPedidoItem(
            solicitud_id=pedido.id,
            producto_id=i["producto_id"],
            cantidad_solicitada=i["cantidad"],
            unidad_solicitada=i["unidad"] or existentes[i["producto_id"]].unidad_medida,
        ))
    db.commit()
    db.refresh(pedido)
    return _pedido_dict(pedido, existentes)


def _pedido_dict(pedido: SolicitudPedido, productos: dict | None = None,
                 duplicado: bool = False) -> dict:
    productos = productos or {}
    return {
        "id": pedido.id,
        "tienda_id": pedido.tienda_id,
        "proveedor": pedido.proveedor,
        "fecha": pedido.fecha_solicitud.isoformat() if pedido.fecha_solicitud else None,
        "nota": pedido.nota,
        "items": [
            {
                "producto_id": it.producto_id,
                "nombre": (productos[it.producto_id].nombre if it.producto_id in productos
                           else (it.producto.nombre if it.producto else "")),
                "cantidad": float(it.cantidad_solicitada or 0),
                "unidad": it.unidad_solicitada or "",
            }
            for it in pedido.items
        ],
        # Se devolvió un pedido que YA estaba: la pantalla lo dice en vez de
        # celebrar un guardado que no ocurrió.
        "ya_estaba": duplicado,
    }


def pedidos_registrados(db: Session, tienda_id: int,
                        desde: datetime | None = None,
                        hasta: datetime | None = None) -> list[dict]:
    """Los pedidos que el dueño mandó, del más reciente al más viejo."""
    q = (
        db.query(SolicitudPedido)
        .options(joinedload(SolicitudPedido.items).joinedload(SolicitudPedidoItem.producto))
        .filter(SolicitudPedido.tienda_id == tienda_id,
                SolicitudPedido.origen == ORIGEN_ADMIN)
    )
    if desde is not None:
        q = q.filter(SolicitudPedido.fecha_solicitud >= desde)
    if hasta is not None:
        q = q.filter(SolicitudPedido.fecha_solicitud <= hasta)
    return [_pedido_dict(p) for p in q.order_by(SolicitudPedido.fecha_solicitud.desc()).all()]


def anular_pedido(db: Session, pedido_id: int, tienda_id: int | None = None) -> dict:
    """Borra un pedido mal registrado (el dedo gordo en la tablet).

    Solo alcanza a los del DUEÑO. Una solicitud de barista no se borra por acá:
    tiene su propio camino —aprobar o rechazar— y ese deja rastro de quién
    decidió. Borrarla desde este botón sería hacer desaparecer el aviso de otra
    persona sin que quede constancia de nada.
    """
    p = (db.query(SolicitudPedido)
         .filter(SolicitudPedido.id == pedido_id).first())
    if not p:
        raise HTTPException(status_code=404, detail="Ese pedido no existe")
    if p.origen != ORIGEN_ADMIN:
        raise HTTPException(status_code=400,
                            detail="Eso es una solicitud del kiosko: se aprueba o se rechaza, no se borra")
    if tienda_id is not None and p.tienda_id != tienda_id:
        raise HTTPException(status_code=404, detail="Ese pedido no es de esta sede")
    resumen = _pedido_dict(p)
    db.delete(p)          # los items caen con él (cascade del modelo)
    db.commit()
    return resumen


def pedido_del_dia_por_proveedor(db: Session, tienda_id: int,
                                 dia: date | None = None) -> dict[str, dict]:
    """Lo ya pedido HOY, indexado por la MISMA clave con la que la pantalla
    agrupa los proveedores (`_clave_proveedor`).

    Sin esto, recargar la pantalla —o abrirla en el celular después de haber
    pedido desde la tablet— borraría la memoria de lo que ya se mandó y el dueño
    lo pediría dos veces. El estado de «ya pedí» no puede vivir solo en la
    pestaña del navegador.
    """
    dia = dia or hoy_col()
    out: dict[str, dict] = {}
    for p in pedidos_registrados(db, tienda_id,
                                 inicio_dia_col_utc(dia), fin_dia_col_utc(dia)):
        clave = _clave_proveedor(p["proveedor"])
        if not clave:
            continue
        # Varios pedidos al mismo proveedor en el día: se muestran todos, porque
        # todos se mandaron. Quedan del más viejo al más nuevo para que se lean
        # en el orden en que salieron.
        g = out.setdefault(clave, {"proveedor": p["proveedor"], "pedidos": []})
        g["pedidos"].insert(0, p)
    return out
