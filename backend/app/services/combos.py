"""Administración de combos: qué combos existen y en qué sedes se venden.

La lectura que consume el POS vive en `services/pos.py`. Acá van SOLO las
operaciones de administración (activar/desactivar y disponibilidad por sede),
que hasta ahora no tenían endpoint: habilitar un combo en una sede obligaba a
insertar la fila de `combo_tiendas` a mano en la base.
"""
import re
import unicodedata

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import (CategoriaProductoEnum, Combo, ComboGrupo, ComboOpcion,
                               ComboOpcionProducto, ComboTienda, Producto, Tienda)
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


# ─────────────────────────────────────────────────────────────────────────────
# Alta y edición de la DEFINICIÓN de un combo
#
# Esta lógica vivía SOLO dentro de `cargar_combos.py`, así que crear un combo
# exigía entrar al servidor y correr un script contra la base: no había forma
# de hacerlo desde la app ni por API. Se movió acá para que el script y el
# endpoint usen LA MISMA implementación. Dos copias de esto se habrían
# separado enseguida —cada una con sus propias validaciones— y el modo de
# fallar sería un combo creado por un camino que el otro no sabe mantener.
#
# La definición que entra usa IDS, no nombres: el script resuelve sus nombres
# contra la base antes de llamar (ya tiene los índices armados) y la API recibe
# ids del formulario. Un solo formato adentro.
# ─────────────────────────────────────────────────────────────────────────────

