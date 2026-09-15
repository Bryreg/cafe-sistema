from datetime import date, datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.models import (
    AuditoriaInventario, AuditoriaInventarioItem,
    AuditoriaLimpieza, AuditoriaLimpiezaItem,
    AuditoriaControlPunto, AuditoriaControlPuntoItem,
    Inventario, EstadoAuditoriaEnum,
)
from app.services import audit

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
        # Respetar el null explícito: `or` dejaba el nombre viejo cuando se vaciaba el campo.
        if "realizado_por" in upd:
            item.realizado_por = upd["realizado_por"] or None
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

# ─── Control del punto ───────────────────────────────────────────────────────
#
# Portado del Google Form «Control de Médium Café». Había uno por sede, así que
# comparar Vida contra Palmetto era abrir dos formularios y dos hojas de
# respuestas; acá es la misma revisión con la sede como un campo.
#
# El texto de las preguntas es el del formulario, con la ortografía normalizada
# («Si»/«Sí» alternaban entre preguntas) y los signos de interrogación sueltos
# quitados. Las claves NO se renombran nunca: son lo que ata las respuestas
# guardadas a su pregunta, así que cambiar una clave despega el histórico.
#
# Dos diferencias con el formulario original, las dos decididas por el dueño:
#   · «Formularios llenos correctamente» y «Limpieza general del punto» estaban
#     bajo «Máquina espresso» y no son cosas de la máquina: se movieron a
#     Operativo. Las CLAVES no cambiaron, así que las revisiones ya registradas
#     siguen atadas a su pregunta y solo se reordena cómo se muestran.
#   · «Pastelería rotulada» era de tipo CASILLAS en Google, o sea que admitía
#     marcar Sí y No a la vez. Acá es Sí/No como las otras catorce: eso no se
#     podía portar fiel sin portar el error.
CONTROL_PUNTO_SECCIONES = [
    ("operativo", "Operativo",
     "Se hace la respectiva revisión de limpieza y presentación personal del punto.", [
         ("past_rotulada",     "Pastelería rotulada"),
         ("past_estado",       "Pastelería en buen estado, buen tamaño de las porciones "
                               "y cubiertas limpias"),
         ("salsas_rotuladas",  "Salsas y granizados rotulados y con fecha"),
         # Movidas desde «Máquina espresso»: no son cosas de la máquina.
         ("formularios",       "Formularios llenos correctamente"),
         ("limpieza_general",  "Limpieza general del punto: mesones, vitrinas, sillas y mesas"),
     ]),
    ("espresso", "Máquina espresso", None, [
        ("loza",              "Loza limpia y seca"),
        ("apisonar",          "Preparación y apisonado apropiados"),
        ("velinos",           "Limpieza de los velinos y licores"),
        ("plasticos",         "Limpieza de los plásticos donde van las cucharas y el azúcar"),
        ("calentamiento",     "Calentamiento apropiado de la pastelería"),
    ]),
    ("presentacion", "Presentación personal", None, [
        ("sin_joyas",         "Presentación sin aretes, anillos ni pulseras"),
        ("unas",              "Uñas cortas y sin esmalte"),
        ("maquillaje",        "Presentación adecuada con poco maquillaje"),
        ("uniforme",          "Uniforme completo: gorra, camiseta, delantal y cofia"),
    ]),
    ("administrativo", "Administrativo", None, [
        ("caja_cuadrada",     "Caja cuadrada y sin novedad"),
    ]),
]

CONTROL_PUNTO_KEYS = [k for _, _, _, pregs in CONTROL_PUNTO_SECCIONES for k, _ in pregs]


def get_control_punto_formato() -> dict:
    """El formato en blanco: secciones y preguntas, para que la pantalla lo pinte
    sin tener el texto duplicado en el front."""
    return {
        "secciones": [
            {"key": sk, "nombre": nombre, "descripcion": desc,
             "preguntas": [{"key": k, "label": lbl} for k, lbl in pregs]}
            for sk, nombre, desc, pregs in CONTROL_PUNTO_SECCIONES
        ],
        "total_preguntas": len(CONTROL_PUNTO_KEYS),
    }


