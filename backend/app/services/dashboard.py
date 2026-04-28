from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from app.models.models import (CajaTurno, Inventario, Consignacion, ChecklistDiario,
                                 Tienda, Producto, SolicitudPedido, SolicitudSencilla,
                                 EstadoTurnoEnum, EstadoConsignacionEnum)

def get_dashboard(db: Session, tienda_id: int):
    tienda = db.query(Tienda).filter(Tienda.id == tienda_id).first()
    hoy = datetime.utcnow().date()

    # Turno activo
    turno = db.query(CajaTurno).filter(
        CajaTurno.tienda_id == tienda_id,
        CajaTurno.estado == EstadoTurnoEnum.abierto
    ).first()

    ventas_dia = turno.total_ventas if turno else 0.0
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
            "stock_actual": round(inv.stock_actual, 2),
            "stock_minimo": round(inv.stock_minimo, 2),
            "unidad": p.unidad_medida,
        }
        for inv, p in criticos_q
    ]

    # Consignaciones pendientes
    cons_pendientes = db.query(Consignacion).filter(
        Consignacion.tienda_id == tienda_id,
        Consignacion.estado == EstadoConsignacionEnum.pendiente
    ).count()

    # Solicitudes pendientes (pedidos + sencillas sin resolver)
    from app.models.models import EstadoSolicitudEnum
    sol_pedidos = db.query(SolicitudPedido).filter(
        SolicitudPedido.tienda_id == tienda_id,
        SolicitudPedido.estado == EstadoSolicitudEnum.pendiente
    ).count()
    sol_sencillas = db.query(SolicitudSencilla).filter(
        SolicitudSencilla.tienda_id == tienda_id,
        SolicitudSencilla.estado == EstadoSolicitudEnum.pendiente
    ).count()
    solicitudes_pendientes = sol_pedidos + sol_sencillas

    # Checklist
    checklist = db.query(ChecklistDiario).filter(
        ChecklistDiario.tienda_id == tienda_id,
        func.date(ChecklistDiario.fecha) == hoy
    ).first()

    cumplimiento = 0.0
    if checklist:
        campos = [checklist.apertura_realizada, checklist.inventario_check,
                  checklist.pasteleria_check, checklist.siigo_check,
                  checklist.limpieza_check, checklist.cierre_realizado]
        cumplimiento = sum(1 for c in campos if c) / len(campos) * 100

    # Alertas
    alertas = []
    if estado_caja == "sin_turno":
        alertas.append({"tipo": "caja", "mensaje": "No hay turno abierto hoy", "nivel": "advertencia"})
    if criticos > 0:
        alertas.append({"tipo": "inventario", "mensaje": f"{criticos} producto(s) en stock crítico", "nivel": "critico"})
    if cons_pendientes > 0:
        alertas.append({"tipo": "consignacion", "mensaje": f"{cons_pendientes} consignación(es) pendiente(s)", "nivel": "advertencia"})
    if solicitudes_pendientes > 0:
        alertas.append({"tipo": "solicitud", "mensaje": f"{solicitudes_pendientes} solicitud(es) sin atender", "nivel": "advertencia"})
    if checklist and not checklist.pasteleria_check and datetime.utcnow().hour >= 11:
        alertas.append({"tipo": "pasteleria", "mensaje": "Registro de pastelería pendiente", "nivel": "critico"})

    return {
        "tienda_id": tienda_id,
        "tienda_nombre": tienda.nombre if tienda else "",
        "ventas_dia": ventas_dia,
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
        "siigo_check": checklist.siigo_check if checklist else False,
        "limpieza_check": checklist.limpieza_check if checklist else False,
        "cierre_realizado": checklist.cierre_realizado if checklist else False,
    }


def actualizar_checklist_manual(db: Session, tienda_id: int, campo: str, valor: bool):
    campos_permitidos = {"siigo_check", "limpieza_check"}
    if campo not in campos_permitidos:
        return None  # caller raises 400

    hoy = datetime.utcnow().date()
    checklist = db.query(ChecklistDiario).filter(
        ChecklistDiario.tienda_id == tienda_id,
        func.date(ChecklistDiario.fecha) == hoy
    ).first()
    if not checklist:
        checklist = ChecklistDiario(tienda_id=tienda_id, fecha=datetime.utcnow())
        db.add(checklist)
        db.flush()

    setattr(checklist, campo, valor)
    db.commit()
    db.refresh(checklist)
    return checklist
