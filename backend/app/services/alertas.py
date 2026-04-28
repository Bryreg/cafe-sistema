"""Etapa 4: Motor de alertas inteligentes — detecta patrones anómalos."""
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from collections import defaultdict
from app.models.models import (
    CajaTurno, EntregaTurno, Inventario, Merma,
    MovimientoInventario, VentaDiaria, EstadoTurnoEnum, Usuario,
)


def get_alertas_inteligentes(db: Session, tienda_id: int) -> dict:
    alertas = []
    ahora = datetime.utcnow()
    hace_7_dias = ahora - timedelta(days=7)
    hace_30_dias = ahora - timedelta(days=30)

    # ----------------------------------------------------------------
    # 1. Turno abierto demasiado tiempo (>16h)
    # ----------------------------------------------------------------
    turno_abierto = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto,
    ).first()

    if turno_abierto:
        horas = (ahora - turno_abierto.fecha_apertura).total_seconds() / 3600
        if horas > 16:
            alertas.append({
                "tipo": "turno_largo",
                "nivel": "critico",
                "mensaje": f"Turno lleva {horas:.0f}h abierto sin cierre (turno #{turno_abierto.id})",
                "referencia_id": turno_abierto.id,
            })
        elif turno_abierto.tiene_conteo_apertura:
            # Sin cuadre de llegada en más de 8h
            ultima = db.query(EntregaTurno).filter(
                EntregaTurno.turno_id == turno_abierto.id
            ).order_by(EntregaTurno.fecha_hora.desc()).first()
            ref = ultima.fecha_hora if ultima else turno_abierto.fecha_apertura
            h_sin = (ahora - ref).total_seconds() / 3600
            if h_sin > 8:
                alertas.append({
                    "tipo": "sin_cuadre_llegada",
                    "nivel": "advertencia",
                    "mensaje": f"Sin cuadre de llegada hace {h_sin:.0f}h en el turno activo",
                    "referencia_id": turno_abierto.id,
                })

    # ----------------------------------------------------------------
    # 2. Baristas con diferencias repetidas en 30 días (≥3 turnos)
    # ----------------------------------------------------------------
    turnos_diff = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.cerrado,
        CajaTurno.diferencia_cierre != 0,
        CajaTurno.diferencia_cierre.isnot(None),
        CajaTurno.fecha_cierre >= hace_30_dias,
    ).all()

    diffs_por_usuario: dict = defaultdict(list)
    for t in turnos_diff:
        if t.usuario_apertura_id:
            diffs_por_usuario[t.usuario_apertura_id].append(t.diferencia_cierre or 0)

    for uid, diffs in diffs_por_usuario.items():
        if len(diffs) >= 3:
            u = db.query(Usuario).filter(Usuario.id == uid).first()
            nombre = u.nombre if u else f"Usuario {uid}"
            prom = sum(diffs) / len(diffs)
            alertas.append({
                "tipo": "diferencias_repetidas",
                "nivel": "advertencia",
                "mensaje": (
                    f"{nombre}: {len(diffs)} turnos con diferencia en 30 días "
                    f"(promedio ${prom:,.0f})"
                ),
                "referencia_id": uid,
            })

    # ----------------------------------------------------------------
    # 3. Mermas anómalas (>50% más que semana anterior para mismo producto)
    # ----------------------------------------------------------------
    mermas_esta = (
        db.query(Merma.producto_id, func.sum(Merma.cantidad).label("total"))
        .filter(Merma.tienda_id == tienda_id, Merma.fecha_registro >= hace_7_dias)
        .group_by(Merma.producto_id)
        .all()
    )
    mermas_ant = (
        db.query(Merma.producto_id, func.sum(Merma.cantidad).label("total"))
        .filter(
            Merma.tienda_id == tienda_id,
            Merma.fecha_registro >= ahora - timedelta(days=14),
            Merma.fecha_registro < hace_7_dias,
        )
        .group_by(Merma.producto_id)
        .all()
    )
    ant_map = {r.producto_id: r.total for r in mermas_ant}

    for row in mermas_esta:
        ant = ant_map.get(row.producto_id, 0) or 0
        if ant > 0 and row.total > ant * 1.5:
            inv = db.query(Inventario).filter(
                Inventario.producto_id == row.producto_id,
                Inventario.tienda_id == tienda_id,
            ).first()
            nombre_p = inv.producto.nombre if inv else f"Producto {row.producto_id}"
            alertas.append({
                "tipo": "merma_anormal",
                "nivel": "advertencia",
                "mensaje": (
                    f"Merma de {nombre_p} esta semana ({row.total:.1f}) es "
                    f">50% mayor que semana anterior ({ant:.1f})"
                ),
                "referencia_id": row.producto_id,
            })

    # ----------------------------------------------------------------
    # 4. Inventario crítico sin reabastecimiento en 7 días
    # ----------------------------------------------------------------
    criticos = db.query(Inventario).filter(
        Inventario.tienda_id == tienda_id,
        Inventario.stock_actual <= Inventario.stock_minimo,
    ).all()

    for item in criticos:
        ultimo_mov = db.query(MovimientoInventario).filter(
            MovimientoInventario.producto_id == item.producto_id,
            MovimientoInventario.tienda_id == tienda_id,
            MovimientoInventario.tipo == "entrada",
            MovimientoInventario.fecha >= hace_7_dias,
        ).first()
        if not ultimo_mov:
            alertas.append({
                "tipo": "stock_critico_recurrente",
                "nivel": "critico",
                "mensaje": (
                    f"{item.producto.nombre}: stock crítico "
                    f"({item.stock_actual} {item.producto.unidad_medida}) "
                    f"sin reabastecimiento en 7 días"
                ),
                "referencia_id": item.producto_id,
            })

    # ----------------------------------------------------------------
    # 5. Caída de ventas (esta semana vs anterior >30%)
    # ----------------------------------------------------------------
    ventas_esta = db.query(func.sum(VentaDiaria.venta_total)).filter(
        VentaDiaria.tienda_id == tienda_id,
        VentaDiaria.fecha_registro >= hace_7_dias,
    ).scalar() or 0

    ventas_ant = db.query(func.sum(VentaDiaria.venta_total)).filter(
        VentaDiaria.tienda_id == tienda_id,
        VentaDiaria.fecha_registro >= ahora - timedelta(days=14),
        VentaDiaria.fecha_registro < hace_7_dias,
    ).scalar() or 0

    if ventas_ant > 0 and ventas_esta < ventas_ant * 0.7:
        caida = (1 - ventas_esta / ventas_ant) * 100
        alertas.append({
            "tipo": "caida_ventas",
            "nivel": "advertencia",
            "mensaje": (
                f"Ventas esta semana (${ventas_esta:,.0f}) cayeron "
                f"{caida:.0f}% vs semana anterior (${ventas_ant:,.0f})"
            ),
            "referencia_id": None,
        })

    return {"alertas": alertas, "total": len(alertas)}