def _serial_cp(a: AuditoriaControlPunto) -> dict:
    por_key = {it.pregunta_key: it for it in a.items}
    respuestas = {k: it.cumple for k, it in por_key.items()}
    # El resumen que de verdad se lee. `sin_responder` va aparte y NO se suma a
    # los «No»: una revisión a medias y una con fallas son cosas distintas, y
    # meterlas en el mismo número deja al dueño persiguiendo fallas que nadie
    # verificó. Es la misma distinción que `fue_contado` en el conteo mensual.
    cumplen = sum(1 for v in respuestas.values() if v is True)
    fallan = sum(1 for v in respuestas.values() if v is False)
    sin_responder = len(CONTROL_PUNTO_KEYS) - cumplen - fallan
    return {
        "id": a.id,
        "tienda_id": a.tienda_id,
        "tienda_nombre": a.tienda.nombre if a.tienda else "",
        "fecha_revision": a.fecha_revision.isoformat() if a.fecha_revision else None,
        "observaciones": a.observaciones,
        "vobo": bool(a.vobo),
        "vobo_por": a.vobo_usuario.nombre if a.vobo_usuario else None,
        "vobo_fecha": a.vobo_fecha.isoformat() if a.vobo_fecha else None,
        "usuario": a.usuario.nombre if a.usuario else "",
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "respuestas": {
            k: {
                "cumple": respuestas.get(k),
                "nota": por_key[k].nota if k in por_key else None,
                "foto_url": por_key[k].foto_url if k in por_key else None,
            } for k in CONTROL_PUNTO_KEYS
        },
        "cumplen": cumplen,
        "fallan": fallan,
        "sin_responder": sin_responder,
        "total": len(CONTROL_PUNTO_KEYS),
        # Los que fallaron, con su texto, su nota y su foto: es lo que hay que ir
        # a arreglar, y el detalle es lo que lo hace accionable.
        "incumplidas": [
            {"key": k, "label": lbl,
             "nota": por_key[k].nota if k in por_key else None,
             "foto_url": por_key[k].foto_url if k in por_key else None}
            for _, _, _, pregs in CONTROL_PUNTO_SECCIONES
            for k, lbl in pregs if respuestas.get(k) is False],
    }


def _get_cp(db: Session, auditoria_id: int, tienda_id: int) -> AuditoriaControlPunto:
    a = db.query(AuditoriaControlPunto).filter(
        AuditoriaControlPunto.id == auditoria_id,
        AuditoriaControlPunto.tienda_id == tienda_id,
    ).first()
    if not a:
        raise HTTPException(404, "Control del punto no encontrado")
    return a


def _escribir_items(db: Session, a: AuditoriaControlPunto, respuestas: dict) -> None:
    """Deja una fila por pregunta del formato, siempre las mismas.

    Se recorre el CATÁLOGO, no lo que mandó el cliente: así una pregunta nueva
    aparece en las auditorías viejas como «sin responder» —que es la verdad— y
    una clave inventada por el cliente no entra a la tabla.

    Cada respuesta puede venir como `{cumple, nota, foto_url}` o como el valor
    suelto (True/False/None). Se aceptan las dos formas porque la pantalla manda
    objetos y las pruebas y los scripts es más cómodo que manden el booleano.

    La NOTA y la FOTO no se borran cuando la respuesta pasa a Sí: la corrección
    se hizo, y el detalle de qué estaba mal es justamente lo que uno quiere
    releer en la visita siguiente. Para quitarlas hay que mandarlas vacías."""
    existentes = {it.pregunta_key: it for it in a.items}
    for k in CONTROL_PUNTO_KEYS:
        cruda = respuestas.get(k, None)
        if isinstance(cruda, dict):
            valor = cruda.get("cumple")
            nota = cruda.get("nota")
            foto = cruda.get("foto_url")
            trae_nota = "nota" in cruda
            trae_foto = "foto_url" in cruda
        else:
            valor = cruda
            nota = foto = None
            trae_nota = trae_foto = False
        if valor is not None:
            valor = bool(valor)
        nota = (nota or "").strip()[:300] or None
        foto = (foto or "").strip() or None

        it = existentes.get(k)
        if it is None:
            db.add(AuditoriaControlPuntoItem(auditoria_id=a.id, pregunta_key=k,
                                             cumple=valor, nota=nota, foto_url=foto))
        else:
            it.cumple = valor
            if trae_nota:
                it.nota = nota
            if trae_foto:
                it.foto_url = foto


