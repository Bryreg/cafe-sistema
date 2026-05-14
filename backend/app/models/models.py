from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, Enum as SAEnum
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


class EstadoSolicitudEnum(str, enum.Enum):
    pendiente = "pendiente"
    aprobada = "aprobada"
    rechazada = "rechazada"


class TipoPagoEnum(str, enum.Enum):
    contado = "contado"
    credito = "credito"
    transferencia = "transferencia"


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


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    pin_hash = Column(String(255), nullable=True)
    rol = Column(SAEnum(RolEnum), nullable=False, default=RolEnum.barista)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=True)
    activo = Column(Boolean, default=True)
    ultimo_acceso = Column(DateTime, nullable=True)   # Etapa 9: seguridad
    tienda = relationship("Tienda", back_populates="usuarios")


class CajaTurno(Base):
    __tablename__ = "caja_turnos"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    usuario_apertura_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    usuario_cierre_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    fecha_apertura = Column(DateTime, default=datetime.utcnow)
    fecha_cierre = Column(DateTime, nullable=True)
    base_sistema = Column(Float, default=0.0)
    base_real = Column(Float, nullable=False)
    diferencia_apertura = Column(Float, default=0.0)
    justificacion_apertura = Column(Text, nullable=True)
    # Totales calculados automáticamente desde VentaDiaria
    total_ventas = Column(Float, default=0.0)
    total_efectivo = Column(Float, default=0.0)
    total_tarjeta = Column(Float, default=0.0)
    efectivo_final_real = Column(Float, nullable=True)   # total contado en caja al cierre
    datafono_real = Column(Float, nullable=True)          # total datáfono Bold al cierre
    diferencia_cierre = Column(Float, nullable=True)
    diferencia_tarjeta = Column(Float, nullable=True)
    justificacion_cierre = Column(Text, nullable=True)
    estado = Column(SAEnum(EstadoTurnoEnum), default=EstadoTurnoEnum.abierto)
    # Flags de flujo obligatorio — solo el backend las activa
    tiene_conteo_apertura = Column(Boolean, default=False)
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


class MovimientoCaja(Base):
    __tablename__ = "movimientos_caja"
    id = Column(Integer, primary_key=True)
    caja_turno_id = Column(Integer, ForeignKey("caja_turnos.id"), nullable=False)
    tipo = Column(SAEnum(TipoMovCajaEnum), nullable=False)
    concepto = Column(String(200), nullable=False)
    valor = Column(Float, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    imagen_url = Column(String(300), nullable=True)
    turno = relationship("CajaTurno", back_populates="movimientos")
    usuario = relationship("Usuario")


class Producto(Base):
    __tablename__ = "productos"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(150), nullable=False)
    categoria = Column(SAEnum(CategoriaProductoEnum), nullable=False)
    unidad_medida = Column(String(30), nullable=False)
    controla_stock = Column(Boolean, default=True)
    proveedor = Column(String(100), nullable=True)
    lead_time_dias = Column(Integer, default=2, server_default="2")
    inventarios = relationship("Inventario", back_populates="producto")
    movimientos_inv = relationship("MovimientoInventario", back_populates="producto")
    pastelerias = relationship("PasteleriaDiaria", back_populates="producto")
    lotes = relationship("LoteInventario", back_populates="producto")
    mermas = relationship("Merma", back_populates="producto")


class Inventario(Base):
    __tablename__ = "inventario"
    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    stock_actual = Column(Float, default=0.0)
    stock_minimo = Column(Float, default=0.0)
    producto = relationship("Producto", back_populates="inventarios")
    tienda = relationship("Tienda", back_populates="inventarios")


