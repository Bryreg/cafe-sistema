import math
from datetime import datetime, timedelta, date
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from pydantic import BaseModel
import logging
from sqlalchemy import func
from app.core.tz import fin_dia_col_utc, inicio_dia_col_utc
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.core.deps import ensure_tienda_access, get_current_user, require_admin, get_barista_actor, require_barista_en_turno
from app.models.models import (Usuario, Producto, ProductoInsumo, ProductoDesechable,
                               Inventario, Tienda, CategoriaProductoEnum, LoteInventario,
                               MovimientoInventario, FacturaCompra, FacturaCompraItem,
                               SolicitudPedido, SolicitudPedidoItem,
                               ORIGEN_ADMIN, ORIGEN_KIOSKO)
from app.schemas.inventario import (
    MovimientoInvRequest, ProductoCreate, ProductoUpdate, StockMinimoUpdate, UmbralesStockUpdate,
    InsumosProductoUpdate, DesechablesProductoUpdate, PreparacionRequest,
    UmbralesMinimosAplicar,
)
from app.services import audit
from app.services import proveedor_canon
from app.services import inventario as svc

logger = logging.getLogger(__name__)
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

@router.get("/orden-conteo")
def reporte_orden_conteo(db: Session = Depends(get_db), user: Usuario = Depends(require_admin)):
    """Qué matcheó la lista del recorrido contra el catálogo REAL de esta base.

    El archivo `app/data/orden_conteo.json` está escrito contra los nombres de
    producción que se conocen, que no son todos. Este reporte es la forma de
    verificarlo sin adivinar: dice qué entrada de la lista del dueño no encontró
    producto (falta una variante), qué producto quedó sin posición (se cuenta al
    final, alfabético) y qué posición difiere del archivo porque alguien la movió
    a mano.

    Solo lectura: no siembra ni corrige nada. Sembrar es cosa del arranque.
    """
    from app.services import orden_conteo as svc_orden
    try:
        return svc_orden.reporte(db)
    except svc_orden.OrdenConteoInvalido as e:
        raise HTTPException(500, f"El archivo del orden de conteo no se pudo leer: {e}")


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


@router.get("/duplicados/plan")
def duplicados_plan(db: Session = Depends(get_db),
                    admin: Usuario = Depends(require_admin)):
    """Admin: qué se movería si se fusionan los duplicados archivados. NO ESCRIBE.

    Es el dry-run del script `scripts/fusionar_duplicados_dryrun.py` servido como
    dato, para poder leerlo desde la app y desde producción sin abrir una consola.
    Devuelve los tres desenlaces:

      · `fusionables`  archivados con EXACTAMENTE un vivo del mismo nombre, con
                       qué se movería por tabla, qué chocaría (y cómo se
                       resuelve) y qué lo bloquea. `seguro: true` = se puede
                       ejecutar sin decisiones a mano.
      · `ambiguos`     hay más de un vivo con ese nombre: nadie adivina cuál es
                       el bueno, lo elige el admin.
      · `huerfanos`    archivados sin ningún vivo (el menú viejo), cada uno con
                       `tiene_historia`: los vacíos se pueden borrar y punto;
                       los que tienen historia se conservan, con el detalle de
                       qué los ancla.
    """
    from app.services import fusion_duplicados
    return fusion_duplicados.plan(db)


class ParFusion(BaseModel):
    muerto: int          # el archivado que desaparece
    vivo: int            # el producto que se queda con la historia


class FusionarRequest(BaseModel):
    pares: list[ParFusion] = []
    borrar_huerfanos_vacios: bool = False


