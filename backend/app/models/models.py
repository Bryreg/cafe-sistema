from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, Enum as SAEnum, Date, UniqueConstraint, Numeric, Index, text
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from app.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RolEnum(str, enum.Enum):
    admin = "admin"
    barista = "barista"


class EstadoTurnoEnum(str, enum.Enum):
    abierto = "abierto"
    cerrado = "cerrado"


class TipoMovCajaEnum(str, enum.Enum):
    ingreso = "ingreso"
    egreso = "egreso"


class CategoriaProductoEnum(str, enum.Enum):
    pasteleria = "pasteleria"
    bebida = "bebida"
    insumo = "insumo"
    porciones = "porciones"


class TipoMovInvEnum(str, enum.Enum):
    entrada = "entrada"
    salida = "salida"
    ajuste = "ajuste"


class EstadoConsignacionEnum(str, enum.Enum):
    pendiente = "pendiente"
    realizada = "realizada"


class TipoConteoEnum(str, enum.Enum):
    apertura = "apertura"
    cierre = "cierre"
    # Formato de desechables: solo se cuenta cuando el admin lo solicita.
    desechables = "desechables"
    # Existencia ad-hoc: la barista cuenta cuando quiere, sobre todo lo que NO
    # entra al conteo diario (vasos, tapas, helado). Compara vs sistema, no toca stock.
    existencia = "existencia"


class TipoTurnoEnum(str, enum.Enum):
    apertura = "apertura"
    intermedio = "intermedio"
    cierre = "cierre"


class EstadoDiaEnum(str, enum.Enum):
    abierto = "abierto"
    cerrado = "cerrado"


class EstadoSolicitudEnum(str, enum.Enum):
    pendiente = "pendiente"
    aprobada = "aprobada"
    rechazada = "rechazada"


class TipoPagoEnum(str, enum.Enum):
    contado = "contado"
    credito = "credito"
    transferencia = "transferencia"


class TipoMermaEnum(str, enum.Enum):
    consumo = "consumo"
    traslado = "traslado"
    dano = "daño"


class Tienda(Base):
    __tablename__ = "tiendas"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False)
    direccion = Column(String(200))
    activa = Column(Boolean, default=True)
    usuarios = relationship("Usuario", back_populates="tienda")
    turnos = relationship("CajaTurno", back_populates="tienda")
    inventarios = relationship("Inventario", back_populates="tienda")
    movimientos_inv = relationship("MovimientoInventario", back_populates="tienda")
    pastelerias = relationship("PasteleriaDiaria", back_populates="tienda")
    consignaciones = relationship("Consignacion", back_populates="tienda")
    checklists = relationship("ChecklistDiario", back_populates="tienda")
    lotes = relationship("LoteInventario", back_populates="tienda")
    mermas = relationship("Merma", back_populates="tienda", foreign_keys="Merma.tienda_id")
    solicitudes_pedido = relationship("SolicitudPedido", back_populates="tienda")
    solicitudes_sencilla = relationship("SolicitudSencilla", back_populates="tienda")
    notificaciones = relationship("Notificacion", back_populates="tienda")
    facturas_compra = relationship("FacturaCompra", back_populates="tienda")
    conteos_compras = relationship("ConteoCompras", back_populates="tienda")


class ConfigTicket(Base):
    """Datos que aparecen en el ticket impreso del POS, editables por admin."""
    __tablename__ = "config_tickets"
    id              = Column(Integer, primary_key=True)
    tienda_id       = Column(Integer, ForeignKey("tiendas.id"), unique=True, nullable=False)
    nombre_negocio  = Column(String(150), nullable=False, server_default="AZ CAFE")
    nit             = Column(String(30),  nullable=True)
    telefono        = Column(String(30),  nullable=True)
    direccion       = Column(String(250), nullable=True)
    logo_url        = Column(String(500), nullable=True)
    mensaje_footer  = Column(String(300), nullable=True, server_default="¡Gracias por tu compra!")
    # Dimensiones de impresión
    ancho_papel_mm  = Column(Integer, nullable=False, server_default="80")
    escala_fuente   = Column(String(10), nullable=False, server_default="normal")  # small | normal | large
    margen_mm       = Column(Integer, nullable=False, server_default="2")          # margen lateral en mm (0-10)
    tienda          = relationship("Tienda", foreign_keys=[tienda_id])


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    pin_hash = Column(String(255), nullable=True)
    rol = Column(SAEnum(RolEnum), nullable=False, default=RolEnum.barista)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=True)
    activo = Column(Boolean, default=True)
    ultimo_acceso = Column(DateTime, nullable=True)   # Etapa 9: seguridad
    tienda = relationship("Tienda", back_populates="usuarios")
    movimientos_caja = relationship("MovimientoCaja", back_populates="usuario")
    movimientos_inv = relationship("MovimientoInventario", back_populates="usuario")
    ventas_diarias = relationship("VentaDiaria", back_populates="usuario")
    conteos_fisicos = relationship("ConteoFisico", back_populates="usuario")
    mermas = relationship("Merma", back_populates="usuario")
    entregas_turno = relationship("EntregaTurno", back_populates="usuario")
    pastelerias = relationship("PasteleriaDiaria", back_populates="usuario")
    consignaciones = relationship("Consignacion", back_populates="usuario")
    lotes_inventario = relationship("LoteInventario", back_populates="usuario")


class DiaOperativo(Base):
    """Agregado del día operativo: dueño de los turnos de una tienda en una fecha.

    Da continuidad entre turnos (apertura → intermedio → cierre comparten el día)
    y es la raíz sobre la que cuelgan rollups y reportes diarios. Una fila por
    (tienda_id, fecha_operativa). La fecha es la del NEGOCIO (hora local), no UTC,
    para que un cierre pasada la medianoche siga contando en el día correcto.
    """
    __tablename__ = "dias_operativos"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    fecha_operativa = Column(Date, nullable=False, index=True)
    estado = Column(SAEnum(EstadoDiaEnum), default=EstadoDiaEnum.abierto, nullable=False, index=True)
    abierto_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    cerrado_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True)
    fecha_apertura = Column(DateTime, default=datetime.utcnow)
    fecha_cierre = Column(DateTime, nullable=True)
    notas = Column(Text, nullable=True)
    tienda = relationship("Tienda")
    turnos = relationship("CajaTurno", back_populates="dia")
    __table_args__ = (
        UniqueConstraint("tienda_id", "fecha_operativa", name="uq_dia_tienda_fecha"),
    )


class CajaTurno(Base):
    __tablename__ = "caja_turnos"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False, index=True)
    usuario_apertura_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    usuario_cierre_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=True)
    fecha_apertura = Column(DateTime, default=datetime.utcnow)
    fecha_cierre = Column(DateTime, nullable=True)
    base_sistema = Column(Numeric(12, 2, asdecimal=False), default=0.0)
    base_real = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    # Reserva de caja fuerte: efectivo fijo guardado APARTE de la registradora (por si pasa
    # algo extraordinario). Se registra para control pero NO entra en efectivo_esperado ni en
    # el cuadre de la registradora. La base es SOLO el efectivo operativo de la caja.
    #
    # DECLARARLA AL ABRIR ES LO QUE EVITA EL SOBRANTE FANTASMA, y no es teoría:
    # Palmetto, sábado 15-ago. La barista contó la reserva adentro de `base_real`
    # en vez de declararla acá; el sistema leyó los $500.000 como sobrante de
    # apertura y el día pasó a pedir consignar $697.900 en vez de $197.900 — la
    # plata de emergencia de la propia sede rumbo al banco. Si ya pasó, se arregla
    # rehaciendo la apertura con `ajustar_apertura`, que reescribe también
    # `sobrante_consignable`.
    caja_fuerte = Column(Numeric(12, 2, asdecimal=False), nullable=True, default=0.0)
    diferencia_apertura = Column(Numeric(12, 2, asdecimal=False), default=0.0)
    # SOBRANTE de apertura que debe bancarse con este turno (max(0, diferencia)).
    # Columna aparte (no derivar de diferencia_apertura): solo se llena desde el
    # fix de jul-2026 — los turnos viejos quedan NULL para no reclamar sobrantes
    # arrastrados N veces (turnos 38/40 mismo +24.600) ni la carga inicial (+673k).
    sobrante_consignable = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    justificacion_apertura = Column(Text, nullable=True)
    # Totales calculados automáticamente desde VentaDiaria
    total_ventas = Column(Numeric(12, 2, asdecimal=False), default=0.0)
    total_efectivo = Column(Numeric(12, 2, asdecimal=False), default=0.0)
    total_tarjeta = Column(Numeric(12, 2, asdecimal=False), default=0.0)
    efectivo_final_real = Column(Numeric(12, 2, asdecimal=False), nullable=True)   # total contado en caja al cierre
    datafono_real = Column(Numeric(12, 2, asdecimal=False), nullable=True)          # total datáfono Bold al cierre
    diferencia_cierre = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    diferencia_tarjeta = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    consignaciones_deducidas = Column(Numeric(12, 2, asdecimal=False), default=0.0, nullable=True)
    justificacion_cierre = Column(Text, nullable=True)
    # Cierre administrativo que SALTÓ el conteo de inventario (rescate de un turno
    # de un día anterior). Queda visible para el admin: ese cierre no tiene línea
    # base de inventario detrás.
    cerrado_sin_conteo = Column(Boolean, default=False)
    tipo_turno = Column(SAEnum(TipoTurnoEnum), nullable=True)
    # Fase 1: enlace al día operativo (continuidad entre turnos)
    dia_operativo_id = Column(Integer, ForeignKey("dias_operativos.id", ondelete="RESTRICT"), nullable=True, index=True)
    turno_anterior_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="RESTRICT"), nullable=True)
    secuencia_dia = Column(Integer, nullable=True)
    estado = Column(SAEnum(EstadoTurnoEnum), default=EstadoTurnoEnum.abierto, index=True)
    # Flags de flujo obligatorio — solo el backend las activa
    tiene_conteo_apertura = Column(Boolean, default=False)
    tiene_cuadre_llegada = Column(Boolean, default=False)
    tiene_ventas = Column(Boolean, default=False)
    tiene_conteo_cierre = Column(Boolean, default=False)
    # Etapa 6: timestamps operativos para métricas de tiempo
    ts_conteo_apertura = Column(DateTime, nullable=True)
    ts_primera_venta = Column(DateTime, nullable=True)
    ts_conteo_cierre = Column(DateTime, nullable=True)
    tienda = relationship("Tienda", back_populates="turnos")
    usuario_apertura = relationship("Usuario", foreign_keys=[usuario_apertura_id])
    usuario_cierre = relationship("Usuario", foreign_keys=[usuario_cierre_id])
    movimientos = relationship("MovimientoCaja", back_populates="turno")
    ventas = relationship("VentaDiaria", back_populates="turno")
    conteos = relationship("ConteoFisico", back_populates="turno")
    entregas = relationship("EntregaTurno", back_populates="turno")
    baristas_turno = relationship("TurnoBarista", back_populates="turno", cascade="all, delete-orphan")
    dia = relationship("DiaOperativo", back_populates="turnos")


class MovimientoCaja(Base):
    __tablename__ = "movimientos_caja"
    id = Column(Integer, primary_key=True)
    caja_turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="RESTRICT"), nullable=False)
    tipo = Column(SAEnum(TipoMovCajaEnum), nullable=False)
    concepto = Column(String(200), nullable=False)
    valor = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    imagen_url = Column(String(300), nullable=True)
    # Barista REAL que operó (≠ usuario_id del dispositivo/kiosko). Columna PLANA sin FK
    # para no introducir un segundo ForeignKey a usuarios (AmbiguousForeignKeysError).
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    # Factura de proveedor que originó este movimiento (pago/reverso/ajuste). Columna
    # PLANA sin FK: la factura puede eliminarse y el movimiento compensatorio queda.
    # Antes el vínculo era solo el texto del concepto, que se rompía al renombrar
    # el proveedor o corregir el número de factura.
    factura_id = Column(Integer, nullable=True)
    turno = relationship("CajaTurno", back_populates="movimientos")
    usuario = relationship("Usuario", back_populates="movimientos_caja")


