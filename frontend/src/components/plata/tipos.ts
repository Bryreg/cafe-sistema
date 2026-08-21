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
export interface Categoria {
  id: number
  clave: string
  nombre: string
  grupo: string
  /** 'cafe' | 'personal' | 'banco'. Con `?` por la ventana de deploy: ausente
   *  se trata como café (es lo que un servidor viejo devuelve: solo café). */
  ambito?: string
  /** true = se elige pero su plata NO cuenta como costo del mes (retefuente,
   *  reteica, prima, cesantías). El trato viaja dicho, no descubierto después. */
  fuera_del_gasto?: boolean
}
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
  /**
   * `false` = esta fila es del SISTEMA y el formulario no la puede tocar: la
   * declaración del impoconsumo (su monto lo mide el server sobre la venta real
   * y su fecha sale del calendario de la DIAN) y las viejas de 'proveedores'
   * (esa deuda ya entra al P&L y a la agenda por su factura de Compras).
   *
   * LO DECIDE EL BACKEND, con la misma lista que usa para rechazar la edición.
   * No se recalcula acá: una segunda regla del lado de la pantalla se despega
   * de la del server en la primera clave que se agregue, y la pantalla ofrecería
   * un botón que el server contesta con un 400. Sin esto, «Corregir» sobre la
   * fila del impoconsumo la movía a una categoría contada y el piso del mes del
   * devengo subía $12.447.999 con el margen neto cayendo $11.525.925,93.
   *
   * OPCIONAL A PROPÓSITO, y no porque el backend lo omita: `_serializar` lo
   * escribe SIEMPRE. Esto es una PWA con service worker, así que existe una
   * ventana real —la del deploy— en la que la tablet ya tiene el bundle NUEVO
   * contra el backend VIEJO, y ahí el campo llega `undefined`. Marcarlo
   * `boolean` a secas era decirle al que edite esta pantalla que ese caso no
   * existe, y de ahí salía el `o.editable_a_mano ? … : candado`: `undefined` es
   * falsy, así que TODAS las filas —arriendo, servicios, contador— mostraban el
   * candado y el dueño se quedaba sin poder corregir nada. El consumidor tiene
   * que preguntar por `!== false`: el candado solo cuando el server lo AFIRMA.
   */
  editable_a_mano?: boolean
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
  /**
   * false filtrando por sede: la cuenta es de la empresa, no de la sede.
   *
   * Gobierna DOS buckets, no uno. En el backend es literalmente
   * `tienda_id is None`, y la plata en mano del dueño se suma al total con esa
   * misma regla: tampoco pertenece a una sede y tampoco hay dato para repartirla.
   */
  saldo_banco_incluido: boolean
  /**
   * El efectivo que el DUEÑO tiene ENCIMA: lo que recogió de las sedes menos lo
   * que ya pagó en efectivo y lo que consignó él mismo.
   *
   * ── POR QUÉ ESTE CAMPO EXISTE ────────────────────────────────────────────
   * Hasta julio la barista consignaba: la plata salía del cajón y entraba al
   * banco, y con dos lugares el sistema los conocía a los dos. Desde agosto el
   * dueño PASA Y RECOGE: paga proveedores en efectivo (esa plata nunca toca el
   * banco) y consigna el resto. La plata pasó a vivir en TRES lugares y este es
   * el tercero.
   *
   * ── `null` NO ES CERO ────────────────────────────────────────────────────
   * `null` significa que el bucket TODAVÍA NO EXISTE: nunca se registró una
   * recogida, así que no hay desde cuándo contar. Un `$0` ahí AFIRMARÍA que no
   * tiene plata en la mano, que es justo lo que no se sabe. Es la misma familia
   * de error que este módulo viene arrastrando —decidir con un dato que está
   * CERCA del correcto, y siempre hacia el lado tranquilizador—, así que acá el
   * tipo la deja ver: `number | null` obliga a escribir la rama.
   */
  efectivo_en_mano: number | null
  /**
   * El día de la PRIMERA recogida registrada: de ahí para adelante se cuenta.
   * `null` cuando el bucket no existe. No es una fecha de corte que alguien
   * eligió: es el primer día del que hay algo que sumar.
   */
  efectivo_en_mano_desde: string | null
  /**
   * Si la plata de la mano ENTRÓ al `total`. En el backend es
   * `tienda_id is None and monto is not None`: no pertenece a ninguna sede (igual
   * que la cuenta del banco) y no se puede sumar un bucket que no existe.
   *
   * Viene del backend en vez de deducirse acá con
   * `saldo_banco_incluido && efectivo_en_mano !== null`. Da lo mismo hoy y esa es
   * exactamente la trampa: el día que allá se agregue una condición, la pantalla
   * seguiría rotulando el total con la regla vieja y diría que sumó una plata que
   * no sumó. Una sola matemática, del lado que hace la cuenta.
   */
  efectivo_en_mano_incluido: boolean
  total: number
}

/**
 * Un gasto grande que el sistema SABE MEDIR SOLO y que esta proyección no está
 * viendo, porque nadie lo agendó todavía.
 *
 * `monto` es `number | null` a propósito y acá no va ningún `?? 0`: un cero se
 * leería como «no hay nada que reservar», que es la conclusión OPUESTA a la
 * verdadera. Cuando viene en null, `sin_monto_porque` dice por qué en castellano.
 */