@router.post("/duplicados/fusionar")
def duplicados_fusionar(data: FusionarRequest, db: Session = Depends(get_db),
                        admin: Usuario = Depends(require_admin)):
    """Admin: ejecuta la fusión. Cada par en su propia transacción.

    Por cada par: re-apunta toda la referencia del archivado al vivo, borra el
    cascarón ya vacío y verifica que no quedó ninguna referencia colgada (si
    quedó, ese par se revierte). Un par que falla NO arrastra a los demás y se
    reporta con su razón.

    Con `borrar_huerfanos_vacios` borra los archivados sin ningún vivo Y sin
    ninguna referencia en ninguna tabla. Los que tienen historia se conservan
    siempre: se devuelven en `huerfanos_conservados` con qué los ancla.
    """
    from app.services import fusion_duplicados as fusion

    # La validación de «jamás fusionar dos vivos» se hace ANTES de tocar nada:
    # si un solo par del lote apunta a un producto vivo como muerto, no se
    # ejecuta ninguno. Mover ventas reales al producto equivocado es el daño
    # máximo de este endpoint, y un lote a medio aplicar es peor que uno
    # rechazado entero.
    for par in data.pares:
        muerto = db.query(Producto).filter_by(id=par.muerto).first()
        if muerto is None:
            raise HTTPException(404, f"El producto #{par.muerto} no existe.")
        if not fusion.es_archivado(muerto):
            raise HTTPException(
                400,
                f"#{par.muerto} «{muerto.nombre}» no está archivado. Solo se fusiona un "
                f"producto archivado hacia uno vivo: fusionar dos vivos movería ventas "
                f"reales al producto equivocado.")
        if fusion.es_combo_sombra(db, par.muerto):
            raise HTTPException(
                400,
                f"#{par.muerto} «{muerto.nombre}» es el producto sombra de un combo, "
                f"no un duplicado. Fusionarlo movería el combo a otro producto.")

    return fusion.fusionar(db, [p.model_dump() for p in data.pares],
                           borrar_huerfanos_vacios=data.borrar_huerfanos_vacios,
                           usuario_id=admin.id)


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


@router.get("/pasteleria-impulso-resumen/{tienda_id}")
def pasteleria_impulso_resumen(tienda_id: int, db: Session = Depends(get_db),
                               user: Usuario = Depends(get_current_user)):
    """
    Pastelería «por impulsar» AGRUPADA POR PRODUCTO (no por lote).

    Un producto entra a la lista si su lote más viejo lleva 3+ días en
    inventario (la misma ventana de rotación que el pop-up del barista). Por
    cada producto se devuelve el total de unidades en bodega y el detalle del
    lote más viejo y el más nuevo, para decidir qué empujar primero (FIFO)
    sin tener que listar cada lote por separado.

    Diferencia con /pasteleria-impulso: ese es por-lote (lo usa el barista);
    este consolida por producto para el panel de administración. El total y el
    «lote más nuevo» consideran TODOS los lotes con stock del producto (también
    los frescos de <3 días), no solo los que ya cumplieron la ventana.
    """
    ensure_tienda_access(user, tienda_id)
    ahora = datetime.utcnow()
    lotes_q = (
        db.query(LoteInventario)
        .join(Producto, LoteInventario.producto_id == Producto.id)
        .options(joinedload(LoteInventario.producto))
        .filter(
            LoteInventario.tienda_id == tienda_id,
            LoteInventario.cantidad_restante > 0,
            Producto.categoria == CategoriaProductoEnum.pasteleria,
        )
        .order_by(LoteInventario.fecha_entrada.asc())
        .all()
    )
    # Agrupar por producto conservando el orden (más viejo primero).
    por_prod: dict[int, list] = {}
    for l in lotes_q:
        por_prod.setdefault(l.producto_id, []).append(l)

    result = []
    for pid, lotes in por_prod.items():
        viejo = lotes[0]          # menor fecha_entrada (lote más viejo)
        nuevo = lotes[-1]         # mayor fecha_entrada (lote más nuevo)
        dias_viejo = (ahora - viejo.fecha_entrada).days
        if dias_viejo < 3:
            continue              # nada por impulsar todavía en este producto
        dias_nuevo = (ahora - nuevo.fecha_entrada).days
        total = sum(l.cantidad_restante for l in lotes)
        result.append({
            "producto_id": pid,
            "producto_nombre": viejo.producto.nombre,
            "total_unidades": total,
            "n_lotes": len(lotes),
            "lote_viejo": {
                "cantidad": viejo.cantidad_restante,
                "dias": dias_viejo,
                "fecha_entrada": viejo.fecha_entrada.isoformat(),
            },
            "lote_nuevo": {
                "cantidad": nuevo.cantidad_restante,
                "dias": dias_nuevo,
                "fecha_entrada": nuevo.fecha_entrada.isoformat(),
            },
            "dias_en_inventario": dias_viejo,   # días del lote más viejo (orden/urgencia)
            "urgente": dias_viejo >= 5,         # 5+ días = ya pasó la ventana
        })
    # Más urgente primero, luego más días en inventario.
    result.sort(key=lambda r: (r["urgente"], r["dias_en_inventario"]), reverse=True)
    return result

