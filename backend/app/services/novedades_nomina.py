"""Novedades LABORALES: incapacidad, vacaciones, permisos, ausencias.

Ojo con el nombre: `Novedad` (a secas) ya existe en este repo y es la bitácora
operativa del turno —incidentes, cosas para la del siguiente turno—. Esto es otra
cosa: lo que le pasa a UNA persona respecto de su tiempo de trabajo.

Lo importante está en el mapa TIPOS: cada tipo declara EXPLÍCITAMENTE si cuenta
como tiempo trabajado y por qué. Eso cambia la liquidación, así que no puede
estar enterrado en un `if` adentro del cálculo: se lee, se discute y se corrige
en un solo lugar.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import (
    EstadoProgramadoEnum, NovedadNomina, TipoNovedadNominaEnum, TurnoProgramado,
    Usuario,
)
from app.services import notificaciones

# `remunerada`     → default de si se paga (editable por novedad).
# `acredita_horas` → si, estando remunerada, el día cuenta como tiempo trabajado
#                    para el resumen (se acreditan las horas PLANEADAS de ese día).
# `justifica`      → si el día deja de ser una "ausencia sin justificar".
TIPOS: dict[str, dict] = {
    "incapacidad": {
        "label": "Incapacidad",
        "remunerada": True,
        "acredita_horas": True,
        "justifica": True,
        "razon": (
            "La incapacidad la respalda un certificado médico y la persona no falta "
            "por decisión propia. El día se acredita con las horas que tenía "
            "programadas. Quién paga qué parte (EPS/ARL vs empleador) y en qué "
            "porcentaje lo define el contador: acá solo se acredita el TIEMPO."
        ),
    },
    "vacaciones": {
        "label": "Vacaciones",
        "remunerada": True,
        "acredita_horas": True,
        "justifica": True,
        "razon": "Descanso remunerado: el día se paga y no es una falta.",
    },
    "permiso_remunerado": {
        "label": "Permiso remunerado",
        "remunerada": True,
        "acredita_horas": True,
        "justifica": True,
        "razon": (
            "Permiso que el negocio decidió pagar (calamidad, licencia de luto, "
            "trámite autorizado). Cuenta como tiempo trabajado porque así se pactó."
        ),
    },
    "permiso_no_remunerado": {
        "label": "Permiso no remunerado",
        "remunerada": False,
        "acredita_horas": False,
        "justifica": True,
        "razon": (
            "La ausencia está autorizada, así que NO es una falta — pero el tiempo "
            "no se trabajó ni se paga. Justifica el día sin acreditar horas."
        ),
    },
    "licencia": {
        "label": "Licencia",
        "remunerada": False,
        "acredita_horas": False,
        "justifica": True,
        "razon": (
            "Licencia (maternidad, paternidad, estudio, no remunerada…). El default "
            "es NO acreditar porque hay licencias que las paga la EPS y no el "
            "negocio; si esta se paga, marcá 'remunerada' en la novedad."
        ),
    },
    "ausencia": {
        "label": "Ausencia",
        "remunerada": False,
        "acredita_horas": False,
        "justifica": True,
        "razon": (
            "Se registra para dejar constancia de que la falta se conoce y se "
            "documentó. No acredita horas. Un día sin marcación y SIN novedad "
            "aparece aparte, como ausencia sin justificar."
        ),
    },
    "cambio_turno": {
        "label": "Cambio de turno",
        "remunerada": False,
        "acredita_horas": False,
        "justifica": True,
        "razon": (
            "Documenta que dos personas se cambiaron el turno. No mueve plata por "
            "sí solo: las horas de cada una salen de lo que efectivamente marcaron."
        ),
    },
}


def catalogo() -> list[dict]:
    """Los tipos para la pantalla, con su razón visible: quien carga una novedad
    tiene que poder leer qué implica antes de elegirla."""
    return [
        {"tipo": clave, "label": meta["label"], "remunerada": meta["remunerada"],
         "acredita_horas": meta["acredita_horas"], "justifica": meta["justifica"],
         "razon": meta["razon"]}
        for clave, meta in TIPOS.items()
    ]


def _validar_tipo(tipo: str) -> str:
    if tipo not in TIPOS:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de novedad desconocido: {tipo}. "
                   f"Los válidos son: {', '.join(TIPOS)}.")
    return tipo


def crear(db: Session, tienda_id: int, usuario_id: int, tipo: str,
          fecha_desde: date, fecha_hasta: date, creado_por_id: int | None = None,
          remunerada: bool | None = None, nota: str | None = None,
          soporte_url: str | None = None) -> NovedadNomina:
    """Registra una novedad. Si pisa un turno ya publicado, la barista se entera.

    `remunerada` arranca en el default del tipo pero se puede forzar: hay permisos
    que el dueño decide pagar aunque el default diga que no, y al revés.
    """
    _validar_tipo(tipo)
    if fecha_hasta < fecha_desde:
        raise HTTPException(status_code=400,
                            detail="La fecha final no puede ser anterior a la inicial.")
    u = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if u is None:
        raise HTTPException(status_code=404, detail="Esa barista no existe.")

    fila = NovedadNomina(
        tienda_id=tienda_id, usuario_id=usuario_id, nombre_snapshot=u.nombre,
        tipo=TipoNovedadNominaEnum(tipo), fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        remunerada=TIPOS[tipo]["remunerada"] if remunerada is None else bool(remunerada),
        nota=nota, soporte_url=soporte_url, creado_por_id=creado_por_id,
    )
    db.add(fila)
    db.flush()

    pisados = db.query(TurnoProgramado).filter(
        TurnoProgramado.usuario_id == usuario_id,
        TurnoProgramado.fecha >= fecha_desde,
        TurnoProgramado.fecha <= fecha_hasta,
        TurnoProgramado.estado == EstadoProgramadoEnum.publicado,
    ).count()
    if pisados:
        rango = (fecha_desde.isoformat() if fecha_desde == fecha_hasta
                 else f"{fecha_desde.isoformat()} al {fecha_hasta.isoformat()}")
        cuerpo = (f"Se registró: {TIPOS[tipo]['label'].lower()} ({rango}). "
                  f"Toca {pisados} turno(s) que tenías asignado(s).")
        notificaciones.disparar(
            db, tienda_id, "novedad_laboral", f"{u.nombre}: {cuerpo}", "info",
            referencia_id=fila.id,
            push_titulo="Novedad en tu horario", push_cuerpo=cuerpo,
            usuario_id=usuario_id, push_url="/mi-horario",
        )

    db.commit()
    db.refresh(fila)
    return fila


def actualizar(db: Session, novedad_id: int, cambios: dict) -> NovedadNomina | None:
    fila = db.query(NovedadNomina).filter(NovedadNomina.id == novedad_id).first()
    if fila is None:
        return None
    if "tipo" in cambios:
        fila.tipo = TipoNovedadNominaEnum(_validar_tipo(cambios["tipo"]))
    for campo in ("fecha_desde", "fecha_hasta", "nota", "soporte_url"):
        if campo in cambios:
            setattr(fila, campo, cambios[campo])
    if "remunerada" in cambios:
        fila.remunerada = bool(cambios["remunerada"])
    if fila.fecha_hasta < fila.fecha_desde:
        raise HTTPException(status_code=400,
                            detail="La fecha final no puede ser anterior a la inicial.")
    db.commit()
    db.refresh(fila)
    return fila


def borrar(db: Session, novedad_id: int) -> bool:
    fila = db.query(NovedadNomina).filter(NovedadNomina.id == novedad_id).first()
    if fila is None:
        return False
    db.delete(fila)
    db.commit()
    return True


def a_dict(n: NovedadNomina) -> dict:
    tipo = n.tipo.value if hasattr(n.tipo, "value") else n.tipo
    meta = TIPOS.get(tipo, {})
    return {
        "id": n.id,
        "usuario_id": n.usuario_id,
        "nombre": n.nombre_snapshot,
        "tipo": tipo,
        "label": meta.get("label", tipo),
        "fecha_desde": n.fecha_desde.isoformat(),
        "fecha_hasta": n.fecha_hasta.isoformat(),
        "dias": (n.fecha_hasta - n.fecha_desde).days + 1,
        "remunerada": bool(n.remunerada),
        "acredita_horas": bool(n.remunerada) and bool(meta.get("acredita_horas")),
        "razon": meta.get("razon", ""),
        "nota": n.nota,
        "soporte_url": n.soporte_url,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def a_dict_publico(n: NovedadNomina) -> dict:
    """La misma novedad SIN la nota libre ni el soporte.

    El kiosko es un dispositivo compartido: su token lo usan todas las baristas
    de la sede y el selector de «barista activa» deja pedir el horario de
    cualquiera. Mandar la nota («incapacidad por embarazo de alto riesgo») y el
    link al certificado médico en ese payload expone un dato de salud entre
    compañeras — y la pantalla ni siquiera los pinta: muestra la etiqueta y las
    fechas. Lo que no se usa, no viaja."""
    d = a_dict(n)
    d.pop("nota", None)
    d.pop("soporte_url", None)
    return d


def listar(db: Session, tienda_id: int | None, desde: date, hasta: date,
           usuario_id: int | None = None) -> list[NovedadNomina]:
    """Novedades que TOCAN el rango (no solo las que empiezan dentro): unas
    vacaciones que arrancan el 28 del mes pasado siguen afectando este mes.

    `tienda_id=None` trae las de TODAS las sedes. Hace falta para liquidar a una
    PERSONA: una novedad se carga en la sede donde el admin la escribe, pero una
    incapacidad no es de un local — es de ella. Leyendo solo las de la sede que
    se está mirando, su liquidación daba distinto en cada pantalla.
    """
    q = db.query(NovedadNomina).filter(
        NovedadNomina.fecha_desde <= hasta,
        NovedadNomina.fecha_hasta >= desde,
    )
    if tienda_id is not None:
        q = q.filter(NovedadNomina.tienda_id == tienda_id)
    if usuario_id is not None:
        q = q.filter(NovedadNomina.usuario_id == usuario_id)
    return q.order_by(NovedadNomina.fecha_desde.asc()).all()
