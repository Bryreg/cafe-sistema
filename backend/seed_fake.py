#!/usr/bin/env python3
"""
seed_fake.py — Datos de prueba realistas para revisar alertas, movimientos,
               interfaz, colores y posibles bugs del sistema.

Uso:
    cd backend
    python seed_fake.py           # idempotente: salta si ya hay 6+ turnos
    python seed_fake.py --force   # borra y resembra desde cero por tienda
"""

import os, sys, json as _json, random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Carga .env local si existe
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from app.database import SessionLocal, engine
from sqlalchemy import text as _text
from app.models.models import (
    Tienda, Usuario, Producto, Inventario, LoteInventario,
    CajaTurno, VentaDiaria, MovimientoCaja, Consignacion,
    ConteoFisico, ConteoFisicoItem, Merma,
    SolicitudPedido, SolicitudPedidoItem, SolicitudSencilla,
    FacturaCompra, FacturaCompraItem,
    ChecklistDiario, PasteleriaDiaria, Comunicado,
    EstadoTurnoEnum, EstadoConsignacionEnum, TipoMovCajaEnum,
    TipoConteoEnum, EstadoSolicitudEnum, TipoPagoEnum,
    TipoMovInvEnum, MovimientoInventario,
)

# Migración inline idempotente
with engine.connect() as _c:
    for _sql in [
        "ALTER TABLE consignaciones ADD COLUMN caja_turno_id INTEGER REFERENCES caja_turnos(id)",
    ]:
        try:
            _c.execute(_text(_sql)); _c.commit()
        except Exception:
            _c.rollback()

FORCE = "--force" in sys.argv
rng   = random.Random(42)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def r_int(a, b):      return rng.randint(a, b)
def r_f(a, b):        return round(rng.uniform(a, b), 1)
def r_pick(lst):      return rng.choice(lst)
def r_sample(lst, k): return rng.sample(lst, min(k, len(lst)))

def qty(p) -> int:
    """Cantidad inicial realista para un producto según su unidad y categoría."""
    u = p.unidad_medida
    c = p.categoria.value if hasattr(p.categoria, 'value') else str(p.categoria)
    if u == 'g':
        nombre = p.nombre.lower()
        if 'cafe' in nombre or 'caf' in nombre:
            return r_int(1000, 6000)
        if 'velino' in nombre or 'saborizante' in nombre:
            return r_int(400, 1800)
        if 'leche' in nombre and 'polvo' in nombre:
            return r_int(1500, 5000)
        if 'condensada' in nombre:
            return r_int(800, 4000)
        if 'salsa' in nombre:
            return r_int(300, 3500)
        if 'milo' in nombre or 'oreo' in nombre or 'galleta' in nombre:
            return r_int(300, 2500)
        if 'azucar' in nombre or 'azúcar' in nombre:
            return r_int(500, 5000)
        if 'chai' in nombre:
            return r_int(300, 900)
        if 'licor' in nombre:
            return r_int(200, 1500)
        if 'sour' in nombre or 'crema' in nombre:
            return r_int(100, 500)
        return r_int(200, 2000)
    elif c == 'pasteleria':
        return r_int(0, 60)
    else:
        return r_int(5, 80)

PROVEEDORES = [
    "Cafe del Huila S.A.", "Distribuidora Lacteos Andina", "Panaderia La Canasta",
    "Envases & Mas", "Aromaticas del Campo", "Industrias Dulces S.A.",
    "Suministros Cafeteros Ltda", "Frutas & Pulpas Express",
]

CONCEPTOS_EGRESO = [
    "Domicilio mercado barrio", "Compra urgente cafe molido", "Transporte domicilio",
    "Pago moto mensajero", "Compra hielo bolsa", "Materiales limpieza maquina",
    "Propina domiciliario", "Caja chica papeleria", "Recarga gas",
]

MOTIVOS_MERMA = [
    "Producto vencido", "Dano en manipulacion", "Contaminacion cruzada",
    "Error de preparacion", "Derrame accidental", "Producto caido al piso",
]

