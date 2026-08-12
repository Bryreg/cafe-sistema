import math
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload
from app.models.models import (
    Inventario, MovimientoInventario, TipoMovInvEnum,
    SolicitudPedido, SolicitudPedidoItem, EstadoSolicitudEnum,
    FacturaCompra, FacturaCompraItem,
)
from app.services import preparables as preparables_svc


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


def sugerencia_pedido(db: Session, tienda_id: int) -> dict:
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

    # Productos que el barista marcó como urgentes (solicitudes pendientes)
    barista_alerto: set[int] = set(
        item.producto_id
        for item in db.query(SolicitudPedidoItem)
        .join(SolicitudPedido)
        .filter(
            SolicitudPedido.tienda_id == tienda_id,
            SolicitudPedido.estado == EstadoSolicitudEnum.pendiente,
        )
        .all()
    )

    inventarios = (
        db.query(Inventario)
        .options(joinedload(Inventario.producto))   # evita N+1 al leer inv.producto en el loop
        .filter(Inventario.tienda_id == tienda_id)
        .all()
    )

    # Proveedor por historial de compras: fallback cuando no hay asignación manual
    prov_compras = _proveedores_por_compras(db)

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
        consumo_diario = round(salidas_por_prod.get(p.id, 0.0) / DIAS_ANALISIS, 3)

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
            # Manual manda; si no hay, el proveedor de la última compra (Recibir)
            "proveedor": p.proveedor or prov_compras.get(p.id),
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
    _orden = {"agotado": 0, "urgente": 1, "pronto": 2, "bajo": 3, "ok": 4}
    items.sort(key=lambda x: (_orden.get(x["estado"], 9), x["nombre"]))

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
    _orden_r = {"agotado": 0, "urgente": 1, "pronto": 2, "bajo": 3, "ok": 4}
    for g in grupos.values():
        peor = min(g["productos"], key=lambda x: _orden_r.get(x["estado"], 9))
        g["estado_resumen"] = peor["estado"]

    grupos_lista = sorted(
        grupos.values(),
        key=lambda g: _orden_r.get(g["estado_resumen"], 9),
    )

    return {
        "grupos_fijos": grupos_lista,
        "insumos_generales": generales,
        "total_urgentes": sum(1 for i in items if i["estado"] in ("agotado", "urgente")),
        "total_pronto": sum(1 for i in items if i["estado"] == "pronto"),
        "total_bajo": sum(1 for i in items if i["estado"] == "bajo"),
        "total_ok": sum(1 for i in items if i["estado"] == "ok"),
    }