def _num(x) -> float:
    return float(x or 0)


def _pedido_por_producto(db: Session, tienda_id: int, d_utc: datetime, h_utc: datetime,
                         producto_ids: list[int] | None = None) -> dict[int, dict]:
    """Lo que el DUEÑO pidió por escrito en el rango, por producto.

    Solo `origen='admin'`: son los pedidos que salieron a un proveedor, con la
    cantidad en la unidad del producto. La solicitud del kiosko queda afuera a
    propósito —la barista avisa que falta algo, no le pide a nadie, y sus
    unidades cambian de un día para otro para el mismo insumo—; sumarlas daría
    un «pedí» que no se puede restar contra ninguna factura.

    Se agrega en Python sobre filas crudas y no con un GROUP BY: son los pedidos
    que una persona tecleó, no el libro de movimientos, así que caben de sobra en
    memoria; y agrupando en SQL por (producto, unidad) el conteo de pedidos se
    duplicaría en cuanto un mismo pedido trajera el mismo insumo en dos unidades.
    """
    q = (
        db.query(SolicitudPedidoItem.producto_id, SolicitudPedidoItem.unidad_solicitada,
                 SolicitudPedidoItem.cantidad_solicitada, SolicitudPedido.id,
                 SolicitudPedido.proveedor)
        .join(SolicitudPedido, SolicitudPedidoItem.solicitud_id == SolicitudPedido.id)
        .filter(SolicitudPedido.tienda_id == tienda_id,
                SolicitudPedido.origen == ORIGEN_ADMIN,
                SolicitudPedido.fecha_solicitud >= d_utc,
                SolicitudPedido.fecha_solicitud <= h_utc)
    )
    if producto_ids is not None:
        q = q.filter(SolicitudPedidoItem.producto_id.in_(producto_ids))

    out: dict[int, dict] = {}
    for pid, unidad, cant, sid, prov in q.all():
        d = out.setdefault(pid, {"por_unidad": {}, "pedidos": set(), "proveedores": set()})
        u = (unidad or "").strip()
        d["por_unidad"][u] = round(d["por_unidad"].get(u, 0.0) + float(cant or 0), 4)
        d["pedidos"].add(sid)
        if (prov or "").strip():
            d["proveedores"].add(prov.strip())
    return out


