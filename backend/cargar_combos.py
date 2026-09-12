"""
Carga los COMBOS del POS (precio fijo, grupos de opciones).

- Match por nombre normalizado (sin acentos, mayúsculas, espacios colapsados),
  igual que cargar_menu_venta.py.
- Si el combo existe  -> actualiza precio/orden/activo y sincroniza su estructura.
- Si no existe        -> lo crea junto con su producto SOMBRA (precio_venta=0,
  controla_stock=False: la línea del ticket apunta a él, pero NO aparece en la
  grilla del POS ni descuenta stock).
- Los PRODUCTOS componentes deben existir en la DB: si falta alguno, el script
  falla con la lista de faltantes (no los inventa).
- Cada combo declara EN QUÉ SEDES se vende (clave `sedes`). Antes había una
  constante global `TIENDA_COMBOS = "Vida"` que asociaba TODOS los combos a esa
  única sede, así que un combo de otra sede no se podía cargar sin mover los
  demás. La disponibilidad solo se AGREGA: lo que ya esté habilitado a mano
  desde la pantalla de Combos no se toca (el Combo 03 vive así en las dos).
- Idempotente: correrlo dos veces no duplica nada.

Uso:
    cd backend
    # dev:
    set ENV_FILE=.env.dev && python cargar_combos.py
    # producción: con las variables de entorno de prod cargadas
    python cargar_combos.py

    python cargar_combos.py --dry-run   # muestra qué haría, sin commitear
"""
import sys, os, re, unicodedata

sys.path.append(os.path.dirname(__file__))

from app.models import models  # noqa
from fastapi import HTTPException

from app.models.models import Combo, ComboTienda, Producto, Tienda
from app.services import combos as combos_svc

# Sede por defecto cuando un combo no declara `sedes`. Los combos 01-03 nacieron
# como "solo Vida" y lo siguen siendo de forma explícita.
SEDES_POR_DEFECTO = ["Vida"]

