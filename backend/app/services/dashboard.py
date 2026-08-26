from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from app.models.models import (CajaTurno, Inventario, Consignacion, ChecklistDiario,
                                 Tienda, Producto, SolicitudPedido, SolicitudSencilla,
                                 EstadoTurnoEnum, EstadoConsignacionEnum)
from app.core.tz import hoy_col, inicio_dia_col_utc, fin_dia_col_utc, hora_col

def get_dashboard(db: Session, tienda_id: int):
    tienda = db.query(Tienda).filter(Tienda.id == tienda_id).first()
    hoy = hoy_col()
    ayer = hoy - timedelta(days=1)
    # Rangos UTC que cubren el día Colombia (los timestamps se guardan en UTC).
    # Reemplazan func.date(col) == fecha, que comparaba contra la fecha UTC.
    hoy_desde, hoy_hasta = inicio_dia_col_utc(hoy), fin_dia_col_utc(hoy)
    ayer_desde, ayer_hasta = inicio_dia_col_utc(ayer), fin_dia_col_utc(ayer)

    # Turno activo
    turno = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()

    # Ventas/efectivo/tarjeta del día — suma de los turnos de hoy (POS nativo
    # mantiene estos totales en cada venta). No depende de Siigo.
    turnos_hoy = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.fecha_apertura >= hoy_desde,
        CajaTurno.fecha_apertura <= hoy_hasta,
    ).all()
    ventas_dia   = sum(t.total_ventas   or 0 for t in turnos_hoy)
    efectivo_dia = sum(t.total_efectivo or 0 for t in turnos_hoy)
    tarjeta_dia  = sum(t.total_tarjeta  or 0 for t in turnos_hoy)

    # Ventas de ayer (turnos cerrados)
    turnos_ayer = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.cerrado,
        CajaTurno.fecha_apertura >= ayer_desde,
        CajaTurno.fecha_apertura <= ayer_hasta,
    ).all()
    ventas_ayer = sum(t.total_ventas or 0 for t in turnos_ayer)
    if turno:
        if turno.diferencia_cierre is not None:
            diferencia_caja = turno.diferencia_cierre
        else:
            diferencia_caja = turno.diferencia_apertura
        estado_caja = "cuadrado" if diferencia_caja == 0 else "diferencia"
    else:
        diferencia_caja = 0.0
        estado_caja = "sin_turno"

    # Inventario crítico — count + lista top 10
    criticos_q = (
        db.query(Inventario, Producto)
        .join(Producto, Inventario.producto_id == Producto.id)
        .filter(
            Inventario.tienda_id == tienda_id,
            Inventario.stock_actual <= Inventario.stock_minimo,
            Producto.controla_stock == True,
        )
        .order_by(Inventario.stock_actual.asc())
        .limit(10)
        .all()
    )
    criticos = len(criticos_q)
    productos_criticos_lista = [
        {
            "nombre": p.nombre,
            "stock_actual": round(inv.stock_actual),
            "stock_minimo": round(inv.stock_minimo),
            "unidad": p.unidad_medida,
        }
        for inv, p in criticos_q
    ]

    # Consignaciones pendientes
    cons_pendientes = db.query(Consignacion).filter(
        Consignacion.tienda_id == tienda_id,
        Consignacion.estado == EstadoConsignacionEnum.pendiente
    ).count()

    # Solicitudes pendientes (pedidos + sencillas sin resolver). Solo las del
    # kiosko: el pedido que el dueño manda al proveedor vive en la misma tabla y
    # no es nada que él tenga que resolverse a sí mismo.
    from app.models.models import EstadoSolicitudEnum
    from app.services.solicitudes import _solo_kiosko
    sol_pedidos = _solo_kiosko(db.query(SolicitudPedido).filter(
        SolicitudPedido.tienda_id == tienda_id,
        SolicitudPedido.estado == EstadoSolicitudEnum.pendiente
    )).count()
    sol_sencillas = db.query(SolicitudSencilla).filter(
        SolicitudSencilla.tienda_id == tienda_id,
        SolicitudSencilla.estado == EstadoSolicitudEnum.pendiente
    ).count()
    solicitudes_pendientes = sol_pedidos + sol_sencillas

    # Checklist
    checklist = db.query(ChecklistDiario).filter(
        ChecklistDiario.tienda_id == tienda_id,
        ChecklistDiario.fecha >= hoy_desde,
        ChecklistDiario.fecha <= hoy_hasta,
    ).first()

    cumplimiento = 0.0
    if checklist:
        campos = [checklist.apertura_realizada, checklist.inventario_check,
                  checklist.pasteleria_check,
                  checklist.limpieza_check, checklist.cierre_realizado]
        cumplimiento = sum(1 for c in campos if c) / len(campos) * 100

    # Alertas operativas básicas
    alertas = []
    if estado_caja == "sin_turno":
        alertas.append({"tipo": "caja", "mensaje": "No hay turno abierto hoy", "nivel": "advertencia"})
    if criticos > 0:
        alertas.append({"tipo": "inventario", "mensaje": f"{criticos} producto(s) en stock crítico", "nivel": "critico"})
    if cons_pendientes > 0:
        alertas.append({"tipo": "consignacion", "mensaje": f"{cons_pendientes} consignación(es) pendiente(s)", "nivel": "advertencia"})
    if solicitudes_pendientes > 0:
        alertas.append({"tipo": "solicitud", "mensaje": f"{solicitudes_pendientes} solicitud(es) sin atender", "nivel": "advertencia"})
    if checklist and not checklist.pasteleria_check and hora_col(datetime.utcnow()) >= 11:
        alertas.append({"tipo": "pasteleria", "mensaje": "Registro de pastelería pendiente", "nivel": "critico"})

    # Alertas inteligentes: patrones anómalos (mermas, baristas con diferencias, caída de ventas…)
    try:
        from app.services import alertas as alertas_svc
        smart = alertas_svc.get_alertas_inteligentes(db, tienda_id)
        alertas.extend(smart.get("alertas", []))
    except Exception:
        pass  # nunca bloquear el dashboard por fallo en alertas

    return {
        "tienda_id": tienda_id,
        "tienda_nombre": tienda.nombre if tienda else "",
        "ventas_dia": ventas_dia,
        "efectivo_dia": efectivo_dia,
        "tarjeta_dia": tarjeta_dia,
        "ventas_ayer": ventas_ayer,
        "estado_caja": estado_caja,
        "diferencia_caja": diferencia_caja,
        "productos_criticos": criticos,
        "productos_criticos_lista": productos_criticos_lista,
        "consignaciones_pendientes": cons_pendientes,
        "solicitudes_pendientes": solicitudes_pendientes,
        "cumplimiento_checklist": cumplimiento,
        "alertas": alertas,
        "apertura_realizada": checklist.apertura_realizada if checklist else False,
        "inventario_check": checklist.inventario_check if checklist else False,
        "pasteleria_check": checklist.pasteleria_check if checklist else False,
        "limpieza_check": checklist.limpieza_check if checklist else False,
        "cierre_realizado": checklist.cierre_realizado if checklist else False,
    }


