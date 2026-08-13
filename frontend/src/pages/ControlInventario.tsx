import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  Layers, Search, RotateCcw, Download, Check, Package, AlertTriangle,
} from 'lucide-react'
import SidePanel from '../components/SidePanel'
import NivelEnvase from '../components/NivelEnvase'
import { dark } from '../constants/darkTheme'

// ─── Types ────────────────────────────────────────────────────────────────────

interface ProductoInventario {
  producto_id: number
  nombre: string
  categoria: string
  unidad: string
  proveedor: string | null
  lead_time_dias: number
  stock_actual: number
  stock_minimo: number
  stock_ideal: number
  stock_critico: number
  consumo_diario: number
  dias_restantes: number | null
  estado: 'agotado' | 'urgente' | 'pronto' | 'bajo' | 'ok'
  cantidad_sugerida: number
  // Qué hacer con `cantidad_sugerida`. 'preparar' es el producto que se arma con
  // receta en la barra (la mezcla de granizado): nadie lo vende hecho, así que su
  // número bajo la columna «Pedir» sería una orden de compra imposible.
  // `tandas_sugeridas` solo viaja cuando el rendimiento por tanda está cargado.
  accion?: 'comprar' | 'preparar'
  tandas_sugeridas?: number | null
  rendimiento_tanda?: number | null
  barista_alerto: boolean
  fraccionable?: boolean
  envase?: 'bolsa' | 'botella' | null
}

interface Sugerencia {
  grupos_fijos: { proveedor: string; productos: ProductoInventario[]; estado_resumen: string }[]
  insumos_generales: ProductoInventario[]
  total_urgentes: number
  total_pronto: number
  total_bajo: number
  total_ok: number
}

interface FilaRotacion {
  producto_id: number
  producto: string
  categoria: string
  unidad: string
  stock_actual: number
  stock_minimo: number
  entradas: number
  salidas: number
  rotacion: number | null
  estado: string
  alerta_min: boolean
}

interface ResumenRotacion {
  activos: number
  estancados: number
  sin_movimiento: number
  bajo_minimo: number
}

// Ficha del producto: una sola llamada que junta lo que hoy obliga a recorrer
// Control de inventario, Lotes, Conteos y Rotación.
interface FichaLote {
  id: number
  numero_lote: string | null
  proveedor: string | null
  cantidad_inicial: number
  cantidad_restante: number
  consumido_pct: number
  fecha_entrada: string | null
  fecha_vencimiento: string | null
  estado: 'activo' | 'por_vencer' | 'vencido' | 'agotado'
}

interface FichaMovimiento {
  id: number
  fecha: string | null
  tipo: string
  cantidad: number
  motivo: string | null
  barista: string | null
}

interface FichaConteo {
  conteo_id: number
  turno_id: number
  tipo: string
  fecha: string | null
  cantidad_sistema: number
  cantidad_real: number
  diferencia: number
  barista_nombre: string | null
  es_atajo: boolean
}

interface FichaItemReceta {
  nombre: string
  unidad_medida: string
  cantidad: number
}

interface Ficha {
  stock: {
    stock_actual: number
    stock_critico: number
    stock_minimo: number
    stock_ideal: number
  }
  lotes: FichaLote[]
  movimientos: FichaMovimiento[]
  conteos: FichaConteo[]
  receta: { insumos: FichaItemReceta[]; usado_en: FichaItemReceta[] }
}

// Fila cruda de /inventario/lotes-trazabilidad. Solo se usan tres campos: el
// cruce por producto se hace EN CLIENTE, igual que lo hace la pantalla /lotes.
interface LoteTraza {
  producto_id: number
  fecha_vencimiento: string | null
  estado: 'activo' | 'por_vencer' | 'vencido' | 'agotado'
}

type VencInfo = { fecha: string; estado: 'por_vencer' | 'vencido' }
type MapaVenc = Record<number, VencInfo>

// GET /inventario/diagnostico — la respuesta del sistema a las dos preguntas del
// dueño: por qué el motor no avisa (umbrales sin cargar) y por qué hay
// negativos. Acá se usan tres pedazos: la fracción de productos con mínimo (una
// línea arriba de la lista), la causa de cada negativo y las recetas con
// sospecha de unidad (los dos últimos, DENTRO del panel del producto).
interface DiagNegativo {
  producto_id: number
  producto: string
  sede: string
  stock: number
  unidad: string
  ultima_entrada: string | null
  lo_consumen_n_recetas: number
  causa: string
  titulo: string
  sospecha: string
  que_hacer: string
  tambien_aplica: string[]
  por_que_gana: string | null
  dias_sin_entrada: number | null
}

interface DiagRecetaSospechosa {
  producto_vendido: string
  producto_id: number
  insumo: string
  insumo_id: number
  dice_la_receta: number
  unidad_del_insumo: string
  sospecha: string
}

interface Diagnostico {
  umbrales: {
    total: {
      filas: number
      con_minimo: number
      filas_gestionadas: number
      con_minimo_gestionadas: number
    }
  }
  // El motor de pedidos avisa por DÍAS RESTANTES (stock/consumo vs lead time) y
  // solo cae al mínimo cuando no tiene consumo medido. Sin este dato, el aviso
  // de umbrales afirmaba que un producto sin mínimo «no avisa nada», que es
  // falso para todo el que sí rota. El backend ya lo calculaba y la pantalla no
  // lo leía.
  consumo: {
    productos_con_salidas_14d: number
    motor_sin_datos: boolean
  }
  negativos: DiagNegativo[]
  recetas_sospechosas: DiagRecetaSospechosa[]
}

// GET /inventario/umbrales/propuestas — lo que el sistema PROPONE como mínimo
// para los productos que no tienen uno, según lo que se gastó de verdad.
// Read-only: aceptar es otro pedido (PATCH /inventario/umbrales/aplicar) y viaja
// con la lista explícita de lo que el dueño marcó.
interface PropuestaMinimo {
  producto_id: number
  nombre: string
  categoria: string
  unidad: string
  stock_actual: number
  lead_time_dias: number
  accion: 'comprar' | 'preparar'
  consumo_diario: number
  // Días DISTINTOS con salida dentro de la ventana. Es lo que sostiene el
  // número: 6 días de datos y 14 de ventana no es lo mismo que 14 de 14.
  dias_de_datos: number
  ventana_dias: number
  minimo_propuesto: number
  cubre_dias: number
  motor_repone_hasta: number
  estado_hoy: string
  quedaria_en: string
  cambia_a_alerta: boolean
  // Por qué NO confiar en este número (receta con la unidad sospechosa). Cuando
  // viene, la fila queda FUERA del aceptar-todo.
  advertencia: string | null
  en_aceptar_todo: boolean
}

interface SinDatoMinimo {
  producto_id: number
  nombre: string
  unidad: string
  stock_actual: number
  razon: string
}

interface PropuestasUmbrales {
  ventana_dias: number
  propuestas: PropuestaMinimo[]
  sin_dato: SinDatoMinimo[]
  impacto: {
    propuestas: number
    sin_dato: number
    nuevos_en_alerta: number
    ya_en_alerta: number
    con_advertencia: number
    aceptar_todo: { propuestas: number; nuevos_en_alerta: number }
  }
}

// ─── Config ───────────────────────────────────────────────────────────────────

// Paleta MEDIUM CAFÉ. Los cuatro primeros son los del manual de marca; el resto
// se deriva de ellos (papel, líneas y tintas) o es la escalera de urgencia, que
// es UNA sola familia cálida —de brasa a hoja— para que el ojo la lea como un
// gradiente y no como cinco alarmas distintas.
//
// `negativo` es deliberadamente FRÍO y no un rojo más: un stock negativo no es
// «más urgente que urgente», es otro problema (falta un registro, no falta
// mercancía). Si compartiera la escalera roja, cero y negativo volverían a
// parecer lo mismo.
const MC = {
  negro:     '#0D0C0B',
  crema:     '#F7F2E7',
  // El fondo de la pantalla. Fue crema (el de las piezas gráficas de la marca) y
  // el dueño lo pidió blanco, como el resto del admin: la marca queda en los
  // acentos —terracota, oliva, las líneas cálidas— y no en el papel de fondo.
  // `crema` se conserva porque las pastillas activas lo usan como texto sobre negro.
  hoja:      '#FFFFFF',
  terracota: '#B5622A',
  oliva:     '#4B5A3E',

  // Fue '#FBF8F0' (papel calido): sobre la hoja blanca, cada fila se leia como
  // una tira beige detras del texto — el dueno lo marco dos veces. Blanco: la
  // marca vive en lineas y acentos, no en ningun fondo.
  papel:     '#FFFFFF',
  fondo:     '#F2ECDD',
  tinta70:   '#46413B',
  tinta45:   '#7A736A',
  tinta28:   '#A79E92',
  linea:     '#E3DBC8',
  lineaFte:  '#D2C7AE',

  vence:     '#8A5A12',   // otro eje: tiempo, no stock
  negativo:  '#3E4A55',   // otro eje: registro, no stock
} as const

// `mc` es el MISMO tono que pinta la regla de la fila y el punto de la leyenda:
// se agrega acá, y no en un objeto aparte, para que no puedan divergir. Los
// campos viejos (label/color/bg/bar/dot) siguen intactos: los usan la leyenda
// histórica y PedidosAdmin.
const ESTADO_CFG = {
  agotado: { label: 'AGOTADO', color: 'text-red-700',    bg: 'bg-red-100',    bar: 'bg-red-500',    dot: 'bg-red-500',    mc: '#8C2A16' },
  urgente: { label: 'URGENTE', color: 'text-red-600',    bg: 'bg-red-50',     bar: 'bg-red-400',    dot: 'bg-red-400',    mc: '#B5622A' },
  pronto:  { label: 'PEDIR',   color: 'text-amber-700',  bg: 'bg-amber-50',   bar: 'bg-amber-400',  dot: 'bg-amber-400',  mc: '#C98A2E' },
  bajo:    { label: 'BAJO',    color: 'text-yellow-700', bg: 'bg-yellow-50',  bar: 'bg-yellow-400', dot: 'bg-yellow-400', mc: '#A99433' },
  ok:      { label: 'OK',      color: 'text-green-700',  bg: 'bg-green-50',   bar: 'bg-green-500',  dot: 'bg-green-500',  mc: '#4B5A3E' },
}

const ROT_CFG: Record<string, { label: string; bg: string; text: string }> = {
  activo:         { label: 'Activo',        bg: 'oklch(93% 0.015 155)', text: 'oklch(30% 0.10 155)' },
  estancado:      { label: 'Estancado',     bg: 'oklch(95% 0.015 60)',  text: 'oklch(38% 0.12 55)'  },
  agotado:        { label: 'Agotado',       bg: 'oklch(96% 0.015 20)',  text: 'oklch(38% 0.16 25)'  },
  sin_movimiento: { label: 'Sin movimiento',bg: 'oklch(95% 0.005 60)',  text: 'oklch(55% 0.01 60)'  },
}

const ESTADO_ORDER: Record<string, number> = { agotado: 0, urgente: 1, pronto: 2, bajo: 3, ok: 4 }

// El filtro de la lista. `todos` es el DEFAULT: el inventario es el libro de LO
// QUE HAY, así que la pantalla abre con las 56 filas y su cantidad a la vista.
// Los otros ocho son recortes que el dueño pide tocando una pastilla — y todos
// siguen siendo deep links `?estado=` válidos.
const FILTROS = [
  { id: 'todos',    label: 'Ver todo' },
  { id: 'atencion', label: 'Necesita atención' },
  // Stock NEGATIVO. No es un estado del backend —`pedidos._estado` devuelve
  // «agotado» tanto para 0 como para -13— y por eso no puede salir de `estado`:
  // se lee del stock de la MISMA lista que se filtra. Deliberadamente NO se lee
  // de `diag.negativos`, que es otro payload: esa consulta no filtra el
  // inventario gestionado (diagnostico_stock._negativos no aplica _gestionado())
  // y corta en 200 filas, así que contar de ahí daría un número que la lista no
  // puede mostrar. Y si el diagnóstico no cargó, este contador sigue siendo
  // exacto.
  { id: 'negativo', label: 'Solo en negativo' },
  { id: 'urgente',  label: 'Solo urgentes' },
  { id: 'pronto',   label: 'Solo pedir hoy' },
  { id: 'bajo',     label: 'Solo stock bajo' },
  { id: 'vence',    label: 'Solo se vence' },
  // Destino del aviso de umbrales: sin este filtro, el aviso sería una queja.
  { id: 'sinmin',   label: 'Sin mínimo cargado' },
  { id: 'ok',       label: 'Solo al día (OK)' },
] as const
type FiltroId = typeof FILTROS[number]['id']
const ES_FILTRO = (v: string): v is FiltroId => FILTROS.some(f => f.id === v)

