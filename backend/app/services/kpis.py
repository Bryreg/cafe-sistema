"""Etapa 5: Cálculo de KPIs operativos por tienda y período."""
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date
from app.models.models import CajaTurno, VentaDiaria, Merma, EstadoTurnoEnum, Tienda
from app.core.tz import inicio_dia_col_utc, fin_dia_col_utc


def get_kpis(db: Session, tienda_id: int, fecha_desde: date, fecha_hasta: date) -> dict:
    desde = inicio_dia_col_utc(fecha_desde)
    hasta = fin_dia_col_utc(fecha_hasta)

    turnos = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.cerrado,
        CajaTurno.fecha_cierre >= desde,
        CajaTurno.fecha_cierre <= hasta,
    ).all()

    n_turnos = len(turnos)
    n_con_diff_ef = sum(1 for t in turnos if (t.diferencia_cierre or 0) != 0)
    n_con_diff_tarj = sum(1 for t in turnos if (t.diferencia_tarjeta or 0) != 0)
    porcentaje_descuadre = round(n_con_diff_ef / n_turnos * 100, 1) if n_turnos > 0 else 0.0

    # Horas operadas totales
    horas_op = sum(
        (t.fecha_cierre - t.fecha_apertura).total_seconds() / 3600
        for t in turnos if t.fecha_cierre and t.fecha_apertura
    )
    total_ventas = sum(t.total_ventas or 0 for t in turnos)
    ventas_por_hora = round(total_ventas / horas_op, 0) if horas_op > 0 else 0.0

    # Ticket promedio (venta_total / n_registros de venta)
    n_reg_venta = db.query(func.count(VentaDiaria.id)).filter(
        VentaDiaria.tienda_id == tienda_id,
        VentaDiaria.fecha_registro >= desde,
        VentaDiaria.fecha_registro <= hasta,
    ).scalar() or 0
    ticket_promedio = round(total_ventas / n_reg_venta, 0) if n_reg_venta > 0 else 0.0

    # Diferencia promedio (solo turnos con diferencia)
    diffs = [abs(t.diferencia_cierre) for t in turnos if (t.diferencia_cierre or 0) != 0]
    diferencia_promedio = round(sum(diffs) / len(diffs), 0) if diffs else 0.0

    # Mermas del período
    n_mermas = db.query(func.count(Merma.id)).filter(
        Merma.tienda_id == tienda_id,
        Merma.fecha_registro >= desde,
        Merma.fecha_registro <= hasta,
    ).scalar() or 0

    # Tiempos operativos promedio (Etapa 6)
    tiempos_apertura_a_venta = [
        (t.ts_primera_venta - t.ts_conteo_apertura).total_seconds() / 60
        for t in turnos
        if t.ts_primera_venta and t.ts_conteo_apertura
    ]
    tiempo_promedio_apertura_venta = (
        round(sum(tiempos_apertura_a_venta) / len(tiempos_apertura_a_venta), 1)
        if tiempos_apertura_a_venta else None
    )

    duraciones_operativas = [
        (t.fecha_cierre - t.fecha_apertura).total_seconds() / 3600
        for t in turnos if t.fecha_cierre and t.fecha_apertura
    ]
    duracion_promedio_turno = (
        round(sum(duraciones_operativas) / len(duraciones_operativas), 1)
        if duraciones_operativas else None
    )

    return {
        "tienda_id": tienda_id,
        "fecha_desde": str(fecha_desde),
        "fecha_hasta": str(fecha_hasta),
        "n_turnos": n_turnos,
        "porcentaje_descuadre": porcentaje_descuadre,
        "n_turnos_con_diferencia_efectivo": n_con_diff_ef,
        "n_turnos_con_diferencia_tarjeta": n_con_diff_tarj,
        "diferencia_promedio_efectivo": diferencia_promedio,
        "horas_operadas": round(horas_op, 1),
        "total_ventas": round(total_ventas, 0),
        "ventas_por_hora": ventas_por_hora,
        "n_registros_venta": n_reg_venta,
        "ticket_promedio": ticket_promedio,
        "n_mermas": n_mermas,
        "tiempo_promedio_apertura_a_venta_min": tiempo_promedio_apertura_venta,
        "duracion_promedio_turno_horas": duracion_promedio_turno,
    }


def get_comparativo(db: Session) -> list:
    """Etapa 10: KPIs del día actual para todas las tiendas activas."""
    from datetime import date as date_type
    hoy = date_type.today()
    tiendas = db.query(Tienda).filter(Tienda.activa == True).all()
    result = []
    for t in tiendas:
        kpis = get_kpis(db, t.id, hoy, hoy)
        result.append({
            "tienda_id": t.id,
            "tienda_nombre": t.nombre,
            **kpis,
        })
    return result
