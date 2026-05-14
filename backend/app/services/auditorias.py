from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import (
    AuditoriaInventario, AuditoriaInventarioItem,
    AuditoriaLimpieza, AuditoriaLimpiezaItem,
    Inventario, EstadoAuditoriaEnum,
)

# ─── Tareas fijas de limpieza (del Cronograma de Aseo físico) ─────────────────
TAREAS_LIMPIEZA = [
    ("pisos",            "Aseo general pisos y puntos ciegos"),
    ("mesas_barra",      "Sillas, mesas y barra (aseo general patas y por debajo)"),
    ("utensilios",       "Desinfección de utensilios (jarras de leche, espresso, cucharas, jigger, cuchillos)"),
    ("equipos_oficina",  "Limpieza computador, cajón monedero, impresora, teléfono, datáfono"),
    ("gabinetes",        "Asear y organizar gabinetes, cajones y materias primas por fecha de ingreso"),
    ("congelador",       "Lavar congelador de helado"),
    ("nevera_pasteleria","Lavar nevera de pastelería"),
    ("nevera_leche",     "Lavar nevera de leche"),
    ("recipientes",      "Limpieza de recipientes (Milo, Oreo, granizado, descafeinado, azúcar)"),
    ("trampa_grasas",    "Lavar trampa de grasas"),
    ("maquinas",         "Aseo de máquinas (licuadoras, hornos y molinos)"),
    ("material_pop",     "Limpieza de avisos y material POP (menú y fotografías)"),
    ("loza",             "Limpieza y desmanchado de loza (tazas, platos y copas)"),
]


# ─── Auditoría de inventario ──────────────────────────────────────────────────

def crear_auditoria_inv(db: Session, tienda_id: int, usuario_id: int,
                        fecha: datetime, descripcion: str,
                        items: list[dict], causa: str | None = None,
                        observaciones: str | None = None):
    if not descripcion.strip():
        raise HTTPException(status_code=400, detail="La descripción es obligatoria")
    if not items:
        raise HTTPException(status_code=400, detail="Debe incluir al menos un producto")

    a = AuditoriaInventario(
        tienda_id=tienda_id, usuario_id=usuario_id,
        fecha=fecha, descripcion=descripcion.strip(),
        causa=causa, observaciones=observaciones,
    )
    db.add(a); db.flush()

    for it in items:
        inv = db.query(Inventario).filter(
            Inventario.producto_id == it["producto_id"],
            Inventario.tienda_id == tienda_id,
        ).first()
        sistema = inv.stock_actual if inv else 0.0
        real = float(it["cantidad_real"])
        db.add(AuditoriaInventarioItem(
            auditoria_id=a.id,
            producto_id=it["producto_id"],
            cantidad_sistema=sistema,
            cantidad_real=real,
            diferencia=round(real - sistema, 3),
            observacion=it.get("observacion"),
        ))

    db.commit(); db.refresh(a)
    return _serial_inv(a)


def cerrar_auditoria_inv(db: Session, auditoria_id: int, tienda_id: int,
                         acciones_tomadas: str | None, causa: str | None):
    a = _get_inv(db, auditoria_id, tienda_id)
    a.estado = EstadoAuditoriaEnum.cerrada
    if acciones_tomadas is not None:
        a.acciones_tomadas = acciones_tomadas
    if causa is not None:
        a.causa = causa
    db.commit(); db.refresh(a)
    return _serial_inv(a)


def listar_auditorias_inv(db: Session, tienda_id: int):
    rows = (db.query(AuditoriaInventario)
            .filter(AuditoriaInventario.tienda_id == tienda_id)
            .order_by(AuditoriaInventario.fecha.desc())
            .all())
    return [_serial_inv(r) for r in rows]


def eliminar_auditoria_inv(db: Session, auditoria_id: int, tienda_id: int):
    a = _get_inv(db, auditoria_id, tienda_id)
    db.delete(a); db.commit()
    return {"ok": True}


