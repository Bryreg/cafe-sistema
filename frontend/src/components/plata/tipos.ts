// ─── Los tipos del módulo de la plata, en un solo lugar ──────────────────────
//
// Antes vivían adentro de `pages/Costos.tsx` y `pages/PagosProveedores.tsx`, que
// eran PANTALLAS. Cuando esas pantallas se disolvieron en banners, cada banner
// habría tenido que importar tipos desde la página de la que salió — o peor,
// redeclararlos. Un tipo redeclarado es el lugar donde después se cuela un campo
// que el backend ya no manda y nadie se entera hasta producción.
//
// La forma de acá es la EXACTA que devuelve el backend (`routers/costos.py`,
// `routers/facturas.py`). No hay tipo "de pantalla" distinto del tipo "de la
// API": cada traducción es un lugar donde se recalcula plata con otra regla.

// ── Catálogos ────────────────────────────────────────────────────────────────
export interface Categoria { id: number; clave: string; nombre: string; grupo: string }
export interface Tienda { id: number; nombre: string }

// ── Obligaciones (los costos fijos: arriendo, nómina, servicios) ─────────────
export interface Pago {
  id: number
  obligacion_id: number | null
  factura_id: number | null
  tienda_id: number | null
  monto: number
  fecha_pago: string                // EL DÍA QUE SALIÓ LA PLATA (no el de registro)
  metodo: string
  /** Con valor = el pago es el espejo de un egreso de caja adoptado. */
  movimiento_caja_id?: number | null
  imagen_soporte_url?: string | null
  nota: string | null
  anulado: boolean
  fecha_registro?: string | null
}

export interface Obligacion {
  id: number
  tienda_id: number | null; tienda_nombre: string | null
  categoria_id: number; categoria_clave: string; categoria_nombre: string; categoria_grupo: string
  concepto: string; beneficiario: string | null
  monto: number; pagado: number; saldo: number
  estado: 'pendiente' | 'parcial' | 'pagada' | 'anulada'
  fecha_devengo: string; fecha_vencimiento: string | null
  /** Llave de la serie mensual: la escribe «Repetir» y une agosto→septiembre→… */
  plantilla_id: number | null
  nota: string | null
  pagos: Pago[]
}

export interface Listado {
  obligaciones: Obligacion[]
  totales: { monto: number; pagado: number; saldo: number; n: number }
}

// ── Agenda: la unión de facturas de proveedor y costos fijos ─────────────────
// El backend nunca copia la deuda del proveedor acá: la factura sigue siendo su
// única verdad, y esto es una VISTA de las dos fuentes.
export interface AgendaItem {
  tipo: 'factura' | 'obligacion'
  id: number
  concepto: string; beneficiario: string | null; referencia: string | null
  tienda_id: number | null; tienda_nombre: string | null
  monto: number                    // el SALDO, no el total
  fecha: string                    // YYYY-MM-DD ya proyectada por el backend
  origen_fecha: string             // programada | vencimiento | plazo
  vencida: boolean
  categoria: string | null         // clave estable ('nomina', 'arriendo'…)
  categoria_nombre: string | null  // lo que se pinta: «Nómina», «Arriendo»
}

/**
 * Obligación con saldo y SIN fecha de vencimiento. No se agenda (no hay para
 * cuándo) pero tampoco puede ser invisible: «Vence» es opcional en el alta, así
 * que el caso normal terminaba en una pantalla vacía y en la conclusión de que
 * el módulo no guarda nada.
 */
export interface AgendaSinFecha extends Omit<AgendaItem, 'fecha'> {
  fecha: null
  fecha_devengo: string
}

export interface GrupoCategoria { clave: string; nombre: string; monto: number; n: number }

export interface Agenda {
  items: AgendaItem[]
  sin_fecha: AgendaSinFecha[]
  /**
   * Cuánta plata hay de nómina, de arriendo, de proveedores. Se calcula sobre
   * `items`, o sea sobre TODO lo agendado — lo vencido incluido. Cualquier
   * rótulo que lo llame «lo que viene» estaría escondiendo la mora adentro.
   */
  por_categoria: GrupoCategoria[]
  totales: { monto: number; vencido: number; n: number; sin_fecha: number; n_sin_fecha: number }
}

// ── Egresos de caja sin categorizar ──────────────────────────────────────────
// Adoptarlos NO cambia ningún total: el movimiento de caja queda intacto y el
// gasto pasa de "concepto suelto" a "categoría". Es ordenamiento, no plata nueva.
export interface EgresoSuelto {
  id: number
  concepto: string
  valor: number
  fecha: string | null             // día Colombia en que se TECLEÓ el egreso
  tienda_id: number | null; tienda_nombre: string | null
  barista_nombre: string | null
}
export interface Bandeja {
  egresos: EgresoSuelto[]
  totales: { monto: number; n: number }
}