function pasaFiltro(p: ProductoInventario, f: FiltroId, venc: MapaVenc) {
  switch (f) {
    case 'todos':   return true
    case 'ok':      return p.estado === 'ok'
    case 'urgente': return p.estado === 'agotado' || p.estado === 'urgente'
    case 'pronto':  return p.estado === 'pronto'
    case 'bajo':    return p.estado === 'bajo'
    case 'vence':   return !!venc[p.producto_id]
    // Un mínimo en 0 es el default del esquema, no una decisión: ese producto no
    // dispara ninguna alerta hasta llegar a cero.
    case 'sinmin':  return !(p.stock_minimo > 0)
    // 0 y negativo NO son el mismo problema: 0 es «se acabó, hay que comprar»;
    // negativo es «falta registrar algo que ya pasó». El backend los mete a los
    // dos en `agotado`, así que la separación se hace acá.
    case 'negativo': return p.stock_actual < 0
    // «Necesita atención» tiene que incluir los CUATRO buckets que cuentan las
    // tarjetas de arriba, y «se vence» es uno de ellos. Sin esto, un insumo con
    // stock sano y un lote por vencer sumaba en la tarjeta naranja y no aparecía
    // en la lista con la que abre la pantalla: el número no mentía, el rótulo sí,
    // por omisión.
    default:        return p.estado !== 'ok' || !!venc[p.producto_id]   // atencion
  }
}

// ─── Las pastillas: filtros con su cuenta ─────────────────────────────────────
//
// NO son buckets: se pisan entre sí a propósito (un negativo también es
// «se acabó»; un lote por vencer le puede pasar a cualquiera). Lo que sí tiene
// que cerrar es cada pastilla POR SEPARADO: su número se calcula con el MISMO
// `pasaFiltro` que recorta la lista al tocarla, sobre la misma base. Tocar
// «Se acabó o urgente · 13» tiene que dar 13 filas, siempre.
//
// El color es el de la regla izquierda de las filas que van a quedar, salvo los
// dos ejes que no son stock: `negativo` (falta un registro) y `vence` (tiempo).
const PASTILLAS: { id: FiltroId; corto: string; c: string; ayuda: string }[] = [
  { id: 'todos',    corto: 'Todo',               c: MC.negro,
    ayuda: 'Todos los productos de la sede, con su cantidad.' },
  { id: 'atencion', corto: 'Necesita atención',  c: MC.terracota,
    ayuda: 'Todo lo que no está al día, más lo que tiene un lote por vencer.' },
  { id: 'negativo', corto: 'En negativo',        c: MC.negativo,
    ayuda: 'El sistema descontó más de lo que se registró que entró: falta cargar una entrada.' },
  { id: 'urgente',  corto: 'Se acabó o urgente', c: ESTADO_CFG.agotado.mc,
    ayuda: 'Se acabó, o no llega a la próxima entrega.' },
  { id: 'pronto',   corto: 'Pedir hoy',          c: ESTADO_CFG.pronto.mc,
    ayuda: 'Todavía hay, pero no alcanza para el próximo ciclo de pedido.' },
  { id: 'bajo',     corto: 'Bajo',               c: ESTADO_CFG.bajo.mc,
    ayuda: 'Quedó por debajo del mínimo cargado.' },
  { id: 'vence',    corto: 'Se vence',           c: MC.vence,
    ayuda: 'Tiene un lote vencido o por vencer. No se pide: se vende o se saca.' },
  // «ok» filtra por estado de STOCK a secas: un producto con stock sano y lote
  // por vencer entra acá Y en «Se vence» (las pastillas se pisan a propósito).
  // Por eso la ayuda no puede decir «sin novedades» — el Croissant con lote del
  // 15-08 es la primera fila de este filtro y tiene una novedad gritando.
  { id: 'ok',       corto: 'Al día',             c: ESTADO_CFG.ok.mc,
    ayuda: 'Con stock sano. Los lotes con fecha se ven en su chip y en «Se vence».' },
  { id: 'sinmin',   corto: 'Sin mínimo',         c: MC.tinta45,
    ayuda: 'No tiene mínimo cargado: el sistema no puede avisar por umbral.' },
]

// Lo que dice la columna «Alcanza»: cuánto tiempo dura el stock que hay.
//
// `dias_restantes` es stock/consumo_diario (pedidos.py:108-110) y trae dos casos
// que el número crudo no sabía contar, y que la versión anterior de esta función
// imprimía igual:
//   · con el stock en NEGATIVO los días son negativos → salía «-2h», que no
//     significa nada. Con cero o menos no quedan días: se acabó, y se dice así.
//   · viene NULL cuando el motor no midió consumo en 14 días. Ahí va un guion:
//     cualquier palabra afirmaría algo que el payload no dice.
// El resto se redondea a días enteros — la décima de «9.3d» no cambia ninguna
// decisión y el sufijo «d» había que traducirlo.
function alcanzaLabel(p: ProductoInventario) {
  if (p.stock_actual <= 0) return 'se acabó'
  if (p.dias_restantes === null) return '—'
  if (p.dias_restantes < 1) return 'hoy'
  const d = Math.round(p.dias_restantes)
  return `${d} ${d === 1 ? 'día' : 'días'}`
}

// 24062 → «24.062»; -0,2 → «-0,2». Un número de cinco cifras sin separador, en
// una lista que se escanea con el pulgar, se lee mal. `n === 0` normaliza el -0
// que llega de redondear un negativo minúsculo en el backend.
const NUM_FMT = new Intl.NumberFormat('es-CO', { maximumFractionDigits: 2 })
function num(n: number) { return NUM_FMT.format(n === 0 ? 0 : n) }

// 'YYYY-MM-DD…' -> 'dd-mm'. Se parte el string a mano: new Date('2026-08-01') es
// UTC y en Colombia (UTC-5) mostraría el día anterior.
function ddmm(iso: string) {
  const [, m, d] = iso.slice(0, 10).split('-')
  return m && d ? `${d}-${m}` : '—'
}