# Motivos coherentes para solicitud de sencilla (cambio de dinero)
MOTIVOS_SENCILLA = [
    "La caja se quedo sin sencilla para dar cambio",
    "Sin monedas para el turno, clientes pagando con billetes grandes",
    "Se agotaron los billetes de $5.000 y $10.000 en caja",
    "Necesito sencilla antes del almuerzo, mucho movimiento hoy",
    "Caja solo tiene billetes de $50.000, necesito cambio urgente",
]


def generar_detalle_sencilla() -> tuple[str, int]:
    """Genera un desglose realista de billetes y retorna (detalle_json, monto_total)."""
    opciones = [
        (10000, "billete", "$10.000"),
        (5000,  "billete", "$5.000"),
        (2000,  "billete", "$2.000"),
        (1000,  "billete", "$1.000"),
    ]
    items = []
    total = 0
    for val, tipo, label in opciones:
        cant = r_int(0, 5)
        if cant == 0:
            continue
        m = cant * val
        items.append({"label": label, "tipo": tipo, "valor": val, "monto": m, "cantidad": cant})
        total += m
    if total == 0:
        items.append({"label": "$10.000", "tipo": "billete", "valor": 10000, "monto": 20000, "cantidad": 2})
        total = 20000
    return _json.dumps(items), total


# ─── Limpieza por tienda (solo con --force) ───────────────────────────────────

def limpiar_tienda(db, tienda_id: int):
    """Borra todos los datos sembrados para una tienda, en orden FK-seguro."""
    from sqlalchemy import delete

    # Solicitudes
    sol_ids = [r[0] for r in db.execute(
        _text("SELECT id FROM solicitudes_pedido WHERE tienda_id = :t"), {"t": tienda_id}
    ).fetchall()]
    if sol_ids:
        db.execute(_text(
            f"DELETE FROM solicitudes_pedido_items WHERE solicitud_id IN ({','.join(str(i) for i in sol_ids)})"
        ))
    db.execute(_text("DELETE FROM solicitudes_pedido   WHERE tienda_id = :t"), {"t": tienda_id})
    db.execute(_text("DELETE FROM solicitudes_sencilla WHERE tienda_id = :t"), {"t": tienda_id})

    # Conteos fisicos
    ct_ids = [r[0] for r in db.execute(
        _text("SELECT id FROM conteos_fisicos WHERE tienda_id = :t"), {"t": tienda_id}
    ).fetchall()]
    if ct_ids:
        db.execute(_text(
            f"DELETE FROM conteos_fisicos_items WHERE conteo_id IN ({','.join(str(i) for i in ct_ids)})"
        ))
    db.execute(_text("DELETE FROM conteos_fisicos WHERE tienda_id = :t"), {"t": tienda_id})

    # Turnos y todo lo que cuelga de ellos
    turno_ids = [r[0] for r in db.execute(
        _text("SELECT id FROM caja_turnos WHERE tienda_id = :t"), {"t": tienda_id}
    ).fetchall()]
    if turno_ids:
        ids_str = ",".join(str(i) for i in turno_ids)
        db.execute(_text(f"DELETE FROM ventas_diarias    WHERE turno_id IN ({ids_str})"))
        db.execute(_text(f"DELETE FROM movimientos_caja  WHERE caja_turno_id IN ({ids_str})"))
        db.execute(_text(f"DELETE FROM consignaciones    WHERE caja_turno_id IN ({ids_str})"))
    db.execute(_text("DELETE FROM consignaciones WHERE tienda_id = :t AND caja_turno_id IS NULL"), {"t": tienda_id})
    db.execute(_text("DELETE FROM caja_turnos    WHERE tienda_id = :t"), {"t": tienda_id})

    # Resto
    db.execute(_text("DELETE FROM mermas             WHERE tienda_id = :t"), {"t": tienda_id})
    db.execute(_text("DELETE FROM pasteleria_diaria  WHERE tienda_id = :t"), {"t": tienda_id})
    db.execute(_text("DELETE FROM checklist_diario   WHERE tienda_id = :t"), {"t": tienda_id})

    fact_ids = [r[0] for r in db.execute(
        _text("SELECT id FROM facturas_compra WHERE tienda_id = :t"), {"t": tienda_id}
    ).fetchall()]
    if fact_ids:
        db.execute(_text(
            f"DELETE FROM facturas_compra_items WHERE factura_id IN ({','.join(str(i) for i in fact_ids)})"
        ))
    db.execute(_text("DELETE FROM facturas_compra        WHERE tienda_id = :t"), {"t": tienda_id})
    db.execute(_text("DELETE FROM lotes_inventario        WHERE tienda_id = :t"), {"t": tienda_id})
    db.execute(_text("DELETE FROM movimientos_inventario  WHERE tienda_id = :t"), {"t": tienda_id})

    db.flush()
    print(f"  [limpieza] Datos anteriores borrados para tienda {tienda_id}")