class Producto(Base):
    __tablename__ = "productos"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    categoria = Column(SAEnum(CategoriaProductoEnum), nullable=False)
    unidad_medida = Column(String(30), nullable=False)
    controla_stock = Column(Boolean, default=True)
    incluir_en_conteo = Column(Boolean, default=True, server_default="true")
    proveedor = Column(String(100), nullable=True)
    lead_time_dias = Column(Integer, default=2, server_default="2")
    precio_venta = Column(Numeric(12, 2, asdecimal=False), nullable=False, server_default="0")
    # A granel: se cuenta en unidades selladas + nivel de la abierta (dibujo). envase: bolsa | botella.
    fraccionable = Column(Boolean, default=False, server_default="false")
    envase = Column(String(10), nullable=True)   # 'bolsa' (sólidos) | 'botella' (líquidos)
    # A granel en GRAMOS: gr que trae la unidad sellada (bolsa de café 2500). El conteo con
    # gramera = bolsas cerradas × contenido + gramos pesados de la abierta.
    contenido_por_unidad = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    # Gr/ml que trae UN empaque comercial (botella Baileys=1000, frasco salsa=1800).
    # Lo usa Recibir para convertir "N empaques" → gramos. NO confundir con
    # contenido_por_unidad (rendimiento de preparaciones / bolsa sellada del conteo).
    contenido_por_empaque = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    # Orden fijo del conteo/inventario (planilla de pedidos). NULL → al final, alfabético.
    orden_conteo = Column(Integer, nullable=True)
    # NULL = conteo diario normal; 'desechables' = solo se cuenta cuando el admin lo pide.
    grupo_conteo = Column(String(20), nullable=True)
    # Costo OFICIAL por unidad de inventario (lo fija el dueño, ej. en el verificador
    # de facturas). Manda sobre el promedio de FacturaCompraItem en rentabilidad:
    # las lecturas automáticas con ruido no ensucian un costo confirmado a mano.
    precio_costo = Column(Numeric(12, 4, asdecimal=False), nullable=True)
    # Producto intercambiable de RESERVA: al consumir este insumo por receta, si su
    # stock no alcanza, el resto se descuenta del sustituto (ej. Leche Entera →
    # Deslactosada). NULL = sin sustituto (comportamiento normal).
    sustituto_id = Column(Integer, ForeignKey("productos.id"), nullable=True)
    inventarios = relationship("Inventario", back_populates="producto")
    movimientos_inv = relationship("MovimientoInventario", back_populates="producto")
    pastelerias = relationship("PasteleriaDiaria", back_populates="producto")
    lotes = relationship("LoteInventario", back_populates="producto")
    mermas = relationship("Merma", back_populates="producto")


class Inventario(Base):
    __tablename__ = "inventario"
    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False, index=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False, index=True)
    stock_actual = Column(Float, default=0.0)
    stock_minimo = Column(Float, default=0.0)
    stock_ideal = Column(Float, default=0.0, server_default="0")
    stock_critico = Column(Float, default=0.0, server_default="0")
    producto = relationship("Producto", back_populates="inventarios")
    tienda = relationship("Tienda", back_populates="inventarios")
    __table_args__ = (
        UniqueConstraint("producto_id", "tienda_id", name="uq_inventario_producto_tienda"),
    )


class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"
    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False, index=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    tipo = Column(SAEnum(TipoMovInvEnum), nullable=False)
    cantidad = Column(Float, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    motivo = Column(String(200), nullable=True)
    # Actor real en kiosko compartido (≠ usuario_id del dispositivo). Plano, sin FK,
    # para no introducir un segundo ForeignKey a usuarios (AmbiguousForeignKeysError).
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    producto = relationship("Producto", back_populates="movimientos_inv")
    tienda = relationship("Tienda", back_populates="movimientos_inv")
    usuario = relationship("Usuario", back_populates="movimientos_inv")


class LoteInventario(Base):
    """Lote FIFO — invisible para el barista, solo admin puede consultarlo."""
    __tablename__ = "lotes_inventario"
    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    cantidad_inicial = Column(Float, nullable=False)
    cantidad_restante = Column(Float, nullable=False)
    fecha_entrada = Column(DateTime, default=datetime.utcnow)
    fecha_vencimiento = Column(DateTime, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Trazabilidad: de dónde vino el lote y cuándo se agotó (consumo FIFO completo).
    numero_lote = Column(String(100), nullable=True)
    proveedor = Column(String(150), nullable=True)
    fecha_fabricacion = Column(DateTime, nullable=True)
    factura_id = Column(Integer, nullable=True)        # plano, sin FK (evita acoplar)
    fecha_agotado = Column(DateTime, nullable=True)     # set cuando cantidad_restante llega a 0
    producto = relationship("Producto", back_populates="lotes")
    tienda = relationship("Tienda", back_populates="lotes")
    usuario = relationship("Usuario", back_populates="lotes_inventario")


class VentaDiaria(Base):
    """Registro de ventas del turno — actualiza totales en CajaTurno automáticamente."""
    __tablename__ = "ventas_diarias"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="RESTRICT"), nullable=False, index=True)
    venta_total = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    nota_credito = Column(Numeric(12, 2, asdecimal=False), default=0.0)
    vales = Column(Numeric(12, 2, asdecimal=False), default=0.0)
    tarjetas = Column(Numeric(12, 2, asdecimal=False), default=0.0)
    efectivo_calculado = Column(Numeric(12, 2, asdecimal=False), nullable=False)  # venta_total - nota_credito - vales - tarjetas
    fecha_registro = Column(DateTime, default=datetime.utcnow, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    nota = Column(String(300), nullable=True)
    turno = relationship("CajaTurno", back_populates="ventas")
    usuario = relationship("Usuario", back_populates="ventas_diarias")


class ConteoFisico(Base):
    """Conteo físico de inventario — apertura activa tiene_conteo_apertura, cierre activa tiene_conteo_cierre."""
    __tablename__ = "conteos_fisicos"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="RESTRICT"), nullable=False)
    tipo = Column(SAEnum(TipoConteoEnum), nullable=False)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Barista REAL que operó (≠ usuario_id del dispositivo/kiosko). Columna PLANA sin FK.
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    # True si usaron el atajo "Todo coincide con sistema": el conteo es un eco del
    # stock, no un conteo físico — el admin debe poder distinguirlos.
    es_atajo = Column(Boolean, default=False)
    turno = relationship("CajaTurno", back_populates="conteos")
    usuario = relationship("Usuario", back_populates="conteos_fisicos")
    items = relationship("ConteoFisicoItem", back_populates="conteo", cascade="all, delete-orphan")
    # Único apertura y cierre POR TURNO; los desechables pueden repetirse si el admin
    # vuelve a pedir el formato. Índice único PARCIAL (no un UniqueConstraint de tabla):
    # en prod la migración dropea el constraint viejo y crea este mismo índice.
    __table_args__ = (
        Index(
            "uq_conteo_turno_tipo", "turno_id", "tipo", unique=True,
            postgresql_where=text("tipo IN ('apertura', 'cierre')"),
            sqlite_where=text("tipo IN ('apertura', 'cierre')"),
        ),
    )