def _fila_insumo(p: dict, proveedor: str | None, pedido: dict | None = None) -> dict:
    """Una fila de «qué pasó con este insumo», a partir del renglón que ya
    calculó la escalera de conciliación, más el proveedor y lo que se le pidió.

    Vive acá, compartida, porque la TABLA (`/movimiento-insumos`) y la FICHA
    (`/insumo/{id}/ficha`) muestran exactamente los mismos números: si cada una
    los armara por su lado, el día que alguien agregue un renglón las dos
    pantallas dirían cosas distintas del mismo producto y nadie sabría cuál
    creer."""
    salidas = {
        "ventas": _num(p.get("ventas")),
        "mermas": _num(p.get("mermas")),
        "traslados": _num(p.get("traslados")),
        "preparaciones": _num(p.get("preparaciones")),
        "reversas_salida": _num(p.get("reversas_salida")),
        "otras_salidas": _num(p.get("otras_salidas")),
    }
    entradas = _num(p.get("entradas"))
    vu = _num(p.get("valor_unitario"))

    # Lo pedido SOLO cuenta en la unidad del producto: es la única en la que
    # restarlo contra lo que entró significa algo. Lo pedido en otra unidad no se
    # descarta en silencio —se informa aparte— porque un «pedí 0» junto a una
    # entrada grande manda a buscar un problema que no existe.
    ped = pedido or {}
    por_unidad = dict(ped.get("por_unidad") or {})
    unidad_prod = (p.get("unidad_medida") or "").strip()
    pedi = round(por_unidad.pop(unidad_prod, 0.0), 2)

    proveedor = (proveedor or "").strip() or None
    if proveedor is None:
        origen = "sin_origen"
    elif proveedor_canon.es_compra_directa(proveedor):
        origen = "directa"
    else:
        origen = "proveedor"
    return {
        "producto_id": p.get("producto_id"),
        "producto": p.get("producto_nombre"),
        "unidad": p.get("unidad_medida"),
        "categoria": p.get("categoria"),
        "proveedor": proveedor,
        "origen": origen,
        # Lo que el dueño pidió por escrito en el rango. 0 significa que no le
        # pidió nada a nadie, no que el sistema no lo sepa: desde que «Armar
        # pedido» guarda lo que manda, la ausencia es un dato.
        "pedi": pedi,
        "pedi_n_pedidos": len(ped.get("pedidos") or ()),
        "pedi_proveedores": sorted(ped.get("proveedores") or ()),
        "pedi_otras_unidades": {u: round(c, 2) for u, c in por_unidad.items() if c},
        "entradas": entradas,
        # Lo que entró SIN comprarse: aparte, para que una tanda preparada no se
        # lea como mercadería que alguien facturó.
        "traslados_recibidos": _num(p.get("traslados_recibidos")),
        "preparaciones_producidas": _num(p.get("preparaciones_producidas")),
        **salidas,
        "total_salio": sum(salidas.values()),
        "ajustes_conteo": _num(p.get("ajustes_conteo")),
        "ajustes": _num(p.get("ajustes")),
        "queda": _num(p.get("stock_esperado")),
        "valor_unitario": vu,
        "valor_origen": p.get("valor_origen"),
        "valor_sin_causa": round(salidas["otras_salidas"] * vu, 2),
        "valor_total_salio": round(sum(salidas.values()) * vu, 2),
        "arranque_estimado": bool(p.get("stock_inicial_estimado")),
        # Se exige que TAMPOCO haya preparaciones: un insumo que solo se consume
        # preparando (la leche en polvo del granizado) vende cero y SÍ está
        # medido — marcarlo mandaría a revisar un agujero que no existe.
        "no_se_mide": (entradas > 0 and salidas["ventas"] == 0
                       and salidas["preparaciones"] == 0),
    }


