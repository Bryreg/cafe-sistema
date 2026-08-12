import math
from datetime import datetime, timedelta, date
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin, get_barista_actor, require_barista_en_turno
from app.models.models import Usuario, Producto, ProductoInsumo, ProductoDesechable, Inventario, Tienda, CategoriaProductoEnum, LoteInventario
from app.schemas.inventario import (
    MovimientoInvRequest, ProductoCreate, ProductoUpdate, StockMinimoUpdate, UmbralesStockUpdate,
    InsumosProductoUpdate, DesechablesProductoUpdate, PreparacionRequest,
    UmbralesMinimosAplicar,
)
from app.services import audit
from app.services import inventario as svc

router = APIRouter(prefix="/inventario", tags=["inventario"])

@router.get("/tienda/{tienda_id}")
def get_inventario(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_inventario_tienda(db, tienda_id)

@router.post("/movimiento")
def movimiento(data: MovimientoInvRequest, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user),
               barista: tuple = Depends(require_barista_en_turno)):
    ensure_tienda_access(user, data.tienda_id)
    # El AJUSTE reescribe el stock a un valor absoluto y borra la evidencia del
    # doble conteo. Es una herramienta de correccion, no de operacion: solo admin.
    # Las baristas registran HECHOS (entrada por factura, salida, merma,
    # preparacion); las correcciones van por verificacion o por el administrador.
    if data.tipo == "ajuste" and getattr(user.rol, "value", user.rol) != "admin":
        raise HTTPException(
            status_code=403,
            detail="El ajuste de inventario es solo del administrador. Si un número no cuadra, registralo en el conteo o avisale al admin.",
        )
    return svc.registrar_movimiento(db, data.producto_id, data.tienda_id, data.tipo, data.cantidad, data.motivo, user.id,
                                    barista_id=barista[0], barista_nombre=barista[1])


@router.get("/movimientos/{tienda_id}")
def movimientos_inventario(tienda_id: int, tipo: Optional[str] = Query(None),
                           fecha: Optional[date] = Query(None),
                           db: Session = Depends(get_db),
                           user: Usuario = Depends(require_admin)):
    """Revisión de movimientos (admin): auditar ajustes, entradas y salidas."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_movimientos_inventario(db, tienda_id, tipo, fecha)

@router.get("/preparables/{tienda_id}")
def preparables(tienda_id: int, db: Session = Depends(get_db),
                user: Usuario = Depends(get_current_user)):
    """Productos intermedios que la barista puede preparar (ej. mezcla de granizado)."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_preparables(db, tienda_id)


@router.post("/preparaciones")
def registrar_preparacion(data: PreparacionRequest, db: Session = Depends(get_db),
                          user: Usuario = Depends(get_current_user),
                          barista: tuple = Depends(require_barista_en_turno)):
    """Barista registra una preparación: descuenta insumos de la receta y suma el rendimiento."""
    ensure_tienda_access(user, data.tienda_id)
    return svc.registrar_preparacion(db, data.producto_id, data.tienda_id, data.cantidad,
                                     user.id, barista_id=barista[0], barista_nombre=barista[1],
                                     idempotency_key=data.idempotency_key)


