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
    caja_fuerte = Column(Numeric(12, 2, asdecimal=False), nullable=True, default=0.0)
    diferencia_apertura = Column(Numeric(12, 2, asdecimal=False), default=0.0)
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
    # Orden fijo del conteo/inventario (planilla de pedidos). NULL → al final, alfabético.
    orden_conteo = Column(Integer, nullable=True)
    # NULL = conteo diario normal; 'desechables' = solo se cuenta cuando el admin lo pide.
    grupo_conteo = Column(String(20), nullable=True)
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
    solicitud = relationship("SolicitudPedido", back_populates="items")
    producto = relationship("Producto")

    @property
    def nombre(self):
        return self.producto.nombre if self.producto else ""

    @property
    def unidad_medida(self):
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
    diferencia = Column(Float, default=0)
    valor_unitario = Column(Numeric(12, 2, asdecimal=False), default=0)
    valor_diferencia = Column(Numeric(12, 2, asdecimal=False), default=0)
    inventario = relationship("InventarioMensual", back_populates="items")
    producto = relationship("Producto")


class Configuracion(Base):
    """Ajustes globales editables en runtime (key-value). Ej: 'kiosk_pin'."""
    __tablename__ = "configuracion"
    id = Column(Integer, primary_key=True)
    clave = Column(String(50), unique=True, nullable=False, index=True)
    valor = Column(String(255), nullable=True)