@router.get("/movimiento-insumos")
def movimiento_insumos(
    tienda_id: int = Query(...),
    desde: date = Query(...),
    hasta: date = Query(...),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """La vida de cada insumo en un rango, en una sola tabla: qué entró, por
    dónde salió y qué queda.

    Responde la pregunta con la que el dueño llegó —«tener en un mismo sitio
    control de lo que se pidió, comparado con lo que llegó, y también lo que
    salió, sea por merma, venta o traslado»— reusando la escalera de
    conciliación (`services/conciliacion.py`), que ya clasifica cada movimiento
    del libro por su causa. Acá NO se recalcula nada de eso: se le agrega lo que
    la escalera no sabe, que es DE DÓNDE VIENE cada insumo.

    Ese origen importa porque cambia el significado de la fila: contra un
    proveedor (Cafexcoop) hay pedido, precio acordado y lead time, así que
    comparar lo que salió con lo que entró habla de cumplimiento; en una compra
    directa (Makro, Galerías) no hay pedido que incumplir y la misma resta es,
    en la práctica, la lista de mercado. En producción la compra directa es ~25%
    de la plata: no es un caso de borde.

    Dos cosas que la tabla dice EXPLÍCITAMENTE en vez de dejar un cero mudo:
      · `no_se_mide`: el producto tuvo entradas y el libro no registra ni una
        venta ni una preparación que lo consuma. No es que no se use —los vasos
        y el jabón se gastan todos los días—, es que la caja no los descuenta.
        Un 0 ahí es un agujero de configuración, no una buena noticia. Se pide
        también preparaciones=0 porque un insumo que solo se gasta preparando
        (la leche en polvo del granizado) vende cero y sin embargo SÍ se mide.
      · `ajustes_conteo` viaja SEPARADO del total que salió: un ajuste no es una
        causa de salida, es faltante viejo que apareció al contar. Mezclarlo
        taparía todo lo demás (es el renglón más grande después de las ventas).

    Sin conteo cerrado en el rango, `queda` es la reconstrucción del libro y no
    el conteo físico; `arranque_estimado` avisa cuando ni el arranque se pudo
    reconstruir con certeza.
    """
    ensure_tienda_access(admin, tienda_id)
    if hasta < desde:
        raise HTTPException(400, "El rango termina antes de empezar")

    from app.services import conciliacion as esc
    from app.services import facturas as fact_svc

    escalera = esc.escalera_rango(db, tienda_id, desde, hasta)

    # Origen: el proveedor REAL de las compras del rango, y para los que no se
    # compraron en el rango, el que tenga cargado el producto.
    prov_rango = fact_svc.proveedor_por_producto(db, tienda_id, desde, hasta)
    prov_ficha = {
        pid: (nombre or "").strip()
        for pid, nombre in db.query(Producto.id, Producto.proveedor)
        .filter(Producto.proveedor.isnot(None)).all()
    }

    pedidos = _pedido_por_producto(db, tienda_id,
                                   inicio_dia_col_utc(desde), fin_dia_col_utc(hasta))

    filas = [
        _fila_insumo(p, prov_rango.get(p.get("producto_id"))
                     or prov_ficha.get(p.get("producto_id")),
                     pedidos.get(p.get("producto_id")))
        for p in escalera.get("productos", [])
    ]

    # Más plata sin explicar primero: es el orden en el que conviene mirarlas.
    filas.sort(key=lambda f: (-f["valor_sin_causa"], -f["total_salio"]))

    return {
        "tienda_id": tienda_id,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "insumos": filas,
        "resumen": {
            "n_insumos": len(filas),
            "n_sin_causa": sum(1 for f in filas if f["otras_salidas"] > 0),
            "valor_sin_causa": round(sum(f["valor_sin_causa"] for f in filas), 2),
            "n_no_se_mide": sum(1 for f in filas if f["no_se_mide"]),
            "n_compra_directa": sum(1 for f in filas if f["origen"] == "directa"),
            # Cuántos insumos tienen pedido escrito en el rango. Sirve para que la
            # pantalla sepa si la columna «pedí» tiene algo que contar todavía: en
            # los rangos anteriores a que «Armar pedido» guardara, es cero para
            # todos, y una columna vacía sin explicación se lee como un bug.
            "n_con_pedido": sum(1 for f in filas if f["pedi"] > 0),
        },
    }

# Tope de movimientos que devuelve la ficha. Un insumo de alta rotación tiene
# cientos por mes (el café de Vida hizo ~500 en dos semanas) y traerlos todos no
# ayuda a nadie: la ficha responde «qué pasó», no es un export contable. Cuando
# se recorta, la respuesta lo DICE (`movimientos_truncados`) en vez de mostrar
# una lista incompleta que parece completa.
_MAX_MOVS_FICHA = 250


@router.get("/insumo/{producto_id}/ficha")
def ficha_insumo(
    producto_id: int,
    tienda_id: int = Query(...),
    desde: date = Query(...),
    hasta: date = Query(...),
    causa: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: Usuario = Depends(require_admin),
):
    """La vida de UN insumo en un rango: qué hacía falta, qué llegó, por dónde
    salió y qué queda — más los movimientos uno por uno.

    Es el detalle detrás de una fila de `/movimiento-insumos`, y los totales son
    LOS MISMOS (los arma `_fila_insumo`, compartida): si la ficha recalculara por
    su cuenta, el día que se agregue un renglón la tabla y la ficha dirían cosas
    distintas del mismo producto.

    Lo que agrega sobre la fila:

      · `pedi` — lo que el DUEÑO pidió por escrito, contra lo que llegó. Existe
        desde que «Armar pedido» guarda el pedido que manda
        (`services/pedidos.registrar_pedido`): antes el pedido se iba por
        WhatsApp y no quedaba en ninguna parte, y esta ficha lo decía con todas
        las letras. Solo suma lo pedido en la unidad DEL PRODUCTO —la única en la
        que restarlo contra una factura significa algo—; lo pedido en otra unidad
        viaja aparte en vez de desaparecer.

      · `hacia_falta` — lo que el sistema CALCULA que hay que reponer, que no es
        lo mismo que lo que el dueño decidió pedir. Las dos cifras conviven a
        propósito: la diferencia entre ellas es el criterio de quien compra
        (aprovechar una promoción, cubrir un puente, no fiarse de un proveedor
        flojo), y aplanarla en un solo número escondería justamente eso. Sale del
        MOTOR de pedidos (`_items_base`), la única fórmula de consumo del
        sistema, para no inventar una segunda.

      · `pedido_escrito` — la bitácora de TODO lo que se pidió por escrito, del
        dueño y del kiosko, cada línea con su origen. Lo del kiosko no se suma
        nunca: la barista teclea la unidad libre y el azúcar aparece como «2
        bolsa», «2 unidad» y «5000 gr» en la misma semana. Y en una solicitud del
        kiosko «aprobada» es un sello, no un envío: aprobar no toca stock ni
        genera pedido.

      · `movimientos` — cada movimiento con su causa puesta por el MISMO
        clasificador de la escalera (`conciliacion._bucket`), para que el detalle
        y los totales no puedan contradecirse.

    `causa` filtra esa lista (ventas, entradas, mermas, otras_salidas…). NO es un
    lujo: un insumo de alta rotación tiene miles de movimientos y casi todos son
    ventas de a 10 gr, así que los más recientes TAPAN exactamente lo que se
    vino a mirar. El café de Vida tiene 2.561 movimientos en dos meses y sus 250
    últimos son 239 ventas: sin filtro, «¿de dónde salieron los 14.480 gr sin
    causa?» no se puede contestar desde la ficha. `causas` viene siempre con el
    conteo de CADA causa sobre el rango completo, para que la pantalla ofrezca
    los filtros sin una segunda llamada y sin mentir sobre cuántos hay.
    """
    ensure_tienda_access(admin, tienda_id)
    if hasta < desde:
        raise HTTPException(400, "El rango termina antes de empezar")
    prod = db.query(Producto).filter(Producto.id == producto_id).first()
    if not prod:
        raise HTTPException(404, "Producto no encontrado")

    from app.services import conciliacion as esc
    from app.services import facturas as fact_svc
    from app.services import pedidos as ped_svc

    # ── El renglón de la escalera, igual que en la tabla ────────────────────
    escalera = esc.escalera_rango(db, tienda_id, desde, hasta)
    crudo = next((p for p in escalera.get("productos", [])
                  if p.get("producto_id") == producto_id), None)
    prov_rango = fact_svc.proveedor_por_producto(db, tienda_id, desde, hasta)
    proveedor = prov_rango.get(producto_id) or (prod.proveedor or "").strip() or None
    pedido = _pedido_por_producto(db, tienda_id, inicio_dia_col_utc(desde),
                                  fin_dia_col_utc(hasta), [producto_id]).get(producto_id)
    if crudo is None:
        # Un producto sin fila de inventario en esta sede no tiene escalera: se
        # responde la ficha vacía en vez de un 404, porque la pregunta («¿qué
        # pasó con esto acá?») tiene una respuesta legítima: nada.
        fila = _fila_insumo({"producto_id": producto_id, "producto_nombre": prod.nombre,
                             "unidad_medida": prod.unidad_medida}, proveedor, pedido)
    else:
        fila = _fila_insumo(crudo, proveedor, pedido)

    # ── Hacía falta ─────────────────────────────────────────────────────────
    sugerido = None
    try:
        items, _ = ped_svc._items_base(db, tienda_id)
        sugerido = next((i for i in items if i["producto_id"] == producto_id), None)
    except Exception:
        logger.exception("No se pudo calcular la sugerencia de pedido del insumo %s", producto_id)
    cpe = float(prod.contenido_por_empaque or 0) or None
    a_pedir = float(sugerido["cantidad_sugerida"]) if sugerido else None
    hacia_falta = {
        # Reponer lo que salió: es el MISMO total que muestra el bloque «salió»,
        # no un segundo número que lo contradiga.
        "para_reponer": fila["total_salio"],
        "se_compro": fila["entradas"],
        "hoy_hay_que_pedir": a_pedir,
        "empaques_sugeridos": (round(a_pedir / cpe, 1) if (a_pedir and cpe) else None),
        "contenido_por_empaque": cpe,
        "consumo_diario": (sugerido or {}).get("consumo_diario"),
        "dias_restantes": (sugerido or {}).get("dias_restantes"),
        "estado": (sugerido or {}).get("estado"),
        "accion": (sugerido or {}).get("accion"),
        "tandas_sugeridas": (sugerido or {}).get("tandas_sugeridas"),
        "stock_minimo": (sugerido or {}).get("stock_minimo"),
        "lead_time_dias": (sugerido or {}).get("lead_time_dias"),
    }

    d_utc, h_utc = inicio_dia_col_utc(desde), fin_dia_col_utc(hasta)

    # ── Llegó: las facturas del rango que traen este producto ───────────────
    fc_fecha = func.coalesce(FacturaCompra.fecha_recibido, FacturaCompra.fecha_registro)
    facturas = [
        {
            "factura_id": fid,
            "fecha": (fecha.isoformat() if fecha else None),
            "proveedor": prov,
            "numero_factura": nro,
            "cantidad": float(cant or 0),
            "precio_unitario": (float(pu) if pu is not None else None),
            "total": round(float(cant or 0) * float(pu or 0), 2) if pu is not None else None,
        }
        for fid, fecha, prov, nro, cant, pu in (
            db.query(FacturaCompra.id, fc_fecha, FacturaCompra.proveedor,
                     FacturaCompra.numero_factura, FacturaCompraItem.cantidad,
                     FacturaCompraItem.precio_unitario)
            .join(FacturaCompraItem, FacturaCompraItem.factura_id == FacturaCompra.id)
            .filter(FacturaCompraItem.producto_id == producto_id,
                    FacturaCompra.tienda_id == tienda_id,
                    fc_fecha >= d_utc, fc_fecha <= h_utc)
            .order_by(fc_fecha.asc()).all()
        )
    ]
    total_facturado = sum(f["cantidad"] for f in facturas)
    llego = {
        "facturas": facturas,
        "con_factura": total_facturado,
        # Entró al libro pero no hay factura que lo respalde: mercadería cargada
        # a mano. Se muestra aparte porque es la puerta de atrás del inventario.
        "sin_papel": round(fila["entradas"] - total_facturado, 2),
        "vino_de_la_otra_sede": fila["traslados_recibidos"],
        "se_produjo_aca": fila["preparaciones_producidas"],
    }

    # ── Lo que se pidió por escrito ─────────────────────────────────────────
    # Bitácora de las dos clases de pedido, cada línea con su origen. Las del
    # dueño SÍ se suman (arriba, en `pedi`, y solo en la unidad del producto);
    # las del kiosko no se suman nunca. Se muestran juntas porque para quien mira
    # la ficha son la misma pregunta —«¿alguien pidió esto?»— y separarlas en dos
    # listas obligaría a leer dos veces para contestarla.
    pedido_escrito = [
        {
            "solicitud_id": sid,
            "fecha": (f.isoformat() if f else None),
            "cantidad": float(cant or 0),
            "unidad": (unidad or prod.unidad_medida),
            "estado": getattr(estado, "value", estado),
            # Las filas anteriores a la columna son todas del kiosko: era lo
            # único que existía. Ver `models.SolicitudPedido`.
            "origen": origen or ORIGEN_KIOSKO,
            "proveedor": (proveedor_ped or "").strip() or None,
        }
        for sid, f, cant, unidad, estado, origen, proveedor_ped in (
            db.query(SolicitudPedido.id, SolicitudPedido.fecha_solicitud,
                     SolicitudPedidoItem.cantidad_solicitada,
                     SolicitudPedidoItem.unidad_solicitada, SolicitudPedido.estado,
                     SolicitudPedido.origen, SolicitudPedido.proveedor)
            .join(SolicitudPedidoItem, SolicitudPedidoItem.solicitud_id == SolicitudPedido.id)
            .filter(SolicitudPedidoItem.producto_id == producto_id,
                    SolicitudPedido.tienda_id == tienda_id,
                    SolicitudPedido.fecha_solicitud >= d_utc,
                    SolicitudPedido.fecha_solicitud <= h_utc)
            .order_by(SolicitudPedido.fecha_solicitud.asc()).all()
        )
    ]

    # ── Pedí vs. llegó ──────────────────────────────────────────────────────
    # La comparación que el dueño vino a buscar, y la razón de que el pedido se
    # guarde. `diferencia` es lo que FALTÓ (positivo = trajeron de menos), contra
    # lo que entró CON FACTURA: la mercadería cargada a mano no respalda un
    # pedido, y contarla acá haría cuadrar pedidos que nadie cumplió.
    pedi_llego = {
        "pedi": fila["pedi"],
        "n_pedidos": fila["pedi_n_pedidos"],
        "proveedores": fila["pedi_proveedores"],
        "en_otra_unidad": fila["pedi_otras_unidades"],
        "llego_con_factura": total_facturado,
        "diferencia": round(fila["pedi"] - total_facturado, 2) if fila["pedi"] else 0.0,
    }

    # ── Los movimientos, con la causa del MISMO clasificador de la escalera ──
    # La causa se calcula en Python (sale del texto del motivo), así que el
    # filtro no puede ir en el WHERE: se traen las filas del producto en el
    # rango —son de un solo insumo, no de la sede entera— y se clasifican acá.
    crudos = (
        db.query(MovimientoInventario)
        .filter(MovimientoInventario.producto_id == producto_id,
                MovimientoInventario.tienda_id == tienda_id,
                MovimientoInventario.fecha >= d_utc,
                MovimientoInventario.fecha <= h_utc)
        .order_by(MovimientoInventario.fecha.desc())
        .all()
    )
    todos = [
        {
            "id": m.id,
            "fecha": m.fecha.isoformat() if m.fecha else None,
            "tipo": getattr(m.tipo, "value", m.tipo),
            "cantidad": float(m.cantidad or 0),
            "motivo": m.motivo,
            "causa": esc._bucket(getattr(m.tipo, "value", m.tipo), m.motivo),
            "barista": m.barista_nombre,
        }
        for m in crudos
    ]
    # El conteo por causa se hace SIEMPRE sobre el rango completo, aunque haya
    # filtro: si contara solo lo filtrado, los chips dirían que hay 1 movimiento
    # de cada otra causa.
    causas: dict[str, int] = {}
    for m in todos:
        causas[m["causa"]] = causas.get(m["causa"], 0) + 1

    filtrados = [m for m in todos if m["causa"] == causa] if causa else todos
    total_movs = len(filtrados)
    movimientos = filtrados[:_MAX_MOVS_FICHA]

    return {
        "producto": {
            "id": prod.id,
            "nombre": prod.nombre,
            "unidad": prod.unidad_medida,
            "categoria": getattr(prod.categoria, "value", None) or str(prod.categoria or ""),
            "contenido_por_empaque": cpe,
            "proveedor": fila["proveedor"],
            "origen": fila["origen"],
        },
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "resumen": fila,
        "hacia_falta": hacia_falta,
        "pedi_llego": pedi_llego,
        "llego": llego,
        "pedido_escrito": pedido_escrito,
        "movimientos": movimientos,
        "movimientos_total": total_movs,
        "movimientos_truncados": total_movs > len(movimientos),
        "causas": causas,
        "causa_filtrada": causa,
    }