@router.get("/alertas/{tienda_id}")
def alertas(tienda_id: int, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_alertas(db, tienda_id)


@router.get("/alertas")
def alertas_consolidadas(
    tienda_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Alertas de stock consolidadas (solo admin). Sin tienda_id agrega todas las
    sedes activas; con tienda_id filtra esa sede. No colisiona con /alertas/{tienda_id}
    (distinta cantidad de segmentos)."""
    if tienda_id is not None:
        ensure_tienda_access(user, tienda_id)
    return svc.get_alertas_consolidadas(db, tienda_id)


@router.get("/lotes-trazabilidad")
def lotes_trazabilidad(
    tienda_id: Optional[int] = Query(None),
    producto_id: Optional[int] = Query(None),
    proveedor: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Trazabilidad de lotes (baristas y admin): origen, vencimiento, consumo, estado."""
    if tienda_id is not None:
        ensure_tienda_access(user, tienda_id)
    return svc.get_trazabilidad(db, tienda_id, producto_id, proveedor, estado)

@router.get("/desechables/{tienda_id}")
def inventario_desechables(tienda_id: int, db: Session = Depends(get_db),
                           user: Usuario = Depends(get_current_user)):
    """Productos del formato de desechables, agrupables por proveedor (kiosko)."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_inventario_desechables(db, tienda_id)


@router.get("/productos")
def productos(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    rows = db.query(Producto).order_by(Producto.categoria, Producto.nombre).all()
    # Archivados FUERA (firma: no controla stock + excluido del conteo + sin precio de
    # venta). Las bebidas preparadas del POS también tienen controla_stock=False pero
    # conservan precio_venta > 0. Sin este filtro los duplicados archivados reaparecían
    # en el buscador de Ingresos y las baristas les daban entrada (caso agua con gas 2-jul).
    rows = [p for p in rows if not (
        not p.controla_stock and p.incluir_en_conteo is False and not (p.precio_venta or 0)
    )]
    return [{"id": p.id, "nombre": p.nombre, "categoria": p.categoria.value,
             "unidad_medida": p.unidad_medida, "controla_stock": p.controla_stock,
             # Para el modo "Existencia" del kiosko: distinguir lo que NO entra al
             # conteo diario (vasos, tapas, helado) — incluir_en_conteo False.
             "incluir_en_conteo": p.incluir_en_conteo is not False,
             "grupo_conteo": p.grupo_conteo,
             # Recibir: convertir "N empaques" → gr/ml (botella Baileys = 1000).
             "contenido_por_empaque": p.contenido_por_empaque} for p in rows]

@router.post("/productos")
def crear_producto(data: ProductoCreate, db: Session = Depends(get_db),
                   user: Usuario = Depends(require_admin)):
    cat_map = {"pasteleria": CategoriaProductoEnum.pasteleria,
               "bebida": CategoriaProductoEnum.bebida,
               "insumo": CategoriaProductoEnum.insumo,
               "porciones": CategoriaProductoEnum.porciones}
    if data.categoria not in cat_map:
        raise HTTPException(400, "Categoría inválida")
    p = Producto(nombre=data.nombre, categoria=cat_map[data.categoria],
                 unidad_medida=data.unidad_medida, controla_stock=data.controla_stock)
    db.add(p)
    db.flush()
    for t in db.query(Tienda).all():
        db.add(Inventario(producto_id=p.id, tienda_id=t.id, stock_actual=0.0, stock_minimo=0.0))
    db.commit()
    db.refresh(p)
    return {"id": p.id, "nombre": p.nombre, "categoria": p.categoria.value,
            "unidad_medida": p.unidad_medida, "controla_stock": p.controla_stock}

@router.patch("/productos/{producto_id}")
def editar_producto(producto_id: int, data: ProductoUpdate, db: Session = Depends(get_db),
                    user: Usuario = Depends(require_admin)):
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    cat_map = {"pasteleria": CategoriaProductoEnum.pasteleria,
               "bebida": CategoriaProductoEnum.bebida,
               "insumo": CategoriaProductoEnum.insumo,
               "porciones": CategoriaProductoEnum.porciones}
    if data.nombre is not None: p.nombre = data.nombre
    if data.categoria is not None:
        if data.categoria not in cat_map: raise HTTPException(400, "Categoría inválida")
        p.categoria = cat_map[data.categoria]
    if data.unidad_medida is not None: p.unidad_medida = data.unidad_medida
    if data.controla_stock is not None: p.controla_stock = data.controla_stock
    if data.lead_time_dias is not None: p.lead_time_dias = data.lead_time_dias
    if data.proveedor is not None: p.proveedor = data.proveedor if data.proveedor.strip() else None
    if data.incluir_en_conteo is not None: p.incluir_en_conteo = data.incluir_en_conteo
    if data.fraccionable is not None: p.fraccionable = data.fraccionable
    if data.envase is not None:
        if data.envase not in ("", "bolsa", "botella"):
            raise HTTPException(400, "envase debe ser bolsa o botella")
        p.envase = data.envase or None
    if data.contenido_por_unidad is not None:
        p.contenido_por_unidad = data.contenido_por_unidad if data.contenido_por_unidad > 0 else None
    if data.orden_conteo is not None:
        p.orden_conteo = data.orden_conteo if data.orden_conteo >= 0 else None
    if data.grupo_conteo is not None:
        if data.grupo_conteo not in ("", "desechables"):
            raise HTTPException(400, "grupo_conteo debe ser desechables o vacío")
        p.grupo_conteo = data.grupo_conteo or None
    if data.sustituto_id is not None:
        if data.sustituto_id == 0:
            p.sustituto_id = None
        elif data.sustituto_id == p.id:
            raise HTTPException(400, "Un producto no puede ser su propio sustituto")
        else:
            p.sustituto_id = data.sustituto_id
    if data.contenido_por_empaque is not None:
        p.contenido_por_empaque = data.contenido_por_empaque if data.contenido_por_empaque > 0 else None
    db.commit()
    return {"id": p.id, "nombre": p.nombre, "categoria": p.categoria.value,
            "unidad_medida": p.unidad_medida, "controla_stock": p.controla_stock,
            "incluir_en_conteo": p.incluir_en_conteo,
            "fraccionable": p.fraccionable, "envase": p.envase,
            "contenido_por_unidad": p.contenido_por_unidad,
            "orden_conteo": p.orden_conteo, "grupo_conteo": p.grupo_conteo,
            "sustituto_id": p.sustituto_id,
            "contenido_por_empaque": p.contenido_por_empaque}

@router.get("/productos/{producto_id}/insumos")
def get_insumos_producto(producto_id: int, db: Session = Depends(get_db),
                         user: Usuario = Depends(get_current_user)):
    """Receta de consumo: insumos que se descuentan del inventario por cada unidad vendida."""
    return svc.get_insumos_de_producto(db, producto_id)

@router.put("/productos/{producto_id}/insumos")
def set_insumos_producto(producto_id: int, data: InsumosProductoUpdate,
                         db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Reemplaza la receta de consumo completa del producto (lista de insumo+cantidad)."""
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    vistos: set[int] = set()
    for it in data.items:
        if it.insumo_id == producto_id:
            raise HTTPException(400, "Un producto no puede ser insumo de sí mismo")
        if it.cantidad <= 0:
            raise HTTPException(400, "La cantidad de cada insumo debe ser mayor a 0")
        if it.insumo_id in vistos:
            raise HTTPException(400, "Insumo repetido en la receta")
        vistos.add(it.insumo_id)
        if not db.query(Producto.id).filter_by(id=it.insumo_id).first():
            raise HTTPException(400, f"Insumo {it.insumo_id} no existe")
    db.query(ProductoInsumo).filter_by(producto_id=producto_id).delete()
    for it in data.items:
        db.add(ProductoInsumo(producto_id=producto_id, insumo_id=it.insumo_id, cantidad=it.cantidad))
    db.commit()
    return {"producto_id": producto_id, "n_insumos": len(data.items)}

@router.get("/productos/{producto_id}/desechables")
def get_desechables_producto(producto_id: int, db: Session = Depends(get_db),
                             user: Usuario = Depends(get_current_user)):
    """Desechables (vaso, tapa, servilleta, azúcar…) que lleva el producto para
    llevar. Capa de costo SOLO para rentabilidad: NO descuenta inventario."""
    rows = (
        db.query(ProductoDesechable, Producto)
        .join(Producto, Producto.id == ProductoDesechable.insumo_id)
        .filter(ProductoDesechable.producto_id == producto_id)
        .order_by(Producto.nombre)
        .all()
    )
    return [{"insumo_id": pd.insumo_id, "nombre": prod.nombre,
             "unidad_medida": prod.unidad_medida, "cantidad": pd.cantidad}
            for pd, prod in rows]

@router.put("/productos/{producto_id}/desechables")
def set_desechables_producto(producto_id: int, data: DesechablesProductoUpdate,
                             db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Reemplaza la lista de desechables del producto (insumo+cantidad). Solo
    afecta el costo en rentabilidad, nunca el inventario del POS."""
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    vistos: set[int] = set()
    for it in data.items:
        if it.insumo_id == producto_id:
            raise HTTPException(400, "Un producto no puede ser desechable de sí mismo")
        if it.cantidad <= 0:
            raise HTTPException(400, "La cantidad de cada desechable debe ser mayor a 0")
        if it.insumo_id in vistos:
            raise HTTPException(400, "Desechable repetido")
        vistos.add(it.insumo_id)
        if not db.query(Producto.id).filter_by(id=it.insumo_id).first():
            raise HTTPException(400, f"Desechable {it.insumo_id} no existe")
    db.query(ProductoDesechable).filter_by(producto_id=producto_id).delete()
    for it in data.items:
        db.add(ProductoDesechable(producto_id=producto_id, insumo_id=it.insumo_id, cantidad=it.cantidad))
    db.commit()
    return {"producto_id": producto_id, "n_desechables": len(data.items)}

@router.patch("/tienda/{tienda_id}/producto/{producto_id}/minimo")
def actualizar_minimo(tienda_id: int, producto_id: int, data: StockMinimoUpdate,
                      db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    inv = db.query(Inventario).filter_by(tienda_id=tienda_id, producto_id=producto_id).first()
    if not inv:
        raise HTTPException(404, "Registro de inventario no encontrado")
    inv.stock_minimo = data.stock_minimo
    db.commit()
    return {"ok": True}

@router.patch("/tienda/{tienda_id}/producto/{producto_id}/umbrales")
def actualizar_umbrales(tienda_id: int, producto_id: int, data: UmbralesStockUpdate,
                        db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Módulo 6: setea stock_minimo, stock_ideal y stock_critico por producto/sede.
    Valida coherencia: critico <= minimo <= ideal (los que vengan)."""
    inv = db.query(Inventario).filter_by(tienda_id=tienda_id, producto_id=producto_id).first()
    if not inv:
        raise HTTPException(404, "Registro de inventario no encontrado")
    if data.stock_minimo is not None:
        inv.stock_minimo = data.stock_minimo
    if data.stock_ideal is not None:
        inv.stock_ideal = data.stock_ideal
    if data.stock_critico is not None:
        inv.stock_critico = data.stock_critico
    # Usar `is not None` (no truthiness): un umbral legítimamente en 0 es falsy y
    # antes saltaba la validación de coherencia.
    if inv.stock_critico is not None and inv.stock_minimo is not None and inv.stock_critico > inv.stock_minimo:
        raise HTTPException(400, "stock_critico no puede ser mayor que stock_minimo")
    if inv.stock_ideal is not None and inv.stock_minimo is not None and inv.stock_ideal < inv.stock_minimo:
        raise HTTPException(400, "stock_ideal no puede ser menor que stock_minimo")
    db.commit()
    return {
        "ok": True,
        "stock_minimo": inv.stock_minimo,
        "stock_ideal": inv.stock_ideal,
        "stock_critico": inv.stock_critico,
    }

# Tope de cordura para un mínimo escrito a mano. No es una regla de negocio —un
# mínimo de 12.000 gr de mezcla es legítimo— sino una barrera contra el dedo que
# pega 15 ceros: un umbral absurdo deja el producto en alerta para siempre y el
# dueño no tiene forma de entender por qué.
MINIMO_MAX = 1e9


@router.get("/umbrales/propuestas")
def umbrales_propuestas(tienda_id: int = Query(...),
                        db: Session = Depends(get_db),
                        admin: Usuario = Depends(require_admin)):
    """Admin: mínimos que el sistema PROPONE para los productos de esta sede que
    todavía no tienen uno, según lo que se gastó de verdad.

    READ-ONLY ABSOLUTO. No escribe una fila, un umbral ni un movimiento: es una
    propuesta para mirar. Aceptarla es otro pedido (PATCH /umbrales/aplicar) y
    lleva explícitamente qué productos se aceptan.

    Devuelve `propuestas` (con el consumo que las sostiene y en qué estado
    quedaría cada producto HOY si se aceptaran), `sin_dato` (los que no tienen
    consumo medido: esos los pone el dueño, el sistema no inventa un número) e
    `impacto` (cuántos pasan a necesitar atención hoy mismo).
    """
    ensure_tienda_access(admin, tienda_id)
    from app.services import umbrales as umbrales_svc
    return umbrales_svc.proponer(db, tienda_id)


@router.patch("/umbrales/aplicar")
def umbrales_aplicar(data: UmbralesMinimosAplicar,
                     db: Session = Depends(get_db),
                     admin: Usuario = Depends(require_admin)):
    """Admin: escribe los mínimos que el dueño aceptó. SOLO `stock_minimo`, SOLO
    de los productos que vienen en el cuerpo, SOLO en la sede que viene en el
    cuerpo (la fila de inventario es (producto, tienda): el consumo de Vida no
    es el de Palmetto). No toca `stock_critico`, `stock_ideal` ni `lead_time`.

    Valida ACÁ y no en el schema: con `Field(ge=…, allow_inf_nan=False)` el 422
    de pydantic incrusta el valor ofensor en el cuerpo y un `inf` no es
    serializable a JSON — la respuesta de error revienta antes de llegar.

    Todo o nada: un item inválido aborta el lote entero sin escribir. Una
    escritura parcial silenciosa deja al dueño sin saber qué quedó aplicado.
    """
    ensure_tienda_access(admin, data.tienda_id)
    if not data.items:
        raise HTTPException(400, "No llegó ningún mínimo para aplicar")

    nuevos: dict[int, float] = {}
    for it in data.items:
        valor = float(it.stock_minimo)
        if not math.isfinite(valor):
            raise HTTPException(400, "El mínimo tiene que ser un número válido")
        if valor < 0:
            raise HTTPException(400, "El mínimo no puede ser negativo")
        if valor > MINIMO_MAX:
            raise HTTPException(400, "El mínimo es demasiado grande")
        if it.producto_id in nuevos:
            raise HTTPException(400, f"El producto {it.producto_id} viene repetido")
        nuevos[it.producto_id] = valor

    filas = (
        db.query(Inventario)
        .filter(Inventario.tienda_id == data.tienda_id,
                Inventario.producto_id.in_(list(nuevos.keys())))
        .all()
    )
    por_producto = {f.producto_id: f for f in filas}
    faltan = [pid for pid in nuevos if pid not in por_producto]
    if faltan:
        raise HTTPException(404, f"Sin registro de inventario en esta sede: {faltan}")

    # Coherencia con los umbrales que NO se tocan, y solo si están CONFIGURADOS:
    # un `stock_critico`/`stock_ideal` en 0 significa «nadie lo cargó» (es el
    # mismo default que el mínimo que estamos arreglando), no «el techo es 0».
    # Compararse contra un umbral inexistente rechazaría todo el lote.
    # El 400 nombra el PRODUCTO, no su id: este texto le llega al dueño tal cual
    # (el front lo muestra en el alert) y «el producto 42» no le dice nada.
    nombres = dict(db.query(Producto.id, Producto.nombre)
                   .filter(Producto.id.in_(list(nuevos))).all())
    for pid, valor in nuevos.items():
        inv = por_producto[pid]
        critico = float(inv.stock_critico or 0)
        ideal = float(inv.stock_ideal or 0)
        nombre = nombres.get(pid, f"producto {pid}")
        if critico > 0 and critico > valor:
            raise HTTPException(
                400, f"{nombre} ya tiene un crítico de {critico}, mayor que el "
                     f"mínimo {valor}. No se guardó ninguno: destildalo o ajustá "
                     f"su número y volvé a aceptar.")
        if ideal > 0 and ideal < valor:
            raise HTTPException(
                400, f"{nombre} ya tiene un ideal de {ideal}, menor que el "
                     f"mínimo {valor}. No se guardó ninguno: destildalo o ajustá "
                     f"su número y volvé a aceptar.")

    for pid, valor in nuevos.items():
        inv = por_producto[pid]
        anterior = float(inv.stock_minimo or 0)
        if anterior == valor:
            continue
        inv.stock_minimo = valor
        audit.registrar(
            db, accion="umbral_minimo_aplicado", tabla="inventario",
            registro_id=inv.id, usuario_id=admin.id, tienda_id=data.tienda_id,
            datos_antes={"producto_id": pid, "stock_minimo": anterior},
            datos_despues={"producto_id": pid, "stock_minimo": valor},
        )
    db.commit()
    return {"ok": True, "tienda_id": data.tienda_id, "aplicados": len(nuevos)}


@router.get("/admin/resumen")
def resumen_admin(db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Todos los productos con stock por tienda — para el panel de admin."""
    tiendas = db.query(Tienda).filter_by(activa=True).all()
    tienda_ids = [t.id for t in tiendas]
    productos = db.query(Producto).order_by(Producto.categoria, Producto.nombre).all()

    # Single query for all inventarios across all active stores — eliminates N×M loop
    inventarios = (
        db.query(Inventario)
        .filter(Inventario.tienda_id.in_(tienda_ids))
        .all()
    )
    inv_map: dict[tuple[int, int], Inventario] = {
        (i.producto_id, i.tienda_id): i for i in inventarios
    }

    result = []
    for p in productos:
        stocks = {}
        for t in tiendas:
            inv = inv_map.get((p.id, t.id))
            stocks[str(t.id)] = {
                "stock_actual": inv.stock_actual if inv else 0,
                "stock_minimo": inv.stock_minimo if inv else 0,
                "stock_ideal": inv.stock_ideal if inv else 0,
                "stock_critico": inv.stock_critico if inv else 0,
                "alerta": (inv.stock_actual <= inv.stock_minimo) if inv else False,
            }
        result.append({
            "id": p.id,
            "nombre": p.nombre,
            "categoria": p.categoria.value,
            "unidad_medida": p.unidad_medida,
            "controla_stock": p.controla_stock,
            "incluir_en_conteo": p.incluir_en_conteo if p.incluir_en_conteo is not None else True,
            "precio_venta": p.precio_venta or 0.0,
            "fraccionable": bool(p.fraccionable),
            "envase": p.envase,
            "stocks": stocks,
        })
    return {"tiendas": [{"id": t.id, "nombre": t.nombre} for t in tiendas], "productos": result}

@router.delete("/productos/{producto_id}")
def eliminar_producto(producto_id: int, db: Session = Depends(get_db),
                      user: Usuario = Depends(require_admin)):
    """Elimina un producto si no tiene movimientos ni conteos relacionados."""
    from app.models.models import MovimientoInventario, LoteInventario
    p = db.query(Producto).filter_by(id=producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    # Chequear dependencias
    mov = db.query(MovimientoInventario).filter_by(producto_id=producto_id).first()
    if mov:
        raise HTTPException(400, "El producto tiene movimientos registrados y no puede eliminarse")
    # Eliminar tablas dependientes y el producto
    db.query(LoteInventario).filter_by(producto_id=producto_id).delete()
    db.query(Inventario).filter_by(producto_id=producto_id).delete()
    db.delete(p)
    db.commit()
    return {"ok": True}

@router.get("/lotes/{tienda_id}/{producto_id}")
def lotes(tienda_id: int, producto_id: int, db: Session = Depends(get_db),
          user: Usuario = Depends(require_admin)):
    ensure_tienda_access(user, tienda_id)
    return svc.get_lotes(db, tienda_id, producto_id)


@router.get("/producto/{producto_id}/ficha")
def ficha_producto(producto_id: int, tienda_id: int = Query(...),
                   db: Session = Depends(get_db),
                   user: Usuario = Depends(require_admin)):
    """Ficha del producto (admin): stock, lotes, últimos conteos, últimos
    movimientos y receta de un producto en una sede, en UNA sola llamada. Hoy
    esa información vive repartida en Control de inventario, Lotes, Conteos y
    Rotación, y nadie la cruza."""
    ensure_tienda_access(user, tienda_id)
    return svc.get_ficha_producto(db, tienda_id, producto_id)


@router.get("/cobertura")
def cobertura_recetas(db: Session = Depends(get_db), admin: Usuario = Depends(require_admin)):
    """Admin: agujeros del modelo relacional — (a) productos que se VENDEN en el POS
    pero no descuentan nada (sin receta y sin stock propio); (b) insumos que controlan
    stock pero NINGUNA receta los consume (se gastan físicamente y el sistema nunca
    los baja). Ambos generan diferencias de conteo inexplicables."""
    prods = db.query(Producto).all()
    consumidos = {r.insumo_id for r in db.query(ProductoInsumo.insumo_id).distinct()}
    con_receta = {r.producto_id for r in db.query(ProductoInsumo.producto_id).distinct()}
    pos_sin_descuento = [
        {"id": p.id, "nombre": p.nombre, "precio_venta": p.precio_venta}
        for p in prods
        if (p.precio_venta or 0) > 0 and not p.controla_stock and p.id not in con_receta
    ]
    insumos_sin_consumidor = [
        {"id": p.id, "nombre": p.nombre, "unidad": p.unidad_medida}
        for p in prods
        if p.controla_stock and p.incluir_en_conteo is not False
        and not (p.precio_venta or 0) and p.id not in consumidos
        and p.grupo_conteo != "desechables"   # los desechables no se consumen por receta
    ]
    return {"pos_sin_descuento": pos_sin_descuento,
            "insumos_sin_consumidor": insumos_sin_consumidor}


@router.get("/diagnostico")
def diagnostico_stock(tienda_id: Optional[int] = Query(None),
                      db: Session = Depends(get_db),
                      admin: Usuario = Depends(require_admin)):
    """Admin: por qué el motor de stock no avisa y por qué hay negativos.

    Es la respuesta PERMANENTE a las dos preguntas del dueño —«contá los
    umbrales» y «por qué tengo inventario negativo»— sin depender de que nadie
    entre a la consola de la base. Devuelve:

      · `umbrales`  cuántas filas de inventario tienen mínimo / crítico / ideal
                    configurados, por sede y en total. Con el mínimo en 0 (el
                    default del esquema) el motor no avisa hasta llegar a cero.
      · `consumo`   cuántos productos tuvieron salidas medidas. Sin esto, el eje
                    TIEMPO del motor tampoco opera y todo cae al mínimo.
      · `negativos` cada producto en negativo con su causa PROBABLE, la última
                    entrada registrada en esa sede y cuántas recetas lo consumen.
      · `recetas_sospechosas`  cantidades que huelen a unidad mal cargada.

    Read-only: no escribe, no corrige stock, no crea movimientos.
    """
    if tienda_id is not None:
        ensure_tienda_access(admin, tienda_id)
    from app.services import diagnostico_stock
    return diagnostico_stock.diagnostico(db, tienda_id)


class UnificarRequest(BaseModel):
    keeper_id: int
    archive_ids: list[int]
    dry_run: bool = True


@router.post("/unificar")
def unificar(data: UnificarRequest, db: Session = Depends(get_db),
             admin: Usuario = Depends(require_admin)):
    """Admin: consolida productos duplicados en uno (keeper). dry_run=True (default)
    solo devuelve el plan; dry_run=False ejecuta (mueve stock + archiva)."""
    return svc.unificar_productos(db, data.keeper_id, data.archive_ids, admin.id,
                                  dry_run=data.dry_run)


@router.get("/pasteleria-impulso/{tienda_id}")
def pasteleria_impulso(tienda_id: int, db: Session = Depends(get_db),
                       user: Usuario = Depends(get_current_user)):
    """
    Lotes de pastelería con 3+ días en inventario.
    Se usan para mostrar el pop-up de impulso al barista al entrar al Hub.
    Rotación objetivo: 5 días desde recepción.
    """
    ensure_tienda_access(user, tienda_id)
    corte = datetime.utcnow() - timedelta(days=3)
    ahora = datetime.utcnow()
    lotes_q = (
        db.query(LoteInventario)
        .join(Producto, LoteInventario.producto_id == Producto.id)
        .options(joinedload(LoteInventario.producto))
        .filter(
            LoteInventario.tienda_id == tienda_id,
            LoteInventario.cantidad_restante > 0,
            LoteInventario.fecha_entrada <= corte,
            Producto.categoria == CategoriaProductoEnum.pasteleria,
        )
        .order_by(LoteInventario.fecha_entrada.asc())
        .all()
    )
    result = []
    for l in lotes_q:
        dias = (ahora - l.fecha_entrada).days
        result.append({
            "lote_id": l.id,
            "producto_id": l.producto_id,
            "producto_nombre": l.producto.nombre,
            "cantidad_restante": l.cantidad_restante,
            "fecha_entrada": l.fecha_entrada.isoformat(),
            "dias_en_inventario": dias,
            "urgente": dias >= 5,          # 5+ días = ya pasó la ventana de rotación
        })
    return result