# Estructura: cada opción lista sus productos reales (nombre, cantidad).
# Una opción puede componerse de VARIOS productos (ej. "Americano Grande" =
# Americano Medium + Bebida Agrandada) y un grupo con UNA sola opción es fijo
# (se auto-selecciona, ej. las bebidas del Combo 03).
COMBOS = [
    {
        "nombre": "Combo 01",
        "precio": 9900,
        "orden": 1,
        "sedes": ["Vida"],
        "grupos": [
            {"nombre": "Bebida", "opciones": [
                {"nombre": "Americano Medium", "productos": [("Americano Medium", 1)]},
                {"nombre": "Cafe con Leche", "productos": [("Cafe con Leche", 1)]},
            ]},
            {"nombre": "Acompañamiento", "opciones": [
                {"nombre": "Almojabanas", "productos": [("Almojabanas", 1)]},
                {"nombre": "Croissant Mantequilla", "productos": [("Croissant Mantequilla", 1)]},
            ]},
        ],
    },
    {
        "nombre": "Combo 02",
        "precio": 15900,
        "orden": 2,
        "sedes": ["Vida"],
        "grupos": [
            {"nombre": "Bebida", "opciones": [
                {"nombre": "Cafe Latte", "productos": [("Cafe Latte", 1)]},
                # Opción compuesta: DOS productos reales detrás de un solo display
                {"nombre": "Americano Grande", "productos": [
                    ("Americano Medium", 1), ("Bebida Agrandada", 1)]},
            ]},
            {"nombre": "Acompañamiento", "opciones": [
                {"nombre": "Pastel de Pollo", "productos": [("Pastel de Pollo", 1)]},
                {"nombre": "Esponjado de Queso", "productos": [("Esponjado de Queso", 1)]},
            ]},
        ],
    },
    {
        "nombre": "Combo 03",
        "precio": 27900,
        "orden": 3,
        "sedes": ["Vida"],
        "grupos": [
            # Grupo FIJO: una sola opción → sin elección, ×2 cappuccinos
            {"nombre": "Bebidas", "opciones": [
                {"nombre": "Cappuccino Tradicional Medium x2", "productos": [
                    ("Cappuccino Tradicional Medium", 2)]},
            ]},
            {"nombre": "Torta", "opciones": [
                {"nombre": "Torta Naranja", "productos": [("Torta Naranja", 1)]},
                {"nombre": "Torta Chocolate", "productos": [("Torta Chocolate", 1)]},
            ]},
        ],
    },
    {
        # Pedido del dueño para Palmetto. Los dos grupos son FIJOS (una sola
        # opción cada uno): no hay nada que elegir, así que el POS los
        # auto-selecciona y el combo se vende de un toque.
        #
        # OJO con el nombre de la bebida: el pedido decía «mokaccino
        # tradicional» y en el catálogo NO existe ese producto. El único
        # mokaccino sin sabor agregado es «Mokaccino Medium» ($12.900) — los
        # demás son Canela, Vainilla, Macadamia, Baileys, Amaretto, Vienes. Se
        # asume ese. Si la bebida era otra, es cambiar este nombre y volver a
        # correr el script (es idempotente).
        #
        # Suelto: 12.900 + 7.900 = 20.800 → el combo a 18.000 descuenta 2.800.
        "nombre": "Combo Borondo",
        "precio": 18000,
        "orden": 4,
        "sedes": ["Palmetto"],
        "grupos": [
            {"nombre": "Bebida", "opciones": [
                {"nombre": "Mokaccino Medium", "productos": [("Mokaccino Medium", 1)]},
            ]},
            {"nombre": "Acompañamiento", "opciones": [
                {"nombre": "Croissant Mantequilla", "productos": [("Croissant Mantequilla", 1)]},
            ]},
        ],
    },
]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def run(dry_run: bool = False, db=None):
    """db=None → sesión propia contra la DB configurada (create_all incluido).
    Con `db` explícito (tests) usa esa sesión y no toca el engine global."""
    own_session = db is None
    if own_session:
        from app.database import SessionLocal, engine
        models.Base.metadata.create_all(bind=engine)
        db = SessionLocal()
    try:
        productos_idx = {norm(p.nombre): p for p in db.query(Producto).all()}

        # Validar que TODOS los productos componentes existan (no se inventan)
        referenciados = {
            nombre
            for cdef in COMBOS
            for gdef in cdef["grupos"]
            for odef in gdef["opciones"]
            for nombre, _ in odef["productos"]
        }
        faltantes = sorted(n for n in referenciados if norm(n) not in productos_idx)
        if faltantes:
            raise ValueError(
                "Productos NO encontrados en la DB (crearlos primero o corregir el nombre): "
                + ", ".join(faltantes)
            )

        # Un combo sin grupos (o con grupos sin opciones) sería vendible a precio
        # completo sin entregar ni descontar nada — se aborta antes de crear.
        sin_grupos = sorted(
            cdef["nombre"] for cdef in COMBOS
            if not cdef.get("grupos") or any(not g.get("opciones") for g in cdef["grupos"])
        )
        if sin_grupos:
            raise ValueError(
                "Combos sin grupos de opciones definidos (o con grupos vacíos): "
                + ", ".join(sin_grupos)
            )

        tiendas_idx = {norm(t.nombre): t for t in db.query(Tienda).all()}
        # Las sedes se validan TODAS de una, antes de crear nada: un nombre mal
        # escrito tiene que frenar el script, no dejar un combo creado y sin
        # sede (vendible en ninguna parte y sin que nadie se entere).
        sedes_por_combo = {
            cdef["nombre"]: list(cdef.get("sedes") or SEDES_POR_DEFECTO)
            for cdef in COMBOS
        }
        sedes_malas = sorted({
            nombre for sedes in sedes_por_combo.values()
            for nombre in sedes if norm(nombre) not in tiendas_idx
        })
        if sedes_malas:
            raise ValueError(
                "Sedes NO encontradas en la DB (corregir el nombre): "
                + ", ".join(sedes_malas)
                + " — disponibles: " + ", ".join(sorted(t.nombre for t in tiendas_idx.values()))
            )
        sin_sede = sorted(n for n, sedes in sedes_por_combo.items() if not sedes)
        if sin_sede:
            raise ValueError(
                "Combos sin ninguna sede: no se venderían en ninguna parte — "
                + ", ".join(sin_sede)
            )

        # Validación PREVIA de todas las definiciones: una corrida que crea dos
        # combos y aborta en el tercero deja el trabajo a medias y hay que
        # deshacerlo a mano. El servicio habla en HTTPException porque lo usa la
        # API; acá, que es una consola, se traduce.
        for cdef in COMBOS:
            definicion_seca = {
                "nombre": cdef["nombre"], "precio": cdef["precio"],
                "orden": cdef["orden"],
                "grupos": [
                    {"nombre": g["nombre"], "opciones": [
                        {"nombre": o["nombre"], "productos": [
                            {"producto_id": productos_idx[norm(n)].id, "cantidad": c}
                            for n, c in o["productos"]]}
                        for o in g["opciones"]]}
                    for g in cdef["grupos"]],
            }
            try:
                combos_svc.validar_definicion(definicion_seca)
                combos_svc.verificar_sombra(db, cdef["nombre"])
            except HTTPException as e:
                raise ValueError(f"{cdef['nombre']}: {e.detail}") from e

        creados, actualizados, sin_cambio = 0, 0, 0

        # El armado del combo (sombra, grupos, opciones, productos) vive en
        # `services/combos.sincronizar_combo`: la MISMA función que usa el
        # endpoint de la app. Estaba acá adentro, y por eso crear un combo
        # obligaba a correr este script en el servidor. Dos copias de esta
        # lógica se habrían separado enseguida.
        for cdef in COMBOS:
            definicion = {
                "nombre": cdef["nombre"],
                "precio": cdef["precio"],
                "orden": cdef["orden"],
                "grupos": [
                    {"nombre": gdef["nombre"], "opciones": [
                        {"nombre": odef["nombre"], "productos": [
                            {"producto_id": productos_idx[norm(nombre)].id,
                             "cantidad": cant}
                            for nombre, cant in odef["productos"]]}
                        for odef in gdef["opciones"]]}
                    for gdef in cdef["grupos"]],
            }
            combo, estado = combos_svc.sincronizar_combo(db, definicion, log=print)
            if estado == "creado":
                creados += 1
            elif estado == "actualizado":
                actualizados += 1
            else:
                sin_cambio += 1

            # ── Disponibilidad: las sedes que declara ESTE combo.
            # Solo se AGREGA. No se quita lo que no esté en la lista: la
            # pantalla de Combos también habilita sedes a mano (así vive hoy el
            # Combo 03 en las dos), y borrar acá apagaría en silencio un combo
            # que alguien prendió desde la app.
            for nombre_sede in sedes_por_combo[cdef["nombre"]]:
                t = tiendas_idx[norm(nombre_sede)]
                asociado = db.query(ComboTienda).filter(
                    ComboTienda.combo_id == combo.id,
                    ComboTienda.tienda_id == t.id,
                ).first()
                if not asociado:
                    db.add(ComboTienda(combo_id=combo.id, tienda_id=t.id))
                    print(f"    + tienda  {combo.nombre} -> {t.nombre}")

        if dry_run:
            db.rollback()
            print("\n[DRY-RUN] nada commiteado.")
        else:
            db.commit()

        print(f"\n[OK] Combos creados      : {creados}")
        print(f"[OK] Combos actualizados : {actualizados}")
        print(f"[OK] Sin cambio          : {sin_cambio}")
        for nombre_combo, sedes in sedes_por_combo.items():
            print(f"[OK] {nombre_combo:16} -> {', '.join(sedes)}")

    except Exception:
        db.rollback()
        raise
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