def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def validar_definicion(d: dict) -> None:
    """Lo que hace a una definición vendible, antes de tocar la base.

    Cada guarda está por una forma concreta de quedar roto:

    · SIN GRUPOS, O CON UN GRUPO SIN OPCIONES: el combo se vendería a precio
      completo sin entregar ni descontar NADA. Es la peor de todas porque no
      falla: cobra bien y el inventario nunca se mueve.
    · UNA OPCIÓN SIN PRODUCTOS: igual, pero solo cuando el cliente elige justo
      esa — o sea que aparece semanas después y como una fuga inexplicada.
    · CANTIDAD ≤ 0: un renglón que no descuenta, o que SUMA stock al vender.
    · PRECIO ≤ 0: el combo entraría gratis en la grilla del POS.
    · NOMBRES REPETIDOS entre grupos o entre opciones del mismo grupo: el
      sincronizado matchea por nombre normalizado, así que dos «Bebida» se
      pisarían una a la otra y la segunda se perdería en silencio.
    """
    nombre = (d.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(400, "El combo necesita un nombre")
    if float(d.get("precio") or 0) <= 0:
        raise HTTPException(400, "El precio del combo debe ser mayor a 0")

    grupos = d.get("grupos") or []
    if not grupos:
        raise HTTPException(
            400, "El combo necesita al menos un grupo con una opción: sin eso se "
                 "vendería a precio completo sin entregar ni descontar nada")

    vistos_g = set()
    for g in grupos:
        gn = (g.get("nombre") or "").strip()
        if not gn:
            raise HTTPException(400, "Cada grupo necesita un nombre")
        if _norm(gn) in vistos_g:
            raise HTTPException(400, f"Grupo repetido en el combo: «{gn}»")
        vistos_g.add(_norm(gn))

        opciones = g.get("opciones") or []
        if not opciones:
            raise HTTPException(400, f"El grupo «{gn}» no tiene opciones")

        vistos_o = set()
        for o in opciones:
            on = (o.get("nombre") or "").strip()
            if not on:
                raise HTTPException(400, f"Una opción de «{gn}» no tiene nombre")
            if _norm(on) in vistos_o:
                raise HTTPException(400, f"Opción repetida en «{gn}»: «{on}»")
            vistos_o.add(_norm(on))

            productos = o.get("productos") or []
            if not productos:
                raise HTTPException(
                    400, f"La opción «{on}» no consume ningún producto: quien la "
                         f"elija pagaría el combo y no se descontaría nada")
            vistos_p = set()
            for p in productos:
                pid = p.get("producto_id")
                if pid in vistos_p:
                    raise HTTPException(400, f"Producto repetido en la opción «{on}»")
                vistos_p.add(pid)
                if float(p.get("cantidad") or 0) <= 0:
                    raise HTTPException(
                        400, f"La cantidad de cada producto de «{on}» debe ser mayor a 0")


def verificar_sombra(db: Session, nombre: str) -> Producto | None:
    """¿Se puede usar ese nombre para la sombra del combo? Devuelve el producto
    reutilizable, o None si hay que crearlo. NO escribe nada.

    Existe aparte de `_sombra_para` para poder validar TODOS los combos antes
    de crear el primero. El script creaba combos en orden y, si el tercero
    colisionaba, los dos primeros ya estaban hechos: una corrida a medias que
    hay que deshacer a mano."""
    existente = next(
        (p for p in db.query(Producto).all() if _norm(p.nombre) == _norm(nombre)), None)
    if existente is None:
        return None
    if float(existente.precio_venta or 0) > 0 or existente.controla_stock:
        raise HTTPException(
            400,
            f"Ya existe un producto real llamado «{existente.nombre}» "
            f"(precio {existente.precio_venta:g}, "
            f"{'con' if existente.controla_stock else 'sin'} control de stock). "
            f"No se usa como sombra del combo: ponele otro nombre al combo.")
    return existente


def _sombra_para(db: Session, nombre: str) -> Producto:
    """El producto SOMBRA al que apunta la línea del ticket: inerte (precio 0,
    así no aparece en la grilla del POS que filtra precio>0) y sin stock."""
    existente = verificar_sombra(db, nombre)
    if existente is not None:
        return existente
    sombra = Producto(
        nombre=nombre.strip(),
        categoria=CategoriaProductoEnum.bebida,
        unidad_medida="und",
        controla_stock=False,
        incluir_en_conteo=False,
        precio_venta=0,
    )
    db.add(sombra)
    db.flush()
    return sombra


def sincronizar_combo(db: Session, d: dict, combo: Combo | None = None,
                      log=None) -> tuple:
    """Crea o actualiza un combo desde su definición. Devuelve (combo, estado).

    `combo=None` → se busca por nombre normalizado y se crea si no está. Con un
    combo explícito se edita ESE (permite renombrarlo sin perder su historia,
    que es lo que necesita la pantalla).

    Grupos, opciones y productos se sincronizan por nombre normalizado: lo que
    la definición no menciona se retira. Las SEDES no se tocan acá — van por
    `set_tiendas`, porque quitar una sede es una decisión distinta a cambiar la
    composición y no tiene por qué viajar en el mismo guardado.
    """
    di = log or (lambda *a: None)
    validar_definicion(d)
    nombre = d["nombre"].strip()
    precio = float(d["precio"])
    orden = int(d.get("orden") or 0)

    if combo is None:
        combo = next(
            (c for c in db.query(Combo).all() if _norm(c.nombre) == _norm(nombre)), None)

    if combo is None:
        sombra = _sombra_para(db, nombre)
        combo = Combo(nombre=nombre, precio_venta=precio, activo=True,
                      orden=orden, producto_id=sombra.id)
        db.add(combo)
        db.flush()
        di(f"  + combo   {combo.nombre}  (${precio:g})")
        estado = "creado"
    else:
        # Renombrar: el nombre también es el de la sombra, y la sombra es lo que
        # el ticket muestra. Si no se renombra, el histórico dice un nombre y la
        # pantalla otro.
        cambio = False
        if _norm(combo.nombre) != _norm(nombre) or combo.nombre != nombre:
            otro = next((c for c in db.query(Combo).all()
                         if c.id != combo.id and _norm(c.nombre) == _norm(nombre)), None)
            if otro is not None:
                raise HTTPException(400, f"Ya hay otro combo llamado «{otro.nombre}»")
            di(f"  ~ nombre  {combo.nombre} -> {nombre}")
            combo.nombre = nombre
            if combo.producto is not None:
                combo.producto.nombre = nombre
            cambio = True
        if float(combo.precio_venta or 0) != precio:
            di(f"  ~ precio  {combo.nombre}: {combo.precio_venta} -> {precio}")
            combo.precio_venta = precio
            cambio = True
        if combo.orden != orden:
            combo.orden = orden
            cambio = True
        estado = "actualizado" if cambio else "sin_cambio"

    # ── Grupos / opciones / productos (match por nombre normalizado)
    grupos_db = {_norm(g.nombre): g for g in combo.grupos}
    grupos_def = set()
    for gi, gdef in enumerate(d["grupos"]):
        clave = _norm(gdef["nombre"])
        grupos_def.add(clave)
        grupo = grupos_db.get(clave)
        if grupo is None:
            grupo = ComboGrupo(combo_id=combo.id, nombre=gdef["nombre"].strip(), orden=gi)
            db.add(grupo)
            db.flush()
            di(f"    + grupo   {combo.nombre} / {grupo.nombre}")
        else:
            grupo.orden = gi

        opciones_db = {_norm(o.nombre): o for o in grupo.opciones}
        opciones_def = set()
        for oi, odef in enumerate(gdef["opciones"]):
            clave_o = _norm(odef["nombre"])
            opciones_def.add(clave_o)
            opcion = opciones_db.get(clave_o)
            if opcion is None:
                opcion = ComboOpcion(grupo_id=grupo.id, nombre=odef["nombre"].strip(), orden=oi)
                db.add(opcion)
                db.flush()
                di(f"      + opcion  {grupo.nombre} / {opcion.nombre}")
            else:
                opcion.orden = oi

            deseados = {int(p["producto_id"]): float(p["cantidad"])
                        for p in odef["productos"]}
            existentes = {op.producto_id: op for op in opcion.productos}
            for pid, op in existentes.items():
                if pid not in deseados:
                    db.delete(op)
            for pid, cant in deseados.items():
                op = existentes.get(pid)
                if op is None:
                    db.add(ComboOpcionProducto(opcion_id=opcion.id, producto_id=pid,
                                               cantidad=cant))
                elif float(op.cantidad) != cant:
                    op.cantidad = cant

        for clave_o, opcion in opciones_db.items():
            if clave_o not in opciones_def:
                di(f"      - opcion  {grupo.nombre} / {opcion.nombre} (retirada)")
                db.delete(opcion)

    for clave, grupo in grupos_db.items():
        if clave not in grupos_def:
            di(f"    - grupo   {combo.nombre} / {grupo.nombre} (retirado)")
            db.delete(grupo)

    return combo, estado


def crear(db: Session, d: dict, tienda_ids: list[int], usuario_id: int) -> dict:
    """Alta de un combo desde la app + las sedes donde se vende.

    Un combo sin sede no se vende en ninguna parte y la pantalla lo muestra
    igual, así que se exige al menos una: es el error que nadie descubre."""
    nombre = (d.get("nombre") or "").strip()
    if next((c for c in db.query(Combo).all() if _norm(c.nombre) == _norm(nombre)), None):
        raise HTTPException(400, f"Ya existe un combo llamado «{nombre}»")
    _validar_productos(db, d)
    if not tienda_ids:
        raise HTTPException(400, "Elegí al menos una sede: un combo sin sede no se vende")
    _validar_tiendas(db, tienda_ids)

    combo, _ = sincronizar_combo(db, d)
    for tid in dict.fromkeys(tienda_ids):
        db.add(ComboTienda(combo_id=combo.id, tienda_id=tid))
    audit.registrar(
        db, accion="crear_combo", tabla="combos", registro_id=combo.id,
        usuario_id=usuario_id, tienda_id=tienda_ids[0],
        datos_despues={"nombre": combo.nombre, "precio": float(combo.precio_venta),
                       "tiendas": sorted(set(tienda_ids))},
    )
    db.commit()
    db.refresh(combo)
    return _serializar(combo)


def editar(db: Session, combo_id: int, d: dict, usuario_id: int) -> dict:
    """Edita nombre, precio, orden y composición de un combo existente. Las
    sedes van por `set_tiendas`, no acá."""
    combo = db.query(Combo).filter(Combo.id == combo_id).first()
    if not combo:
        raise HTTPException(404, "Combo no encontrado")
    _validar_productos(db, d)
    antes = {"nombre": combo.nombre, "precio": float(combo.precio_venta),
             "grupos": len(combo.grupos)}
    combo, _estado = sincronizar_combo(db, d, combo=combo)
    # Se audita siempre, sin mirar `estado`: ese solo refleja el encabezado
    # (nombre/precio/orden), y una edición que cambia SOLO la composición —sacar
    # un producto de una opción, que es justo lo que altera lo que se descuenta—
    # dejaría de tener traza.
    audit.registrar(
        db, accion="editar_combo", tabla="combos", registro_id=combo.id,
        usuario_id=usuario_id,
        tienda_id=(sorted(ct.tienda_id for ct in combo.tiendas) or [None])[0],
        datos_antes=antes,
        datos_despues={"nombre": combo.nombre, "precio": float(combo.precio_venta),
                       "grupos": len(d.get("grupos") or [])},
    )
    db.commit()
    db.refresh(combo)
    return _serializar(combo)


def _validar_productos(db: Session, d: dict) -> None:
    """Todos los productos de la definición tienen que existir. Se validan de
    una sola vez y se listan TODOS los que falten: uno por uno obliga a guardar
    el formulario tantas veces como errores tenga."""
    pedidos = {int(p["producto_id"])
               for g in (d.get("grupos") or [])
               for o in (g.get("opciones") or [])
               for p in (o.get("productos") or [])}
    if not pedidos:
        return
    existen = {pid for (pid,) in db.query(Producto.id).filter(Producto.id.in_(pedidos)).all()}
    faltan = sorted(pedidos - existen)
    if faltan:
        raise HTTPException(400, f"Productos que no existen: {faltan}")


def _validar_tiendas(db: Session, tienda_ids: list[int]) -> None:
    existen = {tid for (tid,) in db.query(Tienda.id).filter(Tienda.id.in_(tienda_ids)).all()}
    faltan = sorted(set(tienda_ids) - existen)
    if faltan:
        raise HTTPException(400, f"Sedes que no existen: {faltan}")


def _serializar(combo: Combo) -> dict:
    return {
        "id": combo.id, "nombre": combo.nombre,
        "precio_venta": float(combo.precio_venta), "activo": combo.activo,
        "orden": combo.orden,
        "tienda_ids": sorted(ct.tienda_id for ct in combo.tiendas),
        "grupos": [
            {"nombre": g.nombre,
             "opciones": [
                 {"nombre": o.nombre,
                  "productos": [{"producto_id": cp.producto_id,
                                 "nombre": cp.producto.nombre if cp.producto else "",
                                 "cantidad": cp.cantidad} for cp in o.productos]}
                 for o in g.opciones]}
            for g in combo.grupos],
    }