def revision_anterior(db: Session, tienda_id: int,
                      excluir_id: int | None = None) -> dict | None:
    """La última revisión de esa sede, para arrancar la siguiente mirándola.

    Una auditoría que encuentra cuatro fallas y nadie verifica en la visita
    siguiente si se corrigieron es teatro: la foto se repite y la tendencia no
    existe. Los datos ya están, solo hay que ponerlos delante de quien revisa.

    `excluir_id` es para cuando se está EDITANDO una revisión: la anterior a
    ella, no ella misma."""
    q = db.query(AuditoriaControlPunto).filter(
        AuditoriaControlPunto.tienda_id == tienda_id)
    if excluir_id is not None:
        q = q.filter(AuditoriaControlPunto.id != excluir_id)
    a = (q.order_by(AuditoriaControlPunto.fecha_revision.desc(),
                    AuditoriaControlPunto.id.desc()).first())
    if a is None:
        return None
    d = _serial_cp(a)
    return {
        "id": d["id"],
        "fecha_revision": d["fecha_revision"],
        "cumplen": d["cumplen"],
        "fallan": d["fallan"],
        "sin_responder": d["sin_responder"],
        "total": d["total"],
        "incumplidas": d["incumplidas"],
    }


def tendencia_control_punto(db: Session, tienda_id: int, visitas: int = 10) -> dict:
    """Cuántas veces falló CADA pregunta en las últimas visitas de esa sede.

    Es lo que separa un problema de proceso de un martes malo: «el rotulado
    falla 7 de 9 visitas» y «falló una vez» piden cosas distintas, y con la
    lista de una sola visita no se distinguen.

    El denominador de cada pregunta es cuántas veces se RESPONDIÓ, no cuántas
    visitas hubo: una pregunta contestada dos veces y fallada las dos es 2 de 2,
    no 2 de 9. Mezclarlas diría que casi nunca falla cuando en realidad casi
    nunca se revisa — y por eso también se devuelve `sin_responder`.
    """
    filas = (db.query(AuditoriaControlPunto)
             .filter(AuditoriaControlPunto.tienda_id == tienda_id)
             .order_by(AuditoriaControlPunto.fecha_revision.desc(),
                       AuditoriaControlPunto.id.desc())
             .limit(max(1, min(visitas, 60))).all())
    etiquetas = {k: lbl for _, _, _, pregs in CONTROL_PUNTO_SECCIONES for k, lbl in pregs}
    conteo = {k: {"fallan": 0, "respondidas": 0, "sin_responder": 0} for k in CONTROL_PUNTO_KEYS}
    for a in filas:
        vistos = {it.pregunta_key: it.cumple for it in a.items}
        for k in CONTROL_PUNTO_KEYS:
            v = vistos.get(k)
            if v is None:
                conteo[k]["sin_responder"] += 1
            else:
                conteo[k]["respondidas"] += 1
                if v is False:
                    conteo[k]["fallan"] += 1
    items = [{
        "key": k, "label": etiquetas.get(k, k),
        "fallan": c["fallan"], "respondidas": c["respondidas"],
        "sin_responder": c["sin_responder"],
    } for k, c in conteo.items()]
    # Primero lo que más falla; entre iguales, lo más veces respondido (más
    # evidencia detrás del mismo número).
    items.sort(key=lambda x: (-x["fallan"], -x["respondidas"], x["label"]))
    return {"visitas": len(filas), "items": items}


