import math
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.models import (
    Inventario, MovimientoInventario, TipoMovInvEnum,
    SolicitudPedido, SolicitudPedidoItem, EstadoSolicitudEnum,
)

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
        .filter(Inventario.tienda_id == tienda_id)
        .all()
    )

    items = []
    for inv in inventarios:
        p = inv.producto
        if not p.controla_stock:
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

        items.append({
            "producto_id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "unidad": p.unidad_medida,
            "proveedor": p.proveedor,
            "lead_time_dias": lead_time,
            "stock_actual": round(stock, 1),
            "stock_minimo": round(inv.stock_minimo, 1),
            "stock_ideal": round(inv.stock_ideal or 0, 1),
            "stock_critico": round(inv.stock_critico or 0, 1),
            "consumo_diario": consumo_diario,
            "dias_restantes": dias_restantes,
            "estado": estado,
            "cantidad_sugerida": cantidad_sugerida,
            "barista_alerto": p.id in barista_alerto,
        })

    # Orden global: agotado → urgente → pronto → bajo → ok, luego alfabético
    _orden = {"agotado": 0, "urgente": 1, "pronto": 2, "bajo": 3, "ok": 4}
    items.sort(key=lambda x: (_orden.get(x["estado"], 9), x["nombre"]))

    # Agrupar proveedores fijos vs. insumos generales
    grupos: dict[str, dict] = {}
    generales: list[dict] = []

    for item in items:
        prov = item["proveedor"]
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