def get_admin_resumen(db: Session, tienda_id: int):
    """Resumen operativo + financiero del mes en curso para el panel de administrador."""
    from app.models.models import (
        VentaDiaria, Consignacion, EstadoConsignacionEnum,
        Inventario, Producto, ConteoFisico, TipoConteoEnum,
        FacturaCompra, MovimientoCaja, TipoMovCajaEnum, CajaTurno,
    )

    hoy = hoy_col()
    # inicio_mes = instante UTC del 1° del mes Colombia a las 00:00 (los timestamps
    # se guardan en UTC; sin el offset el corte de mes caería 5h antes).
    inicio_mes = inicio_dia_col_utc(hoy.replace(day=1))

    # ── 1. Ventas acumuladas del mes ──────────────────────────────────────────
    ventas_mes = (
        db.query(func.coalesce(func.sum(VentaDiaria.venta_total), 0.0))
        .join(CajaTurno, VentaDiaria.turno_id == CajaTurno.id)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            VentaDiaria.fecha_registro >= inicio_mes,
        )
        .scalar()
    ) or 0.0

    # ── 2. Consignaciones pendientes ─────────────────────────────────────────
    cons_q = db.query(Consignacion).filter(
        Consignacion.tienda_id == tienda_id,
        Consignacion.estado == EstadoConsignacionEnum.pendiente,
    ).all()

    # ── 3. Insumos: último conteo apertura / último conteo cierre + stock ────
    ultimo_apertura = (
        db.query(ConteoFisico)
        .filter(ConteoFisico.tienda_id == tienda_id,
                ConteoFisico.tipo == TipoConteoEnum.apertura)
        .order_by(ConteoFisico.fecha_registro.desc())
        .first()
    )
    ultimo_cierre = (
        db.query(ConteoFisico)
        .filter(ConteoFisico.tienda_id == tienda_id,
                ConteoFisico.tipo == TipoConteoEnum.cierre)
        .order_by(ConteoFisico.fecha_registro.desc())
        .first()
    )

    apertura_map = {
        item.producto_id: item.cantidad_real
        for item in (ultimo_apertura.items if ultimo_apertura else [])
    }
    cierre_map = {
        item.producto_id: item.cantidad_real
        for item in (ultimo_cierre.items if ultimo_cierre else [])
    }

    inv_rows = (
        db.query(Inventario)
        .join(Producto, Inventario.producto_id == Producto.id)
        .filter(
            Inventario.tienda_id == tienda_id,
            Producto.controla_stock == True,
        )
        .all()
    )

    insumos = []
    for inv in inv_rows:
        p = inv.producto
        ap = apertura_map.get(inv.producto_id)
        cl = cierre_map.get(inv.producto_id)
        diferencia = round(ap - cl, 2) if (ap is not None and cl is not None) else None
        insumos.append({
            "producto_id": inv.producto_id,
            "nombre": p.nombre,
            "unidad": p.unidad_medida,
            "categoria": p.categoria.value,
            "stock_apertura": ap,
            "stock_cierre": cl,
            "stock_actual": round(inv.stock_actual),
            "stock_minimo": round(inv.stock_minimo),
            "diferencia": diferencia,
            "bajo_minimo": inv.stock_actual < inv.stock_minimo,
        })
    insumos.sort(key=lambda x: (not x["bajo_minimo"], x["nombre"]))

    # ── 4. Entradas por proveedor (facturas del mes) ─────────────────────────
    facturas = (
        db.query(FacturaCompra)
        .filter(
            FacturaCompra.tienda_id == tienda_id,
            FacturaCompra.fecha_recibido >= inicio_mes,
        )
        .all()
    )
    prov_map: dict = {}
    for f in facturas:
        entry = prov_map.setdefault(f.proveedor, {"total": 0.0, "count": 0})
        entry["total"] += f.valor_total
        entry["count"] += 1

    entradas_por_proveedor = [
        {"proveedor": k, "total": round(v["total"], 0), "count": v["count"]}
        for k, v in sorted(prov_map.items(), key=lambda x: -x[1]["total"])
    ]

    # ── 5. Egresos de caja del mes ───────────────────────────────────────────
    egresos_q = (
        db.query(MovimientoCaja)
        .join(CajaTurno, MovimientoCaja.caja_turno_id == CajaTurno.id)
        .filter(
            CajaTurno.tienda_id == tienda_id,
            MovimientoCaja.tipo == TipoMovCajaEnum.egreso,
            MovimientoCaja.fecha >= inicio_mes,
        )
        .all()
    )

    return {
        "tienda_id": tienda_id,
        "periodo": {
            "desde": hoy.replace(day=1).isoformat(),
            "hasta": hoy.isoformat(),
        },
        "ventas_mes": round(ventas_mes, 0),
        "consignaciones": {
            "count": len(cons_q),
            "monto": round(sum(c.valor for c in cons_q), 0),
        },
        "insumos": insumos,
        "entradas": {
            "total": round(sum(f.valor_total for f in facturas), 0),
            "por_proveedor": entradas_por_proveedor,
        },
        "egresos": {
            "total": round(sum(e.valor for e in egresos_q), 0),
            "count": len(egresos_q),
        },
    }


def actualizar_checklist_manual(db: Session, tienda_id: int, campo: str, valor: bool):
    campos_permitidos = {"limpieza_check"}
    if campo not in campos_permitidos:
        return None  # caller raises 400

    hoy = hoy_col()
    checklist = db.query(ChecklistDiario).filter(
        ChecklistDiario.tienda_id == tienda_id,
        ChecklistDiario.fecha >= inicio_dia_col_utc(hoy),
        ChecklistDiario.fecha <= fin_dia_col_utc(hoy),
    ).first()
    if not checklist:
        checklist = ChecklistDiario(tienda_id=tienda_id, fecha=datetime.utcnow())
        db.add(checklist)
        db.flush()

    setattr(checklist, campo, valor)
    db.commit()
    db.refresh(checklist)
    return checklist
