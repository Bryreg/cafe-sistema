// Changelog visible para el equipo. Se actualiza EN CADA DEPLOY con lo que cambió:
// así las baristas y administradores se enteran sin depender del dueño.
// rol: quién ve la novedad. fecha: YYYY-MM-DD (orden descendente).

export type RolNovedad = 'todos' | 'barista' | 'admin'
export type TipoNovedad = 'nuevo' | 'mejora' | 'cambio'

export interface Novedad {
  fecha: string
  titulo: string
  detalle: string
  rol: RolNovedad
  tipo: TipoNovedad
}

export const NOVEDADES: Novedad[] = [
  // ── 6 de julio ──────────────────────────────────────────────────────────
  {
    fecha: '2026-07-06', rol: 'barista', tipo: 'nuevo',
    titulo: 'Contar existencia desde Pedido',
    detalle: 'En "Pedido / Existencia" hay dos modos: Pedir (como siempre) o Contar existencia. Usá "Contar existencia" para registrar cuánto hay de lo que no entra al conteo diario: vasos, tapas, helado. Queda para que el admin lo revise.',
  },
  {
    fecha: '2026-07-06', rol: 'admin', tipo: 'nuevo',
    titulo: 'Existencia ad-hoc de las baristas',
    detalle: 'Las baristas pueden contar la existencia de productos fuera del conteo diario (vasos, tapas, helado) cuando quieran. Aparece en el monitor de conteos como tipo "existencia" — comparás y aplicás si querés. No modifica el stock por sí solo.',
  },
  // ── 5 de julio ──────────────────────────────────────────────────────────
  {
    fecha: '2026-07-05', rol: 'barista', tipo: 'cambio',
    titulo: 'El "ajuste" de inventario ahora es solo del administrador',
    detalle: 'Ustedes registran lo que PASA: entradas, salidas, mermas y preparaciones. Si un número no cuadra, va en el conteo o se le avisa al admin — los números los corrige solo el administrador.',
  },
  {
    fecha: '2026-07-05', rol: 'barista', tipo: 'nuevo',
    titulo: 'Aviso cuando falta registrar la mezcla',
    detalle: 'Si se venden granizados sin registrar la preparación, aparece un aviso en la pantalla de turno con botón directo a Preparaciones.',
  },
  {
    fecha: '2026-07-05', rol: 'admin', tipo: 'nuevo',
    titulo: 'Control de ajustes y preparaciones',
    detalle: 'Notificación (campana y push) cuando un preparado queda en negativo. Y los movimientos de inventario se pueden auditar por tipo y fecha — quién movió qué, cuándo y por qué.',
  },
  {
    fecha: '2026-07-05', rol: 'barista', tipo: 'cambio',
    titulo: 'Conteos: referencia del conteo anterior y botón "Coincide"',
    detalle: 'En la apertura ves el cierre de anoche; en el cierre, la apertura de hoy. Si un producto no se movió, tocá "Coincide"; lo demás se pesa o se cuenta. Hay que registrar todos los productos — el botón "Todo coincide" ya no existe.',
  },
  {
    fecha: '2026-07-05', rol: 'admin', tipo: 'mejora',
    titulo: 'Conteos a ciegas: comparación justa',
    detalle: 'La pantalla del conteo ya no muestra el stock del sistema — la barista cuenta contra el conteo anterior, no contra el sistema. Copiar la referencia no puede esconder faltantes: si el producto se movió, la diferencia aparece sola.',
  },
  {
    fecha: '2026-07-05', rol: 'todos', tipo: 'mejora',
    titulo: 'El turno se cierra solo con la última salida',
    detalle: 'Cuando la última barista registra su salida y el conteo de cierre ya está hecho, el turno se cierra automáticamente con el último cuadre. Ya no puede quedar un turno abierto por cerrar la app antes de tiempo.',
  },
  // ── 4 de julio ──────────────────────────────────────────────────────────
  {
    fecha: '2026-07-04', rol: 'barista', tipo: 'nuevo',
    titulo: 'Consignaciones: elegí el día que estás consignando',
    detalle: 'La pantalla muestra el total pendiente y los días con saldo. Tocá el día que estás consignando y el valor se llena solo con lo pendiente de ese día.',
  },
  {
    fecha: '2026-07-04', rol: 'barista', tipo: 'nuevo',
    titulo: 'Conteos: guardá y seguí después',
    detalle: 'Botón "Guardar cambios" en el conteo: si salís a revisar otra cosa, al volver seguís donde ibas. Y las casillas ahora calculan: escribí +2500+1000 y dale Enter.',
  },
  {
    fecha: '2026-07-04', rol: 'todos', tipo: 'nuevo',
    titulo: 'Las ventas descuentan el inventario solas',
    detalle: 'Cada bebida y producto del POS tiene su receta cargada: al vender, el sistema descuenta café, leche, salsas y demás ingredientes automáticamente. No hay que registrar nada extra.',
  },
  {
    fecha: '2026-07-04', rol: 'barista', tipo: 'nuevo',
    titulo: 'Preparaciones: registrá cada tanda de mezcla',
    detalle: 'Cuando prepares mezcla de granizado: Menú → Preparaciones → Registrar. El sistema descuenta la materia prima y suma la mezcla preparada. En los conteos, la jarra de mezcla se pesa con la gramera.',
  },
  {
    fecha: '2026-07-04', rol: 'todos', tipo: 'cambio',
    titulo: 'Granizados de 12 oz salieron del POS',
    detalle: 'Ya no se venden. Todos los granizados son de 16 oz.',
  },
  {
    fecha: '2026-07-04', rol: 'admin', tipo: 'nuevo',
    titulo: 'Los conteos con "Todo coincide" quedan marcados',
    detalle: 'Cuando un conteo se registra con el atajo "Todo coincide con sistema", aparece con la etiqueta ⚡ en Conciliación y en el monitor de conteos — para distinguir un conteo físico real de una confirmación sin contar.',
  },
  {
    fecha: '2026-07-04', rol: 'admin', tipo: 'nuevo',
    titulo: 'Conciliación: la película del día completo',
    detalle: 'El detalle de Conciliación ahora muestra por producto: lo que el sistema calcula, lo que la barista contó al abrir, lo que entró durante el día y lo que contó al cerrar. Con selector de día.',
  },
  {
    fecha: '2026-07-04', rol: 'admin', tipo: 'nuevo',
    titulo: 'Corregir consignaciones',
    detalle: 'Botón de lápiz en cada consignación del panel: corrige el valor si la barista lo registró mal. El saldo del día se recalcula solo.',
  },
  {
    fecha: '2026-07-04', rol: 'admin', tipo: 'nuevo',
    titulo: 'Editar facturas de proveedores',
    detalle: 'Botón "Editar" en Pagos proveedores: corrige proveedor, número, fecha, tipo de pago, montos y productos. Si cambia una cantidad, el inventario se ajusta solo por la diferencia.',
  },
  // ── 3 de julio ──────────────────────────────────────────────────────────
  {
    fecha: '2026-07-03', rol: 'barista', tipo: 'mejora',
    titulo: 'Mermas rediseñadas',
    detalle: 'Menú → Merma: elegí consumo, traslado o daño. En consumo se registra quién consumió. Las bebidas preparadas descuentan sus ingredientes por receta.',
  },
  {
    fecha: '2026-07-03', rol: 'barista', tipo: 'mejora',
    titulo: 'Tu inicio ahora es un dashboard',
    detalle: 'La pantalla de turno muestra lo que hicieron hoy: pedidos recibidos con su valor, mermas con quién, y solicitudes de sencilla.',
  },
  {
    fecha: '2026-07-03', rol: 'barista', tipo: 'nuevo',
    titulo: 'Avisos del administrador en tu inicio',
    detalle: 'Los comunicados aparecen como banner en la pantalla de turno hasta que toques "Entendido".',
  },
  {
    fecha: '2026-07-03', rol: 'barista', tipo: 'mejora',
    titulo: 'Pedido con cantidad y unidad editables',
    detalle: 'En Solicitar pedido podés cambiar la cantidad sugerida y elegir la unidad (gr, unidad, lt, paquete...).',
  },
  {
    fecha: '2026-07-03', rol: 'admin', tipo: 'mejora',
    titulo: 'Cuadres como línea de tiempo',
    detalle: 'Cada día es una tarjeta con toda la información a la vista: base, ventas, cuadres de cada barista con diferencia, y cierre. Los turnos que quedaron abiertos se cierran desde ahí.',
  },
  {
    fecha: '2026-07-03', rol: 'admin', tipo: 'mejora',
    titulo: 'Pagos a proveedores más completos',
    detalle: 'Cada factura muestra los productos ingresados y la forma de pago real. Los pagos se registran con foto del soporte.',
  },
  {
    fecha: '2026-07-03', rol: 'admin', tipo: 'mejora',
    titulo: 'Lotes agrupados por producto',
    detalle: 'La vista de lotes agrupa por producto con sus vencimientos y consumo, más un historial rápido de entradas al lado.',
  },
  {
    fecha: '2026-07-03', rol: 'admin', tipo: 'mejora',
    titulo: 'Monitor de conteos más claro',
    detalle: 'Vista legible por conteo con toggle "Bajo gramaje — para pedidos" para armar el pedido de la semana.',
  },
  {
    fecha: '2026-07-03', rol: 'admin', tipo: 'cambio',
    titulo: 'Ticket configurable por sede',
    detalle: 'Config ticket permite elegir la sede y editar el ticket de cada una por separado.',
  },
  // ── 2 de julio ──────────────────────────────────────────────────────────
  {
    fecha: '2026-07-02', rol: 'todos', tipo: 'nuevo',
    titulo: 'Doble conteo de inventario',
    detalle: 'El sistema lleva su propio stock por movimientos (ventas, facturas, mermas). Los conteos físicos COMPARAN contra ese stock: las diferencias se investigan, ya no se pisan.',
  },
  {
    fecha: '2026-07-02', rol: 'barista', tipo: 'mejora',
    titulo: 'Conteos en gramos y en orden de planilla',
    detalle: 'Los productos a granel se pesan con la gramera y se registran en gramos. El orden del conteo es el mismo de la planilla física.',
  },
  {
    fecha: '2026-07-02', rol: 'barista', tipo: 'nuevo',
    titulo: 'Venta de ayer separada en el cuadre',
    detalle: 'Si la venta del día anterior quedó apartada, marcá la casilla al contar la base para que el cuadre no la mezcle.',
  },
  {
    fecha: '2026-07-02', rol: 'barista', tipo: 'nuevo',
    titulo: 'Formato de desechables a pedido',
    detalle: 'Cuando el administrador lo solicite, aparece el formato de desechables para llenar, agrupado por proveedor.',
  },
]

const VISTO_KEY = 'novedades_ultima_vista'

export function novedadesParaRol(rol: 'barista' | 'admin'): Novedad[] {
  return NOVEDADES.filter(n => n.rol === 'todos' || n.rol === rol)
}

export function contarNoVistas(rol: 'barista' | 'admin'): number {
  const visto = localStorage.getItem(VISTO_KEY) ?? ''
  return novedadesParaRol(rol).filter(n => n.fecha > visto).length
}

export function marcarVistas(): void {
  const max = NOVEDADES.reduce((m, n) => (n.fecha > m ? n.fecha : m), '')
  localStorage.setItem(VISTO_KEY, max)
}