class ConteoFisicoItem(Base):
    __tablename__ = "conteos_fisicos_items"
    id = Column(Integer, primary_key=True)
    conteo_id = Column(Integer, ForeignKey("conteos_fisicos.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad_sistema = Column(Float, nullable=False)
    cantidad_real = Column(Float, nullable=False)
    diferencia = Column(Float, nullable=False)
    conteo = relationship("ConteoFisico", back_populates="items")
    producto = relationship("Producto")


class Merma(Base):
    """Merma — crea MovimientoInventario tipo=salida automáticamente."""
    __tablename__ = "mermas"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Float, nullable=False)
    motivo = Column(String(300), nullable=False)
    tipo = Column(SAEnum(TipoMermaEnum), default=TipoMermaEnum.consumo, nullable=False)
    # Quién consumió (consumo de dueños/reuniones): distinto de barista_nombre (quien registró).
    quien = Column(String(100), nullable=True)
    tienda_destino_id = Column(Integer, ForeignKey("tiendas.id"), nullable=True)
    recibido = Column(Boolean, default=False, nullable=False)
    fecha_recibido = Column(DateTime, nullable=True)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Barista REAL que operó (≠ usuario_id del dispositivo/kiosko). Columna PLANA sin FK.
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    tienda = relationship("Tienda", back_populates="mermas", foreign_keys=[tienda_id])
    tienda_destino = relationship("Tienda", foreign_keys=[tienda_destino_id])
    producto = relationship("Producto", back_populates="mermas")
    usuario = relationship("Usuario", back_populates="mermas")


class SolicitudPedido(Base):
    __tablename__ = "solicitudes_pedido"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    fecha_solicitud = Column(DateTime, default=datetime.utcnow)
    estado = Column(SAEnum(EstadoSolicitudEnum), default=EstadoSolicitudEnum.pendiente)
    nota = Column(String(500), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    usuario_aprobacion_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_aprobacion = Column(DateTime, nullable=True)
    tienda = relationship("Tienda", back_populates="solicitudes_pedido")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    usuario_aprobacion = relationship("Usuario", foreign_keys=[usuario_aprobacion_id])
    items = relationship("SolicitudPedidoItem", back_populates="solicitud", cascade="all, delete-orphan")


class SolicitudPedidoItem(Base):
    __tablename__ = "solicitudes_pedido_items"
    id = Column(Integer, primary_key=True)
    solicitud_id = Column(Integer, ForeignKey("solicitudes_pedido.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad_solicitada = Column(Float, nullable=False)
    # Unidad elegida por la barista al pedir (gr, unidad, lt, paquete…): puede diferir
    # de la unidad del producto (p.ej. pedir café en "paquetes" aunque el stock sea gr).
    unidad_solicitada = Column(String(20), nullable=True)
    solicitud = relationship("SolicitudPedido", back_populates="items")
    producto = relationship("Producto")

    @property
    def nombre(self):
        return self.producto.nombre if self.producto else ""

    @property
    def proveedor(self):
        # A quién se le compra este producto (lo alimentan las facturas al Recibir).
        return self.producto.proveedor if self.producto else None

    @property
    def unidad_medida(self):
        # La unidad que la barista eligió manda; si no eligió, la del producto.
        if self.unidad_solicitada:
            return self.unidad_solicitada
        return self.producto.unidad_medida if self.producto else ""


class SolicitudSencilla(Base):
    __tablename__ = "solicitudes_sencilla"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    fecha_solicitud = Column(DateTime, default=datetime.utcnow)
    estado = Column(SAEnum(EstadoSolicitudEnum), default=EstadoSolicitudEnum.pendiente)
    monto_solicitado = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    motivo = Column(String(300), nullable=False)
    detalle = Column(Text, nullable=True)  # JSON: [{label, valor, cantidad, subtotal}]
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    usuario_aprobacion_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_aprobacion = Column(DateTime, nullable=True)
    tienda = relationship("Tienda", back_populates="solicitudes_sencilla")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    usuario_aprobacion = relationship("Usuario", foreign_keys=[usuario_aprobacion_id])


class EntregaTurno(Base):
    """Cuadre de llegada — barista entrante registra cuadre sin cerrar el turno."""
    __tablename__ = "entregas_turno"
    id = Column(Integer, primary_key=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id"), nullable=False)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_hora = Column(DateTime, default=datetime.utcnow)
    efectivo_esperado = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    efectivo_real = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    ventas_efectivo_siigo = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    ventas_tarjeta_bold = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    diferencia_efectivo = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    diferencia_tarjeta = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    # Desglose del efectivo esperado, congelado al momento del cuadre (nullable: cuadres
    # anteriores a esta feature no lo tienen). esperado = base + ventas_efectivo + ingresos - egresos.
    base_snapshot = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    ventas_efectivo_snapshot = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    ingresos_snapshot = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    egresos_snapshot = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    imagen_url = Column(String(300), nullable=True)
    tipo = Column(String(20), default="entrega", nullable=False, server_default="entrega")
    # Venta de ayer separada: la barista contó SOLO la registradora; el monto separado
    # (la base del día anterior) quedó guardado aparte sin contar. El monto vive en
    # base_snapshot; efectivo_esperado/diferencia se calculan contra la registradora.
    base_separada = Column(Boolean, default=False, nullable=False, server_default="false")
    # Barista REAL que operó (≠ usuario_id del dispositivo/kiosko). Columna PLANA sin FK.
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    turno = relationship("CajaTurno", back_populates="entregas")
    usuario = relationship("Usuario", back_populates="entregas_turno")


class SolicitudConteoDesechables(Base):
    """El admin pide el conteo de desechables; la barista lo llena desde el kiosko.
    El formato NO entra en el conteo diario (grupo_conteo='desechables')."""
    __tablename__ = "solicitudes_conteo_desechables"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False, index=True)
    estado = Column(String(20), default="pendiente", nullable=False)  # pendiente | respondida
    fecha_solicitud = Column(DateTime, default=datetime.utcnow)
    solicitada_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    conteo_id = Column(Integer, ForeignKey("conteos_fisicos.id", ondelete="RESTRICT"), nullable=True)
    fecha_respuesta = Column(DateTime, nullable=True)
    # Barista REAL que respondió (plano, sin FK — AmbiguousForeignKeysError).
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)


class PasteleriaDiaria(Base):
    __tablename__ = "pasteleria_diaria"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Float, nullable=False)
    fecha_frescura = Column(DateTime, nullable=False)     # legado — igual a fecha_vencimiento
    numero_lote = Column(String(100), nullable=True)      # número o código del lote
    fecha_vencimiento = Column(DateTime, nullable=True)   # fecha límite de venta
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    activo = Column(Boolean, default=True)
    tienda = relationship("Tienda", back_populates="pastelerias")
    producto = relationship("Producto", back_populates="pastelerias")
    usuario = relationship("Usuario", back_populates="pastelerias")


class Consignacion(Base):
    __tablename__ = "consignaciones"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    caja_turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="RESTRICT"), nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow)
    valor = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    imagen_url = Column(String(300), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    estado = Column(SAEnum(EstadoConsignacionEnum), default=EstadoConsignacionEnum.pendiente)
    # Barista REAL que operó (≠ usuario_id del dispositivo/kiosko). Columna PLANA sin FK.
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    tienda = relationship("Tienda", back_populates="consignaciones")
    turno = relationship("CajaTurno", foreign_keys=[caja_turno_id])
    usuario = relationship("Usuario", back_populates="consignaciones")


class RecogidaEfectivo(Base):
    """El dueño pasó por la sede y SE LLEVÓ el efectivo. La tercera bolsa de plata.

    Hasta julio la plata iba del cajón al banco: la barista consignaba y se
    conservaba. Desde agosto el dueño recoge el efectivo en persona y con esa
    misma plata paga a los proveedores que aceptan contado —eso NUNCA toca el
    banco— y consigna el resto. O sea que la plata vive en TRES lugares y el
    sistema solo conocía dos: el cajón y el banco. La recogida no quedaba en
    ninguna parte, así que el cajón seguía afirmando que la plata estaba ahí.

    El error medido, con números: venden $1.000.000 en efectivo, él recoge el
    $1.000.000 (el cajón sigue diciendo $1.000.000), paga $400.000 a un proveedor
    de contado (tampoco toca el cajón) y consigna $600.000 (recién ahí el cajón
    baja a $400.000). La pantalla mostraba $1.000.000 donde había $600.000: sobra
    exactamente lo pagado en efectivo, y sobra hacia el lado TRANQUILIZADOR, que
    es la peor dirección posible para el número que el dueño mira antes de abrir.

    POR QUÉ ES TABLA PROPIA Y NO UNA `Consignacion` SIN TURNO. Una consignación
    afirma que la plata ENTRÓ AL BANCO; recoger no es depositar. Lo recogido queda
    en la mano y una parte puede no llegar nunca al banco. Además la ausencia de
    `caja_turno_id` ya significa otra cosa en `Consignacion` (la consignó él y no
    la barista), y no se pueden colgar dos significados del mismo NULL.

    La crea `create_all` (main.py:282). El loop de ALTERs corre ANTES, así que una
    tabla NUEVA no lleva entrada allí — solo las columnas nuevas de tablas que ya
    existen en producción.
    """
    __tablename__ = "recogidas_efectivo"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), index=True, nullable=False)
    # EL DÍA COLOMBIA EN QUE RECOGIÓ, no el día en que lo tecleó. Date nativo por
    # la misma razón que Pago.fecha_pago: él registra la pasada de ayer o la de
    # anteayer, y el reporte tiene que ubicarla en su día, no en el del teclado.
    fecha = Column(Date, index=True, nullable=False)
    monto = Column(Numeric(12, 2, asdecimal=False), nullable=False)   # siempre positivo
    # EL DÍA (turno) QUE ESTA RECOGIDA SALDA. Con turno puesto, la recogida se
    # imputa a ESE día y solo a ese: el dueño tocó «recogí» en la tarjeta de un
    # día puntual y espera que ESE quede «Recogido», no que la plata se reparta
    # al día más viejo. Sin turno (recogidas viejas, o una pasada suelta sin día)
    # cae al reparto histórico del más viejo primero, como antes. FK plana en la
    # migración (sin REFERENCES) por el mismo motivo que `caja_turno_id`.
    turno_id = Column(Integer, ForeignKey("caja_turnos.id"), index=True, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Con max_length explícito: sin él el INSERT explota en Postgres (ya pasó en
    # este repo con otras columnas de texto libre).
    nota = Column(String(300), nullable=True)
    # CUÁNDO SE TECLEÓ (UTC-naive, convención del repo). No es metadata decorativa:
    # es el campo con el que `_efectivo_en_registradora` decide si una recogida ya
    # está reflejada en el conteo físico del cierre. `fecha` es un DÍA y no alcanza
    # para ordenarse contra `CajaTurno.fecha_cierre`, que es un INSTANTE.
    creado_en = Column(DateTime, default=datetime.utcnow)
    # Sin back_populates a propósito (mismo patrón que Mantenimiento y Pago): no
    # hace falta tocar Tienda ni Usuario para agregar una tabla satélite.
    tienda = relationship("Tienda")
    usuario = relationship("Usuario")


class ChecklistDiario(Base):
    __tablename__ = "checklist_diario"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    fecha = Column(DateTime, nullable=False)
    apertura_realizada = Column(Boolean, default=False)
    inventario_check = Column(Boolean, default=False)
    pasteleria_check = Column(Boolean, default=False)
    siigo_check = Column(Boolean, default=False)
    limpieza_check = Column(Boolean, default=False)
    cierre_realizado = Column(Boolean, default=False)
    tienda = relationship("Tienda", back_populates="checklists")


class TipoMantenimientoEnum(str, enum.Enum):
    equipo      = "equipo"
    fumigacion  = "fumigacion"
    sondeo      = "sondeo"
    plomeria    = "plomeria"
    electrico   = "electrico"
    otro        = "otro"


class Mantenimiento(Base):
    """Registro de mantenimientos, fumigaciones, sondeos y reparaciones."""
    __tablename__ = "mantenimientos"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    tipo = Column(SAEnum(TipoMantenimientoEnum), nullable=False)
    titulo = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)
    fecha_realizado = Column(DateTime, nullable=False)
    costo = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    tecnico = Column(String(150), nullable=True)
    imagen_url = Column(String(300), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    tienda = relationship("Tienda")
    usuario = relationship("Usuario")


class CausaAuditoriaEnum(str, enum.Enum):
    acceso_no_autorizado = "acceso_no_autorizado"
    error_conteo         = "error_conteo"
    dano                 = "dano"
    traslado_no_registrado = "traslado_no_registrado"
    otro                 = "otro"


class EstadoAuditoriaEnum(str, enum.Enum):
    abierta  = "abierta"
    cerrada  = "cerrada"


class AuditoriaInventario(Base):
    """Auditoría ad-hoc de inventario — conteo físico puntual con análisis de diferencias."""
    __tablename__ = "auditorias_inventario"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    fecha = Column(DateTime, nullable=False)
    descripcion = Column(String(300), nullable=False)
    causa = Column(SAEnum(CausaAuditoriaEnum), nullable=True)
    observaciones = Column(Text, nullable=True)
    acciones_tomadas = Column(Text, nullable=True)
    estado = Column(SAEnum(EstadoAuditoriaEnum), default=EstadoAuditoriaEnum.abierta)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    tienda = relationship("Tienda")
    usuario = relationship("Usuario")
    items = relationship("AuditoriaInventarioItem", back_populates="auditoria",
                         cascade="all, delete-orphan")


class AuditoriaInventarioItem(Base):
    __tablename__ = "auditorias_inventario_items"
    id = Column(Integer, primary_key=True)
    auditoria_id = Column(Integer, ForeignKey("auditorias_inventario.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad_sistema = Column(Float, nullable=False)
    cantidad_real = Column(Float, nullable=False)
    diferencia = Column(Float, nullable=False)
    observacion = Column(String(200), nullable=True)
    auditoria = relationship("AuditoriaInventario", back_populates="items")
    producto = relationship("Producto")


class AuditoriaLimpieza(Base):
    """Cronograma semanal de aseo — basado en el formato físico Cronograma de Aseo."""
    __tablename__ = "auditorias_limpieza"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    semana = Column(String(10), nullable=False)       # "2026-W07"
    fecha_inicio = Column(DateTime, nullable=False)   # lunes de la semana
    observaciones = Column(Text, nullable=True)
    vobo = Column(Boolean, default=False)
    vobo_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    vobo_fecha = Column(DateTime, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    tienda = relationship("Tienda")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    vobo_usuario = relationship("Usuario", foreign_keys=[vobo_por_id])
    items = relationship("AuditoriaLimpiezaItem", back_populates="auditoria",
                         cascade="all, delete-orphan")


class AuditoriaLimpiezaItem(Base):
    __tablename__ = "auditorias_limpieza_items"
    id = Column(Integer, primary_key=True)
    auditoria_id = Column(Integer, ForeignKey("auditorias_limpieza.id"), nullable=False)
    tarea_key = Column(String(50), nullable=False)
    realizado = Column(Boolean, default=False)
    realizado_por = Column(String(100), nullable=True)
    auditoria = relationship("AuditoriaLimpieza", back_populates="items")


class AuditLog(Base):
    """Etapa 1: Registro inmutable de acciones críticas del sistema."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    tienda_id = Column(Integer, nullable=True)        # sin FK para evitar cascadas
    accion = Column(String(100), nullable=False)      # "apertura_caja", "registro_venta", ...
    tabla_afectada = Column(String(50), nullable=False)
    registro_id = Column(Integer, nullable=True)
    datos_antes = Column(Text, nullable=True)         # JSON serializado
    datos_despues = Column(Text, nullable=True)       # JSON serializado
    fecha = Column(DateTime, default=datetime.utcnow, index=True)
    usuario = relationship("Usuario")


class LimpiezaSemanal(Base):
    """Registro de tareas semanales de limpieza y mantenimiento preventivo."""
    __tablename__ = "limpieza_semanal"
    id         = Column(Integer, primary_key=True, index=True)
    tienda_id  = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tarea_key  = Column(String(60), nullable=False)
    fecha      = Column(DateTime, nullable=False, default=datetime.utcnow)
    vobo       = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Barista REAL que marcó la tarea (≠ usuario del dispositivo/kiosko). Columna plana sin FK.
    barista_id     = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)

    usuario = relationship("Usuario")


class TareaLimpieza(Base):
    """Catálogo de tareas de limpieza por tienda (editable por admin)."""
    __tablename__ = "tareas_limpieza"
    id        = Column(Integer, primary_key=True, index=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    key       = Column(String(80),  nullable=False)
    label     = Column(String(200), nullable=False)
    activa    = Column(Boolean, default=True, nullable=False)
    orden     = Column(Integer, default=0, nullable=False)


class Receta(Base):
    """Escandallo / receta estándar con lista de ingredientes y costo teórico."""
    __tablename__ = "recetas"
    id           = Column(Integer, primary_key=True)
    nombre       = Column(String(150), nullable=False)
    categoria    = Column(String(50), nullable=False, default="bebida")  # bebida | pasteleria | comida
    precio_venta = Column(Numeric(12, 2, asdecimal=False), nullable=True)   # precio de venta para calcular food cost %
    activa       = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    ingredientes = relationship("RecetaIngrediente", back_populates="receta", cascade="all, delete-orphan")


class RecetaIngrediente(Base):
    __tablename__ = "recetas_ingredientes"
    id         = Column(Integer, primary_key=True)
    receta_id  = Column(Integer, ForeignKey("recetas.id"), nullable=False)
    producto_id= Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad   = Column(Float, nullable=False)
    receta     = relationship("Receta", back_populates="ingredientes")
    producto   = relationship("Producto")


class ConteoVerificacion(Base):
    """Verificación de una diferencia de conteo: el admin la solicita desde el hub,
    la barista recuenta ese producto en el kiosko y responde, y el admin resuelve.
    Si aprueba con un valor distinto al stock, se ajusta el inventario (con auditoría).
    El conteo original YA aplicó al stock — esto es el circuito de corrección."""
    __tablename__ = "conteo_verificaciones"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False, index=True)
    conteo_id = Column(Integer, ForeignKey("conteos_fisicos.id", ondelete="RESTRICT"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    estado = Column(String(20), default="solicitada", nullable=False)  # solicitada | respondida | aprobada | rechazada
    cantidad_sistema = Column(Float, nullable=False)     # lo que decía el sistema al contar
    cantidad_conteo = Column(Float, nullable=False)      # lo que contó la barista originalmente
    cantidad_verificada = Column(Float, nullable=True)   # el recuento de la verificación
    nota_barista = Column(String(300), nullable=True)
    nota_admin = Column(String(300), nullable=True)
    solicitada_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    # Barista REAL que respondió (plano, sin FK — patrón del proyecto)
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    fecha_solicitud = Column(DateTime, default=datetime.utcnow)
    fecha_respuesta = Column(DateTime, nullable=True)
    fecha_resolucion = Column(DateTime, nullable=True)
    __table_args__ = (
        UniqueConstraint("conteo_id", "producto_id", name="uq_verificacion_conteo_producto"),
    )


class ProductoInsumo(Base):
    """Receta de consumo del POS: por cada unidad vendida de producto_id se
    descuentan `cantidad` unidades del insumo_id en inventario (y se reponen al
    anular). Sin relationships: dos FKs a productos dispararían
    AmbiguousForeignKeysError en el mapper; se consulta con joins explícitos."""
    __tablename__ = "producto_insumos"
    id          = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="CASCADE"), nullable=False, index=True)
    insumo_id   = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    cantidad    = Column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("producto_id", "insumo_id", name="uq_producto_insumo"),
    )


class ProductoDesechable(Base):
    """Receta de desechables SOLO para costeo de rentabilidad: los empaques que
    lleva un producto cuando es 'para llevar' (vaso, tapa, servilleta, azúcar,
    mezclador, pitillo). A diferencia de ProductoInsumo, esto NO descuenta
    inventario en la venta ni se toca en el POS — es una capa de costo aparte
    que se suma únicamente al margen por producto en rentabilidad (en el punto
    se usa cristalería y no todos piden azúcar, por eso no va en la receta real).
    Sin relationships: dos FKs a productos dispararían AmbiguousForeignKeysError;
    se consulta con joins explícitos, igual que ProductoInsumo."""
    __tablename__ = "producto_desechables"
    id          = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="CASCADE"), nullable=False, index=True)
    insumo_id   = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    cantidad    = Column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("producto_id", "insumo_id", name="uq_producto_desechable"),
    )


class IdempotencyKey(Base):
    """Llave de idempotencia para operaciones que MUEVEN inventario y no pueden
    aplicarse dos veces (ej. preparaciones). El cliente manda una llave única por
    intento; si el servidor ya la vio, es un doble-disparo (doble tap, reintento de
    red, otro dispositivo) y devuelve el resultado previo SIN volver a aplicar el
    movimiento. La defensa vive en el servidor porque es donde ocurre la escritura:
    el guardián del front (botón deshabilitado) es cortesía, no garantía."""
    __tablename__ = "idempotency_keys"
    id         = Column(Integer, primary_key=True)
    key        = Column(String(64), unique=True, index=True, nullable=False)
    scope      = Column(String(40), nullable=True)   # "preparacion", ...
    resultado  = Column(Text, nullable=True)          # JSON del resultado, para el replay
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Notificacion(Base):
    """Etapa 7: Notificaciones operativas internas para el admin."""
    __tablename__ = "notificaciones"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False, index=True)
    tipo = Column(String(50), nullable=False)         # "diferencia_caja", "inventario_critico", ...
    mensaje = Column(String(300), nullable=False)
    nivel = Column(String(20), default="info")        # "info", "advertencia", "critico"
    leida = Column(Boolean, default=False, index=True)
    fecha = Column(DateTime, default=datetime.utcnow)
    referencia_id = Column(Integer, nullable=True)    # turno_id, producto_id, etc.
    tienda = relationship("Tienda", back_populates="notificaciones")


class NotificacionRegla(Base):
    """Motor de reglas: configura por tienda y tipo qué eventos disparan
    notificación, su umbral, canales (campana / push) y nivel."""
    __tablename__ = "notificacion_reglas"
    id         = Column(Integer, primary_key=True)
    tienda_id  = Column(Integer, ForeignKey("tiendas.id"), index=True, nullable=False)
    tipo       = Column(String(40), nullable=False)   # ventas_dia, stock_critico, ...
    umbral     = Column(Float, default=0)             # monto/tolerancia según el tipo
    activa     = Column(Boolean, default=True)
    canal_bell = Column(Boolean, default=True)        # notificación in-app (campana)
    canal_push = Column(Boolean, default=False)       # push web (PWA)
    nivel      = Column(String(20), default="advertencia")
    __table_args__ = (
        UniqueConstraint("tienda_id", "tipo", name="uq_notif_regla_tienda_tipo"),
    )


class PushSubscription(Base):
    """Suscripción Web Push (PWA) de un dispositivo. Columnas de atribución
    PLANAS (sin ForeignKey) para no romper el mapper."""
    __tablename__ = "push_subscriptions"
    id         = Column(Integer, primary_key=True)
    tienda_id  = Column(Integer, index=True, nullable=True)   # plano, sin FK
    usuario_id = Column(Integer, nullable=True)               # plano, sin FK
    endpoint   = Column(String(500), unique=True, nullable=False)
    p256dh     = Column(String(255), nullable=False)
    auth       = Column(String(255), nullable=False)
    creado     = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Comunicados admin → barista
# ---------------------------------------------------------------------------

class Comunicado(Base):
    """Mensaje del administrador hacia los baristas. Puede ser para una tienda
    específica o para todas (tienda_id = None)."""
    __tablename__ = "comunicados"
    id              = Column(Integer, primary_key=True)
    titulo          = Column(String(120), nullable=True)
    mensaje         = Column(Text, nullable=False)
    tienda_id       = Column(Integer, ForeignKey("tiendas.id"), nullable=True)  # None = todas
    activo          = Column(Boolean, default=True)
    urgente         = Column(Boolean, default=False)   # resalta en rojo en el hub
    fecha_creacion  = Column(DateTime, default=datetime.utcnow)
    creado_por      = Column(Integer, ForeignKey("usuarios.id"), nullable=False)

    tienda    = relationship("Tienda")
    creador   = relationship("Usuario", foreign_keys=[creado_por])
    leidos    = relationship("ComunicadoLeido", back_populates="comunicado",
                             cascade="all, delete-orphan")


class ComunicadoLeido(Base):
    """Registro de qué barista leyó/descartó qué comunicado."""
    __tablename__ = "comunicados_leidos"
    id              = Column(Integer, primary_key=True)
    comunicado_id   = Column(Integer, ForeignKey("comunicados.id"), nullable=False)
    usuario_id      = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_leido     = Column(DateTime, default=datetime.utcnow)

    comunicado  = relationship("Comunicado", back_populates="leidos")
    usuario     = relationship("Usuario")
    __table_args__ = (
        UniqueConstraint("comunicado_id", "usuario_id", name="uq_comunicado_leido"),
    )


# ---------------------------------------------------------------------------
# Facturas de compra (Problema 1: ingreso de mercancía con soporte DIAN)
# ---------------------------------------------------------------------------

class FacturaCompra(Base):
    __tablename__ = "facturas_compra"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    proveedor = Column(String(150), nullable=False)
    numero_factura = Column(String(100), nullable=True)
    numero_lote = Column(String(100), nullable=True)
    fecha_recibido = Column(DateTime, nullable=True)
    valor_total = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    tipo_pago = Column(SAEnum(TipoPagoEnum), nullable=False)
    imagen_url = Column(String(300), nullable=True)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Barista REAL que operó (≠ usuario_id del dispositivo/kiosko). Columna PLANA sin FK.
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    # Pagos a proveedores: cuánto se pagó, con qué forma y la foto del soporte de pago.
    valor_pagado = Column(Numeric(12, 2, asdecimal=False), default=0)
    forma_pago_real = Column(String(40), nullable=True)
    imagen_soporte_url = Column(String(300), nullable=True)
    # Vencimientos (Fase 2 de Costos): la factura es la ÚNICA verdad de la deuda con
    # el proveedor, así que la fecha de pago vive ACÁ y no en una obligación espejo.
    # TIMESTAMP y no Date por consistencia con su columna hermana fecha_recibido: se
    # guardan con inicio_dia_col_utc(d) para que el día Colombia no se corra a UTC.
    fecha_vencimiento = Column(DateTime, nullable=True)   # cuándo hay que pagarla
    # Plazo del proveedor. Si viene y fecha_vencimiento es NULL, la agenda deriva
    # fecha_recibido + plazo_dias. No se puede backfillear: no existe tabla maestra de
    # proveedores (FacturaCompra.proveedor es un String suelto).
    plazo_dias = Column(Integer, nullable=True)
    # Cuándo el dueño DECIDIÓ pagarla (puede diferir del vencimiento). MANDA sobre
    # fecha_vencimiento en la agenda: lo decidido pesa más que lo exigido.
    fecha_programada = Column(DateTime, nullable=True)
    tienda = relationship("Tienda", back_populates="facturas_compra")
    usuario = relationship("Usuario")
    items = relationship("FacturaCompraItem", back_populates="factura", cascade="all, delete-orphan")


class FacturaCompraItem(Base):
    __tablename__ = "facturas_compra_items"
    id = Column(Integer, primary_key=True)
    factura_id = Column(Integer, ForeignKey("facturas_compra.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Float, nullable=False)
    precio_unitario = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    numero_lote = Column(String(100), nullable=True)
    fecha_vencimiento = Column(DateTime, nullable=True)
    factura = relationship("FacturaCompra", back_populates="items")
    producto = relationship("Producto")


class ProductoAlias(Base):
    """Alias proveedor→producto que el sistema APRENDE de las facturas (Fase 2
    del OCR): cómo llama cada proveedor a cada producto del inventario.
    `alias_normalizado` usa la MISMA normalización que cargar_menu_venta.norm
    (NFKD sin tildes, espacios colapsados, MAYÚSCULAS). En el escaneo el match
    por alias es determinístico y gana sobre la IA y el fuzzy: es verdad
    confirmada por humanos (correccion) o por matches confiables del backfill
    (bootstrap) / del registro sin cambios (escaneo). Datos aprendidos y
    desechables: si el producto se borra, sus aliases se van con él (CASCADE)."""
    __tablename__ = "producto_aliases"
    id = Column(Integer, primary_key=True)
    alias_normalizado = Column(String(200), unique=True, nullable=False, index=True)
    alias_original = Column(String(200), nullable=False)   # snapshot tal cual la factura
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    origen = Column(String(20), nullable=False)            # bootstrap | correccion | escaneo
    veces_visto = Column(Integer, nullable=False, default=1, server_default="1")
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Autoría plana (patrón X-Barista-Id del proyecto, sin FK — igual que
    # facturas_compra/tickets): QUIÉN enseñó el alias (lo creó o lo repuntó por
    # corrección). NULL = flujo sin barista identificada (backfill, admin).
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    producto = relationship("Producto")


# ---------------------------------------------------------------------------
# Conteo de compras (Problema 2: conteo físico independiente para pedidos)
# ---------------------------------------------------------------------------

class ConteoCompras(Base):
    """Conteo físico independiente del turno — para sincronizar stock con realidad
    antes de generar pedidos a proveedores."""
    __tablename__ = "conteos_compras"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    fecha_conteo = Column(DateTime, nullable=False)
    ajustado = Column(Boolean, default=False)       # True cuando admin aprueba y ajusta stock
    fecha_ajuste = Column(DateTime, nullable=True)
    usuario_ajuste_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    nota = Column(String(300), nullable=True)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    tienda = relationship("Tienda", back_populates="conteos_compras")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    usuario_ajuste = relationship("Usuario", foreign_keys=[usuario_ajuste_id])
    items = relationship("ConteoComprasItem", back_populates="conteo", cascade="all, delete-orphan")


class ConteoComprasItem(Base):
    __tablename__ = "conteos_compras_items"
    id = Column(Integer, primary_key=True)
    conteo_id = Column(Integer, ForeignKey("conteos_compras.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad_sistema = Column(Float, nullable=False)
    cantidad_real = Column(Float, nullable=False)
    diferencia = Column(Float, nullable=False)
    conteo = relationship("ConteoCompras", back_populates="items")
    producto = relationship("Producto")


# ---------------------------------------------------------------------------
# POS nativo (reemplazo de Siigo): tickets de venta itemizados
# ---------------------------------------------------------------------------

class Ticket(Base):
    """Venta itemizada generada por el POS nativo. Cabecera de la venta."""
    __tablename__ = "tickets"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False, index=True)
    caja_turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="RESTRICT"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow, index=True)
    total = Column(Numeric(12, 2, asdecimal=False), nullable=False)   # total final (con descuento aplicado)
    descuento = Column(Numeric(12, 2, asdecimal=False), default=0)    # descuento libre por ticket
    metodo_pago = Column(String(20), nullable=False)        # 'efectivo' | 'tarjeta' | 'mixto'
    monto_efectivo = Column(Numeric(12, 2, asdecimal=False), default=0)
    monto_tarjeta = Column(Numeric(12, 2, asdecimal=False), default=0)
    efectivo_recibido = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    cambio = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    estado = Column(String(20), default="completado")
    # Barista REAL que vendió (≠ usuario_id del dispositivo/kiosko). Columna PLANA sin FK.
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    # Día del negocio en que se COBRÓ la venta, sellado al crear el ticket e
    # independiente del día del propio turno: un turno que queda abierto de un día
    # anterior sigue vendiendo (el índice uq_one_turno_abierto impide abrir otro) y
    # NO debe arrastrar las ventas de hoy a su día. Columna PLANA sin FK, misma
    # convención que barista_id (evita un segundo ForeignKey en el mapper).
    dia_operativo_id = Column(Integer, nullable=True, index=True)
    items = relationship("TicketItem", back_populates="ticket", cascade="all, delete-orphan")
    tienda = relationship("Tienda", foreign_keys=[tienda_id])
    turno = relationship("CajaTurno", foreign_keys=[caja_turno_id])
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


class TicketItem(Base):
    """Línea de un ticket POS — snapshot de nombre y precio al momento de la venta."""
    __tablename__ = "ticket_items"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    nombre_producto = Column(String(150), nullable=False)
    cantidad = Column(Integer, nullable=False)
    precio_unitario = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    subtotal = Column(Numeric(12, 2, asdecimal=False), nullable=False)   # neto (con descuento de linea)
    descuento = Column(Numeric(12, 2, asdecimal=False), default=0)       # descuento de esta linea
    ticket = relationship("Ticket", back_populates="items")
    producto = relationship("Producto", foreign_keys=[producto_id])
    # Solo líneas de combo: la combinación elegida (qué opción de qué grupo).
    combo_selecciones = relationship("TicketItemComboSeleccion", back_populates="ticket_item",
                                     cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Combos del POS: precio fijo, grupos de opciones y disponibilidad por tienda
# ---------------------------------------------------------------------------

class Combo(Base):
    """Combo de precio fijo del POS (ej. bebida + acompañamiento).

    En el ticket el combo entra como una línea NORMAL de ticket_items apuntando
    a su producto SOMBRA (producto_id): así el conteo de combos vendidos sale de
    las mismas queries que el resto del historial/analytics sin tocar el esquema
    de ticket_items (producto_id sigue NOT NULL). El producto sombra tiene
    precio_venta=0 para que NO aparezca en la grilla del POS (filtro precio>0);
    el precio que manda es SIEMPRE Combo.precio_venta, fijado en el servidor.
    """
    __tablename__ = "combos"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    precio_venta = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    activo = Column(Boolean, default=True, nullable=False)
    orden = Column(Integer, default=0, nullable=False)
    # Producto sombra para la línea del ticket (snapshot nombre/precio como todo item).
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False, unique=True)
    producto = relationship("Producto")
    grupos = relationship("ComboGrupo", back_populates="combo",
                          cascade="all, delete-orphan", order_by="ComboGrupo.orden")
    tiendas = relationship("ComboTienda", back_populates="combo", cascade="all, delete-orphan")


class ComboGrupo(Base):
    """Grupo de elección dentro de un combo (ej. 'Bebida', 'Acompañamiento').
    Un grupo con UNA sola opción es fijo: se auto-selecciona (sin elección)."""
    __tablename__ = "combo_grupos"
    id = Column(Integer, primary_key=True)
    combo_id = Column(Integer, ForeignKey("combos.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(100), nullable=False)
    orden = Column(Integer, default=0, nullable=False)
    combo = relationship("Combo", back_populates="grupos")
    opciones = relationship("ComboOpcion", back_populates="grupo",
                            cascade="all, delete-orphan", order_by="ComboOpcion.orden")


class ComboOpcion(Base):
    """Opción elegible de un grupo. El nombre es de display (ej. 'Americano
    Grande'); los productos reales que consume viven en ComboOpcionProducto
    (una opción puede componerse de VARIOS productos)."""
    __tablename__ = "combo_opciones"
    id = Column(Integer, primary_key=True)
    grupo_id = Column(Integer, ForeignKey("combo_grupos.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(150), nullable=False)
    orden = Column(Integer, default=0, nullable=False)
    grupo = relationship("ComboGrupo", back_populates="opciones")
    productos = relationship("ComboOpcionProducto", back_populates="opcion",
                             cascade="all, delete-orphan")


class ComboOpcionProducto(Base):
    """Producto real que consume una opción de combo (con su cantidad).
    Ej. opción 'Americano Grande' = Americano Medium ×1 + Bebida Agrandada ×1;
    grupo fijo 'Bebidas' del Combo 03 = Cappuccino Tradicional Medium ×2."""
    __tablename__ = "combo_opcion_productos"
    id = Column(Integer, primary_key=True)
    opcion_id = Column(Integer, ForeignKey("combo_opciones.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    cantidad = Column(Integer, default=1, nullable=False)
    opcion = relationship("ComboOpcion", back_populates="productos")
    producto = relationship("Producto")
    __table_args__ = (
        UniqueConstraint("opcion_id", "producto_id", name="uq_combo_opcion_producto"),
    )


class ComboTienda(Base):
    """Disponibilidad del combo por tienda (asociativa combo↔tienda)."""
    __tablename__ = "combo_tiendas"
    id = Column(Integer, primary_key=True)
    combo_id = Column(Integer, ForeignKey("combos.id", ondelete="CASCADE"), nullable=False, index=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    combo = relationship("Combo", back_populates="tiendas")
    tienda = relationship("Tienda")
    __table_args__ = (
        UniqueConstraint("combo_id", "tienda_id", name="uq_combo_tienda"),
    )


class TicketItemComboSeleccion(Base):
    """Combinación elegida en una línea de combo del ticket: qué opción de qué
    grupo y qué producto real consumió (para reponer inventario al anular).
    grupo_id/opcion_id son columnas PLANAS (sin FK) + snapshots de nombre, para
    que reorganizar el catálogo de combos nunca rompa el historial de ventas.
    cantidad es por UNA unidad de combo (el total = cantidad × TicketItem.cantidad)."""
    __tablename__ = "ticket_item_combo_selecciones"
    id = Column(Integer, primary_key=True)
    ticket_item_id = Column(Integer, ForeignKey("ticket_items.id", ondelete="CASCADE"), nullable=False, index=True)
    combo_id = Column(Integer, ForeignKey("combos.id", ondelete="RESTRICT"), nullable=False, index=True)
    grupo_id = Column(Integer, nullable=True)        # plano, sin FK
    opcion_id = Column(Integer, nullable=True)       # plano, sin FK
    nombre_grupo = Column(String(100), nullable=False)
    nombre_opcion = Column(String(150), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    cantidad = Column(Integer, default=1, nullable=False)
    ticket_item = relationship("TicketItem", back_populates="combo_selecciones")
    producto = relationship("Producto")


# ---------------------------------------------------------------------------
# Turno multi-barista (responsabilidad compartida)
# ---------------------------------------------------------------------------

class TurnoBarista(Base):
    """Baristas asignados a un turno para trazabilidad colectiva."""
    __tablename__ = "turno_baristas"
    id = Column(Integer, primary_key=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    nombre_snapshot = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    salida_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("turno_id", "usuario_id", name="uq_turno_barista"),)
    turno = relationship("CajaTurno", back_populates="baristas_turno")
    usuario = relationship("Usuario")


# ---------------------------------------------------------------------------
# Fase 2: Motor de Rutinas (recurrentes como EVENTOS) + bitácora operativa
# ---------------------------------------------------------------------------

class FrecuenciaRutinaEnum(str, enum.Enum):
    por_turno = "por_turno"
    diaria = "diaria"
    semanal = "semanal"


class CategoriaRutinaEnum(str, enum.Enum):
    limpieza = "limpieza"
    surtido = "surtido"
    banos = "banos"
    vitrina = "vitrina"
    temperatura = "temperatura"
    otro = "otro"


class RutinaPlantilla(Base):
    """La REGLA: define qué rutina recurrente existe y su cadencia esperada.
    No es el evento — es la expectativa contra la que se mide el cumplimiento."""
    __tablename__ = "rutina_plantillas"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="CASCADE"), nullable=True, index=True)  # null = todas las sedes
    clave = Column(String(60), nullable=False)
    nombre = Column(String(150), nullable=False)
    categoria = Column(SAEnum(CategoriaRutinaEnum), nullable=False, default=CategoriaRutinaEnum.otro)
    frecuencia = Column(SAEnum(FrecuenciaRutinaEnum), nullable=False, default=FrecuenciaRutinaEnum.por_turno)
    esperadas_por_periodo = Column(Integer, default=1)      # cuántas veces se espera por turno/día/semana
    requiere_evidencia = Column(Boolean, default=False)     # foto obligatoria
    requiere_valor = Column(Boolean, default=False)         # captura un número (ej. temperatura)
    activa = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RutinaEvento(Base):
    """El HECHO: la rutina se ejecutó. Una fila por ejecución — fecha, hora,
    usuario, turno. La EXISTENCIA de la fila ES el cumplimiento (no hay booleano)."""
    __tablename__ = "rutina_eventos"
    id = Column(Integer, primary_key=True)
    plantilla_id = Column(Integer, ForeignKey("rutina_plantillas.id", ondelete="RESTRICT"), nullable=False, index=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    dia_operativo_id = Column(Integer, ForeignKey("dias_operativos.id", ondelete="SET NULL"), nullable=True, index=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="RESTRICT"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    valor = Column(Float, nullable=True)                   # temperatura/cantidad si aplica
    nota = Column(String(300), nullable=True)
    imagen_url = Column(String(300), nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow, index=True)
    # Barista REAL que operó (≠ usuario_id del dispositivo/kiosko). Columna PLANA sin FK.
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    plantilla = relationship("RutinaPlantilla")


class CategoriaEventoEnum(str, enum.Enum):
    turno = "turno"
    inventario = "inventario"
    ventas = "ventas"
    caja = "caja"
    seguridad = "seguridad"
    rutina = "rutina"
    sistema = "sistema"


class AuditEvent(Base):
    """Bitácora operativa estructurada — un evento por acción, consultable para
    dashboards y alertas en tiempo real. Distinta del AuditLog forense (diffs)."""
    __tablename__ = "audit_events"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="SET NULL"), nullable=True, index=True)
    dia_operativo_id = Column(Integer, ForeignKey("dias_operativos.id", ondelete="SET NULL"), nullable=True, index=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="SET NULL"), nullable=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True, index=True)
    categoria = Column(SAEnum(CategoriaEventoEnum), nullable=False, index=True)
    accion = Column(String(80), nullable=False)            # 'venta.crear', 'turno.abrir', 'temp.fuera_rango'
    entidad = Column(String(50), nullable=True)
    entidad_id = Column(Integer, nullable=True)
    payload = Column(Text, nullable=True)                  # JSON
    fecha = Column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# Fase 3: Novedades (bitácora humana por turno, con arrastre entre turnos)
# ---------------------------------------------------------------------------

class CategoriaNovedadEnum(str, enum.Enum):
    incidente = "incidente"
    equipo = "equipo"
    personal = "personal"
    cliente = "cliente"
    seguridad = "seguridad"
    otro = "otro"


class Novedad(Base):
    """Evento operativo narrado por una persona (≠ AuditLog de sistema).

    Incidentes, notas para el siguiente turno, etc. Una novedad con
    requiere_seguimiento y sin resolver se arrastra a los turnos posteriores
    del mismo día (y más allá) hasta que alguien la resuelve — reemplaza el
    'le aviso por WhatsApp a la del otro turno'.
    """
    __tablename__ = "novedades"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    dia_operativo_id = Column(Integer, ForeignKey("dias_operativos.id", ondelete="SET NULL"), nullable=True, index=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="SET NULL"), nullable=True, index=True)
    categoria = Column(SAEnum(CategoriaNovedadEnum), nullable=False, default=CategoriaNovedadEnum.otro)
    nivel = Column(String(20), default="info")             # info | importante | urgente
    titulo = Column(String(150), nullable=False)
    descripcion = Column(Text, nullable=True)
    requiere_seguimiento = Column(Boolean, default=False, index=True)
    resuelta = Column(Boolean, default=False, index=True)
    resuelta_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    fecha_resuelta = Column(DateTime, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    imagen_url = Column(String(300), nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow, index=True)


# ---------------------------------------------------------------------------
# Fase 4: Control de temperaturas (cadena de frío) + Recepción de mercancía
# ---------------------------------------------------------------------------

class TipoEquipoEnum(str, enum.Enum):
    refrigerador = "refrigerador"
    congelador = "congelador"
    nevera_vitrina = "nevera_vitrina"
    ambiente = "ambiente"


class EquipoFrio(Base):
    """Equipo de frío con su rango seguro. El reading se mide contra estos umbrales."""
    __tablename__ = "equipos_frio"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = Column(String(100), nullable=False)
    tipo = Column(SAEnum(TipoEquipoEnum), nullable=False, default=TipoEquipoEnum.refrigerador)
    temp_min = Column(Float, nullable=False, default=0.0)
    temp_max = Column(Float, nullable=False, default=8.0)
    activo = Column(Boolean, default=True)


class LecturaTemperatura(Base):
    """Lectura puntual de temperatura. fuera_de_rango se computa al guardar."""
    __tablename__ = "temperaturas_lecturas"
    id = Column(Integer, primary_key=True)
    equipo_id = Column(Integer, ForeignKey("equipos_frio.id", ondelete="RESTRICT"), nullable=False, index=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    dia_operativo_id = Column(Integer, ForeignKey("dias_operativos.id", ondelete="SET NULL"), nullable=True, index=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="SET NULL"), nullable=True, index=True)
    valor = Column(Float, nullable=False)
    fuera_de_rango = Column(Boolean, default=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    observacion = Column(String(200), nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow, index=True)
    equipo = relationship("EquipoFrio")


class EstadoRecepcionEnum(str, enum.Enum):
    borrador = "borrador"
    confirmada = "confirmada"


class Recepcion(Base):
    """Recepción de mercancía. Al confirmar, escribe inventario (entrada + lote) y
    SANA el stock negativo: si estaba en -4 y se reciben 20, queda en 16."""
    __tablename__ = "recepciones"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    dia_operativo_id = Column(Integer, ForeignKey("dias_operativos.id", ondelete="SET NULL"), nullable=True, index=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="SET NULL"), nullable=True, index=True)
    proveedor = Column(String(150), nullable=True)
    factura_id = Column(Integer, ForeignKey("facturas_compra.id", ondelete="SET NULL"), nullable=True)
    estado = Column(SAEnum(EstadoRecepcionEnum), default=EstadoRecepcionEnum.borrador, nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    nota = Column(String(300), nullable=True)
    imagen_url = Column(String(300), nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow, index=True)
    items = relationship("RecepcionItem", back_populates="recepcion", cascade="all, delete-orphan")


class RecepcionItem(Base):
    __tablename__ = "recepcion_items"
    id = Column(Integer, primary_key=True)
    recepcion_id = Column(Integer, ForeignKey("recepciones.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    cantidad_recibida = Column(Float, nullable=False)
    cantidad_factura = Column(Float, nullable=True)        # lo que dice la factura → diferencia
    numero_lote = Column(String(100), nullable=True)
    fecha_vencimiento = Column(DateTime, nullable=True)
    precio_unitario = Column(Numeric(12, 2, asdecimal=False), nullable=True)
    recepcion = relationship("Recepcion", back_populates="items")
    producto = relationship("Producto")


# ---------------------------------------------------------------------------
# Fase 5: Nota Crédito (reversión de venta) — acción del admin
# ---------------------------------------------------------------------------

class NotaCredito(Base):
    """Reversión contable de una venta. Conecta contabilidad con inventario:
    devuelve la plata siempre; el inventario solo recupera lo que NO se usó."""
    __tablename__ = "notas_credito"
    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=False, index=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="RESTRICT"), nullable=False, index=True)
    dia_operativo_id = Column(Integer, ForeignKey("dias_operativos.id", ondelete="SET NULL"), nullable=True, index=True)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id", ondelete="SET NULL"), nullable=True, index=True)
    usuario_admin_id = Column(Integer, ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False)
    motivo = Column(Text, nullable=False)
    valor_revertido = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow, index=True)
    items = relationship("NotaCreditoItem", back_populates="nota", cascade="all, delete-orphan")


class NotaCreditoItem(Base):
    __tablename__ = "notas_credito_items"
    id = Column(Integer, primary_key=True)
    nota_credito_id = Column(Integer, ForeignKey("notas_credito.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False)
    cantidad = Column(Float, nullable=False)
    producto_usado = Column(Boolean, nullable=False)   # True = consumido (no vuelve) | False = vuelve al stock
    nota = relationship("NotaCredito", back_populates="items")


# ─── Inventario físico mensual (módulo de conciliación) ───────────────────────
class InventarioMensual(Base):
    """Conteo físico COMPLETO mensual por sede. Relacional: FK a tienda y usuario;
    items con FK a producto. estado en_proceso → cerrado al finalizar el conteo."""
    __tablename__ = "inventarios_mensuales"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False, index=True)
    anio = Column(Integer, nullable=False)
    mes = Column(Integer, nullable=False)
    estado = Column(String(20), default="en_proceso")   # en_proceso | cerrado
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    fecha_inicio = Column(DateTime, default=datetime.utcnow)
    fecha_cierre = Column(DateTime, nullable=True)
    # Cuándo se cerró la PRIMERA vez. `fecha_cierre` la borra cada reabertura, así
    # que preguntarle a ella "¿este mes ya pasó por un cierre?" solo funcionaba una
    # vez: la segunda reabertura veía un mes virgen y volvía a fotografiar el stock
    # de HOY sobre la foto del período. Esta columna NO se limpia nunca — es la
    # marca de que existe una medición que proteger.
    fecha_primer_cierre = Column(DateTime, nullable=True)
    # Cuándo se APLICÓ al inventario (stock += diferencia por producto). Null = no
    # aplicado. Un mes aplicado es histórico: no se reabre, corrige ni re-aplica.
    fecha_aplicado = Column(DateTime, nullable=True)
    valor_diferencia_total = Column(Numeric(12, 2, asdecimal=False), default=0)
    tienda = relationship("Tienda")
    items = relationship("InventarioMensualItem", back_populates="inventario", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("tienda_id", "anio", "mes", name="uq_inv_mensual_tienda_periodo"),
    )


class InventarioMensualItem(Base):
    __tablename__ = "inventarios_mensuales_items"
    id = Column(Integer, primary_key=True)
    inventario_id = Column(Integer, ForeignKey("inventarios_mensuales.id", ondelete="CASCADE"), nullable=False, index=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    categoria = Column(String(30), nullable=True)
    unidad_medida = Column(String(30), nullable=True)
    cantidad_sistema = Column(Float, default=0)
    cantidad_real = Column(Float, nullable=True)       # null = aún no contado
    # Si alguien puso ese número o lo rellenó el cierre. `cerrar()` iguala
    # cantidad_real al sistema para todo lo no contado (así la diferencia da 0 y
    # no ensucia el total), y sin esta bandera un producto "contado y dio exacto"
    # queda IDÉNTICO a uno que nadie tocó: la fuga se esconde por definición y un
    # mes con 12 de 180 productos contados se ve igual que uno completo.
    fue_contado = Column(Boolean, default=False)
    diferencia = Column(Float, default=0)
    valor_unitario = Column(Numeric(12, 2, asdecimal=False), default=0)
    valor_diferencia = Column(Numeric(12, 2, asdecimal=False), default=0)
    inventario = relationship("InventarioMensual", back_populates="items")
    producto = relationship("Producto")


# ---------------------------------------------------------------------------
# Costos — obligaciones y pagos (Fase 1)
#
# El arriendo que se paga un sábado por transferencia desde el celular no cabe en
# MovimientoCaja: ese modelo exige un turno ABIERTO con cuadre de llegada hecho
# (services/caja.py::registrar_movimiento) y ni siquiera acepta una fecha propia.
# Acá el costo vive por sí solo, con su fecha de devengo y su fecha de pago.
# ---------------------------------------------------------------------------


class CostoCategoria(Base):
    """Catálogo de categorías de costo. La `clave` (slug estable) mata el texto
    libre: hoy 'Arriendo local' / 'arriendo' / 'ARRIENDO LOCAL' serían tres filas
    distintas al agrupar gastos. El `nombre` es el display y se puede editar sin
    romper el agrupamiento."""
    __tablename__ = "costos_categorias"
    id = Column(Integer, primary_key=True)
    clave = Column(String(40), unique=True, index=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    grupo = Column(String(20), nullable=False)   # 'fijo' | 'variable'
    # A qué mundo pertenece la plata de esta categoría. 'cafe' = costo del
    # negocio (elegible para obligaciones, entra al P&L salvo clave excluida);
    # 'personal' = plata del dueño como persona natural (cuota del carro, la
    # casa): SOLO etiqueta filas del libro del banco y JAMÁS toca resultado ni
    # punto de equilibrio — el dueño dirige el café desde la misma cuenta que su
    # casa y esa plata necesita dónde vivir sin ensuciar los números del café;
    # 'banco' = costos del propio banco (GMF, comisión), sembradas, solo libro.
    ambito = Column(String(20), nullable=False, default="cafe")
    orden = Column(Integer, nullable=True)
    activa = Column(Boolean, default=True)       # baja lógica, nunca DELETE


class Obligacion(Base):
    """Un costo del negocio: qué se debe, a quién, de qué mes y para cuándo."""
    __tablename__ = "obligaciones"
    id = Column(Integer, primary_key=True)
    # NULLABLE A PROPÓSITO: el arriendo o la nómina corporativa NO pertenecen a una
    # sede. Esa es la razón estructural por la que este modelo no cuelga de
    # MovimientoCaja, que siempre está atado a un turno —y por lo tanto a una sede.
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), index=True, nullable=True)
    categoria_id = Column(Integer, ForeignKey("costos_categorias.id"), nullable=False)
    concepto = Column(String(200), nullable=False)
    beneficiario = Column(String(150), nullable=True)
    monto = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    # El día en que el costo SE CAUSA (a qué mes pertenece en el P&L). Date nativo y
    # NO DateTime: es una fecha de negocio, así esquiva el corrimiento UTC-5.
    fecha_devengo = Column(Date, index=True, nullable=False)
    fecha_vencimiento = Column(Date, index=True, nullable=True)  # cuándo hay que pagarla
    # NO HAY COLUMNA `recurrencia`, Y NO ES UN OLVIDO. Existió como
    # NULL | 'mensual' | 'quincenal' | 'semanal', se validaba y se guardaba, y
    # NADIE la leía: `repetir_obligacion` copia SIEMPRE al mes siguiente. Una
    # obligación marcada 'quincenal' daba el mes que viene igual, o sea que el
    # campo afirmaba una periodicidad que el sistema no respetaba. Respetarla no
    # era cambiar una función: la llave de idempotencia de la serie es (serie,
    # MES de devengo) y la pantalla decide qué falta copiar con
    # `fecha_devengo.slice(0,7)`, así que una serie quincenal habría quedado
    # marcada como «ya está» con la primera copia del mes. Sin formulario que la
    # pudiera setear y sin una sola obligación quincenal en el negocio, se saca.
    # En las bases viejas la COLUMNA sigue existiendo con NULL o 'mensual': es
    # nullable, ningún INSERT la necesita y nada la lee.
    plantilla_id = Column(Integer, nullable=True)   # columna PLANA sin FK (autorreferencia)
    nota = Column(Text, nullable=True)
    imagen_url = Column(String(300), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Barista REAL que operó (≠ usuario_id del dispositivo/kiosko). Columnas PLANAS sin FK
    # para no introducir un segundo ForeignKey a usuarios (AmbiguousForeignKeysError).
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    fecha_registro = Column(DateTime, default=datetime.utcnow)   # cuándo se TECLEÓ (≠ devengo)
    anulada = Column(Boolean, default=False)   # baja lógica: borrar dejaría pagos huérfanos
    # NO existe una columna valor_pagado. El estado se DERIVA de la suma de pagos vivos:
    # pendiente (Σ == 0) | parcial (0 < Σ < monto) | pagada (Σ >= monto). `anulada` es el
    # único estado almacenado. Asimetría DELIBERADA con FacturaCompra.valor_pagado, que es
    # justamente la columna que se puede desincronizar de sus movimientos.
    tienda = relationship("Tienda")
    categoria = relationship("CostoCategoria")
    usuario = relationship("Usuario")


class Pago(Base):
    """La plata que efectivamente salió, con SU fecha. Cuelga de una obligación o
    de una factura de proveedor — exactamente una de las dos (validado en el servicio)."""
    __tablename__ = "pagos"
    id = Column(Integer, primary_key=True)
    obligacion_id = Column(Integer, index=True, nullable=True)   # columna PLANA sin FK
    # Columna PLANA sin FK por una razón dura: eliminar_factura (services/facturas.py)
    # hace un db.delete real. Con FK RESTRICT ese borrado quedaría bloqueado; con CASCADE
    # se perdería la traza del pago. Mismo argumento que ya documenta MovimientoCaja.factura_id.
    factura_id = Column(Integer, index=True, nullable=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), index=True, nullable=True)  # snapshot del padre
    monto = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    # EL DÍA QUE SALIÓ LA PLATA — la columna que hoy no existe en ninguna parte del
    # sistema. Date nativo por la misma razón que fecha_devengo.
    fecha_pago = Column(Date, index=True, nullable=False)
    metodo = Column(String(20), nullable=False)   # efectivo|transferencia|tarjeta|cheque|otro
    # Llave anti-doble-conteo de la adopción de egresos de caja ya registrados. La
    # escribe `costos.adoptar_egreso`, y la LEE `costos._efectivo_en_mano` para no
    # restar de la mano del dueño una plata que ya salió de la registradora.
    movimiento_caja_id = Column(Integer, nullable=True)
    imagen_soporte_url = Column(String(300), nullable=True)
    nota = Column(String(300), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    # Barista REAL que operó. Columnas PLANAS sin FK (mismo patrón que el resto del repo).
    barista_id = Column(Integer, nullable=True)
    barista_nombre = Column(String(100), nullable=True)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    anulado = Column(Boolean, default=False)
    tienda = relationship("Tienda")
    usuario = relationship("Usuario")
    # Un egreso de caja se adopta UNA sola vez, garantizado por la DB y no por el
    # servicio. Índice único PARCIAL (mismo patrón que ConteoFisico.uq_conteo_turno_tipo)
    # porque los pagos que no vienen de caja tienen movimiento_caja_id NULL de a montones.
    __table_args__ = (
        Index(
            "uq_pago_movimiento_caja", "movimiento_caja_id", unique=True,
            postgresql_where=text("movimiento_caja_id IS NOT NULL"),
            sqlite_where=text("movimiento_caja_id IS NOT NULL"),
        ),
    )


class Configuracion(Base):
    """Ajustes globales editables en runtime (key-value). Ej: 'kiosk_pin'."""
    __tablename__ = "configuracion"
    id = Column(Integer, primary_key=True)
    clave = Column(String(50), unique=True, nullable=False, index=True)
    valor = Column(String(255), nullable=True)


# ---------------------------------------------------------------------------
# Módulo Horarios & Nómina: tasas de ley con vigencia, festivos, turnos
# programados, novedades laborales y contrato de la barista.
#
# TODAS estas tablas son NUEVAS: las crea create_all() y no necesitan ALTER en
# el loop de main.py (ese loop solo hace falta para columnas sobre tablas viejas).
# ---------------------------------------------------------------------------

class TasaLaboral(Base):
    """Parámetros legales de liquidación, CON VIGENCIA.

    Jamás constantes en el código: la ley colombiana está en transición (la
    jornada máxima baja por etapas y los recargos dominicales suben por etapas),
    así que un número quemado envejece en silencio y obliga a un deploy por cada
    cambio de norma.

    Cada fila es un SNAPSHOT COMPLETO vigente desde `vigente_desde`. El cálculo
    resuelve la tasa por la FECHA DEL TURNO, no por hoy: un turno de junio se
    liquida con la tasa de junio aunque hoy rija otra. Recalcular un mes viejo da
    siempre el mismo resultado.

    `nota` dice de qué norma sale el número y `confirmar_contador` marca las que
    el dueño todavía tiene que validar. Son EDITABLES desde la pantalla: el
    sistema no reemplaza al contador.
    """
    __tablename__ = "tasas_laborales"
    id = Column(Integer, primary_key=True)
    vigente_desde = Column(Date, nullable=False, unique=True, index=True)
    # Jornada máxima ORDINARIA por semana (art. 161 CST + Ley 2101/2021).
    jornada_max_semanal = Column(Float, nullable=False, default=42.0)
    # Franja nocturna en HORA COLOMBIA: [inicio, fin) cruzando la medianoche.
    hora_inicio_nocturna = Column(Integer, nullable=False, default=19)
    hora_fin_nocturna = Column(Integer, nullable=False, default=6)
    # Recargos como FRACCIÓN (0.35 = 35% adicional sobre la hora ordinaria).
    recargo_nocturno = Column(Float, nullable=False, default=0.35)
    recargo_dominical = Column(Float, nullable=False, default=0.90)
    # NULL = se DERIVA como recargo_dominical + recargo_nocturno. Se deja
    # nullable a propósito: si fuera un número fijo y alguien editara solo el
    # dominical, los dos quedarían en desacuerdo sin que nadie lo note.
    recargo_dominical_nocturno = Column(Float, nullable=True)
    extra_diurna = Column(Float, nullable=False, default=0.25)
    extra_nocturna = Column(Float, nullable=False, default=0.75)
    # Divisor convencional para pasar de sueldo mensual a valor hora ordinaria.
    divisor_hora_mensual = Column(Float, nullable=False, default=240.0)
    nota = Column(Text, nullable=True)
    confirmar_contador = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ParametroNomina(Base):
    """Plata de la nómina colombiana CON VIGENCIA: mínimo, auxilio y aportes.

    Hermana de `TasaLaboral` y por el mismo motivo: el salario mínimo y el
    auxilio de transporte se decretan cada diciembre y rigen desde el 1 de
    enero. Un número quemado en el código no avisa cuando envejece — el sistema
    sigue liquidando con el mínimo del año pasado y nadie se entera hasta que
    alguien compara con el desprendible. Cada fila es un SNAPSHOT COMPLETO
    vigente desde `vigente_desde`, y el cálculo resuelve por la FECHA DEL
    PERÍODO liquidado: recalcular un mes de 2025 usa el mínimo de 2025.

    TABLA APARTE de `tasas_laborales` y no columnas nuevas sobre ella, por dos
    razones. Una práctica: `tasas_laborales` ya existe en producción, así que
    cada columna nueva ahí exigiría su ALTER en el loop de main.py, mientras que
    una tabla nueva la crea `create_all` sola. Y otra de fondo: los recargos
    cambian por ETAPAS de una reforma (16-jul-2025, 1-jul-2026...) y el mínimo
    cambia cada 1 de enero. Son dos calendarios distintos; meterlos en la misma
    fila obligaría a duplicar cada snapshot por los cortes del otro.

    Es EDITABLE desde la pantalla, igual que las tasas: el sistema no reemplaza
    al contador, le da un piso verificable.
    """
    __tablename__ = "parametros_nomina"
    id = Column(Integer, primary_key=True)
    vigente_desde = Column(Date, nullable=False, unique=True, index=True)

    # ── Lo que se decreta cada diciembre ──────────────────────────────────────
    smmlv = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    auxilio_transporte = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    # El auxilio se prorratea por DÍA con divisor 30 fijo — no por los días
    # calendario del mes. Un febrero no paga más caro el día que un enero.
    dias_base_auxilio = Column(Integer, nullable=False, default=30)
    # Tienen derecho al auxilio quienes devengan hasta 2 SMMLV. Se guarda EN
    # SMMLV y no en pesos para que el umbral se mueva solo con el mínimo.
    tope_auxilio_smmlv = Column(Float, nullable=False, default=2.0)

    # ── Deducciones del TRABAJADOR (salen de su sueldo) ───────────────────────
    # Sobre el IBC, que incluye recargos y extras pero NO el auxilio.
    salud_empleado = Column(Float, nullable=False, default=0.04)
    pension_empleado = Column(Float, nullable=False, default=0.04)
    # Fondo de Solidaridad Pensional: solo desde 4 SMMLV, o sea que a una
    # barista de mínimo no le aplica. Se guarda el umbral igual para que el día
    # que haya un sueldo alto el sistema no lo ignore en silencio.
    fsp_desde_smmlv = Column(Float, nullable=False, default=4.0)
    fsp_tarifa = Column(Float, nullable=False, default=0.01)

    # ── Aportes del EMPLEADOR (van por encima del sueldo) ─────────────────────
    salud_empleador = Column(Float, nullable=False, default=0.085)
    pension_empleador = Column(Float, nullable=False, default=0.12)
    # ARL por clase de riesgo. Decreto 1607/2002 pone «expendio a la mesa de
    # comidas preparadas en cafeterías» en CLASE I = 0,522%. Sube a clase II si
    # el expendio es por autoservicio y a III si se hornea pan en la sede, así
    # que es EDITABLE: el sistema no puede ver cómo trabaja el local.
    arl = Column(Float, nullable=False, default=0.00522)
    caja_compensacion = Column(Float, nullable=False, default=0.04)
    sena = Column(Float, nullable=False, default=0.02)
    icbf = Column(Float, nullable=False, default=0.03)
    # Exoneración del art. 114-1 ET: apaga salud patronal (8,5%), SENA e ICBF
    # por cada trabajador de menos de 10 SMMLV. NO apaga la caja (4%), que se
    # paga siempre. Cubre a sociedades declarantes de renta, a la persona
    # natural con DOS O MÁS trabajadores y al Régimen Simple; deja afuera a la
    # persona natural con un solo empleado y a las ESAL.
    #
    # Arranca en FALSE a propósito. El sistema no puede saber cómo está
    # constituido el negocio, y de los dos errores posibles este es el barato:
    # sobreestimar el costo hace ver el margen peor de lo que es, que es el lado
    # seguro para decidir. Prenderlo es un click y la pantalla dice cuánto vale.
    exonerado_114_1 = Column(Boolean, nullable=False, default=False)

    # ── Prestaciones sociales (provisión mensual equivalente) ─────────────────
    # OJO CON LAS BASES, que son DOS y es el error clásico: prima, cesantías e
    # intereses se liquidan sobre salario + auxilio (excepción del art. 7 de la
    # Ley 1ª de 1963), y las vacaciones SOLO sobre el salario.
    prima = Column(Float, nullable=False, default=0.0833333)
    cesantias = Column(Float, nullable=False, default=0.0833333)
    intereses_cesantias = Column(Float, nullable=False, default=0.01)
    vacaciones = Column(Float, nullable=False, default=0.0416667)

    nota = Column(Text, nullable=True)
    confirmar_contador = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CuentaBancaria(Base):
    """Los rieles por donde entra y sale la plata del banco.

    El dueño ya los lleva así en su hoja de tesorería: OCCIDENTE (lo que se
    consigna en efectivo) y BOLD (lo que liquida el datáfono), cada uno con su
    columna de entradas y su columna de débitos. Sin la cuenta, un movimiento
    dice cuánto se movió pero no por dónde, y conciliar contra el extracto —que
    llega por banco— deja de ser posible.
    """
    __tablename__ = "cuentas_bancarias"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(60), nullable=False, unique=True)
    # Para ordenar las columnas como están en la hoja, sin depender del id.
    orden = Column(Integer, nullable=False, default=0)
    activa = Column(Boolean, nullable=False, default=True)
    nota = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class MovimientoBanco(Base):
    """UN movimiento del banco, TECLEADO. El libro, no la proyección.

    ═══════════════════════════════════════════════════════════════════════════
    POR QUÉ TECLEADO Y NO DERIVADO — ES UNA DECISIÓN, NO UNA LIMITACIÓN
    ═══════════════════════════════════════════════════════════════════════════
    El sistema podría deducir lo que entró al banco de las consignaciones que ya
    registra y de las ventas con tarjeta. Sería menos trabajo diario y estaría
    MAL: el datáfono liquida con rezago y con comisión descontada, así que el
    número deducido nunca coincide con el extracto. El dueño eligió teclearlo,
    que es lo que hace hace años, porque un libro que cuadra al peso con el
    banco vale más que uno cómodo que no cuadra.

    Consecuencia que hay que respetar en todo el módulo: esta tabla es LA
    VERDAD del saldo. Nada de acá se recalcula desde tickets ni consignaciones.

    EL SALDO NO SE GUARDA, SE DERIVA. No hay columna de saldo: se calcula como
    ancla + Σ(entradas − salidas) hasta la fecha. Guardar el saldo de cada día
    obligaría a reescribir toda la cadena al corregir un movimiento viejo, y el
    día que un recálculo fallara a la mitad el libro quedaría partido en dos sin
    que nadie lo note. Derivado, corregir un movimiento arregla todo aguas abajo
    solo — que es exactamente lo que hace la fórmula de su hoja.
    """
    __tablename__ = "movimientos_banco"
    id = Column(Integer, primary_key=True)
    # LA SEDE dueña de este movimiento. Nullable: los históricos (enero–julio, el
    # banco combinado) van con NULL —no estaban separados por sede y no se pueden
    # repartir hacia atrás—; de agosto en adelante cada movimiento se teclea con su
    # sede. `libro(tienda_id=...)` filtra por acá; la vista «Ambas» no filtra.
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=True, index=True)
    # Fecha del banco (no un timestamp): la hoja es día por día y el extracto
    # también. Sin hora no hay que pelear con la zona horaria acá.
    fecha = Column(Date, nullable=False, index=True)
    cuenta_id = Column(Integer, ForeignKey("cuentas_bancarias.id", ondelete="RESTRICT"),
                       nullable=False, index=True)
    # 'entrada' | 'salida'. Los montos se guardan SIEMPRE en positivo y el signo
    # lo pone el tipo: un monto negativo en una columna de salidas se resta dos
    # veces y nadie lo ve hasta que el saldo no cuadra.
    tipo = Column(String(10), nullable=False)
    monto = Column(Numeric(12, 2, asdecimal=False), nullable=False)
    concepto = Column(String(160), nullable=False)
    # Marca los que el sistema puede sugerir solo (GMF, comisión) para poder
    # distinguirlos de lo que el dueño escribió a mano.
    automatico = Column(Boolean, nullable=False, default=False)
    # DEPÓSITO DE LO RECOGIDO: esta entrada NO es plata nueva, es efectivo que el
    # dueño ya había recogido (y que el libro ya contó como entrada de la MANO) y
    # ahora deposita en el banco. Para el banco es una entrada real —el extracto
    # la muestra y la cadena tiene que cuadrar con ella—, pero para el TOTAL del
    # libro (banco + mano) es neutra: sube el banco y baja la mano por el mismo
    # monto. Sin esta marca, la plata recogida quedaría contada dos veces —una al
    # recogerla, otra al depositarla—. Solo tiene sentido en las entradas.
    desde_mano = Column(Boolean, nullable=False, default=False)
    # Enlace a la obligación que este movimiento paga. Lo consumen
    # `costos._salidas_banco_por_obligacion` y `cubierto_de` (descuentan de la
    # agenda lo ya debitado, combinando con los pagos por MÁXIMO y no por suma),
    # y lo escriben el formulario del libro y el pago que descuenta del banco en
    # la misma transacción (`costos.registrar_pago` con `descontar_banco`).
    obligacion_id = Column(Integer, ForeignKey("obligaciones.id", ondelete="SET NULL"),
                           nullable=True, index=True)
    # La categoría del movimiento (misma tabla que las obligaciones, con su
    # `ambito`): es lo que permite contestar «cuánto nos estamos gastando en
    # cada cosa» a lo largo de los meses, y separar la plata personal de la del
    # café sin inventar un segundo catálogo. Nullable: el concepto libre sigue
    # siendo válido — un movimiento sin categoría es «sin clasificar», no un
    # error.
    categoria_id = Column(Integer, ForeignKey("costos_categorias.id", ondelete="SET NULL"),
                          nullable=True, index=True)
    nota = Column(String(300), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    cuenta = relationship("CuentaBancaria")
    categoria = relationship("CostoCategoria")


class ParametroTributario(Base):
    """Impuestos que tocan la venta y la plata, CON VIGENCIA.

    Tercera hermana de `TasaLaboral` y `ParametroNomina`, por el mismo motivo:
    las tarifas las mueve una reforma y un número quemado no avisa cuando
    envejece. Tabla aparte y no columnas sobre las otras dos porque los tres
    calendarios son distintos —los recargos cambian por etapas de la reforma
    laboral, el mínimo cada 1 de enero, y los impuestos cuando sale una
    tributaria—; meterlos juntos obligaría a duplicar cada snapshot por los
    cortes de los otros.

    ═══════════════════════════════════════════════════════════════════════════
    EL IMPOCONSUMO NO ES PLATA DEL NEGOCIO.
    ═══════════════════════════════════════════════════════════════════════════
    El precio de la carta lo lleva ADENTRO: una aromática de $5.900 son $5.463
    de venta y $437 que se le giran a la DIAN. Hasta acá el sistema sumaba los
    $5.900 como venta propia, así que TODO margen que mostró estaba inflado —
    7,41% de cada peso facturado era un impuesto contado como utilidad.

    Se guarda `precio_incluye_impoconsumo` porque las dos formas existen: si el
    precio ya lo lleva adentro, la venta neta es total/(1+tasa); si se suma
    aparte, la venta neta es el total. Confundirlas mueve el margen un 8%.
    """
    __tablename__ = "parametros_tributarios"
    id = Column(Integer, primary_key=True)
    vigente_desde = Column(Date, nullable=False, unique=True, index=True)
    # Impuesto nacional al consumo de bares y restaurantes.
    impoconsumo = Column(Float, nullable=False, default=0.08)
    # True = el precio de la carta ya lo incluye (es el caso de MEDIUM CAFÉ).
    precio_incluye_impoconsumo = Column(Boolean, nullable=False, default=True)
    # Gravamen a los movimientos financieros (4x1000). Sale del banco en cada
    # movimiento y ningún reporte del sistema lo veía: medido en el flujo de
    # caja real del dueño, $3,4 millones en siete meses.
    gmf = Column(Float, nullable=False, default=0.004)
    nota = Column(Text, nullable=True)
    confirmar_contador = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Festivo(Base):
    """OVERRIDE de festivos, no el catálogo.

    La base la calcula `services/festivos.py` (Ley 51/1983 + Pascua). Esta tabla
    solo AGREGA un día que el código no conoce (un cívico local) o QUITA uno
    calculado (`es_festivo=False`) cuando en la práctica se trabaja normal.
    """
    __tablename__ = "festivos"
    id = Column(Integer, primary_key=True)
    fecha = Column(Date, nullable=False, unique=True, index=True)
    nombre = Column(String(120), nullable=False)
    es_festivo = Column(Boolean, default=True, nullable=False)
    nota = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ContratoBarista(Base):
    """Datos de nómina de una persona. Tabla APARTE de `usuarios` a propósito:
    `usuarios` es una tabla vieja y cada columna nueva ahí exige un ALTER en el
    loop de main.py; además el sueldo no tiene por qué viajar en cada query de
    login. Una fila por usuario (unique)."""
    __tablename__ = "contratos_barista"
    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
                        nullable=False, unique=True, index=True)
    salario_mensual = Column(Numeric(12, 2, asdecimal=False), default=0.0, nullable=False)
    # Sueldo expresado EN SMMLV (1.0 = el mínimo). Cuando está puesto, MANDA
    # sobre `salario_mensual` y el sueldo se deriva del mínimo vigente en la
    # fecha liquidada. Dos cosas se arreglan solas con esto: en enero el sueldo
    # sube sin que nadie se acuerde, y un mes viejo se recalcula con el mínimo
    # de SU año en vez de con el de hoy. Sin esto, subir a la barista al mínimo
    # de 2026 reescribía hacia atrás todos los meses de 2025 ya liquidados.
    # NULL = sueldo en pesos fijos, que sigue siendo válido para quien gana por
    # encima del mínimo y no se mueve con él.
    salario_en_smmlv = Column(Float, nullable=True)
    # Jornada PACTADA (medio tiempo, etc.). NULL = la máxima legal de su fecha.
    horas_semana_pactadas = Column(Float, nullable=True)
    fecha_ingreso = Column(Date, nullable=True)
    activo = Column(Boolean, default=True, nullable=False)
    nota = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    usuario = relationship("Usuario")


class EstadoProgramadoEnum(str, enum.Enum):
    borrador = "borrador"      # el admin lo está armando: la barista NO lo ve
    publicado = "publicado"    # enviado, la barista lo ve y le llegó el aviso
    cancelado = "cancelado"    # se dio de baja después de publicado


class TurnoProgramado(Base):
    """El horario PLANEADO (≠ TurnoBarista, que es lo que realmente pasó).

    Las horas se guardan como texto "HH:MM" de RELOJ DE PARED COLOMBIA, no como
    timestamps: un horario es una intención local ("entra a las 7"), no un
    instante UTC, y guardarlo así lo deja inmune al huso. Si hora_fin <= hora_inicio
    el turno cruza la medianoche y termina al día siguiente.
    """
    __tablename__ = "turnos_programados"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    nombre_snapshot = Column(String(100), nullable=False)
    fecha = Column(Date, nullable=False, index=True)
    hora_inicio = Column(String(5), nullable=False)   # "07:00"
    hora_fin = Column(String(5), nullable=False)      # "15:00"
    # ── Almuerzo (descanso NO remunerado dentro del turno) ────────────────────
    # Se guarda como HORA DE PARED + duración, y no como un simple "minutos de
    # descanso", porque el descanso hay que sacarlo de la FRANJA en la que cae:
    # una hora de almuerzo a las 13:00 sale de horas diurnas y una a las 21:00 de
    # horas nocturnas, que valen distinto. Con un total suelto no se sabe de cuál
    # descontar y el recargo queda mal.
    # Los dos NULL = el turno no tiene almuerzo configurado, que es como quedan
    # todos los turnos anteriores a esta columna: sin almuerzo no se descuenta
    # nada y el cálculo da exactamente lo mismo que antes.
    almuerzo_inicio = Column(String(5), nullable=True)      # "13:00"
    almuerzo_minutos = Column(Integer, nullable=True)       # 60
    estado = Column(SAEnum(EstadoProgramadoEnum), nullable=False,
                    default=EstadoProgramadoEnum.borrador, index=True)
    nota = Column(String(300), nullable=True)
    publicado_at = Column(DateTime, nullable=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("usuario_id", "fecha", "hora_inicio",
                         name="uq_programado_barista_fecha_hora"),
    )
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


class TipoNovedadNominaEnum(str, enum.Enum):
    incapacidad = "incapacidad"
    vacaciones = "vacaciones"
    permiso_remunerado = "permiso_remunerado"
    permiso_no_remunerado = "permiso_no_remunerado"
    licencia = "licencia"
    ausencia = "ausencia"
    cambio_turno = "cambio_turno"


class NovedadNomina(Base):
    """Novedad LABORAL de una persona (incapacidad, vacaciones, ausencia…).

    Se llama NovedadNomina y no Novedad porque `Novedad` ya existe en este repo
    y es otra cosa: la bitácora operativa del turno (incidentes, handoff).
    """
    __tablename__ = "novedades_nomina"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    nombre_snapshot = Column(String(100), nullable=False)
    tipo = Column(SAEnum(TipoNovedadNominaEnum), nullable=False, index=True)
    fecha_desde = Column(Date, nullable=False, index=True)
    fecha_hasta = Column(Date, nullable=False, index=True)
    # Se copia del mapa de tipos al crear, pero queda EDITABLE: hay permisos
    # que el dueño decide pagar aunque el default diga que no.
    remunerada = Column(Boolean, nullable=False, default=False)
    nota = Column(Text, nullable=True)
    soporte_url = Column(String(300), nullable=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
