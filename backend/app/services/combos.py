"""Administración de combos: qué combos existen y en qué sedes se venden.

La lectura que consume el POS vive en `services/pos.py`. Acá van SOLO las
operaciones de administración (activar/desactivar y disponibilidad por sede),
que hasta ahora no tenían endpoint: habilitar un combo en una sede obligaba a
insertar la fila de `combo_tiendas` a mano en la base.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Combo, ComboTienda, Tienda
from app.services import audit


def listar_admin(db: Session) -> list[dict]:
    """Todos los combos (activos e inactivos) con su composición y sus sedes."""
    combos = db.query(Combo).order_by(Combo.orden, Combo.id).all()
    return [
        {
            "id": c.id,
            "nombre": c.nombre,
            "precio_venta": float(c.precio_venta),
            "activo": c.activo,
            "orden": c.orden,
            "tienda_ids": sorted(ct.tienda_id for ct in c.tiendas),
            "grupos": [
                {
                    "nombre": g.nombre,
                    "opciones": [
                        {
                            "nombre": o.nombre,
                            "productos": [
                                {"nombre": cp.producto.nombre, "cantidad": cp.cantidad}
                                for cp in o.productos
                            ],
                        }
                        for o in g.opciones
                    ],
                }
                for g in c.grupos
            ],
        }
        for c in combos
    ]


def set_tiendas(db: Session, combo_id: int, tienda_ids: list[int], usuario_id: int) -> dict:
    """Reemplaza las sedes donde el combo está disponible. Idempotente: si la
    selección no cambia no escribe nada (y no ensucia la auditoría)."""
    combo = db.query(Combo).filter(Combo.id == combo_id).first()
    if not combo:
        raise HTTPException(status_code=404, detail="Combo no encontrado")

    validas = {t.id for t in db.query(Tienda).all()}
    pedidas = set(tienda_ids)
    invalidas = pedidas - validas
    if invalidas:
        raise HTTPException(status_code=400, detail=f"Sedes inexistentes: {sorted(invalidas)}")

    actuales = {ct.tienda_id: ct for ct in combo.tiendas}
    if set(actuales) == pedidas:
        return {"id": combo.id, "tienda_ids": sorted(pedidas), "cambio": False}

    for tid, ct in actuales.items():
        if tid not in pedidas:
            db.delete(ct)
    for tid in pedidas - set(actuales):
        db.add(ComboTienda(combo_id=combo_id, tienda_id=tid))

    audit.registrar(
        db, accion="combo_set_tiendas", tabla="combo_tiendas",
        registro_id=combo_id, usuario_id=usuario_id,
        datos_antes={"tienda_ids": sorted(actuales)},
        datos_despues={"tienda_ids": sorted(pedidas), "combo": combo.nombre},
    )
    db.commit()
    return {"id": combo.id, "tienda_ids": sorted(pedidas), "cambio": True}


def set_activo(db: Session, combo_id: int, activo: bool, usuario_id: int) -> dict:
    """Prende/apaga el combo en TODAS las sedes de una (Combo.activo lo filtra
    el POS antes que la disponibilidad por sede)."""
    combo = db.query(Combo).filter(Combo.id == combo_id).first()
    if not combo:
        raise HTTPException(status_code=404, detail="Combo no encontrado")
    antes = bool(combo.activo)
    if antes == activo:
        return {"id": combo.id, "activo": activo, "cambio": False}
    combo.activo = activo
    audit.registrar(
        db, accion="combo_set_activo", tabla="combos",
        registro_id=combo_id, usuario_id=usuario_id,
        datos_antes={"activo": antes},
        datos_despues={"activo": activo, "combo": combo.nombre},
    )
    db.commit()
    return {"id": combo.id, "activo": activo, "cambio": True}