class MovimientoInventario(Base):
    __tablename__ = "movimientos_inventario"
    id = Column(Integer, primary_key=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    tipo = Column(SAEnum(TipoMovInvEnum), nullable=False)
    cantidad = Column(Float, nullable=False)
    fecha = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    motivo = Column(String(200), nullable=True)
    producto = relationship("Producto", back_populates="movimientos_inv")
    tienda = relationship("Tienda", back_populates="movimientos_inv")
    usuario = relationship("Usuario")


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
    producto = relationship("Producto", back_populates="lotes")
    tienda = relationship("Tienda", back_populates="lotes")
    usuario = relationship("Usuario")


class VentaDiaria(Base):
    """Registro de ventas del turno — actualiza totales en CajaTurno automáticamente."""
    __tablename__ = "ventas_diarias"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id"), nullable=False)
    venta_total = Column(Float, nullable=False)
    nota_credito = Column(Float, default=0.0)
    vales = Column(Float, default=0.0)
    tarjetas = Column(Float, default=0.0)
    efectivo_calculado = Column(Float, nullable=False)  # venta_total - nota_credito - vales - tarjetas
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    nota = Column(String(300), nullable=True)
    turno = relationship("CajaTurno", back_populates="ventas")
    usuario = relationship("Usuario")


class ConteoFisico(Base):
    """Conteo físico de inventario — apertura activa tiene_conteo_apertura, cierre activa tiene_conteo_cierre."""
    __tablename__ = "conteos_fisicos"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    turno_id = Column(Integer, ForeignKey("caja_turnos.id"), nullable=False)
    tipo = Column(SAEnum(TipoConteoEnum), nullable=False)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    turno = relationship("CajaTurno", back_populates="conteos")
    usuario = relationship("Usuario")
    items = relationship("ConteoFisicoItem", back_populates="conteo", cascade="all, delete-orphan")


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
    tipo = Column(String(20), default="consumo", nullable=False)   # consumo | traslado | daño
    tienda_destino_id = Column(Integer, ForeignKey("tiendas.id"), nullable=True)
    recibido = Column(Boolean, default=False, nullable=False)
    fecha_recibido = Column(DateTime, nullable=True)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tienda = relationship("Tienda", back_populates="mermas", foreign_keys=[tienda_id])
    tienda_destino = relationship("Tienda", foreign_keys=[tienda_destino_id])
    producto = relationship("Producto", back_populates="mermas")
    usuario = relationship("Usuario")


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
    monto_solicitado = Column(Float, nullable=False)
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
    efectivo_esperado = Column(Float, nullable=False)
    efectivo_real = Column(Float, nullable=False)
    ventas_efectivo_siigo = Column(Float, nullable=False)
    ventas_tarjeta_bold = Column(Float, nullable=False)
    diferencia_efectivo = Column(Float, nullable=False)
    diferencia_tarjeta = Column(Float, nullable=False)
    imagen_url = Column(String(300), nullable=True)
    tipo = Column(String(20), default="entrega", nullable=False, server_default="entrega")
    turno = relationship("CajaTurno", back_populates="entregas")
    usuario = relationship("Usuario")


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
    usuario = relationship("Usuario")


class Consignacion(Base):
    __tablename__ = "consignaciones"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    caja_turno_id = Column(Integer, ForeignKey("caja_turnos.id"), nullable=True)
    fecha = Column(DateTime, default=datetime.utcnow)
    valor = Column(Float, nullable=False)
    imagen_url = Column(String(300), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    estado = Column(SAEnum(EstadoConsignacionEnum), default=EstadoConsignacionEnum.pendiente)
    tienda = relationship("Tienda", back_populates="consignaciones")
    turno = relationship("CajaTurno", foreign_keys=[caja_turno_id])
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
    fecha = Column(DateTime, default=datetime.utcnow)
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


class Receta(Base):
    """Escandallo / receta estándar con lista de ingredientes y costo teórico."""
    __tablename__ = "recetas"
    id           = Column(Integer, primary_key=True)
    nombre       = Column(String(150), nullable=False)
    categoria    = Column(String(50), nullable=False, default="bebida")  # bebida | pasteleria | comida
    precio_venta = Column(Float, nullable=True)   # precio de venta para calcular food cost %
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


class Notificacion(Base):
    """Etapa 7: Notificaciones operativas internas para el admin."""
    __tablename__ = "notificaciones"
    id = Column(Integer, primary_key=True)
    tienda_id = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    tipo = Column(String(50), nullable=False)         # "diferencia_caja", "inventario_critico", ...
    mensaje = Column(String(300), nullable=False)
    nivel = Column(String(20), default="info")        # "info", "advertencia", "critico"
    leida = Column(Boolean, default=False)
    fecha = Column(DateTime, default=datetime.utcnow)
    referencia_id = Column(Integer, nullable=True)    # turno_id, producto_id, etc.
    tienda = relationship("Tienda", back_populates="notificaciones")


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
    fecha_recibido = Column(DateTime, nullable=False)
    valor_total = Column(Float, nullable=False)
    tipo_pago = Column(SAEnum(TipoPagoEnum), nullable=False)
    imagen_url = Column(String(300), nullable=True)
    fecha_registro = Column(DateTime, default=datetime.utcnow)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tienda = relationship("Tienda", back_populates="facturas_compra")
    usuario = relationship("Usuario")
    items = relationship("FacturaCompraItem", back_populates="factura", cascade="all, delete-orphan")


class FacturaCompraItem(Base):
    __tablename__ = "facturas_compra_items"
    id = Column(Integer, primary_key=True)
    factura_id = Column(Integer, ForeignKey("facturas_compra.id"), nullable=False)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    cantidad = Column(Float, nullable=False)
    precio_unitario = Column(Float, nullable=True)
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