export interface ConceptoSinCargar {
  /** 'impoconsumo' | 'nomina' — la clave de la categoría de costo. */
  clave: string
  /** «Impoconsumo mayo-junio 2026», en el idioma del dueño. */
  nombre: string
  monto: number | null
  sin_monto_porque: string | null
  /** El día en que saldría la plata si se agendara. */
  vence: string
  vencido: boolean
}

/**
 * Lo que la proyección NO sabe. Las entradas se derivan solas de cada ticket,
 * pero las salidas existen solo si alguien las tecleó: la PRESENCIA de un punto
 * de quiebre significa algo, su AUSENCIA sola no significa nada.
 */
export interface AdvertenciasFlujo {
  saldo_banco_desactualizado: boolean
  /**
   * NI UNA SOLA salida cargada en el horizonte. Sigue siendo un caso que vale
   * nombrar, pero YA NO ES la señal de cobertura: se apaga con una obligación
   * cualquiera, y con el arriendo adentro el verde volvía a viajar aunque
   * faltaran los millones de la DIAN. Para eso está `conceptos_sin_cargar`.
   */
  sin_salidas_cargadas: boolean
  sin_historia_ventas: boolean
  excluye_corporativas: boolean
  corporativas_fuera: number
  /**
   * Lo que falta, CON NOMBRE Y PLATA. Lista, no booleano: es lo que se puede
   * convertir en una acción. Vacía = los conceptos medibles están todos adentro.
   *
   * OPCIONAL, Y NO ES UN DESCUIDO. El backend la manda siempre, pero «siempre»
   * quiere decir «el backend de este commit». Esto es una PWA contra un backend
   * que se despliega APARTE: hay una ventana —minutos, y en la tablet más, por
   * el service worker— en la que el bundle es nuevo y el server todavía es el
   * viejo. Ahí el campo no viene, y cuando esto era obligatorio el
   * `for (const c of ...)` de BloqueFinDeMes reventaba con la lista `undefined`
   * y se caía el árbol de React entero: PANTALLA BLANCA, no un bloque roto.
   * Pasó en producción el 2026-08-20 con el deploy de las fases 3 y 4.
   *
   * El `?` es el candado: obliga a que quien la lea distinga AUSENTE de VACÍA.
   * No son lo mismo y la diferencia es la de siempre — vacía es «pregunté y no
   * falta nada», ausente es «no pude preguntar», y publicar un colchón sobre la
   * segunda es afirmar justo lo que no se midió.
   */
  conceptos_sin_cargar?: ConceptoSinCargar[]
  /** Atajo derivado de la lista, para el que solo necesita saber si puede
   *  publicar un número. Nunca se prende por su cuenta.
   *  Opcional por lo mismo que la lista de arriba. */
  salidas_incompletas?: boolean
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

  // ── El horizonte tiene FECHA DE CIERRE, y el colchón sale de esta serie ────
  // Sin `dias`, el backend proyecta HASTA FIN DE MES y no 30 días que se corren.
  // No es cosmético: el colchón de acá y el piso de venta (`/costos/piso`) tienen
  // que mirar la MISMA ventana, o son dos respuestas a dos preguntas distintas
  // puestas una al lado de la otra. Estos dos campos son los que dejan que la
  // pantalla diga cuál está mirando en vez de suponerlo.
  dias_hasta_fin_de_mes: number
  horizonte_es_fin_de_mes: boolean

  /**
   * El punto MÁS BAJO de la serie, no el saldo final.
   *
   * Un mes que termina bien pero pasa por un lunes en rojo no tiene colchón: el
   * proveedor rebota igual. Por eso el colchón se mide contra el mínimo.
   */
  saldo_minimo: number
  /** La plata con la que el negocio no puede quedarse sin. Default 0. */
  reserva_minima_caja: number
  /** true = el 0 es el default, no una decisión que alguien tomó. */
  reserva_es_default: boolean
  /**
   * `saldo_minimo − reserva`. NEGATIVO POSIBLE, y no se recorta en cero: un
   * colchón negativo es exactamente el dato que hay que ver antes de gastar.
   */
  colchon: number
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
  /**
   * Clave con la que el backend AGRUPA (nombre normalizado: sin tildes, sin
   * dobles espacios, en mayúsculas). `proveedor` es la grafía de la factura más
   * reciente, que es la que el dueño reconoce del papel. Los dos viajan porque
   * son cosas distintas: agrupar por el crudo partía a «Lácteos Andina» en tres
   * filas chicas y ninguna mostraba su tamaño real.
   */
  clave?: string
  /**
   * Cuánto de TODO lo comprado en el rango se lleva este proveedor, 0..100.
   *
   * `null` = no hay nada facturado, o sea no hay base para el porcentaje. NO es
   * 0: un 0% diría que ese proveedor no pesa. Lo divide el backend —es
   * `facturado / totales.facturado`, los dos del mismo payload— para que ninguna
   * pantalla lo invente contra otra base, que es justo lo que pasaba cuando la
   * barra se medía contra el proveedor más grande.
   */
  pct_del_total?: number | null
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