def crear_control_punto(db: Session, tienda_id: int, fecha_revision: date,
                        respuestas: dict, usuario_id: int,
                        observaciones: str | None = None) -> dict:
    if fecha_revision is None:
        raise HTTPException(400, "La fecha de revisión es obligatoria")
    if fecha_revision > date.today():
        raise HTTPException(400, "La fecha de revisión no puede ser futura")
    a = AuditoriaControlPunto(
        tienda_id=tienda_id, fecha_revision=fecha_revision,
        observaciones=(observaciones or None), usuario_id=usuario_id)
    db.add(a)
    db.flush()
    _escribir_items(db, a, respuestas or {})
    audit.registrar(db, accion="control_punto_creado", tabla="auditorias_control_punto",
                    registro_id=a.id, usuario_id=usuario_id, tienda_id=tienda_id,
                    datos_despues={"fecha_revision": fecha_revision.isoformat()})
    db.commit()
    db.refresh(a)
    return _serial_cp(a)


def listar_control_punto(db: Session, tienda_id: int | None = None,
                         limite: int = 50) -> list[dict]:
    """Historial, el más reciente primero. Sin `tienda_id` trae las dos sedes —
    que es el punto de haberlo traído acá: el Google Form era uno por sede y
    comparar obligaba a abrir dos hojas."""
    q = db.query(AuditoriaControlPunto)
    if tienda_id is not None:
        q = q.filter(AuditoriaControlPunto.tienda_id == tienda_id)
    filas = (q.order_by(AuditoriaControlPunto.fecha_revision.desc(),
                        AuditoriaControlPunto.id.desc())
             .limit(max(1, min(limite, 200))).all())
    return [_serial_cp(a) for a in filas]


def actualizar_control_punto(db: Session, auditoria_id: int, tienda_id: int,
                             respuestas: dict, usuario_id: int,
                             observaciones: str | None = None) -> dict:
    a = _get_cp(db, auditoria_id, tienda_id)
    if a.vobo:
        raise HTTPException(400, "Este control ya tiene VoBo y no puede editarse")
    antes = _serial_cp(a)
    a.observaciones = (observaciones or None)
    _escribir_items(db, a, respuestas or {})
    audit.registrar(db, accion="control_punto_editado", tabla="auditorias_control_punto",
                    registro_id=a.id, usuario_id=usuario_id, tienda_id=tienda_id,
                    datos_antes={"cumplen": antes["cumplen"], "fallan": antes["fallan"]},
                    datos_despues={"respuestas": {k: v for k, v in (respuestas or {}).items()}})
    db.commit()
    db.refresh(a)
    return _serial_cp(a)


def vobo_control_punto(db: Session, auditoria_id: int, tienda_id: int,
                       usuario_id: int) -> dict:
    """Cierra la revisión. Después del VoBo no se edita: si se pudiera, el
    registro dejaría de ser lo que se revisó ese día."""
    a = _get_cp(db, auditoria_id, tienda_id)
    if a.vobo:
        return _serial_cp(a)
    a.vobo = True
    a.vobo_por_id = usuario_id
    a.vobo_fecha = datetime.utcnow()
    audit.registrar(db, accion="control_punto_vobo", tabla="auditorias_control_punto",
                    registro_id=a.id, usuario_id=usuario_id, tienda_id=tienda_id)
    db.commit()
    db.refresh(a)
    return _serial_cp(a)


def eliminar_control_punto(db: Session, auditoria_id: int, tienda_id: int,
                           usuario_id: int) -> dict:
    a = _get_cp(db, auditoria_id, tienda_id)
    if a.vobo:
        raise HTTPException(400, "Este control ya tiene VoBo y no se elimina")
    audit.registrar(db, accion="control_punto_eliminado", tabla="auditorias_control_punto",
                    registro_id=a.id, usuario_id=usuario_id, tienda_id=tienda_id,
                    datos_antes=_serial_cp(a))
    db.delete(a)
    db.commit()
    return {"ok": True}