// ── Flujo proyectado: el día en que se acaba la plata, ANTES de que pase ─────
// saldo(D) = caja de hoy + venta esperada acumulada − lo que hay que pagar.
export interface PuntoFlujo {
  fecha: string
  entradas: number                 // venta esperada = MEDIANA del mismo día de semana
  salidas: number                  // saldo de facturas + obligaciones que vencen ese día
  saldo: number                    // acumulado desde la caja de hoy
}

export interface CajaHoy {
  efectivo_registradora: number
  por_tienda: { tienda_id: number; tienda_nombre: string; efectivo: number; origen: string }[]
  /**
   * La plata que hay HOY en el banco: el ancla que declaró el dueño MÁS los
   * movimientos que tecleó en el libro. Es el mismo número que muestra el libro:
   * el saldo del banco tiene una sola matemática y vive en services/banco.py.
   */
  saldo_banco: number
  /** El ancla sola —lo que copió del extracto— y lo que se movió después. */
  saldo_banco_declarado: number
  saldo_banco_movimientos: number
  /** 'libro' = ancla + movimientos; 'ancla' = sin extracto usable, no encadena. */
  saldo_banco_origen: 'libro' | 'ancla'
  saldo_banco_fecha: string | null
  saldo_banco_desactualizado: boolean
  /** false filtrando por sede: la cuenta es de la empresa, no de la sede. */
  saldo_banco_incluido: boolean
  total: number
}

/**
 * Lo que la proyección NO sabe. Las entradas se derivan solas de cada ticket,
 * pero las salidas existen solo si alguien las tecleó: la PRESENCIA de un punto
 * de quiebre significa algo, su AUSENCIA sola no significa nada.
 */
export interface AdvertenciasFlujo {
  saldo_banco_desactualizado: boolean
  sin_salidas_cargadas: boolean
  sin_historia_ventas: boolean
  excluye_corporativas: boolean
  corporativas_fuera: number
}

export interface Flujo {
  hoy: string
  dias: number
  caja_hoy: CajaHoy
  serie: PuntoFlujo[]
  punto_de_quiebre: string | null  // null = la proyección nunca cruza cero
  dias_hasta_quiebre: number | null
  advertencias: AdvertenciasFlujo
  totales: { entradas: number; salidas: number; saldo_final: number }
}

// ── Facturas de proveedor ────────────────────────────────────────────────────
export interface FacturaItem {
  id: number; producto_nombre: string; cantidad: number
  precio_unitario: number; unidad_medida: string
}

export interface Factura {
  id: number; tienda_id: number; tienda_nombre: string | null
  proveedor: string; numero_factura: string | null
  fecha_recibido: string | null; valor_total: number
  tipo_pago: string; valor_pagado: number; saldo: number
  estado_pago: 'pagado' | 'parcial' | 'pendiente'
  forma_pago_real: string | null
  imagen_url: string | null; imagen_soporte_url: string | null
  barista_nombre: string; items: FacturaItem[]
  /** Vencimiento: lo que hace que la factura entre en la agenda. */
  fecha_vencimiento: string | null
  plazo_dias: number | null
  fecha_programada: string | null
  /** Lo decide el BACKEND (hay saldo y el vencimiento ya pasó): no se recalcula. */
  vencida: boolean
}

export interface GrupoProveedor {
  proveedor?: string; tienda?: string
  facturado: number; pagado: number; pendiente: number; n?: number
}

export interface DashboardFacturas {
  totales: { facturado: number; pagado: number; pendiente: number; n_facturas: number }
  por_proveedor: GrupoProveedor[]
  por_sede: GrupoProveedor[]
  facturas: Factura[]
}

// ── Constantes compartidas ───────────────────────────────────────────────────

/**
 * Sede «Corporativo»: el arriendo y la nómina no pertenecen a ninguna sede, así
 * que el filtro necesita una opción EXPLÍCITA para ellos. No es lo mismo que
 * «todas»: «todas» las incluye junto con las de sede, «Corporativo» las aísla.
 */
export const CORPORATIVO = 'corp'

/** De dónde salió el efectivo que dice cada sede. Decirlo es lo que distingue
 *  un conteo real de un cuadre viejo. */
export const ORIGEN_CAJA: Record<string, string> = {
  turno_abierto: 'turno abierto',
  ultimo_cierre: 'conteo del cierre',   // el dato bueno con la sede cerrada
  ultimo_cuadre: 'último cuadre',       // respaldo: turno cerrado sin conteo
  sin_datos: 'sin datos',
}

export const METODOS_PAGO = ['transferencia', 'efectivo', 'tarjeta', 'cheque', 'otro']

/**
 * Métodos que sacan la plata del BANCO (y no del cajón de la registradora).
 *
 * Gobierna una sola cosa: si se ofrece cargar el movimiento del banco junto con
 * el pago. El efectivo sale de la caja, no de la cuenta — ofrecerlo ahí metería
 * en el libro del banco una salida que el extracto nunca va a tener.
 */
export const METODOS_DE_BANCO = ['transferencia', 'cheque']