# ─── Seed principal ───────────────────────────────────────────────────────────

def seed():
    db = SessionLocal()
    try:
        tiendas = db.query(Tienda).filter(Tienda.activa == True).order_by(Tienda.id).all()
        if not tiendas:
            print("ERROR  No hay tiendas activas.")
            return

        todos_usuarios = db.query(Usuario).filter(Usuario.activo == True).all()
        admin = next((u for u in todos_usuarios if u.rol.value == "admin"), todos_usuarios[0])

        productos_ctrl = db.query(Producto).filter(Producto.controla_stock == True).all()
        prod_pasteleria = [p for p in productos_ctrl if p.categoria.value == "pasteleria"]
        prod_bebida     = [p for p in productos_ctrl if p.categoria.value == "bebida"]
        prod_insumo     = [p for p in productos_ctrl if p.categoria.value == "insumo"]

        if not productos_ctrl:
            print("ERROR  No hay productos. Ejecuta el backend para que el seed de productos corra.")
            return

        print(f"[tiendas]   {[t.nombre for t in tiendas]}")
        print(f"[admin]     {admin.nombre}")
        print(f"[productos] {len(productos_ctrl)} con control de stock")
        if FORCE:
            print("[modo]      --force: se borraran y resembraran los datos por tienda")

        # ── COMUNICADOS ───────────────────────────────────────────────────────
        if db.query(Comunicado).count() == 0:
            db.add_all([
                Comunicado(
                    titulo="URGENTE: revisar diferencia en caja",
                    mensaje="Ayer Palmetto registro una diferencia de $47.000 al cierre. "
                            "Verificar con Catherin el turno del martes antes de las 10 am.",
                    urgente=True, activo=True,
                    fecha_creacion=datetime.utcnow() - timedelta(hours=14),
                    creado_por=admin.id,
                ),
                Comunicado(
                    titulo="Nuevo protocolo limpieza de equipos",
                    mensaje="A partir del lunes aplicamos el nuevo protocolo semanal para la maquina espresso. "
                            "Ver documento en la carpeta compartida. Preguntar a Laura si tienen dudas.",
                    urgente=False, activo=True,
                    fecha_creacion=datetime.utcnow() - timedelta(days=2),
                    creado_por=admin.id,
                ),
                Comunicado(
                    titulo="Recordatorio: cuadre Siigo antes del cierre",
                    mensaje="Favor no olvidar marcar el cuadre de Siigo en el checklist antes de cerrar turno. "
                            "Varias noches de la semana pasada quedo sin marcar.",
                    urgente=False, activo=True,
                    fecha_creacion=datetime.utcnow() - timedelta(days=5),
                    creado_por=admin.id,
                ),
            ])
            db.flush()
            print("[comunicados] 3 creados")

        # ── POR TIENDA ────────────────────────────────────────────────────────
        for tienda in tiendas:
            baristas = [u for u in todos_usuarios
                        if u.tienda_id == tienda.id and u.rol.value == "barista"]
            if not baristas:
                baristas = [u for u in todos_usuarios if u.rol.value == "barista"][:3]

            print(f"\n===  {tienda.nombre}  ({len(baristas)} baristas)  ===")

            ya_tiene_turnos = db.query(CajaTurno).filter(
                CajaTurno.tienda_id == tienda.id,
                CajaTurno.estado    == EstadoTurnoEnum.cerrado,
            ).count()

            if FORCE and ya_tiene_turnos > 0:
                limpiar_tienda(db, tienda.id)
                ya_tiene_turnos = 0

            # ── Inventario: forzar alertas ────────────────────────────────────
            inv_filas = db.query(Inventario).filter(Inventario.tienda_id == tienda.id).all()
            for inv in r_sample(inv_filas, 6):
                inv.stock_actual = max(0, int(inv.stock_minimo * r_f(0.0, 0.7)))
            for inv in r_sample(inv_filas, 3):
                inv.stock_actual = 0
            db.flush()
            print(f"  [inv] 6 productos bajo minimo + 3 agotados")

            if ya_tiene_turnos >= 6:
                print(f"  [skip] Ya tiene {ya_tiene_turnos} turnos — usa --force para resembrar")
                # aun así crear turno de hoy si no existe
            else:
                # ── 7 turnos cerrados (uno por día) ───────────────────────────
                turnos_creados = []
                for dias_atras in range(7, 0, -1):
                    apertura = (datetime.utcnow()
                                .replace(hour=7, minute=0, second=0, microsecond=0)
                                - timedelta(days=dias_atras))
                    cierre   = apertura + timedelta(hours=r_int(8, 11))
                    barista  = r_pick(baristas)

                    total_ventas  = r_int(180_000, 750_000)
                    pct_efec      = r_f(0.52, 0.72)
                    total_efec    = int(total_ventas * pct_efec)
                    total_tarjeta = total_ventas - total_efec
                    base          = r_int(100_000, 200_000)
                    diff_ap       = r_pick([0, 0, 0, r_int(-10_000, 10_000)])

                    turno = CajaTurno(
                        tienda_id           = tienda.id,
                        usuario_apertura_id = barista.id,
                        usuario_cierre_id   = barista.id,
                        fecha_apertura      = apertura,
                        fecha_cierre        = cierre,
                        base_sistema        = base,
                        base_real           = base + diff_ap,
                        diferencia_apertura = diff_ap,
                        total_ventas        = total_ventas,
                        total_efectivo      = total_efec,
                        total_tarjeta       = total_tarjeta,
                        datafono_real       = total_tarjeta + r_int(-25_000, 25_000),
                        estado              = EstadoTurnoEnum.cerrado,
                        tiene_conteo_apertura = True,
                        tiene_ventas          = True,
                        tiene_conteo_cierre   = True,
                        ts_conteo_apertura  = apertura + timedelta(minutes=20),
                        ts_primera_venta    = apertura + timedelta(minutes=45),
                        ts_conteo_cierre    = cierre   - timedelta(minutes=25),
                    )
                    db.add(turno); db.flush()

                    # Ventas
                    nc   = r_int(0, 30_000)
                    vals = r_int(0, 20_000)
                    db.add(VentaDiaria(
                        tienda_id          = tienda.id,
                        turno_id           = turno.id,
                        venta_total        = total_ventas,
                        nota_credito       = nc,
                        vales              = vals,
                        tarjetas           = total_tarjeta,
                        efectivo_calculado = max(0, total_ventas - nc - vals - total_tarjeta),
                        fecha_registro     = cierre - timedelta(minutes=40),
                        usuario_id         = barista.id,
                    ))

                    # Movimientos de caja (egresos realistas)
                    total_egresos = 0
                    for _ in range(r_int(0, 3)):
                        val_eg = r_int(10_000, 80_000)
                        total_egresos += val_eg
                        db.add(MovimientoCaja(
                            caja_turno_id = turno.id,
                            tipo          = TipoMovCajaEnum.egreso,
                            concepto      = r_pick(CONCEPTOS_EGRESO),
                            valor         = val_eg,
                            usuario_id    = barista.id,
                            fecha         = apertura + timedelta(hours=r_int(2, 8)),
                        ))

                    efec_final      = max(0, total_efec - total_egresos)
                    diff_cierre_val = r_pick([0, 0, 0, r_int(-50_000, 50_000)])
                    turno.efectivo_final_real = efec_final + diff_cierre_val
                    turno.diferencia_cierre   = diff_cierre_val
                    turno.diferencia_tarjeta  = r_int(-20_000, 20_000)

                    # Consignaciones (escenarios variados)
                    esperado = max(0, efec_final)
                    if esperado > 5_000:
                        escenario = r_pick(["full_confirmada", "full_confirmada",
                                            "full_pendiente", "parcial", "sin_consignar"])
                        if escenario in ("full_confirmada", "full_pendiente"):
                            db.add(Consignacion(
                                tienda_id     = tienda.id,
                                caja_turno_id = turno.id,
                                valor         = esperado,
                                usuario_id    = barista.id,
                                estado        = (EstadoConsignacionEnum.realizada
                                                 if escenario == "full_confirmada"
                                                 else EstadoConsignacionEnum.pendiente),
                                fecha         = cierre + timedelta(hours=r_int(1, 6)),
                            ))
                        elif escenario == "parcial":
                            db.add(Consignacion(
                                tienda_id     = tienda.id,
                                caja_turno_id = turno.id,
                                valor         = int(esperado * r_f(0.3, 0.7)),
                                usuario_id    = barista.id,
                                estado        = EstadoConsignacionEnum.realizada,
                                fecha         = cierre + timedelta(hours=2),
                            ))
                        # "sin_consignar": sin registro -> aparece en rojo

                    # ── Conteo físico apertura — TODOS los productos controlados ──
                    inv_map = {
                        inv.producto_id: inv.stock_actual
                        for inv in db.query(Inventario).filter_by(tienda_id=tienda.id).all()
                    }
                    conteo_ap = ConteoFisico(
                        tienda_id      = tienda.id,
                        turno_id       = turno.id,
                        tipo           = TipoConteoEnum.apertura,
                        fecha_registro = apertura + timedelta(minutes=20),
                        usuario_id     = barista.id,
                    )
                    db.add(conteo_ap); db.flush()
                    for p in productos_ctrl:
                        sis  = int(inv_map.get(p.id, qty(p)))
                        real = max(0, sis + r_int(-2, 2))
                        db.add(ConteoFisicoItem(
                            conteo_id        = conteo_ap.id,
                            producto_id      = p.id,
                            cantidad_sistema = sis,
                            cantidad_real    = real,
                            diferencia       = real - sis,
                        ))

                    # ── Conteo físico cierre — TODOS los productos controlados ──
                    conteo_ci = ConteoFisico(
                        tienda_id      = tienda.id,
                        turno_id       = turno.id,
                        tipo           = TipoConteoEnum.cierre,
                        fecha_registro = cierre - timedelta(minutes=20),
                        usuario_id     = barista.id,
                    )
                    db.add(conteo_ci); db.flush()
                    for p in productos_ctrl:
                        sis  = int(inv_map.get(p.id, qty(p)))
                        real = max(0, sis - r_int(0, 4))
                        db.add(ConteoFisicoItem(
                            conteo_id        = conteo_ci.id,
                            producto_id      = p.id,
                            cantidad_sistema = sis,
                            cantidad_real    = real,
                            diferencia       = real - sis,
                        ))

                    # Mermas
                    for p in r_sample(productos_ctrl, r_int(1, 3)):
                        cant = r_int(1, 5)
                        db.add(Merma(
                            tienda_id      = tienda.id,
                            producto_id    = p.id,
                            cantidad       = cant,
                            motivo         = r_pick(MOTIVOS_MERMA),
                            tipo           = r_pick(["consumo", "consumo", "dano"]),
                            fecha_registro = apertura + timedelta(hours=r_int(3, 9)),
                            usuario_id     = barista.id,
                        ))
                        db.add(MovimientoInventario(
                            producto_id = p.id,
                            tienda_id   = tienda.id,
                            tipo        = TipoMovInvEnum.salida,
                            cantidad    = cant,
                            motivo      = "Merma registrada",
                            usuario_id  = barista.id,
                            fecha       = apertura + timedelta(hours=r_int(3, 9)),
                        ))

                    # Checklist
                    completo = dias_atras > 2
                    db.add(ChecklistDiario(
                        tienda_id          = tienda.id,
                        fecha              = apertura,
                        apertura_realizada = True,
                        inventario_check   = completo or r_pick([True, False]),
                        pasteleria_check   = completo or r_pick([True, False]),
                        siigo_check        = completo,
                        limpieza_check     = True,
                        cierre_realizado   = True,
                    ))

                    # Pastelería
                    if prod_pasteleria:
                        for p in r_sample(prod_pasteleria, min(6, len(prod_pasteleria))):
                            dias_vc = r_int(-1, 4)
                            fv = apertura + timedelta(days=dias_vc)
                            db.add(PasteleriaDiaria(
                                tienda_id         = tienda.id,
                                producto_id       = p.id,
                                cantidad          = r_int(2, 15),
                                fecha_frescura    = fv,
                                fecha_vencimiento = fv,
                                numero_lote       = f"L{dias_atras:02d}-{r_int(100,999)}",
                                fecha_registro    = apertura + timedelta(hours=1),
                                usuario_id        = barista.id,
                                activo            = dias_vc >= 0,
                            ))

                    turnos_creados.append(turno)

                print(f"  [turnos]  {len(turnos_creados)} turnos cerrados creados")

                # Facturas de compra
                n_facturas = r_int(4, 8)
                for _ in range(n_facturas):
                    prov  = r_pick(PROVEEDORES)
                    fecha = datetime.utcnow() - timedelta(days=r_int(1, 7))
                    items_f = r_sample(productos_ctrl, r_int(2, 5))
                    total_f = sum(r_int(15_000, 120_000) for _ in items_f)
                    fact = FacturaCompra(
                        tienda_id      = tienda.id,
                        proveedor      = prov,
                        numero_factura = f"FV-{r_int(1000,9999)}",
                        numero_lote    = f"L{r_int(10,99)}-{fecha.strftime('%m%d')}",
                        fecha_recibido = fecha,
                        valor_total    = total_f,
                        tipo_pago      = TipoPagoEnum(r_pick(["contado", "credito", "transferencia"])),
                        fecha_registro = fecha,
                        usuario_id     = admin.id,
                    )
                    db.add(fact); db.flush()
                    for p in items_f:
                        cant = qty(p)
                        fv   = fecha + timedelta(days=r_int(15, 90))
                        db.add(FacturaCompraItem(
                            factura_id       = fact.id,
                            producto_id      = p.id,
                            cantidad         = cant,
                            precio_unitario  = round(total_f / len(items_f), 0),
                            numero_lote      = fact.numero_lote,
                            fecha_vencimiento= fv,
                        ))
                        inv_row = db.query(Inventario).filter_by(
                            producto_id=p.id, tienda_id=tienda.id).first()
                        if inv_row:
                            inv_row.stock_actual += cant
                        db.add(MovimientoInventario(
                            producto_id = p.id,
                            tienda_id   = tienda.id,
                            tipo        = TipoMovInvEnum.entrada,
                            cantidad    = cant,
                            motivo      = f"Factura {fact.numero_factura} - {prov}",
                            usuario_id  = admin.id,
                            fecha       = fecha,
                        ))
                        db.add(LoteInventario(
                            producto_id       = p.id,
                            tienda_id         = tienda.id,
                            cantidad_inicial  = cant,
                            cantidad_restante = cant,
                            fecha_entrada     = fecha,
                            fecha_vencimiento = fv,
                            usuario_id        = admin.id,
                        ))
                print(f"  [facturas] {n_facturas} creadas")

                # Solicitudes de pedido
                n_sols = r_int(2, 4)
                notas_pedido = [
                    "Se esta acabando el cafe y el azucar",
                    "Urgente: leche entera casi agotada",
                    "Necesitamos vasos 12oz antes del fin de semana",
                    "Reponer salsas y crema chantilly",
                ]
                for _ in range(n_sols):
                    b = r_pick(baristas)
                    sol = SolicitudPedido(
                        tienda_id       = tienda.id,
                        usuario_id      = b.id,
                        estado          = EstadoSolicitudEnum.pendiente,
                        nota            = r_pick(notas_pedido),
                        fecha_solicitud = datetime.utcnow() - timedelta(hours=r_int(2, 36)),
                    )
                    db.add(sol); db.flush()
                    for p in r_sample(prod_bebida + prod_insumo, r_int(3, 6)):
                        db.add(SolicitudPedidoItem(
                            solicitud_id       = sol.id,
                            producto_id        = p.id,
                            cantidad_solicitada= r_int(2, 15),
                        ))

                # Solicitud sencilla — motivo y detalle coherentes
                detalle_json, monto_real = generar_detalle_sencilla()
                db.add(SolicitudSencilla(
                    tienda_id        = tienda.id,
                    usuario_id       = r_pick(baristas).id,
                    estado           = EstadoSolicitudEnum.pendiente,
                    monto_solicitado = monto_real,
                    motivo           = r_pick(MOTIVOS_SENCILLA),
                    detalle          = detalle_json,
                    fecha_solicitud  = datetime.utcnow() - timedelta(hours=r_int(1, 12)),
                ))
                print(f"  [solicitudes] {n_sols} pedidos + 1 sencilla pendientes")

            # ── Turno abierto hoy ─────────────────────────────────────────────
            turno_hoy = db.query(CajaTurno).filter(
                CajaTurno.tienda_id == tienda.id,
                CajaTurno.estado    == EstadoTurnoEnum.abierto,
            ).first()

            if not turno_hoy:
                barista_hoy  = r_pick(baristas)
                apertura_hoy = datetime.utcnow().replace(hour=7, minute=0, second=0, microsecond=0)
                ventas_hoy   = r_int(80_000, 350_000)
                efec_hoy     = int(ventas_hoy * r_f(0.55, 0.70))
                t_hoy = CajaTurno(
                    tienda_id           = tienda.id,
                    usuario_apertura_id = barista_hoy.id,
                    fecha_apertura      = apertura_hoy,
                    base_sistema        = r_int(100_000, 200_000),
                    base_real           = r_int(100_000, 200_000),
                    diferencia_apertura = 0,
                    total_ventas        = ventas_hoy,
                    total_efectivo      = efec_hoy,
                    total_tarjeta       = ventas_hoy - efec_hoy,
                    estado              = EstadoTurnoEnum.abierto,
                    tiene_conteo_apertura = True,
                    tiene_ventas          = True,
                    tiene_conteo_cierre   = False,
                    ts_conteo_apertura  = apertura_hoy + timedelta(minutes=15),
                    ts_primera_venta    = apertura_hoy + timedelta(minutes=40),
                )
                db.add(t_hoy); db.flush()
                db.add(VentaDiaria(
                    tienda_id          = tienda.id,
                    turno_id           = t_hoy.id,
                    venta_total        = ventas_hoy,
                    nota_credito       = 0,
                    vales              = 0,
                    tarjetas           = ventas_hoy - efec_hoy,
                    efectivo_calculado = efec_hoy,
                    fecha_registro     = datetime.utcnow() - timedelta(minutes=30),
                    usuario_id         = barista_hoy.id,
                ))
                if r_int(0, 1):
                    db.add(MovimientoCaja(
                        caja_turno_id = t_hoy.id,
                        tipo          = TipoMovCajaEnum.egreso,
                        concepto      = r_pick(CONCEPTOS_EGRESO),
                        valor         = r_int(15_000, 60_000),
                        usuario_id    = barista_hoy.id,
                        fecha         = apertura_hoy + timedelta(hours=r_int(1, 5)),
                    ))
                print(f"  [turno hoy] Abierto por {barista_hoy.nombre}")

            # Checklist de hoy
            from sqlalchemy import func as sqlfunc
            hoy = datetime.utcnow().date()
            if not db.query(ChecklistDiario).filter(
                ChecklistDiario.tienda_id == tienda.id,
                sqlfunc.date(ChecklistDiario.fecha) == hoy,
            ).first():
                db.add(ChecklistDiario(
                    tienda_id          = tienda.id,
                    fecha              = datetime.utcnow(),
                    apertura_realizada = True,
                    inventario_check   = False,
                    pasteleria_check   = False,
                    siigo_check        = False,
                    limpieza_check     = False,
                    cierre_realizado   = False,
                ))

        db.commit()
        print("\nOK  Seed completado.")
        print("  -> Dashboard: alertas de inventario, consignaciones y checklist activos.")
        print("  -> Consignaciones admin: ver distintos estados por turno.")
        print("  -> Bandeja: solicitudes de pedido y sencilla pendientes.")
        print("  -> Informes: ventas, mermas, turnos y rotacion con datos.")

    except Exception as exc:
        db.rollback()
        import traceback
        print(f"\nERROR: {exc}")
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    seed()