// Hora LOCAL: toISOString es UTC y despues de las 19:00 Colombia devuelve manana.
function isoLocal(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function isoHoy() { return isoLocal(new Date()) }
function isoHace(dias: number) {
  const d = new Date(); d.setDate(d.getDate() - dias); return isoLocal(d)
}

// Nombres cargados en MAYÚSCULA (LECHE CONDENSADA, MILO). No es jerarquía: es
// cómo los tipeó quien los dio de alta. El DATO no se toca —renombrar productos
// en producción es otra conversación— y solo se corrige la óptica: menos cuerpo
// y algo de tracking para que no le griten por encima a los demás.
// Se exige una letra con caso (`toLowerCase` distinto) para no marcar «MILO 3»
// ni códigos sin letras.
function esCaps(n: string) {
  return n.length > 3 && n === n.toUpperCase() && n !== n.toLowerCase()
}

// El «tachar» de cada fila (checklist de la jornada en localStorage) se fue con
// la cola de decisiones: era el «ya lo pedí» de una cola que ahora vive en
// /pedidos-admin. En el libro de lo que hay, tachar una fila la bajaba al 45% de
// opacidad — o sea escondía justo la cantidad que esta pantalla existe para
// mostrar. Si el dueño lo quiere de vuelta, vuelve allá, no acá.

async function exportarExcel(nombre: string, cabeceras: string[], filas: (string | number | null)[][]) {
  const XLSX = await import('xlsx')
  const ws = XLSX.utils.aoa_to_sheet([cabeceras, ...filas])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Datos')
  XLSX.writeFile(wb, `${nombre}.xlsx`)
}

// El motivo del movimiento lo escribe services/mermas.py con un prefijo fijo:
// "Consumo (quien): …", "Daño: …", "Traslado a <sede>: …" (y para las mermas que
// bajan por receta, el mismo prefijo + " — insumo de X"). Leer ese prefijo agrupa
// la merma por causa POR INSUMO sin tocar el backend.
// La VENTA entra como una causa más, y no es un detalle: en un insumo que rota es
// la salida DOMINANTE (services/pos.py escribe "Venta POS" y "Venta POS — insumo
// de X"). Sin ella, los chips podían decir "Daño 1,5 kg" sobre veinte movimientos
// donde quince fueron ventas — o sea el título se adjudicaba movimientos que no
// contaba. Una causa que no se puede nombrar cae en `null` y se declara aparte.
function grupoMerma(motivo: string | null): string | null {
  const m = (motivo || '').trim()
  if (/^Venta POS\b/i.test(m)) return 'Venta'
  if (/^Consumo\b/i.test(m)) return 'Consumo'
  if (/^Daño\b/i.test(m))    return 'Daño'
  const t = m.match(/^Traslado a ([^:]+):/i)
  if (t) return `Traslado a ${t[1].trim()}`
  return null
}

// ─── ProductRow ───────────────────────────────────────────────────────────────

// La fila del LIBRO: nombre, cuánto hay, cuánto alcanza. Nada más, y nada
// plegado. Es UN solo <button> —el tache que la partía en dos controles se fue
// con la cola de decisiones— así que la fila entera es el área de toque que abre
// el panel del producto.
//
// La columna «Pedir» también se fue: cuánto pedir es una capa DERIVADA del
// stock, no el stock, y vive en /pedidos-admin. Lo que sí queda de ella son los
// dos rótulos que hablan del producto y no del pedido: «preparar» (no se compra,
// se arma en la barra) y «a ojo» (se acabó y el sistema no tiene con qué
// calcular cuánto) — ahora como chips, al lado del nombre.
//
// El color de estado es la REGLA izquierda y sale del mismo ESTADO_CFG que la
// leyenda: si divergieran, la leyenda dejaría de explicar lo que se ve. Una fila
// sana queda casi monocroma; el color se gasta solo donde hay señal.
function ProductRow({ p, venc, activo, empaque, corte, onSelect }: {
  p: ProductoInventario
  venc?: VencInfo
  activo: boolean
  // La fila anterior era de OTRO estado: acá el alfabeto se reinicia y el
  // hairline se refuerza para que el bloque nuevo se lea como bloque.
  corte?: boolean
  // Cuántas unidades de inventario trae UN empaque de compra
  // (`productos.contenido_por_empaque`). Undefined = sin factor cargado: no se
  // dice nada, porque un factor inventado es peor que ninguno.
  empaque?: number
  onSelect: () => void
}) {
  const cfg = ESTADO_CFG[p.estado] ?? ESTADO_CFG.ok
  const enNegativo = p.stock_actual < 0
  // El stock se pinta en rojo también cuando está en cero o menos. Antes dependía
  // solo de los días restantes, que son NULL sin consumo medido: un producto en 0
  // sin salidas registradas mostraba su cero en gris.
  const critico = p.stock_actual <= 0 ||
    (p.dias_restantes !== null && p.dias_restantes <= p.lead_time_dias)
  // Lo que se arma con receta en la barra. `hayQueReponer` evita el otro extremo:
  // un preparable con stock de sobra no tiene por qué gritar «preparar».
  const esPreparable = p.accion === 'preparar'
  const hayQueReponer = p.cantidad_sugerida > 0 || p.stock_actual <= 0
  // «a ojo»: se acabó Y el sistema no tiene ni mínimo ni consumo medido para
  // decir cuánto. Un preparable nunca lo lleva: su verbo ya es otro.
  const aOjo = !esPreparable && p.stock_actual <= 0 && p.cantidad_sugerida <= 0
  const sano = p.estado === 'ok'
  const caps = esCaps(p.nombre)
  // «24 und ≈ 2 empaques de 12». Con factor 1 el empaque y la unidad son lo
  // mismo y la frase no diría nada. Y por debajo de UN empaque tampoco se dice:
  // «≈ 0,2 empaques de 10» no es un refuerzo de «2 und», es ruido — la cantidad
  // en unidades ya es la lectura más clara ahí.
  const enEmpaques = empaque && empaque > 1 && p.stock_actual >= empaque
    ? Math.round((p.stock_actual / empaque) * 10) / 10
    : null

  const chip = 'shrink-0 text-[10px] font-bold uppercase tracking-[.06em] px-1.5 py-px rounded'

  return (
    <button
      onClick={onSelect}
      title={`${p.categoria}${p.proveedor ? ` · ${p.proveedor}` : ''}`}
      // En el celular la fila son DOS renglones: el nombre entero arriba y la
      // evidencia abajo. En una sola línea, con los chips y las dos columnas
      // peleando por 390px, el nombre —lo único que el dueño está buscando— se
      // comía en «MEZCLA GRAN…». Desde `sm` vuelve a ser una sola línea.
      className="w-full flex flex-wrap sm:flex-nowrap items-center gap-x-2 gap-y-0.5 text-left border-t py-[5px] pr-3 pl-3 hover:bg-[#F4F4F5] transition-colors"
      style={{
        borderTopColor: corte ? MC.lineaFte : MC.linea,
        borderTopWidth: corte ? 2 : 1,
        borderLeft: `3px solid ${cfg.mc}`,
        background: activo ? '#F4F4F5' : MC.papel,
      }}
    >
      <span
        className={`w-full sm:w-auto sm:flex-1 min-w-0 truncate ${caps ? 'text-[13px] tracking-[0.012em]' : 'text-sm'} ${sano ? 'font-medium' : 'font-semibold'}`}
        style={{ color: MC.negro }}
      >
        {p.barista_alerto && '🔔 '}{p.nombre}
      </span>
      {/* Un cero y un -0,2 se pintaban los dos en rojo, y son dos problemas
          distintos con dos acciones distintas. El signo menos solo no alcanza:
          es un píxel. El chip usa la MISMA palabra que la pastilla, que es donde
          se explica qué significa. */}
      {enNegativo && (
        <span className={chip} title="El sistema descontó más de lo que se registró que entró: falta cargar una entrada."
          style={{ color: MC.negativo, boxShadow: `inset 0 0 0 1.4px ${MC.negativo}` }}>
          en negativo
        </span>
      )}
      {/* No se compra: se arma en la barra con la receta. Sin este rótulo, un
          faltante de mezcla de granizado se lee como una orden de compra a un
          proveedor que no existe. Cuánto preparar lo dice el panel. */}
      {esPreparable && hayQueReponer && (
        <span className={chip} title="Esto no se compra: se prepara en la barra. Cuánto, en el panel del producto."
          style={{ color: MC.oliva, boxShadow: `inset 0 0 0 1.4px ${MC.oliva}` }}>
          preparar
        </span>
      )}
      {aOjo && (
        <span className={chip} title="Se acabó y el sistema no tiene mínimo ni consumo medido: la cantidad a pedir la ponés vos."
          style={{ color: ESTADO_CFG.bajo.mc, boxShadow: `inset 0 0 0 1.4px ${ESTADO_CFG.bajo.mc}` }}>
          a ojo
        </span>
      )}
      {/* «⚠ 15-08» solo se explicaba en un `title`, que en el celular no existe.
          El verbo cabe en el mismo nodo. */}
      {venc && (
        <span className={`${chip} tabular-nums`}
          style={{
            color: venc.estado === 'vencido' ? ESTADO_CFG.agotado.mc : MC.vence,
            background: '#F6E7C9',
          }}>
          {venc.estado === 'vencido' ? 'venció' : 'vence'} {ddmm(venc.fecha)}
        </span>
      )}
      {/* El stock dicho en la unidad en que se COMPRA, que es como el dueño
          piensa el pedido («las tortas vienen de 12 porciones, la pulpa de 10»).
          Va pegado al número de stock porque es el mismo número en otra unidad,
          no un dato nuevo. Sale de `contenido_por_empaque` y solo aparece cuando
          ese factor está cargado. */}
      {enEmpaques !== null && (
        <span className="shrink-0 text-[10px] tabular-nums" style={{ color: MC.tinta28 }}
          title={`Un empaque de compra trae ${num(empaque!)} ${p.unidad}.`}>
          ≈ {num(enEmpaques)} {enEmpaques === 1 ? 'empaque' : 'empaques'} de {num(empaque!)}
        </span>
      )}
      <span className="shrink-0 ml-auto sm:ml-0 w-auto sm:w-[74px] text-right text-sm font-semibold tabular-nums"
        style={{ color: critico ? ESTADO_CFG.agotado.mc : (sano ? MC.tinta70 : MC.negro) }}>
        {num(p.stock_actual)}
        <span className="font-normal text-[11px]" style={{ color: MC.tinta45 }}> {p.unidad}</span>
      </span>
      {/* «se acabó» no se esconde en el celular: es justo el rótulo que distingue
          el cero del negativo, y en el renglón de evidencia cabe. */}
      <span className="shrink-0 w-auto sm:w-16 text-right text-[11px] tabular-nums"
        style={{ color: sano ? MC.tinta45 : MC.tinta70 }}>
        {alcanzaLabel(p)}
      </span>
    </button>
  )
}

// ─── Panel lateral del producto ───────────────────────────────────────────────

const TABS = [
  { id: 'hoy',      label: 'Hoy'         },
  { id: 'lotes',    label: 'Lotes'       },
  { id: 'conteos',  label: 'Conteos'     },
  { id: 'movs',     label: 'Movimientos' },
  { id: 'receta',   label: 'Receta'      },
] as const
type TabId = typeof TABS[number]['id']
const ES_TAB = (v: string): v is TabId => TABS.some(t => t.id === v)

function PanelProducto({ producto: p, tiendaId, tab, onTab, onClose, sinConsumidor,
                         negativo, recetasSospechosas, onSaved }: {
  producto: ProductoInventario
  tiendaId: number
  tab: TabId
  onTab: (t: TabId) => void
  onClose: () => void
  sinConsumidor: boolean
  // Por qué este producto está en negativo, y si alguna receta lo descuenta en
  // una unidad que no cierra. Los dos avisos viven ACÁ y no en la lista: el
  // dueño ya abrió el producto, es el único momento en que sirven.
  negativo?: DiagNegativo
  recetasSospechosas: DiagRecetaSospechosa[]
  onSaved: () => void
}) {
  const [ficha, setFicha] = useState<Ficha | null>(null)
  const [fichaErr, setFichaErr] = useState(false)
  // `tick` es lo que revalida la ficha después de guardar. Sin él, registrar un
  // movimiento refrescaba la lista (y con ella la CABECERA del panel, que lee del
  // producto) pero no la ficha: las tarjetas Actual/Crítico/Mínimo/Ideal, los
  // lotes, los conteos y los movimientos seguían mostrando el estado anterior. Con
  // un ajuste —que FIJA el valor absoluto— la contradicción era garantizada: dos
  // stocks distintos del mismo insumo a 40 píxeles uno del otro.
  const [tick, setTick] = useState(0)
  const revalidar = () => { setTick(t => t + 1); onSaved() }

  useEffect(() => {
    let vivo = true
    setFicha(null); setFichaErr(false)
    api.get<Ficha>(`/inventario/producto/${p.producto_id}/ficha`, { params: { tienda_id: tiendaId } })
      .then(r => { if (vivo) setFicha(r.data) })
      .catch(() => { if (vivo) setFichaErr(true) })
    return () => { vivo = false }
  }, [p.producto_id, tiendaId, tick])

  // Movimiento manual. Los tres tipos vienen de la vista admin de /inventario que
  // se borró en este mismo push: ahí el admin podía registrar entrada, salida o
  // ajuste para cualquier sede. Se conserva la capacidad completa — si acá
  // quedara solo el ajuste, borrar aquella pantalla sería una pérdida.
  const [adjTipo, setAdjTipo]         = useState<'entrada' | 'salida' | 'ajuste'>('ajuste')
  const [adjCantidad, setAdjCantidad] = useState('')
  const [adjMotivo, setAdjMotivo]     = useState('')
  const [savingAdj, setSavingAdj]     = useState(false)
  const [savedAdj, setSavedAdj]       = useState(false)

  // Umbrales. Se inicializan de props — por eso el panel se monta con
  // key={producto_id} desde arriba: cambiar de producto REMONTA el componente y
  // los inputs arrancan con los valores del producto nuevo. El acordeón viejo
  // nunca re-sincronizaba y mostraba los umbrales del producto anterior.
  const [critico,  setCritico]  = useState(String(p.stock_critico ?? 0))
  const [minimo,   setMinimo]   = useState(String(p.stock_minimo))
  const [ideal,    setIdeal]    = useState(String(p.stock_ideal ?? 0))
  const [leadTime, setLeadTime] = useState(String(p.lead_time_dias))
  const [savingThr, setSavingThr] = useState(false)
  const [savedThr,  setSavedThr]  = useState(false)

  const thrDirty =
    Number(critico)  !== (p.stock_critico ?? 0) ||
    Number(minimo)   !== p.stock_minimo          ||
    Number(ideal)    !== (p.stock_ideal ?? 0)    ||
    Number(leadTime) !== p.lead_time_dias

  async function submitAdj(e: React.FormEvent) {
    e.preventDefault()
    const cantidad = parseFloat(adjCantidad)
    if (isNaN(cantidad) || cantidad < 0) return
    setSavingAdj(true)
    try {
      await api.post('/inventario/movimiento', {
        tienda_id: tiendaId, producto_id: p.producto_id,
        tipo: adjTipo, cantidad, motivo: adjMotivo.trim() || `${adjTipo} manual`,
      })
      setSavedAdj(true)
      setAdjCantidad('')
      setAdjMotivo('')
      setTimeout(() => { setSavedAdj(false); revalidar() }, 1000)
    } catch { alert('Error al guardar ajuste') }
    finally { setSavingAdj(false) }
  }

  async function saveThr() {
    setSavingThr(true)
    try {
      const ops: Promise<unknown>[] = [
        api.patch(`/inventario/tienda/${tiendaId}/producto/${p.producto_id}/umbrales`, {
          stock_minimo: Number(minimo),
          stock_ideal:  Number(ideal),
          stock_critico: Number(critico),
        }),
      ]
      if (Number(leadTime) !== p.lead_time_dias)
        ops.push(api.patch(`/inventario/productos/${p.producto_id}`, { lead_time_dias: Number(leadTime) }))
      await Promise.all(ops)
      setSavedThr(true)
      setTimeout(() => { setSavedThr(false); revalidar() }, 1200)
    } catch { alert('Error al guardar umbrales') }
    finally { setSavingThr(false) }
  }

  // Desglose de merma por causa. Sale del prefijo del motivo (ver grupoMerma) y
  // por lo tanto solo cubre los movimientos que trae la ficha, no todo el
  // histórico: el rótulo lo dice para que el número no se lea como un total.
  // Los que no matchean ningún prefijo van a «Otros» y NO se descartan: un
  // movimiento que desaparece del desglose hace que los chips no sumen lo que el
  // título dice, y ahí el número deja de ser confiable sin que se note.
  const { merma, nSalidas } = useMemo(() => {
    const acc = new Map<string, number>()
    let n = 0
    for (const m of ficha?.movimientos ?? []) {
      if (m.tipo === 'entrada') continue          // el desglose es de lo que SALE
      n++
      const g = grupoMerma(m.motivo) ?? 'Otros'
      acc.set(g, (acc.get(g) ?? 0) + Math.abs(m.cantidad))
    }
    return { merma: [...acc.entries()].sort((a, b) => b[1] - a[1]), nSalidas: n }
  }, [ficha])

  const H = ({ children }: { children: React.ReactNode }) => (
    <p className="text-[11px] font-bold uppercase tracking-wider mb-2" style={{ color: dark.inkSubtle }}>{children}</p>
  )
  const vacio = (t: string) => <p className="text-xs" style={{ color: dark.inkSubtle }}>{t}</p>

  return (
    <SidePanel onClose={onClose} bottomOffset={0}>
      <div className="px-4 pb-6">
        <h2 className="text-base font-bold" style={{ color: dark.ink }}>{p.nombre}</h2>
        <p className="text-xs mb-3" style={{ color: dark.inkMuted }}>
          {p.categoria}{p.proveedor ? ` · ${p.proveedor}` : ''} · {p.stock_actual} {p.unidad}
        </p>

        <div className="flex gap-1 flex-wrap mb-4">
          {TABS.map(t => (
            <button key={t.id} onClick={() => onTab(t.id)}
              className="px-2.5 py-1 rounded-lg text-xs font-semibold transition-colors"
              style={tab === t.id
                ? { background: dark.ink, color: dark.surface }
                : { background: dark.surfaceAlt, color: dark.inkMuted }}>
              {t.label}
            </button>
          ))}
        </div>

        {fichaErr && vacio('No se pudo cargar el detalle.')}
        {!ficha && !fichaErr && <div className="h-16 rounded animate-pulse" style={{ background: dark.surfaceAlt }} />}

        {/* ── Hoy ── */}
        {tab === 'hoy' && (
          <div className="space-y-5">
            {/* El preparable: acá SÍ cabe la cantidad completa, porque el dueño ya
                abrió el producto y está decidiendo. La lista solo pudo decir el
                verbo. Las tandas se dicen únicamente si el rendimiento está
                cargado — sin ese número no hay forma de convertir gramos en
                tandas y una tanda inventada sería peor que ninguna. */}
            {p.accion === 'preparar' && (
              <div className="rounded-xl px-3 py-2.5 text-xs space-y-1"
                style={{ background: dark.surfaceAlt, color: dark.ink,
                         border: `1px solid ${dark.border}` }}>
                <p className="font-bold">Esto se prepara, no se compra</p>
                {p.cantidad_sugerida > 0 ? (
                  <p>
                    Reponé ~{num(p.cantidad_sugerida)} {p.unidad}
                    {p.tandas_sugeridas
                      ? ` ≈ ${p.tandas_sugeridas} tanda${p.tandas_sugeridas === 1 ? '' : 's'}`
                      : ''}.
                    {p.tandas_sugeridas && p.rendimiento_tanda
                      ? ` Una tanda rinde ${num(p.rendimiento_tanda)} ${p.unidad}.`
                      : ''}
                  </p>
                ) : p.stock_actual <= 0 ? (
                  <p>Se acabó. La cantidad la ponés vos: no hay consumo medido ni mínimo cargado.</p>
                ) : (
                  <p style={{ color: dark.inkMuted }}>Alcanza por ahora.</p>
                )}
                {p.cantidad_sugerida > 0 && !p.tandas_sugeridas && (
                  <p style={{ color: dark.inkSubtle }}>
                    Sin rendimiento por tanda cargado no se puede decir cuántas tandas son.
                  </p>
                )}
              </div>
            )}
            {/* POR QUÉ está en negativo. La lista ya lo muestra en rojo y dice
                «agotado»; lo que falta es la causa, y sin ella el dueño lee
                «el sistema se rompió» cuando lo que pasó es que falta registrar
                una entrada. Eso cambia lo que hace al leerlo.
                La causa es una SOSPECHA, no un veredicto: el backend la escribe
                así y acá NO se reescribe en tono afirmativo. */}
            {negativo && (
              <div className="rounded-xl px-3 py-2.5 text-xs space-y-1.5"
                style={{ background: dark.dangerTint, color: dark.danger, border: `1px solid ${dark.dangerDim}` }}>
                <p className="font-bold flex items-center gap-1.5">
                  <AlertTriangle size={13} className="shrink-0" />
                  {negativo.titulo}
                </p>
                <p>{negativo.sospecha}</p>
                <p style={{ color: dark.ink }}>
                  Un negativo no es que el sistema se rompió: es que falta registrar
                  una entrada. {negativo.que_hacer}
                </p>
                {/* Si dos causas aplicaban, se dice cuál gana Y que la otra
                    existía. Esconder la segunda sería inventar una certeza. */}
                {negativo.por_que_gana && (
                  <p style={{ color: dark.inkMuted }}>{negativo.por_que_gana}</p>
                )}
                <p style={{ color: dark.inkSubtle }}>
                  Última entrada en esta sede: {negativo.ultima_entrada
                    ? `${ddmm(negativo.ultima_entrada)}${negativo.dias_sin_entrada !== null ? ` (hace ${negativo.dias_sin_entrada} días)` : ''}`
                    : 'ninguna'}
                  {' · '}lo consumen {negativo.lo_consumen_n_recetas} receta{negativo.lo_consumen_n_recetas === 1 ? '' : 's'}
                </p>
              </div>
            )}

            {/* Receta que descuenta este insumo en una unidad que no cierra: 18
                «kg» donde se quiso decir 18 g descuenta mil veces de más por
                venta y desploma el stock en horas. El aviso llega acá porque es
                el único lugar donde llega en el momento en que sirve. */}
            {recetasSospechosas.length > 0 && (
              <div className="rounded-xl px-3 py-2.5 text-xs space-y-1.5"
                style={{ background: dark.amberTint, color: dark.amber, border: `1px solid ${dark.amberDim}` }}>
                <p className="font-bold">Revisá la unidad de la receta</p>
                {recetasSospechosas.map(r => (
                  <p key={`${r.producto_id}-${r.insumo_id}`}>{r.sospecha}</p>
                ))}
              </div>
            )}

            {/* Este cartel sale de GET /inventario/cobertura, un endpoint que ya
                existía y no consumía NADIE. Es la explicación más común de un
                descuadre de conteo, puesta justo donde el dueño lo está mirando. */}
            {sinConsumidor && (
              <div className="flex gap-2 text-xs rounded-xl px-3 py-2.5"
                style={{ background: dark.dangerTint, color: dark.danger, border: `1px solid ${dark.dangerDim}` }}>
                <AlertTriangle size={14} className="shrink-0 mt-0.5" />
                <span>
                  Este insumo se gasta físicamente y el sistema <b>nunca lo descuenta</b>:
                  ninguna receta lo consume. Cada conteo va a dar diferencia hasta que
                  entre en la receta de algo o se ajuste a mano.
                </span>
              </div>
            )}

            {/* Los cuatro números salen del PRODUCTO, no de la ficha: el producto
                se refresca con la lista al guardar y la ficha tarda un tick más.
                Leyendo de dos fuentes distintas, la cabecera del panel mostraba el
                stock nuevo y esta tarjeta el viejo, a 40 píxeles de distancia. Los
                cuatro campos existen en ProductoInventario. */}
            {ficha && (
              <div className="grid grid-cols-4 gap-1.5 text-center">
                {[
                  { l: 'Actual',  v: p.stock_actual  },
                  { l: 'Crítico', v: p.stock_critico },
                  { l: 'Mínimo',  v: p.stock_minimo  },
                  { l: 'Ideal',   v: p.stock_ideal   },
                ].map(s => (
                  <div key={s.l} className="rounded-lg py-1.5" style={{ background: dark.surfaceAlt }}>
                    <p className="text-sm font-bold tabular-nums" style={{ color: dark.ink }}>{s.v}</p>
                    <p className="text-[10px]" style={{ color: dark.inkSubtle }}>{s.l}</p>
                  </div>
                ))}
              </div>
            )}

            {p.fraccionable && (
              <div title={`Nivel de la ${p.envase || 'bolsa'} en uso`}>
                <H>Envase en uso</H>
                <NivelEnvase readOnly envase={p.envase === 'botella' ? 'botella' : 'bolsa'}
                  nivel={p.stock_actual <= 0 ? 0 : (p.stock_actual % 1 === 0 ? 1 : p.stock_actual % 1)} />
              </div>
            )}

            <div>
              <H>Movimiento manual</H>
              <form onSubmit={submitAdj} className="flex gap-2 flex-wrap items-end">
                <select value={adjTipo} onChange={e => setAdjTipo(e.target.value as typeof adjTipo)}
                  className="rounded-lg px-2 py-1.5 text-sm focus:outline-none"
                  style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}>
                  <option value="ajuste">Ajuste</option>
                  <option value="entrada">Entrada</option>
                  <option value="salida">Salida</option>
                </select>
                <input
                  type="number" min={0} step={0.5} value={adjCantidad}
                  onChange={e => setAdjCantidad(e.target.value)}
                  // En «ajuste» el número es el stock REAL contado (reemplaza);
                  // en entrada/salida es cuánto se suma o se resta.
                  placeholder={adjTipo === 'ajuste' ? `Real (${p.unidad})` : `Cantidad (${p.unidad})`}
                  className="w-28 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none"
                  style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
                />
                <input
                  type="text" value={adjMotivo} onChange={e => setAdjMotivo(e.target.value)}
                  placeholder="Motivo"
                  className="flex-1 min-w-[120px] rounded-lg px-2.5 py-1.5 text-sm focus:outline-none"
                  style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
                />
                <button type="submit" disabled={adjCantidad === '' || savingAdj || savedAdj}
                  className="px-3 py-1.5 rounded-lg text-sm font-semibold text-white disabled:opacity-40"
                  style={{ background: dark.amber }}>
                  {savedAdj ? <Check size={14} /> : savingAdj ? '…' : 'Confirmar'}
                </button>
              </form>
            </div>

            <div>
              <H>Umbrales y tiempo de entrega</H>
              <div className="flex gap-2 flex-wrap items-end">
                {[
                  { label: 'Crítico', val: critico,  set: setCritico  },
                  { label: 'Mínimo',  val: minimo,   set: setMinimo   },
                  { label: 'Ideal',   val: ideal,    set: setIdeal    },
                  { label: 'Entrega', val: leadTime, set: setLeadTime },
                ].map(({ label, val, set }) => (
                  <div key={label}>
                    <label className="text-[10px] block mb-0.5" style={{ color: dark.inkSubtle }}>{label}</label>
                    <input
                      type="number" min={0} step={label === 'Entrega' ? 1 : 0.5}
                      value={val} onChange={e => set(e.target.value)}
                      className="w-16 text-center rounded-lg px-2 py-1.5 text-sm focus:outline-none"
                      style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }}
                    />
                  </div>
                ))}
                <button onClick={saveThr} disabled={!thrDirty || savingThr || savedThr}
                  className="px-3 py-1.5 rounded-lg text-sm font-semibold text-white disabled:opacity-40"
                  style={{ background: dark.ink }}>
                  {savedThr ? <Check size={14} /> : savingThr ? '…' : 'Guardar'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── Lotes ── */}
        {tab === 'lotes' && ficha && (
          ficha.lotes.length === 0 ? vacio('Sin lotes registrados.') : (
            <div className="space-y-1.5">
              {ficha.lotes.map(l => (
                <div key={l.id} className="rounded-lg px-2.5 py-2 text-xs" style={{
                  background: l.estado === 'vencido' ? dark.dangerTint
                    : l.estado === 'por_vencer' ? dark.amberTint : dark.surface,
                  border: `1px solid ${dark.border}`,
                  opacity: l.estado === 'agotado' ? 0.55 : 1,
                }}>
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-semibold" style={{ color: dark.ink }}>{l.numero_lote || 's/lote'}</span>
                    <span style={{ color: dark.inkSubtle }}>{l.proveedor || '—'}</span>
                    <span className="ml-auto font-semibold tabular-nums" style={{ color: dark.ink }}>
                      {l.cantidad_restante} / {l.cantidad_inicial} {p.unidad}
                    </span>
                  </div>
                  {/* consumido_pct y fecha_entrada ya venían en la ficha y no se
                      pintaban en ningún lado: son el «cuánto va gastado y desde
                      cuándo» de cada lote. */}
                  <div className="mt-1.5 h-1 rounded-full overflow-hidden" style={{ background: dark.surfaceAlt }}>
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, l.consumido_pct)}%`, background: dark.greenDim }} />
                  </div>
                  <p className="mt-1 flex gap-2 flex-wrap" style={{ color: dark.inkSubtle }}>
                    <span>{l.consumido_pct}% consumido</span>
                    {l.fecha_entrada && <span>· entró {ddmm(l.fecha_entrada)}</span>}
                    <span className="ml-auto font-bold" style={{
                      color: l.estado === 'vencido' ? dark.danger : l.estado === 'por_vencer' ? dark.amber : dark.inkSubtle,
                    }}>
                      {l.fecha_vencimiento ? `vence ${ddmm(l.fecha_vencimiento)}` : 'sin vencimiento'}
                    </span>
                  </p>
                </div>
              ))}
            </div>
          )
        )}

        {/* ── Conteos ── */}
        {tab === 'conteos' && ficha && (
          ficha.conteos.length === 0 ? vacio('Todavía nadie contó este producto.') : (
            <div className="space-y-1.5">
              {ficha.conteos.map(c => (
                <div key={c.conteo_id} className="rounded-lg px-2.5 py-2 text-xs"
                  style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold capitalize" style={{ color: dark.ink }}>{c.tipo}</span>
                    <span style={{ color: dark.inkSubtle }}>{(c.fecha || '').slice(0, 10)}</span>
                    <span style={{ color: dark.inkMuted }}>{c.barista_nombre || '—'}</span>
                    {/* La bandera es_atajo ya llegaba tipada y NUNCA se renderizaba.
                        Sin ella una diferencia 0 se lee como un conteo confirmado
                        cuando en realidad es un eco del stock del sistema. */}
                    {c.es_atajo && (
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                        style={{ background: dark.amberTint, color: dark.amber }}
                        title='Registrado con el botón "Todo coincide con sistema" — no es un conteo físico'>
                        ⚡ Todo coincide
                      </span>
                    )}
                    <span className="ml-auto font-bold tabular-nums" style={{
                      color: c.diferencia === 0 ? dark.inkSubtle : c.diferencia > 0 ? dark.green : dark.danger,
                    }}>
                      {c.diferencia > 0 ? '+' : ''}{c.diferencia}
                    </span>
                  </div>
                  <p className="mt-0.5" style={{ color: dark.inkSubtle }}>
                    sistema {c.cantidad_sistema} · contó {c.cantidad_real}
                  </p>
                </div>
              ))}
            </div>
          )
        )}

        {/* ── Movimientos ── */}
        {tab === 'movs' && ficha && (
          <div className="space-y-3">
            {merma.length > 0 && (
              <div>
                <H>Dónde se va — últimas {nSalidas} salidas</H>
                <div className="flex gap-1.5 flex-wrap">
                  {merma.map(([g, v]) => (
                    <span key={g} className="text-[11px] font-semibold px-2 py-1 rounded-lg"
                      style={{ background: dark.surfaceAlt, color: dark.ink }}>
                      {g} <b className="tabular-nums">{Math.round(v * 100) / 100}</b> {p.unidad}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {ficha.movimientos.length === 0 ? vacio('Sin movimientos.') : (
              <div className="space-y-0.5">
                {ficha.movimientos.map(m => (
                  <div key={m.id} className="flex items-center gap-2 text-xs px-1 py-1">
                    <span className="w-16 shrink-0" style={{ color: dark.inkSubtle }}>{ddmm(m.fecha || '')}</span>
                    <span className="w-14 shrink-0 font-semibold capitalize" style={{ color: dark.inkMuted }}>{m.tipo}</span>
                    <span className="w-14 text-right shrink-0 font-bold tabular-nums"
                      style={{ color: m.tipo === 'entrada' ? dark.green : dark.ink }}>
                      {m.cantidad}
                    </span>
                    <span className="truncate" style={{ color: dark.inkSubtle }}>
                      {m.motivo || ''}{m.barista ? ` · ${m.barista}` : ''}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Receta ── */}
        {tab === 'receta' && ficha && (
          ficha.receta.insumos.length === 0 && ficha.receta.usado_en.length === 0
            ? vacio('Sin receta en ninguno de los dos sentidos.')
            : (
              <div className="space-y-3 text-xs" style={{ color: dark.inkMuted }}>
                {ficha.receta.insumos.length > 0 && (
                  <div>
                    <H>Consume</H>
                    {ficha.receta.insumos.map(i => `${i.nombre} (${i.cantidad} ${i.unidad_medida})`).join(' · ')}
                  </div>
                )}
                {ficha.receta.usado_en.length > 0 && (
                  <div>
                    <H>Se usa en</H>
                    {ficha.receta.usado_en.map(i => i.nombre).join(' · ')}
                  </div>
                )}
              </div>
            )
        )}
      </div>
    </SidePanel>
  )
}

// ─── Panel de mínimos propuestos ──────────────────────────────────────────────

// Cómo se lee «en qué quedaría». Sale de `clasificar_estado` del backend
// (services/inventario.py): agotado | critico | bajo | normal. La palabra que se
// muestra es la del dueño, no la del enum.
const QUEDARIA_CFG: Record<string, { label: string; color: string; bg: string }> = {
  agotado: { label: 'sin stock', color: 'oklch(38% 0.16 25)',  bg: 'oklch(95% 0.04 25)'  },
  critico: { label: 'crítico',   color: 'oklch(38% 0.16 25)',  bg: 'oklch(95% 0.04 25)'  },
  bajo:    { label: 'bajo',      color: 'oklch(38% 0.12 70)',  bg: 'oklch(95% 0.045 70)' },
  normal:  { label: 'al día',    color: 'oklch(32% 0.10 155)', bg: 'oklch(94% 0.04 155)' },
}

function PanelMinimos({ tiendaId, onClose, onAplicado }: {
  tiendaId: number
  onClose: () => void
  // Se aplicó algo: la lista y el diagnóstico de la pantalla de atrás quedaron
  // viejos. Mismo patrón que `onSaved` del panel de producto.
  onAplicado: () => void
}) {
  const [data, setData]       = useState<PropuestasUmbrales | null>(null)
  const [err, setErr]         = useState(false)
  const [tick, setTick]       = useState(0)
  // producto_id → marcado, y producto_id → el número que va a escribirse (que el
  // dueño puede haber editado). Se inicializan cuando llegan las propuestas.
  const [marcados, setMarcados] = useState<Record<number, boolean>>({})
  const [valores, setValores]   = useState<Record<number, string>>({})
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    let vivo = true
    setErr(false)
    api.get<PropuestasUmbrales>('/inventario/umbrales/propuestas', { params: { tienda_id: tiendaId } })
      .then(r => {
        if (!vivo) return
        setData(r.data)
        // Nada arranca marcado: el principio es que el dueño ACEPTA, no que
        // desmarca lo que no quiere. Un checkbox premarcado convierte «revisar»
        // en «confirmar sin leer».
        setMarcados({})
        setValores(Object.fromEntries(
          r.data.propuestas.map(p => [p.producto_id, String(p.minimo_propuesto)])))
      })
      .catch(() => { if (vivo) setErr(true) })
    return () => { vivo = false }
  }, [tiendaId, tick])

  const props = data?.propuestas ?? []
  const seguras = props.filter(p => p.en_aceptar_todo)
  const advertidas = props.filter(p => !p.en_aceptar_todo)
  const nMarcados = props.filter(p => marcados[p.producto_id]).length
  const todasSegurasMarcadas = seguras.length > 0 && seguras.every(p => marcados[p.producto_id])

  // La MISMA regla que usa la fila para pintar su chip. Extraída para que el
  // encabezado y la fila no puedan volver a contar distinto.
  const cambiaConValor = (p: PropuestaMinimo, v: string) => {
    if (p.estado_hoy !== 'normal') return false          // ya estaba en alerta
    const n = Number(v)
    return Number.isFinite(n) && n > 0 && p.stock_actual <= n
  }

  // El impacto de arriba es el de LO QUE ESTÁ MARCADO, con el valor EDITADO —
  // no con `cambia_a_alerta`, que el backend congeló sobre el mínimo PROPUESTO.
  // Con el flag congelado, editar un número dejaba el encabezado contradiciendo
  // al chip de la propia fila: el número que anuncia lo que va a hacer el botón
  // tiene que salir de lo que el botón va a mandar.
  const impactoMarcado = props.filter(p =>
    marcados[p.producto_id] && cambiaConValor(p, valores[p.producto_id])).length

  // Marcadas cuyo valor editado no es un número válido (> 0). No se descartan en
  // silencio: bloquean el botón y la fila lo dice. «Aceptar 5» que escribe 4 y
  // responde éxito es la clase exacta de mentira que este panel vino a evitar.
  const invalidas = props.filter(p => {
    if (!marcados[p.producto_id]) return false
    const n = Number(valores[p.producto_id])
    return !(Number.isFinite(n) && n > 0)
  })

  const toggleTodas = () => {
    if (todasSegurasMarcadas) { setMarcados({}); return }
    setMarcados(Object.fromEntries(seguras.map(p => [p.producto_id, true])))
  }

  async function aplicar() {
    if (invalidas.length > 0) return    // el botón ya está deshabilitado; cinturón y tirantes
    const items = props
      .filter(p => marcados[p.producto_id])
      .map(p => ({ producto_id: p.producto_id, stock_minimo: Number(valores[p.producto_id]) }))
    if (items.length === 0) { alert('Marcá al menos un producto.'); return }
    setGuardando(true)
    try {
      await api.patch('/inventario/umbrales/aplicar', { tienda_id: tiendaId, items })
      onAplicado()
      setTick(t => t + 1)     // los aplicados ya no aparecen: tienen mínimo cargado
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || 'No se pudieron guardar los mínimos.')
    }
    finally { setGuardando(false) }
  }

  const H = ({ children }: { children: React.ReactNode }) => (
    <p className="text-[11px] font-bold uppercase tracking-wider mb-2" style={{ color: dark.inkSubtle }}>{children}</p>
  )

  return (
    <SidePanel onClose={onClose} bottomOffset={0}>
      <div className="px-4 pb-24">
        <h2 className="text-base font-bold" style={{ color: dark.ink }}>Mínimos que te propone el sistema</h2>
        {/* La palabra «mínimo» se explica UNA vez, en castellano, y no se repite
            en cada fila. Es literal lo que hace el código: el kiosko marca
            alerta con `stock <= minimo` (services/inventario.py) y el motor lo
            usa igual. */}
        <p className="text-xs mb-4" style={{ color: dark.inkMuted }}>
          El mínimo es el punto de aviso: si te queda menos que eso, el sistema te avisa.
          Estos números salen de lo que se gastó de verdad en esta sede. Vos decidís
          cuáles aceptar y podés cambiarlos antes.
        </p>

        {err && <p className="text-xs" style={{ color: dark.danger }}>No se pudo cargar la propuesta.</p>}
        {!data && !err && <div className="h-16 rounded animate-pulse" style={{ background: dark.surfaceAlt }} />}

        {data && props.length === 0 && data.sin_dato.length === 0 && (
          <p className="text-xs" style={{ color: dark.inkMuted }}>
            No hay nada para proponer: todos los productos de esta sede ya tienen mínimo cargado.
          </p>
        )}

        {data && props.length > 0 && (
          <>
            {/* EL ANTES/DESPUÉS. Va arriba de todo y antes de cualquier checkbox:
                un producto que amanece en alerta sin que nadie sepa por qué es
                lo que rompe la confianza en el sistema entero. */}
            <div className="rounded-xl px-3 py-2.5 text-xs mb-4"
              style={{ background: dark.amberTint, color: dark.ink, border: `1px solid ${dark.amberDim}` }}>
              {nMarcados === 0 ? (
                <p>
                  Si aceptás los {seguras.length} de la lista de abajo,{' '}
                  <b>{data.impacto.aceptar_todo.nuevos_en_alerta}</b>{' '}
                  {data.impacto.aceptar_todo.nuevos_en_alerta === 1
                    ? 'producto pasa a necesitar atención hoy mismo'
                    : 'productos pasan a necesitar atención hoy mismo'}.
                </p>
              ) : (
                <p>
                  Marcaste <b>{nMarcados}</b>. Al guardarlos, <b>{impactoMarcado}</b>{' '}
                  {impactoMarcado === 1 ? 'pasa' : 'pasan'} a necesitar atención hoy mismo.
                </p>
              )}
              {data.impacto.ya_en_alerta > 0 && (
                <p className="mt-1" style={{ color: dark.inkMuted }}>
                  Otros {data.impacto.ya_en_alerta} ya están en alerta hoy por su stock:
                  el mínimo no los cambia.
                </p>
              )}
            </div>

            {seguras.length > 0 && (
              <div className="flex items-center justify-between mb-2">
                <H>{seguras.length} con consumo medido</H>
                <button onClick={toggleTodas}
                  className="text-[11px] font-semibold underline"
                  style={{ color: dark.amber }}>
                  {todasSegurasMarcadas ? 'Desmarcar todos' : 'Marcar todos'}
                </button>
              </div>
            )}

            <div className="space-y-1.5">
              {seguras.map(p => (
                <FilaMinimo key={p.producto_id} p={p}
                  marcado={!!marcados[p.producto_id]}
                  valor={valores[p.producto_id] ?? ''}
                  onMarcar={v => setMarcados(m => ({ ...m, [p.producto_id]: v }))}
                  onValor={v => setValores(x => ({ ...x, [p.producto_id]: v }))} />
              ))}
            </div>

            {/* Las advertidas van APARTE y NUNCA entran en «marcar todos»: su
                consumo medido puede estar inflado 1000× por una receta con la
                unidad mal cargada, y el mínimo heredaría el error. Se muestran
                igual —esconderlas sería peor— pero se aceptan de a una. */}
            {advertidas.length > 0 && (
              <div className="mt-5">
                <H>{advertidas.length} para mirar con cuidado</H>
                <p className="text-[11px] mb-2" style={{ color: dark.inkMuted }}>
                  Estos quedan fuera de «marcar todos»: hay una receta que puede
                  estar descontando en la unidad equivocada, así que lo que el
                  sistema midió que se gasta puede no ser real.
                </p>
                <div className="space-y-1.5">
                  {advertidas.map(p => (
                    <FilaMinimo key={p.producto_id} p={p}
                      marcado={!!marcados[p.producto_id]}
                      valor={valores[p.producto_id] ?? ''}
                      onMarcar={v => setMarcados(m => ({ ...m, [p.producto_id]: v }))}
                      onValor={v => setValores(x => ({ ...x, [p.producto_id]: v }))} />
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {/* SIN DATO: sin número, y se dice por qué. Inventar un mínimo acá sería
            exactamente el 0 del default con otra cara. */}
        {data && data.sin_dato.length > 0 && (
          <div className="mt-5">
            <H>{data.sin_dato.length} que el sistema no puede calcular</H>
            <div className="space-y-1.5">
              {data.sin_dato.map(s => (
                <div key={s.producto_id} className="rounded-lg px-3 py-2"
                  style={{ background: dark.surfaceAlt, border: `1px solid ${dark.border}` }}>
                  <p className="text-xs font-semibold" style={{ color: dark.ink }}>{s.nombre}</p>
                  <p className="text-[11px] mt-0.5" style={{ color: dark.inkMuted }}>{s.razon}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* La acción vive pegada abajo: con 40 filas, un botón al final de la
          lista queda a tres pantallas de scroll del impacto que lo justifica. */}
      {data && props.length > 0 && (
        <div className="sticky bottom-0 px-4 py-3"
          style={{ background: dark.surface, borderTop: `1px solid ${dark.border}` }}>
          <button onClick={aplicar} disabled={guardando || nMarcados === 0 || invalidas.length > 0}
            className="w-full py-2.5 rounded-xl text-sm font-bold disabled:opacity-40"
            style={{ background: dark.ink, color: dark.surface }}>
            {guardando ? 'Guardando…'
              : nMarcados === 0 ? 'Marcá los que quieras aceptar'
              : invalidas.length > 0
                ? `Falta un número válido en: ${invalidas.slice(0, 2).map(p => p.nombre).join(', ')}${invalidas.length > 2 ? '…' : ''}`
              : `Aceptar ${nMarcados} mínimo${nMarcados === 1 ? '' : 's'}`}
          </button>
        </div>
      )}
    </SidePanel>
  )
}

function FilaMinimo({ p, marcado, valor, onMarcar, onValor }: {
  p: PropuestaMinimo
  marcado: boolean
  valor: string
  onMarcar: (v: boolean) => void
  onValor: (v: string) => void
}) {
  // El estado en que quedaría se recalcula con el valor EDITADO, no con el
  // propuesto: si el dueño baja el número para que no se le prenda hoy, la
  // etiqueta tiene que seguirlo. Se replica solo el tramo que depende del
  // mínimo; el resto (agotado / crítico) lo decide el stock y no se mueve.
  const n = Number(valor)
  const quedaria = p.estado_hoy !== 'normal' ? p.estado_hoy
    : (Number.isFinite(n) && n > 0 && p.stock_actual <= n ? 'bajo' : 'normal')
  const cfg = QUEDARIA_CFG[quedaria] ?? QUEDARIA_CFG.normal

  return (
    <label className="flex items-start gap-2.5 rounded-lg px-3 py-2 cursor-pointer"
      style={{ background: marcado ? dark.amberTint : dark.surfaceAlt,
               border: `1px solid ${marcado ? dark.amberDim : dark.border}` }}>
      <input type="checkbox" checked={marcado} onChange={e => onMarcar(e.target.checked)}
        className="mt-0.5 w-4 h-4 shrink-0 accent-amber-600" />
      <span className="flex-1 min-w-0">
        <span className="flex items-baseline gap-1.5">
          <span className="text-xs font-semibold truncate" style={{ color: dark.ink }}>{p.nombre}</span>
          {p.accion === 'preparar' && (
            <span className="text-[10px] font-bold shrink-0" style={{ color: dark.green }}>se prepara</span>
          )}
        </span>
        {/* El dato que sostiene el número. Sin él, el mínimo es un número caído
            del cielo — y este panel existe para que no lo sea. */}
        <span className="block text-[11px] mt-0.5" style={{ color: dark.inkMuted }}>
          Se gastan {num(p.consumo_diario)} {p.unidad} por día
          {p.dias_de_datos > 0 && ` (medido en ${p.dias_de_datos} ${p.dias_de_datos === 1 ? 'día' : 'días'} de los últimos ${p.ventana_dias})`}.
          {' '}Hoy tenés {num(p.stock_actual)} {p.unidad}.
        </span>
        <span className="flex items-center gap-2 mt-1.5">
          <input type="number" min={0} step="any" value={valor}
            onChange={e => onValor(e.target.value)}
            onClick={e => e.preventDefault()}
            className="w-24 px-2 py-1 rounded-lg text-xs text-right tabular-nums"
            style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.ink }} />
          <span className="text-[11px]" style={{ color: dark.inkSubtle }}>{p.unidad}</span>
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
            style={{ background: cfg.bg, color: cfg.color }}>
            {quedaria === 'normal' ? 'no te avisa hoy' : `te avisa ya: ${cfg.label}`}
          </span>
        </span>
        {p.advertencia && (
          <span className="block text-[11px] mt-1.5 rounded-lg px-2 py-1"
            style={{ background: dark.dangerTint, color: dark.danger, border: `1px solid ${dark.dangerDim}` }}>
            {p.advertencia}
          </span>
        )}
      </span>
    </label>
  )
}

// ─── Stock mode ───────────────────────────────────────────────────────────────

// EL LIBRO DE LO QUE HAY. Una lista, todos los productos, cada uno con su
// cantidad, sin nada plegado ni escondido detrás de un filtro por defecto. Lo
// urgente va arriba (el orden por estado no cambió), pero lo sano se ve igual,
// con su número, sin un solo click.
//
// La cola de decisiones por verbo (Investigá / Prepará / Compra hoy) se fue a
// /pedidos-admin: cuánto pedir y cada cuánto rota son capas DERIVADAS del stock,
// no el stock. Lo único que queda de ese flujo acá es la puerta —el link
// «Armar pedido →»— y los dos rótulos que describen al producto y no al pedido
// («preparar», «a ojo»), que viajan como chips en su fila.
function ModoStock({ tiendaId }: { tiendaId: number }) {
  const [sugerencia, setSugerencia] = useState<Sugerencia | null>(null)
  const [loading, setLoading]       = useState(false)
  const [busqueda, setBusqueda]     = useState('')
  const [catFiltro, setCatFiltro]   = useState('todas')
  // El panel de mínimos propuestos. Vive en estado local y NO en la URL: no es
  // un deep-link (la propuesta depende del consumo de HOY) y compartir un link
  // que abre una pantalla de escritura no es lo que nadie quiere compartir.
  const [verMinimos, setVerMinimos] = useState(false)
  const navigate = useNavigate()

  // Filtro y selección viven en la URL: ?estado=urgente&p=42&tab=lotes es un
  // deep-link compartible.
  //
  // ABRIR el panel EMPUJA historia; cambiar de filtro o de pestaña la REEMPLAZA.
  // En el celular el panel es pantalla completa (SidePanel: `w-full sm:w-[420px]`),
  // así que «atrás» es el gesto natural para cerrarlo — con replace en todo, ese
  // gesto te sacaba de Inventario. Y con push en todo, volver del panel te hacía
  // recorrer cada pestaña que tocaste.
  const [sp, setSp] = useSearchParams()
  const rawEstado = sp.get('estado') ?? ''
  // El DEFAULT es ver TODO. Los `?estado=` viejos siguen valiendo uno por uno,
  // incluido `atencion`, que era el default anterior.
  const filtro: FiltroId = ES_FILTRO(rawEstado) ? rawEstado : 'todos'
  const selId = Number(sp.get('p')) || null
  const rawTab = sp.get('tab') ?? ''
  const tab: TabId = ES_TAB(rawTab) ? rawTab : 'hoy'

  const setSp2 = useCallback((patch: Record<string, string | null>, push = false) => {
    setSp(prev => {
      const next = new URLSearchParams(prev)
      for (const [k, v] of Object.entries(patch)) v === null ? next.delete(k) : next.set(k, v)
      return next
    }, { replace: !push })
  }, [setSp])

  const cargar = useCallback(() => {
    setLoading(true)
    api.get('/pedidos/sugerencia', { params: { tienda_id: tiendaId } })
      .then(r => setSugerencia(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tiendaId])

  useEffect(() => { cargar() }, [cargar])

  // Vencimientos: el dato que hoy obliga a irse a /lotes. Se cruza por producto
  // EN CLIENTE, igual que hace esa pantalla — cero backend nuevo.
  const [venc, setVenc] = useState<MapaVenc>({})
  const [vencTruncado, setVencTruncado] = useState(false)
  // Si el pedido FALLA, el mapa queda vacío — y un mapa vacío es indistinguible de
  // "no hay nada por vencer". Sin esta bandera la pastilla afirmaba «Se vence 0»
  // y desaparecían todos los avisos de la lista a partir de un error de red.
  // Ausencia de dato no es buena noticia.
  const [vencErr, setVencErr] = useState(false)
  useEffect(() => {
    let vivo = true
    setVencErr(false)
    api.get<LoteTraza[]>('/inventario/lotes-trazabilidad', { params: { tienda_id: tiendaId } })
      .then(r => {
        if (!vivo) return
        const rows = r.data ?? []
        // OJO: el endpoint corta en 800 lotes (services/inventario.py, .limit(800)
        // dentro de get_trazabilidad). Si la sede tiene más, los más viejos no
        // llegan y algún producto puede quedarse SIN su chip de vencimiento. No se
        // esconde: se avisa arriba de la lista.
        //
        // Y el corte se aplica ANTES de descartar los archivados, así que una
        // respuesta truncada puede llegar con MENOS de 800 filas: el umbral se baja
        // para que el aviso no se pierda justo cuando hace falta. El orden es
        // fecha_entrada DESC, o sea lo que se cae son los lotes más VIEJOS —
        // exactamente los vencidos.
        setVencTruncado(rows.length >= 760)
        const m: MapaVenc = {}
        for (const l of rows) {
          if (!l.fecha_vencimiento) continue
          if (l.estado !== 'vencido' && l.estado !== 'por_vencer') continue
          const f = l.fecha_vencimiento.slice(0, 10)
          const prev = m[l.producto_id]
          if (!prev || f < prev.fecha) m[l.producto_id] = { fecha: f, estado: l.estado }
        }
        setVenc(m)
      })
      .catch(() => { if (vivo) { setVenc({}); setVencErr(true) } })
    return () => { vivo = false }
  }, [tiendaId])

  // EL FACTOR DE EMPAQUE, para poder decir el stock en la unidad en que se
  // compra. `productos.contenido_por_empaque` = cuántas unidades de inventario
  // trae UN empaque comercial (torta = 12 porciones, pulpa = bolsa de 10). Es el
  // MISMO campo que usa Recibir para convertir «N empaques» → cantidad
  // (services/facturas.py) y el que lee el escáner de facturas.
  //
  // NO se usa `contenido_por_unidad`, que tiene dos significados según el
  // producto (rendimiento de una tanda de preparable / gramos de la bolsa
  // sellada del conteo) y por lo tanto no se puede leer sin saber cuál de los
  // dos es. Este endpoint ya existía y lo consumen Catálogo e Ingresos: cero
  // backend nuevo. Si falla, el mapa queda vacío y no se dice nada.
  const [empaques, setEmpaques] = useState<Map<number, number>>(new Map())
  useEffect(() => {
    let vivo = true
    api.get<{ id: number; contenido_por_empaque?: number | null }[]>('/inventario/productos')
      .then(r => {
        if (!vivo) return
        const m = new Map<number, number>()
        for (const p of r.data ?? []) if (p.contenido_por_empaque) m.set(p.id, p.contenido_por_empaque)
        setEmpaques(m)
      })
      .catch(() => {})
    return () => { vivo = false }
  }, [])

  // Insumos que controlan stock y que NINGUNA receta consume. El endpoint existía
  // y no lo leía nadie; acá alimenta el cartel del panel (no pinta nada en la
  // lista, así que no suma peso visual).
  const [sinConsumidor, setSinConsumidor] = useState<Set<number>>(new Set())
  useEffect(() => {
    let vivo = true
    api.get<{ insumos_sin_consumidor: { id: number }[] }>('/inventario/cobertura')
      .then(r => { if (vivo) setSinConsumidor(new Set((r.data?.insumos_sin_consumidor ?? []).map(i => i.id))) })
      .catch(() => {})
    return () => { vivo = false }
  }, [])

  // Diagnóstico de stock: umbrales cargados, negativos con su causa y recetas
  // con sospecha de unidad. UNA llamada que alimenta la línea de aviso de acá
  // arriba y los dos carteles del panel. Si falla, no se muestra nada — nunca
  // se dibuja un aviso sobre un dato que no llegó.
  const [diag, setDiag] = useState<Diagnostico | null>(null)
  // `diagTick` lo revalida después de guardar. Sin él, registrabas la entrada que
  // el propio cartel te pidió y el bloque rojo seguía diciendo «sin ingreso
  // registrado» al lado de una cabecera con el stock ya en positivo. Mismo
  // criterio que el `tick` de la ficha en el panel: dos fuentes que se refrescan
  // a destiempo terminan contradiciéndose en la misma pantalla.
  const [diagTick, setDiagTick] = useState(0)
  useEffect(() => {
    let vivo = true
    if (diagTick === 0) setDiag(null)   // al cambiar de sede sí se limpia; al revalidar, no parpadea
    api.get<Diagnostico>('/inventario/diagnostico', { params: { tienda_id: tiendaId } })
      .then(r => { if (vivo) setDiag(r.data) })
      .catch(() => {})
    return () => { vivo = false }
  }, [tiendaId, diagTick])
  useEffect(() => { setDiagTick(0); setDiag(null) }, [tiendaId])

  const negativosPorProducto = useMemo(() => {
    const m = new Map<number, DiagNegativo>()
    for (const n of diag?.negativos ?? []) m.set(n.producto_id, n)
    return m
  }, [diag])

  // Indexadas por INSUMO: el aviso le sirve al producto que se está desangrando,
  // no al que se vende.
  const sospechaPorInsumo = useMemo(() => {
    const m = new Map<number, DiagRecetaSospechosa[]>()
    for (const r of diag?.recetas_sospechosas ?? []) {
      const prev = m.get(r.insumo_id)
      if (prev) prev.push(r); else m.set(r.insumo_id, [r])
    }
    return m
  }, [diag])

  // El aviso de umbrales sale sobre el inventario GESTIONADO (lo que el motor
  // mira de verdad), no sobre todas las filas: contar los archivados infla el
  // faltante y el número deja de ser el que importa.
  //
  // Se muestra mientras FALTE ALGUNO. El gate anterior («menos de la mitad»)
  // cerraba la única puerta al panel de propuestas a mitad del trabajo: el dueño
  // aceptaba 28 de 55, el aviso desaparecía, y los 27 restantes quedaban sin
  // forma de revisarse en lote.
  const umb = diag?.umbrales.total
  const avisoUmbrales = umb && umb.filas_gestionadas > 0 &&
    umb.con_minimo_gestionadas < umb.filas_gestionadas
    ? { sin: umb.filas_gestionadas - umb.con_minimo_gestionadas, de: umb.filas_gestionadas }
    : null

  const allItems: ProductoInventario[] = useMemo(() => sugerencia
    ? [...sugerencia.grupos_fijos.flatMap(g => g.productos), ...sugerencia.insumos_generales]
    : [], [sugerencia])

  const categorias = useMemo(
    () => ['todas', ...Array.from(new Set(allItems.map(i => i.categoria))).sort()],
    [allItems])

  // LA BASE de las cuentas: todo lo de la sede, ya recortado por categoría y por
  // búsqueda pero NO por estado. Las pastillas cuentan sobre esto y la lista se
  // recorta sobre esto, así que el número de una pastilla es exactamente la
  // cantidad de filas que se ven al tocarla — con o sin categoría puesta.
  const base = useMemo(() => allItems
    .filter(i => catFiltro === 'todas' || i.categoria === catFiltro)
    .filter(i => !busqueda || i.nombre.toLowerCase().includes(busqueda.toLowerCase())),
    [allItems, catFiltro, busqueda])

  // El orden no cambió: primero lo que no hay, después lo urgente, y así hasta
  // lo sano; dentro de cada escalón, alfabético. Lo urgente va PRIMERO y lo sano
  // se VE, que es lo que se pidió.
  const filtrados = useMemo(() => base
    .filter(i => pasaFiltro(i, filtro, venc))
    .sort((a, b) =>
      (ESTADO_ORDER[a.estado] ?? 5) - (ESTADO_ORDER[b.estado] ?? 5) ||
      a.nombre.localeCompare(b.nombre)
    ), [base, filtro, venc])

  // Una pasada por pastilla sobre la MISMA base y con el MISMO `pasaFiltro` que
  // recorta la lista. No hay una segunda cuenta que pueda desincronizarse.
  const cuentas = useMemo(() => {
    const m = {} as Record<FiltroId, number>
    for (const t of PASTILLAS) m[t.id] = base.filter(i => pasaFiltro(i, t.id, venc)).length
    return m
  }, [base, venc])

  const seleccionado = selId !== null ? allItems.find(i => i.producto_id === selId) ?? null : null

  // Se está viendo menos que la sede entera (por estado, por categoría o por
  // búsqueda). Es lo que decide si la línea de conteo ofrece volver a todo.
  const recortado = filtrados.length < allItems.length
  // La etiqueta nombra la causa REAL del recorte. Con solo una categoría elegida
  // el filtro de estado sigue en «Ver todo» —que no recorta nada— y nombrarlo a
  // él era señalar al inocente.
  const etiquetaFiltro = [
    filtro !== 'todos' ? FILTROS.find(f => f.id === filtro)?.label : null,
    catFiltro !== 'todas' ? `categoría ${catFiltro}` : null,
    busqueda.trim() ? `búsqueda «${busqueda.trim()}»` : null,
  ].filter(Boolean).join(' + ')

  const verTodo = () => { setBusqueda(''); setCatFiltro('todas'); setSp2({ estado: 'todos' }) }

  // No se inventa un flujo nuevo: /pedidos-admin ya arma la lista por proveedor
  // y el texto para WhatsApp. `?tab=pedidos` la abre en esa pestaña — sin eso el
  // link dejaría al dueño en «Solicitudes», que es otra pantalla.
  // La SEDE viaja también: el link salía pelado y Pedidos arrancaba en la sede
  // del usuario, así que mirando Palmetto se aterrizaba en Vida y el pedido se
  // armaba con el stock de la otra tienda.
  const irAPedido = () =>
    navigate(`/pedidos-admin?tab=pedidos&tienda_id=${tiendaId}`)

  return (
    <div className="space-y-3">
      {/* La hoja: blanca, como el resto del admin (pedido del dueño — la marca
          vive en los acentos, no en el fondo). El wrapper se queda porque las
          pastillas sticky necesitan un fondo que las respalde al scrollear. */}
      <div
        className={`space-y-2 transition-all rounded-2xl p-3 sm:p-4 ${
          seleccionado || verMinimos ? 'lg:mr-[420px]' : ''}`}
        style={{ background: MC.hoja }}>

        {/* LAS PASTILLAS: cada montón con su tamaño, y cada una es el filtro que
            lo muestra. Tocar la que está puesta vuelve a TODO. Una pastilla en
            cero no lleva a ningún lado: queda punteada y gris, fuera del barrido.
            Sticky, porque con 56 filas el filtro tiene que seguir al pulgar. */}
        {sugerencia && (
          <nav aria-label="Filtrar la lista"
            className="sticky top-0 z-20 -mx-3 px-3 sm:-mx-4 sm:px-4 py-1.5 flex gap-1.5 overflow-x-auto"
            style={{ background: MC.hoja }}>
            {PASTILLAS.map(t => {
              const n = cuentas[t.id] ?? 0
              const activa = filtro === t.id
              if (n === 0 && !activa) return (
                <span key={t.id} title={t.ayuda}
                  className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-dashed pl-2 pr-2.5 py-1 text-[11.5px]"
                  style={{ borderColor: MC.lineaFte, color: MC.tinta28 }}>
                  {t.corto} <b className="tabular-nums">0</b>
                </span>
              )
              return (
                <button key={t.id} title={t.ayuda} aria-pressed={activa}
                  onClick={() => setSp2({ estado: activa ? 'todos' : t.id })}
                  className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-l-[3px] pl-2 pr-2.5 py-1 text-[11.5px] font-semibold"
                  style={activa
                    ? { borderColor: MC.negro, borderLeftColor: t.c, background: MC.negro, color: MC.crema }
                    : { borderColor: MC.lineaFte, borderLeftColor: t.c, background: MC.papel, color: MC.negro }}>
                  {t.corto} <b className="tabular-nums" style={{ color: activa ? MC.crema : t.c }}>{n}</b>
                </button>
              )
            })}
          </nav>
        )}

        <div className="flex gap-2 flex-wrap items-center">
          {/* Misma piel que la lista: papel sobre crema, línea de la paleta. */}
          {/* 140 y no 180: a 390px el select de categorías mide ~190 y con 180
              acá la barra se partía en dos renglones — 38px menos de lista por
              un mínimo que nadie necesitaba. */}
          <div className="relative flex-1 min-w-[140px]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: MC.tinta28 }} />
            <input
              type="text" placeholder="Buscar producto…" value={busqueda}
              onChange={e => setBusqueda(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-sm rounded-xl focus:outline-none focus:ring-2"
              style={{ background: MC.papel, border: `1px solid ${MC.linea}`, color: MC.negro }}
            />
          </div>
          {/* Los N chips de categoría eran N botones siempre visibles. Un select
              dice lo mismo con un nodo y no crece con el catálogo. El filtro de
              ESTADO ya no es un select: son las pastillas, que además cuentan. */}
          <select value={catFiltro} onChange={e => setCatFiltro(e.target.value)}
            className="py-1.5 px-2.5 text-sm rounded-xl focus:outline-none focus:ring-2"
            style={{ background: MC.papel, border: `1px solid ${MC.linea}`, color: MC.tinta70 }}>
            {categorias.map(c => <option key={c} value={c}>{c === 'todas' ? 'Todas las categorías' : c}</option>)}
          </select>
        </div>

        {/* UNA línea: cuántos se están viendo, de cuántos, y dónde vive lo que ya
            no vive acá. El link al pedido es la única puerta que queda a la capa
            derivada (cuánto pedir, por proveedor): sin él, sacarla de esta
            pantalla sería perderla. */}
        {sugerencia && (
          <p className="text-[11.5px] flex flex-wrap items-baseline gap-x-1.5" style={{ color: MC.tinta45 }}>
            <span>
              <b className="tabular-nums" style={{ color: MC.tinta70 }}>{filtrados.length}</b>
              {recortado ? <> de {allItems.length} productos</> : filtrados.length === 1 ? ' producto en esta sede' : ' productos en esta sede'}
              {recortado && etiquetaFiltro ? ` · ${etiquetaFiltro}` : ''}.
            </span>
            {recortado && (
              <button onClick={verTodo} className="font-semibold underline" style={{ color: MC.terracota }}>
                Ver todo
              </button>
            )}
            <span className="ml-auto">
              Cuánto pedir y de qué proveedor:{' '}
              <button onClick={irAPedido} className="font-semibold underline" style={{ color: MC.terracota }}>
                Armar pedido →
              </button>
            </span>
          </p>
        )}

        {avisoUmbrales && (
          <p className="text-[11px] rounded-lg px-2.5 py-1.5 border"
            style={{ background: '#FBF5E3', borderColor: '#E7D8A9', color: '#7A5E10' }}>
            {/* El denominador es el inventario GESTIONADO de la sede entera
                (`filas_gestionadas` del diagnóstico), la misma regla —controla
                stock + entra al conteo— con la que /pedidos/sugerencia arma la
                lista (services/diagnostico_stock.py:233 y services/pedidos.py:109).
                Por eso este número y el de la pastilla «Sin mínimo» son el mismo
                mientras no haya categoría ni búsqueda puestas. */}
            <b>{avisoUmbrales.sin} de {avisoUmbrales.de}</b> sin mínimo cargado: {
              diag?.consumo?.motor_sin_datos
              ? 'no te avisa nada hasta que lleguen a cero.'
              : 'de esos solo avisa por los que tiene medido cuánto se gastan; del resto, nada hasta que lleguen a cero.'}{' '}
            <button onClick={() => { setSp2({ p: null, tab: null }); setVerMinimos(true) }}
              className="font-semibold underline">
              Que el sistema los proponga →
            </button>
          </p>
        )}

        {vencTruncado && (
          <p className="text-[11px] rounded-lg px-2.5 py-1.5 border"
            style={{ background: '#F6E7C9', borderColor: '#E7D2A5', color: MC.vence }}>
            El listado de lotes viene recortado (tope de 800). El aviso de
            vencimiento puede faltar en los productos más antiguos.
          </p>
        )}

        {/* Un mapa de vencimientos vacío es indistinguible de «no hay nada por
            vencer»: callarlo sería afirmar la buena noticia que no se sabe. */}
        {vencErr && (
          <p className="text-[11px] rounded-lg px-2.5 py-1.5 border"
            style={{ background: '#F6E7C9', borderColor: '#E7D2A5', color: MC.vence }}>
            No se pudo leer el listado de lotes: <b>no se sabe qué vence</b>. La
            pastilla «Se vence» y los avisos de las filas están incompletos hasta
            que vuelva a cargar.
          </p>
        )}

        {loading && <p className="text-sm text-center py-8 animate-pulse" style={{ color: MC.tinta45 }}>Cargando…</p>}

        {!loading && sugerencia && filtrados.length === 0 && (
          <p className="text-sm text-center py-6" style={{ color: MC.tinta45 }}>
            {busqueda.trim() ? <>Ningún producto se llama así.</> : <>Nada con este filtro.</>}{' '}
            <button onClick={verTodo} className="font-semibold underline" style={{ color: MC.terracota }}>
              Ver todo
            </button>
          </p>
        )}

        {/* La leyenda va UNA vez acá arriba en lugar de repetir la palabra en las
            56 filas. DERIVA de ESTADO_CFG —el mismo tono que pinta la regla
            izquierda de cada fila—, jamás un color tipeado a mano: una leyenda
            que no coincide con lo que explica es peor que no tenerla.
            Los anchos (w-[74px] / w-16, gap-x-2, pl-[15px] = 3px de regla + 12px
            de padding) son los MISMOS que los de ProductRow; si cambian allá,
            cambian acá o el título deja de estar sobre su columna. */}
        {!loading && filtrados.length > 0 && (
          <div className="pt-1">
            <p className="flex gap-x-3 gap-y-0.5 flex-wrap text-[10px] px-1" style={{ color: MC.tinta45 }}>
              {([['agotado', 'se acabó'], ['urgente', 'urgente'], ['pronto', 'pedir hoy'],
                 ['bajo', 'bajo'], ['ok', 'al día']] as const).map(([k, label]) => (
                <span key={k} className="inline-flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full" style={{ background: ESTADO_CFG[k].mc }} />{label}
                </span>
              ))}
              <span>🔔 la pidió una barista</span>
              <span>«en negativo» = falta registrar una entrada</span>
            </p>
            {/* Solo en escritorio: en el celular la fila son dos renglones y unos
                títulos de columna sobre un layout que ya no es una tabla serían
                un rótulo apuntando al lugar equivocado. */}
            <div className="hidden sm:flex items-center gap-x-2 pl-[15px] pr-3 pt-1 text-[10px] font-bold uppercase tracking-[.14em]"
              style={{ color: MC.tinta45 }}>
              <span className="flex-1 min-w-0">Producto</span>
              <span className="shrink-0 w-[74px] text-right" style={{ color: MC.tinta70 }}>Cuánto hay</span>
              <span className="shrink-0 w-16 text-right">Alcanza</span>
            </div>
          </div>
        )}

        {/* LA LISTA. Plana, entera, sin acordeón.

            El hairline fuerte marca el CAMBIO DE ESTADO: el orden es
            estado→alfabético, así que el alfabeto se reinicia varias veces
            adentro y sin esta línea alguien lee «Azúcar · 0» arriba y concluye
            que no hay, sin llegar al «Azucar a Granel · 3.466» doce filas más
            abajo. Cuesta un borde condicional, cero nodos. */}
        {!loading && filtrados.length > 0 && (
          <div className="rounded-xl border overflow-hidden" style={{ borderColor: MC.linea }}>
            {filtrados.map((p, i) => (
              <ProductRow
                key={p.producto_id}
                p={p}
                venc={venc[p.producto_id]}
                empaque={empaques.get(p.producto_id)}
                activo={selId === p.producto_id}
                corte={i > 0 && filtrados[i - 1].estado !== p.estado}
                onSelect={() => setSp2({ p: String(p.producto_id), tab: 'hoy' }, true)}
              />
            ))}
          </div>
        )}
      </div>

      {seleccionado && (
        <PanelProducto
          key={seleccionado.producto_id}
          producto={seleccionado}
          tiendaId={tiendaId}
          tab={tab}
          onTab={t => setSp2({ tab: t })}
          onClose={() => setSp2({ p: null, tab: null })}
          sinConsumidor={sinConsumidor.has(seleccionado.producto_id)}
          negativo={negativosPorProducto.get(seleccionado.producto_id)}
          recetasSospechosas={sospechaPorInsumo.get(seleccionado.producto_id) ?? []}
          onSaved={() => { cargar(); setDiagTick(t => t + 1) }}
        />
      )}

      {verMinimos && (
        <PanelMinimos
          tiendaId={tiendaId}
          onClose={() => setVerMinimos(false)}
          // Mismo par que el panel de producto: la lista trae el `stock_minimo`
          // que acaba de cambiar y el diagnóstico trae la cuenta de «cuántos sin
          // mínimo». Refrescar uno solo dejaría el aviso de arriba contradiciendo
          // a las filas de abajo.
          onAplicado={() => { cargar(); setDiagTick(t => t + 1) }}
        />
      )}
    </div>
  )
}

// ─── Rotación mode ────────────────────────────────────────────────────────────

function ModoRotacion({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde]             = useState(isoHace(30))
  const [hasta, setHasta]             = useState(isoHoy())
  const [filas, setFilas]             = useState<FilaRotacion[] | null>(null)
  const [resumen, setResumen]         = useState<ResumenRotacion | null>(null)
  const [estadoFiltro, setEstadoFiltro] = useState('todos')
  const [loading, setLoading]         = useState(false)

  useEffect(() => {
    setLoading(true)
    api.get('/informes/rotacion', {
      params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta },
    })
      .then(r => { setFilas(r.data.filas); setResumen(r.data.resumen); setEstadoFiltro('todos') })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tiendaId, desde, hasta])

  const visibles = filas?.filter(f => estadoFiltro === 'todos' || f.estado === estadoFiltro) ?? []

  const exportar = () => {
    if (!filas) return
    exportarExcel(`rotacion_${desde}_${hasta}`,
      ['Producto', 'Unidad', 'Stock actual', 'Stock mínimo', 'Entradas', 'Salidas', 'Rotación', 'Estado'],
      filas.map(f => [f.producto, f.unidad, f.stock_actual, f.stock_minimo,
        f.entradas, f.salidas, f.rotacion ?? '', f.estado]))
  }

  return (
    <div className="space-y-4">
      {/* Date range */}
      <div className="flex gap-3 items-center flex-wrap">
        <div className="flex items-center gap-1.5">
          <label className="text-xs text-gray-500">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300" />
        </div>
        <div className="flex items-center gap-1.5">
          <label className="text-xs text-gray-500">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300" />
        </div>
        {filas && filas.length > 0 && (
          <button onClick={exportar}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold text-white"
            style={{ background: 'oklch(48% 0.15 155)' }}>
            <Download size={14} /> Excel
          </button>
        )}
      </div>

      {/* Stats cards */}
      {resumen && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { key: 'activos',        label: 'Activos',        val: resumen.activos,        num: 'text-green-700'  },
            { key: 'estancados',     label: 'Estancados',     val: resumen.estancados,     num: resumen.estancados > 0 ? 'text-orange-600' : 'text-gray-700' },
            { key: 'sin_movimiento', label: 'Sin movimiento', val: resumen.sin_movimiento, num: 'text-gray-500'   },
            { key: 'bajo_minimo',    label: 'Bajo mínimo',    val: resumen.bajo_minimo,    num: resumen.bajo_minimo > 0 ? 'text-red-600' : 'text-gray-700' },
          ].map(s => (
            <button key={s.key}
              onClick={() => setEstadoFiltro(estadoFiltro === s.key ? 'todos' : s.key)}
              className={`bg-white border rounded-xl p-3 text-center transition-all ${
                estadoFiltro === s.key ? 'border-amber-400 ring-1 ring-amber-200' : 'border-gray-200'
              }`}
            >
              <p className="text-xs font-semibold text-gray-400">{s.label}</p>
              <p className={`text-xl font-bold font-mono mt-0.5 ${s.num}`}>{s.val}</p>
            </button>
          ))}
        </div>
      )}

      {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando…</p>}

      {!loading && filas !== null && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-400 uppercase">Producto</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Stock</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Entradas</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Salidas</th>
                  <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Rotación</th>
                  <th className="px-3 py-2.5"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {visibles.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center text-sm text-gray-400 py-6">
                      Sin productos con este filtro.
                    </td>
                  </tr>
                )}
                {visibles.map(f => {
                  const cfg = ROT_CFG[f.estado] ?? ROT_CFG.sin_movimiento
                  return (
                    <tr key={f.producto_id} className="hover:bg-gray-50">
                      <td className="px-4 py-2.5">
                        <p className="font-medium text-gray-800">{f.producto}</p>
                        <p className="text-xs text-gray-400">{f.unidad}</p>
                      </td>
                      <td className={`px-3 py-2.5 text-right font-mono font-bold text-sm ${f.alerta_min ? 'text-red-600' : 'text-gray-700'}`}>
                        {f.stock_actual}
                        {f.alerta_min && <AlertTriangle size={10} className="inline ml-1 text-red-500" />}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-sm text-green-700">{f.entradas}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-sm text-blue-700">{f.salidas}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-sm text-gray-600">
                        {f.rotacion !== null ? `${f.rotacion}x` : '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        <span className="text-xs px-1.5 py-0.5 rounded font-semibold"
                          style={{ background: cfg.bg, color: cfg.text }}>
                          {cfg.label}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!loading && filas !== null && filas.length === 0 && (
        <p className="text-sm text-gray-400 text-center py-6">Sin movimientos en el período.</p>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ControlInventario() {
  const { user } = useAuth()
  const [sedes, setSedes]     = useState<{ id: number; nombre: string }[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)
  const [modo, setModo]       = useState<'stock' | 'rotacion'>('stock')

  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (!tiendaId && r.data.length > 0) setTiendaId(r.data[0].id)
    }).catch(() => {})
  }, [])

  return (
    <div className="space-y-4 pb-10">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Layers size={18} className="text-forest" />
          <h1 className="text-lg font-bold text-gray-800">Inventario</h1>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {sedes.length > 1 && (
            <div className="flex gap-1">
              {sedes.map(s => (
                <button key={s.id} onClick={() => setTiendaId(s.id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    tiendaId === s.id
                      ? 'bg-forest text-white'
                      : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}>
                  {s.nombre}
                </button>
              ))}
            </div>
          )}

          <div className="flex bg-gray-100 rounded-xl p-0.5">
            {([
              { id: 'stock',    label: 'Stock',    icon: <Package   size={13} /> },
              { id: 'rotacion', label: 'Rotación', icon: <RotateCcw size={13} /> },
            ] as const).map(m => (
              <button
                key={m.id}
                onClick={() => setModo(m.id)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  modo === m.id
                    ? 'bg-white text-gray-800 shadow-sm'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {m.icon} {m.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {tiendaId !== null && (
        modo === 'stock'
          ? <ModoStock    tiendaId={tiendaId} />
          : <ModoRotacion tiendaId={tiendaId} />
      )}
    </div>
  )
}
