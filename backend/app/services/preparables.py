"""Qué es un PREPARABLE — la definición, en UN solo lugar.

Un preparable es el producto que se ARMA en la barra con una receta y que nadie
vende hecho: la mezcla de granizado, el almíbar. Tres condiciones, las tres a la
vez:

  1. `controla_stock` — tiene existencia física que se cuenta;
  2. `precio_venta` <= 0 (o NULL) — no se vende en el POS;
  3. tiene receta PROPIA — hay filas en `producto_insumos.producto_id`.

La condición 3 es la que separa un preparable de un insumo cualquiera que no se
vende (el azúcar también controla stock y tiene precio_venta 0, pero no tiene
receta propia: se compra).

Esta definición vivía COPIADA en `inventario.get_preparables` y en
`conciliacion._rendimiento_preparables`. El motor de pedidos (`pedidos.py`) es su
tercer consumidor, y una tercera copia habría sido la que se desincroniza: el día
que alguien agregue una condición, dos pantallas la tendrían y una no. Vive acá y
las tres la importan.
"""
from sqlalchemy.orm import Session

from app.models.models import Producto, ProductoInsumo


def ids_preparables(db: Session) -> set[int]:
    """Los producto_id que cumplen las tres condiciones. Sin sede: ser preparable
    es una propiedad del catálogo, no del inventario de una tienda."""
    con_receta = {pid for pid, in db.query(ProductoInsumo.producto_id).distinct().all()}
    if not con_receta:
        return set()
    return {
        pid
        for pid, controla, venta in db.query(
            Producto.id, Producto.controla_stock, Producto.precio_venta
        ).filter(Producto.id.in_(con_receta)).all()
        if controla and float(venta or 0) <= 0
    }


def rendimiento_por_tanda(db: Session) -> dict[int, float]:
    """producto_id → cuánto rinde UNA tanda, SOLO de los preparables.

    `Producto.contenido_por_unidad` tiene DOS significados en el catálogo
    (models.py:276): el rendimiento de una preparación, y los gramos que trae la
    bolsa sellada del conteo a granel. Solo en un preparable significa
    rendimiento, así que dividir por él a ciegas rompería la cuenta de cualquier
    producto de reventa que venga en bolsa. Acá se devuelve únicamente donde
    significa rendimiento.

    Un preparable sin `contenido_por_unidad` cargado queda en 0.0 — no en None y
    no ausente: el consumidor decide qué hacer con un factor que no existe, pero
    nunca lo inventa.
    """
    ids = ids_preparables(db)
    if not ids:
        return {}
    return {
        pid: float(contenido or 0)
        for pid, contenido in db.query(
            Producto.id, Producto.contenido_por_unidad
        ).filter(Producto.id.in_(ids)).all()
    }