def _get_inv(db, aid, tid):
    a = db.query(AuditoriaInventario).filter(
        AuditoriaInventario.id == aid,
        AuditoriaInventario.tienda_id == tid,
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Auditoría no encontrada")
    return a


def _serial_inv(a: AuditoriaInventario) -> dict:
    return {
        "id": a.id, "tienda_id": a.tienda_id,
        "fecha": a.fecha, "descripcion": a.descripcion,
        "causa": a.causa, "observaciones": a.observaciones,
        "acciones_tomadas": a.acciones_tomadas,
        "estado": a.estado,
        "usuario_nombre": a.usuario.nombre if a.usuario else None,
        "created_at": a.created_at,
        "items": [
            {
                "id": it.id,
                "producto_id": it.producto_id,
                "producto_nombre": it.producto.nombre if it.producto else "",
                "unidad": it.producto.unidad_medida if it.producto else "",
                "cantidad_sistema": it.cantidad_sistema,
                "cantidad_real": it.cantidad_real,
                "diferencia": it.diferencia,
                "observacion": it.observacion,
            }
            for it in a.items
        ],
    }


# ─── Auditoría de limpieza ────────────────────────────────────────────────────

def crear_auditoria_limp(db: Session, tienda_id: int, usuario_id: int,
                         semana: str, fecha_inicio: datetime,
                         items: list[dict], observaciones: str | None = None):
    """Crea o reemplaza el cronograma de aseo de una semana."""
    existente = db.query(AuditoriaLimpieza).filter(
        AuditoriaLimpieza.tienda_id == tienda_id,
        AuditoriaLimpieza.semana == semana,
    ).first()
    if existente:
        raise HTTPException(status_code=400,
                            detail="Ya existe un registro para esta semana. Edita el existente.")

    a = AuditoriaLimpieza(
        tienda_id=tienda_id, usuario_id=usuario_id,
        semana=semana, fecha_inicio=fecha_inicio,
        observaciones=observaciones,
    )
    db.add(a); db.flush()

    tareas_keys = {k for k, _ in TAREAS_LIMPIEZA}
    items_map = {it["tarea_key"]: it for it in items}

    for key, _ in TAREAS_LIMPIEZA:
        it = items_map.get(key, {})
        db.add(AuditoriaLimpiezaItem(
            auditoria_id=a.id,
            tarea_key=key,
            realizado=it.get("realizado", False),
            realizado_por=it.get("realizado_por") or None,
        ))

    db.commit(); db.refresh(a)
    return _serial_limp(a)


def actualizar_auditoria_limp(db: Session, auditoria_id: int, tienda_id: int,
                               items: list[dict], observaciones: str | None = None):
    a = _get_limp(db, auditoria_id, tienda_id)
    if a.vobo:
        raise HTTPException(status_code=400, detail="La auditoría ya tiene VoBo y no puede editarse")
    a.observaciones = observaciones
    items_map = {it["tarea_key"]: it for it in items}
    for item in a.items:
        upd = items_map.get(item.tarea_key, {})
        item.realizado = upd.get("realizado", item.realizado)
        item.realizado_por = upd.get("realizado_por") or item.realizado_por
    db.commit(); db.refresh(a)
    return _serial_limp(a)


def vobo_auditoria_limp(db: Session, auditoria_id: int, tienda_id: int, usuario_id: int):
    a = _get_limp(db, auditoria_id, tienda_id)
    a.vobo = True
    a.vobo_por_id = usuario_id
    a.vobo_fecha = datetime.utcnow()
    db.commit(); db.refresh(a)
    return _serial_limp(a)


def listar_auditorias_limp(db: Session, tienda_id: int):
    rows = (db.query(AuditoriaLimpieza)
            .filter(AuditoriaLimpieza.tienda_id == tienda_id)
            .order_by(AuditoriaLimpieza.fecha_inicio.desc())
            .all())
    return [_serial_limp(r) for r in rows]


def eliminar_auditoria_limp(db: Session, auditoria_id: int, tienda_id: int):
    a = _get_limp(db, auditoria_id, tienda_id)
    db.delete(a); db.commit()
    return {"ok": True}


def _get_limp(db, aid, tid):
    a = db.query(AuditoriaLimpieza).filter(
        AuditoriaLimpieza.id == aid,
        AuditoriaLimpieza.tienda_id == tid,
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return a


def _serial_limp(a: AuditoriaLimpieza) -> dict:
    tarea_label = {k: lbl for k, lbl in TAREAS_LIMPIEZA}
    items_out = [
        {
            "tarea_key": it.tarea_key,
            "tarea_label": tarea_label.get(it.tarea_key, it.tarea_key),
            "realizado": it.realizado,
            "realizado_por": it.realizado_por,
        }
        for it in sorted(a.items, key=lambda x: [k for k, _ in TAREAS_LIMPIEZA].index(x.tarea_key)
                         if x.tarea_key in [k for k, _ in TAREAS_LIMPIEZA] else 99)
    ]
    completadas = sum(1 for it in items_out if it["realizado"])
    return {
        "id": a.id, "tienda_id": a.tienda_id,
        "semana": a.semana, "fecha_inicio": a.fecha_inicio,
        "observaciones": a.observaciones,
        "vobo": a.vobo, "vobo_fecha": a.vobo_fecha,
        "vobo_por": a.vobo_usuario.nombre if a.vobo_usuario else None,
        "usuario_nombre": a.usuario.nombre if a.usuario else None,
        "completadas": completadas,
        "total_tareas": len(TAREAS_LIMPIEZA),
        "items": items_out,
    }


def get_tareas() -> list[dict]:
    return [{"key": k, "label": lbl} for k, lbl in TAREAS_LIMPIEZA]
