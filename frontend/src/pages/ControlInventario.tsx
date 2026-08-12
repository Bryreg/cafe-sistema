import { useState, useEffect, useCallback, useMemo, Fragment } from 'react'
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
  terracota: '#B5622A',
  oliva:     '#4B5A3E',

  papel:     '#FBF8F0',
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

// El filtro de la lista. `atencion` es el DEFAULT: la pantalla abre mostrando lo
// que hay que resolver, no el catálogo entero. Las 4 tarjetas de arriba escriben
// en este mismo estado — son atajos al filtro, no otra cosa.
const FILTROS = [
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
  { id: 'todos',    label: 'Ver todo' },
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

// ─── La cola de decisiones: agrupar por VERBO ─────────────────────────────────
//
// PRIORIDAD DE ASIGNACIÓN (no es el orden de lectura: es el orden de las
// preguntas). Cada producto cae en el PRIMER grupo cuya condición cumple, así
// que vive en EXACTAMENTE UNO y los contadores de los encabezados suman el
// total. Lo transversal —un lote por vencer, la campana de una barista— NO
// abre grupo propio: viaja como chip dentro de la fila del grupo que le tocó.
//
//   1 investiga  stock < 0                          → falta registrar una entrada
//   2 prepara    accion==='preparar' && estado!=='ok'→ se hace en la barra
//   3 compra     (agotado|urgente) && sugerida > 0  → comprar, y sabemos cuánto
//   4 ojo        agotado (sin cantidad)             → comprar, la cantidad la ponés vos
//   5 pronto     estado !== 'ok'                    → pronto/bajo: todavía hay
//   6 vence      hay lote por vencer (estado 'ok')  → no se pide: se vende o se saca
//   7 aldia      resto
//
// POR QUÉ CIERRA, y contra qué:
//  · 1 se lleva todo stock<0. Después de 1, «agotado» ⇒ stock === 0.
//  · 3 y 4 se reparten TODO lo agotado que quede (4 no tiene condición extra).
//  · Un `urgente` siempre trae cantidad > 0 (services/pedidos.py: la cantidad es
//    ceil(consumo*(lead+colchón) − stock) y urgente exige stock ≤ consumo*lead,
//    con colchón ≥ 4), así que 3 se lo lleva y 5 no hereda huérfanos.
//  · 5 se lleva el resto de `estado !== 'ok'`. ⇒ grupos 1..5 = {estado !== 'ok'}.
//  · 6 y 7 parten lo `ok` según tenga o no lote por vencer.
//  ⇒ 1..6 = {estado !== 'ok' || venc} = EXACTAMENTE `pasaFiltro(·, 'atencion')`,
//    y 1..7 = la lista entera. Los mismos conjuntos que cuentan las tarjetas de
//    siempre: total_urgentes = |agotado|+|urgente| = |1|+|2 agotados|+|3|+|4|,
//    total_pronto+total_bajo = el resto de 5, totalVence = |6| + los que llevan
//    el chip dentro de 1..5.
type GrupoId = 'investiga' | 'prepara' | 'compra' | 'pronto' | 'vence' | 'ojo' | 'aldia'

function grupoDe(p: ProductoInventario, venc: MapaVenc): GrupoId {
  if (p.stock_actual < 0) return 'investiga'
  if (p.accion === 'preparar' && p.estado !== 'ok') return 'prepara'
  if ((p.estado === 'agotado' || p.estado === 'urgente') && p.cantidad_sugerida > 0) return 'compra'
  if (p.estado === 'agotado') return 'ojo'
  if (p.estado !== 'ok') return 'pronto'
  if (venc[p.producto_id]) return 'vence'
  return 'aldia'
}

// Orden de LECTURA de los grupos, que no es el de asignación: primero lo que
// cambia de verbo (investigar, preparar), después lo que se compra.
const GRUPOS: { id: GrupoId; h: string; sub: string; c: string; corto: string }[] = [
  { id: 'investiga', corto: 'Investigá',  h: 'Investigá',
    // La MISMA frase que ya usaba la franja roja: es aritmética (salidas >
    // entradas registradas), no un diagnóstico. La causa de cada uno la da el
    // panel del producto, que es el único que la tiene.
    // Sobrevive entera la franja roja que había arriba de la lista: la frase
    // aritmética, la consecuencia sobre «Pedir» y el destino (el panel del
    // producto, que es el único que tiene la causa de cada uno).
    sub: 'El sistema descontó más de lo que se registró que entró: mientras el stock esté mal, lo que dice «Pedir» también. Acá no se compra primero. Tocá cada producto y el panel te dice qué falta cargar.',
    c: MC.negativo },
  { id: 'prepara',   corto: 'Prepará',    h: 'Prepará en barra',
    sub: 'Esto no se compra: se hace acá con la receta.', c: MC.oliva },
  { id: 'compra',    corto: 'Compra hoy', h: 'Compra hoy',
    sub: 'Se acabó o no llega a la próxima entrega, y el sistema sabe cuánto pedir.', c: ESTADO_CFG.agotado.mc },
  // El sub cubre los DOS poblamientos del grupo: «pronto» (no llega a la próxima
  // entrega) y «bajo» (quedó debajo del mínimo — que por definición del motor
  // aparece justo cuando NO hay consumo medido o hay cobertura de sobra, o sea
  // cuando «se acaba antes del próximo pedido» sería falso).
  { id: 'pronto',    corto: 'Pedir pronto', h: 'Pedir pronto',
    sub: 'Todavía hay, pero el sistema lo marcó: o no llega a la próxima entrega, o quedó por debajo del mínimo.', c: ESTADO_CFG.pronto.mc },
  { id: 'vence',     corto: 'Se vence',   h: 'Se vence',
    sub: 'Hay stock, pero tiene fecha: vendelo o bajale el precio. No se pide.', c: MC.vence },
  { id: 'ojo',       corto: 'A ojo',      h: 'A ojo',
    sub: 'Se acabó y el sistema no tiene mínimo ni consumo medido: la cantidad la ponés vos.', c: ESTADO_CFG.bajo.mc },
  { id: 'aldia',     corto: 'Al día',     h: 'Al día',
    sub: 'Sin novedades. Nada que decidir hoy.', c: ESTADO_CFG.ok.mc },
]

// Los grupos cuyos productos van al pedido del proveedor. `investiga` queda
// FUERA a propósito (su acción es registrar, no comprar) y `prepara` también
// (nadie lo vende). `ojo` sí entra: hay que comprarlo, lo que falta es el
// número — y eso lo dice su grupo, no lo esconde.
const GRUPOS_PEDIDO: GrupoId[] = ['compra', 'ojo', 'pronto']

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

// El «tachar» de cada fila: un checklist VISUAL de la jornada, no un dato del
// negocio. Vive en localStorage por sede y por día —mañana la lista es otra— y
// no toca el backend. Si localStorage no está disponible (modo privado, cuota),
// se degrada a estado en memoria: perder los tachados es molesto, romper la
// pantalla no.
const TACHE_PREFIJO = 'inv:tachados:'
function useTachados(tiendaId: number) {
  const clave = `${TACHE_PREFIJO}${tiendaId}:${isoHoy()}`
  const [ids, setIds] = useState<Set<number>>(new Set())

  useEffect(() => {
    let leidos: number[] = []
    try {
      leidos = JSON.parse(localStorage.getItem(clave) || '[]')
      // Barrido de DÍAS viejos solamente. La versión anterior borraba toda clave
      // distinta de la actual — incluida la de LA OTRA SEDE de hoy: cambiabas de
      // Vida a Palmetto en el header y el checklist ya marcado de Vida
      // desaparecía en silencio. El sufijo de fecha decide, no la clave entera.
      const hoy = isoHoy()
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const k = localStorage.key(i)
        if (k && k.startsWith(TACHE_PREFIJO) && !k.endsWith(`:${hoy}`)) localStorage.removeItem(k)
      }
    } catch { /* sin localStorage: solo memoria */ }
    setIds(new Set(Array.isArray(leidos) ? leidos : []))
  }, [clave])

  const alternar = useCallback((id: number) => {
    setIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      try { localStorage.setItem(clave, JSON.stringify([...next])) } catch { /* idem */ }
      return next
    })
  }, [clave])

  return { tachados: ids, alternar }
}

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

// Fila TONTA a propósito: sin estado propio, sin fetch, sin acordeón. Todo lo que
// antes colgaba de acá (13 useState + la ficha) vive ahora en el panel lateral,
// que se monta UNA sola vez para el producto seleccionado.
//
// La fila es un <div> con DOS botones —tachar y abrir— y no un botón con un
// control adentro: un elemento interactivo dentro de otro es HTML inválido y
// deja el tache fuera del teclado. Cuesta un nodo por fila y los dos controles
// quedan accesibles.
//
// El color de estado ya no es un punto sino la REGLA izquierda de la fila, y
// sale del mismo ESTADO_CFG que la leyenda: si divergieran, la leyenda dejaría
// de explicar lo que se ve. Una fila sana la baja al 45% y queda casi
// monocroma; el color se gasta solo donde hay señal.
function ProductRow({ p, venc, activo, tachado, pedirDespues, onSelect, onTachar }: {
  p: ProductoInventario
  venc?: VencInfo
  activo: boolean
  tachado: boolean
  pedirDespues?: boolean
  onSelect: () => void
  onTachar: () => void
}) {
  const cfg = ESTADO_CFG[p.estado] ?? ESTADO_CFG.ok
  const enNegativo = p.stock_actual < 0
  // El stock se pinta en rojo también cuando está en cero o menos. Antes dependía
  // solo de los días restantes, que son NULL sin consumo medido: un producto en 0
  // sin salidas registradas mostraba su cero en gris.
  const critico = p.stock_actual <= 0 ||
    (p.dias_restantes !== null && p.dias_restantes <= p.lead_time_dias)
  // Lo que se arma con receta en la barra: la columna «Pedir» le cambia el verbo,
  // no el estado. `hayQueReponer` evita el otro extremo: un preparable con stock
  // de sobra no tiene por qué gritar «preparar» en la lista.
  const esPreparable = p.accion === 'preparar'
  const hayQueReponer = p.cantidad_sugerida > 0 || p.stock_actual <= 0
  const sano = p.estado === 'ok'
  const caps = esCaps(p.nombre)

  return (
    <div
      className="flex items-stretch border-t transition-colors"
      style={{
        borderTopColor: MC.linea,
        borderLeft: `3px solid ${cfg.mc}`,
        background: activo ? '#F4EDDB' : MC.papel,
        opacity: tachado ? 0.45 : 1,
      }}
    >
      {/* El tache: checklist de la jornada, local y del día. El disco relleno
          más el tachado del texto dicen «ya lo resolví» sin gastar un ícono. */}
      <button
        onClick={onTachar}
        aria-pressed={tachado}
        title={tachado ? 'Ya lo resolviste — tocá para desmarcar' : 'Marcar como resuelto (solo para vos, solo hoy)'}
        className={`shrink-0 w-9 flex items-center justify-center before:content-[''] before:w-[17px] before:h-[17px] before:rounded-full before:border-[1.5px] ${
          tachado ? 'before:bg-[#0D0C0B] before:border-[#0D0C0B]' : 'before:border-[#D2C7AE] hover:before:border-[#0D0C0B]'
        }`}
      />
      <button
        onClick={onSelect}
        title={`${p.categoria}${p.proveedor ? ` · ${p.proveedor}` : ''}`}
        // En el celular la fila son DOS renglones: el nombre entero arriba y la
        // evidencia abajo. En una sola línea, con los chips y las tres columnas
        // peleando por 390px, el nombre —lo único que el dueño está buscando—
        // se comía en «MEZCLA GRAN…». Desde `sm` vuelve a ser una sola línea.
        className={`flex-1 min-w-0 flex flex-wrap sm:flex-nowrap items-center gap-x-2.5 gap-y-1 text-left py-2 pr-3 hover:bg-[#F4EDDB] ${tachado ? 'line-through decoration-[1.5px]' : ''}`}
      >
        <span
          className={`w-full sm:w-auto sm:flex-1 min-w-0 truncate ${caps ? 'text-[13px] tracking-[0.012em]' : 'text-sm'} ${sano ? 'font-medium' : 'font-semibold'}`}
          style={{ color: MC.negro }}
        >
          {p.barista_alerto && '🔔 '}{p.nombre}
        </span>
        {/* Un cero y un -0,2 se pintaban los dos en rojo con el mismo punto rojo, y
            son dos problemas distintos con dos acciones distintas. El signo menos
            solo no alcanza: es un píxel. El chip usa la MISMA palabra que el
            encabezado de su grupo y que el filtro, que es donde se explica qué
            significa — repetir la explicación en cada fila haría de la lista un
            párrafo. */}
        {enNegativo && (
          <span className="shrink-0 text-[10px] font-bold uppercase tracking-[.07em] px-1.5 py-0.5 rounded"
            style={{ color: MC.negativo, boxShadow: `inset 0 0 0 1.4px ${MC.negativo}` }}>
            en negativo
          </span>
        )}
        {/* «⚠ 15-08» solo se explicaba en un `title`, que en el celular no existe.
            El verbo cabe en el mismo nodo. Vive acá dentro y no como grupo
            aparte: un lote por vencer le puede pasar a un producto de cualquier
            grupo, y duplicarlo rompería la cuenta de los encabezados. */}
        {venc && (
          <span className="shrink-0 text-[10px] font-bold uppercase tracking-[.07em] px-1.5 py-0.5 rounded tabular-nums"
            style={{
              color: venc.estado === 'vencido' ? ESTADO_CFG.agotado.mc : MC.vence,
              background: '#F6E7C9',
            }}>
            {venc.estado === 'vencido' ? 'venció' : 'vence'} {ddmm(venc.fecha)}
          </span>
        )}
        <span className="shrink-0 w-auto sm:w-[74px] text-right text-sm font-semibold tabular-nums"
          style={{ color: critico ? ESTADO_CFG.agotado.mc : (sano ? MC.tinta70 : MC.negro) }}>
          {num(p.stock_actual)}
          <span className="font-normal text-[11px]" style={{ color: MC.tinta45 }}> {p.unidad}</span>
        </span>
        {/* «se acabó» ya no se esconde en el celular: era justo el rótulo que
            distingue el cero del negativo, y en el renglón de evidencia cabe. */}
        <span className="shrink-0 w-auto sm:w-16 text-right text-[11px] tabular-nums"
          style={{ color: sano ? MC.tinta45 : MC.tinta70 }}>
          {alcanzaLabel(p)}
        </span>
        {/* La celda va SIEMPRE, aunque quede vacía: es una columna con encabezado y
            si desapareciera en las filas sin sugerencia, el número de la fila de
            abajo se correría debajo del título «Pedir». El hairline de la
            izquierda la aísla: es la columna de la que sale el pedido.

            El caso que NO puede quedar vacío: el producto que YA SE ACABÓ y sin
            sugerencia. «Azúcar 0 g | (vacío)» bajo el título «Pedir» se lee como
            «no compres azúcar», y la verdad es que el sistema no tiene ni mínimo
            ni consumo medido para calcular cuánto. «a ojo» es eso, honesto y en
            castellano: comprá, pero la cantidad la ponés vos.

            El preparable (la mezcla de granizado) tampoco puede mostrar un número
            a secas: bajo el título «Pedir» se lee como una orden de compra a un
            proveedor que no existe. La falta ES real, así que esconderlo sería
            peor. Va el VERBO en el mismo nodo —la fila tiene presupuesto de uno— y
            la cantidad completa espera en el panel, que es donde se decide. */}
        <span className={`shrink-0 ml-auto sm:ml-0 w-auto sm:w-[62px] pl-2.5 text-right tabular-nums border-l leading-tight ${
          pedirDespues ? 'text-[10px]' : 'text-[11px]'}`}
          style={{
            borderLeftColor: MC.linea,
            color: pedirDespues ? MC.tinta45
              : hayQueReponer && esPreparable ? MC.oliva
              : p.cantidad_sugerida > 0 ? MC.terracota : MC.tinta28,
            fontWeight: !pedirDespues && ((hayQueReponer && esPreparable) || p.cantidad_sugerida > 0) ? 700 : 400,
          }}>
          {esPreparable ? (hayQueReponer ? 'preparar' : '')
            : p.cantidad_sugerida > 0 ? (pedirDespues ? `después ${num(p.cantidad_sugerida)}` : num(p.cantidad_sugerida))
            : p.stock_actual <= 0 ? 'a ojo' : ''}
        </span>
      </button>
    </div>
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

function ModoStock({ tiendaId }: { tiendaId: number }) {
  const [sugerencia, setSugerencia] = useState<Sugerencia | null>(null)
  const [loading, setLoading]       = useState(false)
  const [busqueda, setBusqueda]     = useState('')
  const [catFiltro, setCatFiltro]   = useState('todas')
  // El panel de mínimos propuestos. Vive en estado local y NO en la URL: no es
  // un deep-link (la propuesta depende del consumo de HOY) y compartir un link
  // que abre una pantalla de escritura no es lo que nadie quiere compartir.
  const [verMinimos, setVerMinimos] = useState(false)
  // «Al día» arranca plegado. Es estado de la vista, no del negocio: no va a la
  // URL ni a localStorage.
  const [verAlDia, setVerAlDia] = useState(false)
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
  const filtro: FiltroId = ES_FILTRO(rawEstado) ? rawEstado : 'atencion'
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
  // "no hay nada por vencer". Sin esta bandera la tarjeta naranja afirmaba
  // «Se vence: 0» y desaparecían todos los ⚠ de la lista a partir de un error de
  // red. Ausencia de dato no es buena noticia.
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
  // forma de revisarse en lote. Una línea que ofrece terminar lo empezado no es
  // ruido — ruido era repetir el número cuando ya no había nada que hacer, y eso
  // sigue cubierto: con todos cargados, el aviso no sale.
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

  // Ya no hay contadores sueltos de «negativos» ni de «se vence»: los cuenta la
  // agrupación de más abajo, sobre la MISMA lista que se renderiza. El negativo
  // en particular NO sale de `diag.negativos` —ese payload no aplica la regla de
  // gestionados, corta en 200 filas y puede no haber cargado—, sino de
  // `stock_actual < 0` de la propia lista, así que el número y las filas no
  // pueden discrepar ni siquiera con el diagnóstico caído.
  const filtrados = useMemo(() => allItems
    // El filtro por DEFECTO ya no recorta: con la lista agrupada, «Al día» es un
    // grupo plegado al final, así que los productos sanos siguen contados, siguen
    // sumando al total de la sede y están a un toque — en vez de desaparecer y
    // dejar al dueño sin forma de saber cuántos eran. Los otros ocho filtros
    // (los deep links `?estado=`) siguen recortando exactamente igual que antes.
    .filter(i => filtro === 'atencion' || pasaFiltro(i, filtro, venc))
    .filter(i => catFiltro === 'todas' || i.categoria === catFiltro)
    .filter(i => !busqueda || i.nombre.toLowerCase().includes(busqueda.toLowerCase()))
    .sort((a, b) =>
      (ESTADO_ORDER[a.estado] ?? 5) - (ESTADO_ORDER[b.estado] ?? 5) ||
      a.nombre.localeCompare(b.nombre)
    ), [allItems, filtro, venc, catFiltro, busqueda])

  const seleccionado = selId !== null ? allItems.find(i => i.producto_id === selId) ?? null : null

  // El checklist de la jornada. Local, por sede y por día.
  const { tachados, alternar } = useTachados(tiendaId)

  // Buscar IGNORA los grupos: cuando el dueño tipea un nombre ya sabe qué
  // quiere, y partir cuatro resultados en cuatro encabezados es ruido. La
  // pantalla cae a lista plana y lo dice.
  const buscando = busqueda.trim().length > 0

  // UNA sola pasada de agrupación sobre lo que se está mostrando. El titular,
  // las pastillas de salto, los encabezados y el botón de pedido leen TODOS de
  // acá: no hay un segundo cálculo que pueda desincronizarse.
  const grupos = useMemo(() => {
    const m = new Map<GrupoId, ProductoInventario[]>(GRUPOS.map(g => [g.id, []]))
    for (const p of filtrados) m.get(grupoDe(p, venc))!.push(p)
    return m
  }, [filtrados, venc])
  const nG = (id: GrupoId) => grupos.get(id)!.length

  // Los que van al pedido del proveedor, menos los que ya tachaste. Es EL número
  // del botón: uno solo, y el mismo en el celular y en el escritorio.
  const paraPedir = useMemo(
    () => GRUPOS_PEDIDO.flatMap(id => grupos.get(id)!).filter(p => !tachados.has(p.producto_id)),
    [grupos, tachados])

  // El titular: la jornada en una línea. Los números salen de los grupos de
  // arriba, nunca de una cuenta paralela. «comprar» junta `compra` y `ojo`
  // porque los dos se compran hoy — lo que los separa es si el sistema sabe
  // cuánto, y eso lo dice cada grupo abajo.
  const verbos = [
    { n: nG('investiga'), t: 'para investigar', c: MC.negativo,   id: 'investiga' as GrupoId },
    { n: nG('prepara'),   t: 'para preparar',   c: MC.oliva,      id: 'prepara'   as GrupoId },
    { n: nG('compra') + nG('ojo'), t: 'para comprar', c: MC.terracota, id: 'compra' as GrupoId },
  ].filter(v => v.n > 0)
  // Vencimientos: el TOTAL de productos con lote por vencer, no solo los del
  // grupo «Se vence». Cuando todos los que vencen viven en otros grupos (porque
  // además hay que comprarlos o investigarlos), el grupo queda en 0, no se
  // dibuja, y sin esta suma la pantalla omitía los vencimientos por completo
  // mientras las filas mostraban sus chips «vence dd-mm».
  const totalConLote = filtrados.filter(i => venc[i.producto_id]).length
  const resto = [
    nG('pronto') > 0 ? `${nG('pronto')} para pedir pronto` : null,
    vencErr ? 'no se sabe qué vence' : totalConLote > 0 ? `${totalConLote} con lote por vencer` : null,
    nG('aldia') > 0 ? `${nG('aldia')} al día` : null,
  ].filter(Boolean).join(' · ')

  // Con un filtro puesto, la pantalla NO está contando el día: está contando un
  // recorte. Decir «Hoy: 2 para investigar» cuando hay 3 y uno está filtrado es
  // exactamente la clase de número que miente por omisión.
  // Lo que decide el titular no es «hay un filtro puesto» sino «se está viendo
  // menos que la sede entera»: con «Ver todo» hay filtro y sin embargo los
  // números SÍ son los del día, así que ahí el titular vuelve a decir «Hoy».
  const filtroActivo = filtrados.length < allItems.length
  // La etiqueta nombra la causa REAL del recorte. Con solo una categoría elegida
  // el filtro de estado sigue en «atención» —que no recorta nada— y nombrarlo a
  // él era señalar al inocente: el dueño leía «Necesita atención: 4 de 56» sin
  // forma de saber que el recorte era la categoría (o la búsqueda).
  const etiquetaFiltro = [
    filtro !== 'atencion' ? FILTROS.find(f => f.id === filtro)?.label : null,
    catFiltro !== 'todas' ? `categoría ${catFiltro}` : null,
    busqueda.trim() ? `búsqueda «${busqueda.trim()}»` : null,
  ].filter(Boolean).join(' + ') || (FILTROS.find(f => f.id === filtro)?.label ?? '')

  // Cuántos productos con lote por vencer viven en OTRO grupo (llevan el chip en
  // la fila). Sin esta línea, «Se vence 1» contradiría al viejo contador de 4.
  const venceEnOtros = totalConLote - nG('vence')

  // El botón del pedido cuelga del PRIMER grupo que aporta productos al pedido.
  const grupoConBoton = GRUPOS_PEDIDO.find(id => nG(id) > 0)
  // No se inventa un flujo nuevo: /pedidos-admin ya arma la lista por proveedor
  // y el texto para WhatsApp. `?tab=pedidos` la abre en esa pestaña — sin eso el
  // botón dejaba al dueño en «Solicitudes», que es otra pantalla.
  const irAPedido = () => navigate('/pedidos-admin?tab=pedidos')

  const fila = (p: ProductoInventario, g?: GrupoId) => (
    <ProductRow
      key={p.producto_id}
      p={p}
      venc={venc[p.producto_id]}
      activo={selId === p.producto_id}
      tachado={tachados.has(p.producto_id)}
      // En «Investigá» la cantidad sugerida NO es la acción de hoy: primero se
      // registra la entrada que falta, porque mientras el stock esté mal ese
      // número también lo está. Se muestra igual —esconderlo sería peor— pero
      // en letra chica y con el «después» adelante.
      pedirDespues={g === 'investiga'}
      onSelect={() => setSp2({ p: String(p.producto_id), tab: 'hoy' }, true)}
      onTachar={() => alternar(p.producto_id)}
    />
  )

  // El aviso de umbrales, extraído para poder colgarlo del grupo «A ojo» o —si
  // ese grupo hoy está vacío— dejarlo arriba. Un aviso que se puede evaporar
  // según el filtro no es un aviso.
  const avisoMinimos = avisoUmbrales && (
    <p className="text-[11px] rounded-lg px-2.5 py-1.5 border"
      style={{ background: '#FBF5E3', borderColor: '#E7D8A9', color: '#7A5E10' }}>
      <b>{avisoUmbrales.sin} de {avisoUmbrales.de}</b> productos no tienen mínimo
      cargado: {diag?.consumo?.motor_sin_datos
        ? 'el sistema no te avisa nada hasta que llegan a cero.'
        : 'de esos, el sistema solo avisa por los que tiene medido cuánto se gastan; del resto no te avisa nada hasta que llegan a cero.'}{' '}
      <button onClick={() => { setSp2({ p: null, tab: null }); setVerMinimos(true) }}
        className="font-semibold underline">
        El sistema puede proponértelos según lo que se gastó. Revisar →
      </button>
      {filtro !== 'sinmin' && (
        <>
          {' · '}
          <button onClick={() => setSp2({ estado: 'sinmin' })} className="font-semibold underline">
            Verlos uno por uno
          </button>
        </>
      )}
    </p>
  )

  return (
    <div className="space-y-3">
      {/* La hoja de papel crema: el fondo de marca vive acá adentro y no en el
          <body>, para no repintar el resto del admin desde una sola pantalla. */}
      <div
        className={`space-y-3 transition-all rounded-2xl p-3 sm:p-4 pb-20 sm:pb-4 ${
          seleccionado || verMinimos ? 'lg:mr-[420px]' : ''}`}
        style={{ background: MC.crema }}>
        {/* EL TITULAR: la jornada en una línea, con los números REALES de los
            grupos de abajo. Reemplaza la franja de cuatro tarjetas, que eran
            cuatro sustantivos («Urgente», «Pedir hoy») sin decir qué hacer con
            ellos y que además no sumaban entre sí. Los tres verbos que quedan
            SÍ suman con la segunda línea: todo producto de la sede está contado
            una vez entre las dos. */}
        {sugerencia && !buscando && (
          <div>
            <p className="text-[19px] sm:text-[23px] font-semibold leading-tight tracking-[-.015em]"
              style={{ color: MC.negro }}>
              {verbos.length === 0
                // Sin urgencias pero CON «pedir pronto», el titular no puede
                // negar la compra: a 500px el botón dice «Armar pedido · N» y
                // dos afirmaciones contradictorias en la misma pantalla es el
                // defecto que venimos matando hace nueve rondas.
                ? (filtroActivo ? 'Nada para investigar, preparar ni comprar con este filtro.'
                   : nG('pronto') > 0 ? 'Hoy no hay urgencias: solo lo que conviene pedir pronto.'
                   : 'Hoy no hay nada que comprar ni investigar.')
                : <>{filtroActivo ? 'Con este filtro:' : 'Hoy:'} {verbos.map((v, i) => (
                    // Fragment y no <span>: el separador no necesita un nodo propio.
                    <Fragment key={v.t}>
                      {i > 0 && ' · '}
                      <a href={`#g-${v.id}`} className="tabular-nums" style={{ color: v.c }}>{v.n} {v.t}</a>
                    </Fragment>
                  ))}.</>}
            </p>
            {resto && (
              <p className="text-[12px] mt-1" style={{ color: MC.tinta45 }}>
                {resto}{filtroActivo ? '' : ` · ${allItems.length} productos en la sede`}.
              </p>
            )}
            {filtroActivo && (
              <p className="text-[12px] mt-1" style={{ color: MC.tinta45 }}>
                Filtro «{etiquetaFiltro}»: <b className="tabular-nums" style={{ color: MC.tinta70 }}>{filtrados.length}</b> de {allItems.length} productos.{' '}
                {/* «Ver el día completo» deshace TODO recorte — estado, categoría
                    y búsqueda. Antes solo escribía ?estado=atencion (el valor que
                    ya estaba activo): un botón muerto justo donde el dueño pedía
                    volver a ver todo. */}
                <button onClick={() => { setBusqueda(''); setCatFiltro('todas'); setSp2({ estado: 'atencion' }) }}
                  className="font-semibold underline" style={{ color: MC.terracota }}>
                  Ver el día completo
                </button>
              </p>
            )}
          </div>
        )}

        {/* PASTILLAS DE SALTO — son las viejas tarjetas: mismo rol (ver el
            tamaño de cada montón de un vistazo), pero ahora llevan al grupo en
            vez de recortar la lista, así que ninguna esconde a las demás. Un
            grupo VACÍO no es un link a ningún lado: queda como texto gris
            punteado, sin color, fuera del barrido visual. */}
        {sugerencia && !buscando && (
          <nav aria-label="Ir a un grupo"
            className="sticky top-0 z-20 -mx-3 px-3 sm:-mx-4 sm:px-4 py-1.5 flex gap-1.5 overflow-x-auto"
            style={{ background: MC.crema }}>
            {GRUPOS.map(g => nG(g.id) === 0 && filtroActivo ? null : nG(g.id) > 0 ? (
              // El color del grupo va en el borde izquierdo de la pastilla, no
              // en un punto: mismo mensaje, un nodo menos por cada una.
              <a key={g.id} href={`#g-${g.id}`}
                className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-l-[3px] pl-2 pr-2.5 py-1 text-[11.5px] font-semibold"
                style={{ borderColor: MC.lineaFte, borderLeftColor: g.c, background: MC.papel, color: MC.negro }}>
                {g.corto} <b className="tabular-nums" style={{ color: g.c }}>{nG(g.id)}</b>
              </a>
            ) : (
              <span key={g.id}
                className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-dashed pl-2 pr-2.5 py-1 text-[11.5px]"
                style={{ borderColor: MC.lineaFte, color: MC.tinta28 }}>
                {g.corto} <b className="tabular-nums">0</b>
              </span>
            ))}
          </nav>
        )}

        <div className="flex gap-2 flex-wrap items-center">
          {/* Misma piel que las tarjetas: papel sobre crema, línea de la paleta.
              Eran las últimas tres cajas con gris de admin genérico flotando en
              el medio de la hoja — la única costura que delataba el disfraz. */}
          <div className="relative flex-1 min-w-[180px]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: MC.tinta28 }} />
            <input
              type="text" placeholder="Buscar producto…" value={busqueda}
              onChange={e => setBusqueda(e.target.value)}
              className="w-full pl-8 pr-3 py-2 text-sm rounded-xl focus:outline-none focus:ring-2"
              style={{ background: MC.papel, border: `1px solid ${MC.linea}`, color: MC.negro }}
            />
          </div>
          {/* Los N chips de categoría eran N botones siempre visibles. Un select
              dice lo mismo con un nodo y no crece con el catálogo. */}
          <select value={filtro} onChange={e => setSp2({ estado: e.target.value })}
            className="py-2 px-2.5 text-sm rounded-xl focus:outline-none focus:ring-2"
            style={{ background: MC.papel, border: `1px solid ${MC.linea}`, color: MC.tinta70 }}>
            {FILTROS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
          <select value={catFiltro} onChange={e => setCatFiltro(e.target.value)}
            className="py-2 px-2.5 text-sm rounded-xl focus:outline-none focus:ring-2"
            style={{ background: MC.papel, border: `1px solid ${MC.linea}`, color: MC.tinta70 }}>
            {categorias.map(c => <option key={c} value={c}>{c === 'todas' ? 'Todas las categorías' : c}</option>)}
          </select>
        </div>

        {/* UNA línea. Dice la CONSECUENCIA, no el número suelto, y lleva al
            filtro que muestra exactamente esos productos — donde el panel de
            cada uno ya tiene el campo Mínimo.

            La consecuencia depende de si el motor tiene consumo medido: avisa
            por DÍAS RESTANTES (pedidos.py:39-52) y solo cae al mínimo cuando no
            puede calcularlos. Afirmar «no avisa nada» sin esa condición era
            falso para todo producto que rota — y quedaba contradicho por las
            tarjetas de URGENTE/PEDIR a 40 píxeles de distancia. */}
        {/* El aviso ya no es un callejón sin salida. «Verlos» lleva al filtro
            —donde el panel de cada producto tiene el campo Mínimo, uno por uno—
            y «Que el sistema los proponga» abre la revisión en lote, que es lo
            único que hace viable cargar 55 números.
            Ya NO se esconde dentro del filtro `sinmin`: ahí es donde el dueño
            está mirando exactamente esos productos, o sea el mejor momento para
            ofrecerle la propuesta. Lo que cambia adentro es el texto: el link a
            «verlos» sobraría estando ya ahí. */}
        {/* Con el grupo «A ojo» en pantalla el aviso vive DENTRO de él: es la
            explicación de por qué esas filas dicen «a ojo», y ahí es donde el
            dueño la está necesitando. Si ese grupo está vacío pero todavía
            faltan mínimos, el aviso sale igual acá arriba — nunca desaparece. */}
        {avisoUmbrales && (buscando || nG('ojo') === 0) && avisoMinimos}

        {vencTruncado && (
          <p className="text-[11px] rounded-lg px-2.5 py-1.5 border"
            style={{ background: '#F6E7C9', borderColor: '#E7D2A5', color: MC.vence }}>
            El listado de lotes viene recortado (tope de 800). La columna de
            vencimiento puede estar incompleta para los productos más antiguos.
          </p>
        )}

        {/* Lo que decía la tarjeta «Se vence: —» cuando el fetch de lotes caía.
            Sin tarjetas, el aviso necesita su propia línea: un mapa vacío es
            indistinguible de «no hay nada por vencer», y callarlo sería
            justamente afirmar la buena noticia que no se sabe. */}
        {vencErr && (
          <p className="text-[11px] rounded-lg px-2.5 py-1.5 border"
            style={{ background: '#F6E7C9', borderColor: '#E7D2A5', color: MC.vence }}>
            No se pudo leer el listado de lotes: <b>no se sabe qué vence</b>. El
            grupo «Se vence» y los avisos de vencimiento de las filas están
            incompletos hasta que vuelva a cargar.
          </p>
        )}

        {loading && <p className="text-sm text-center py-8 animate-pulse" style={{ color: MC.tinta45 }}>Cargando…</p>}

        {!loading && sugerencia && filtrados.length === 0 && (
          <p className="text-sm text-center py-6" style={{ color: MC.tinta45 }}>
            {buscando ? <>Ningún producto se llama así.</> : <>Nada con este filtro.</>}{' '}
            <button onClick={() => { setBusqueda(''); setCatFiltro('todas'); setSp2({ estado: 'todos' }) }}
              className="font-semibold underline" style={{ color: MC.terracota }}>
              Ver todo
            </button>
          </p>
        )}

        {/* La leyenda y los encabezados van UNA vez acá arriba en lugar de
            repetir la palabra en las 56 filas: con 56 filas, una palabra por
            fila son 56 palabras y la lista deja de escanearse.
            La leyenda DERIVA de ESTADO_CFG —el mismo tono que pinta la regla
            izquierda de cada fila—, jamás un color tipeado a mano: una leyenda
            que no coincide con lo que explica es peor que no tenerla.
            Los anchos (w-[74px] / w-16 / w-[62px], gap-2.5, pl-[40px]) son los
            MISMOS que los de ProductRow; si cambian allá, cambian acá o el
            título deja de estar sobre su columna. */}
        {!loading && filtrados.length > 0 && (
          <div>
            <p className="flex gap-x-3 gap-y-0.5 flex-wrap text-[10px] px-1" style={{ color: MC.tinta45 }}>
              {([['agotado', 'se acabó'], ['urgente', 'urgente'], ['pronto', 'pedir hoy'],
                 ['bajo', 'bajo'], ['ok', 'al día']] as const).map(([k, label]) => (
                <span key={k} className="inline-flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full" style={{ background: ESTADO_CFG[k].mc }} />{label}
                </span>
              ))}
              <span>🔔 la pidió una barista</span>
              <span>tachado = ya lo resolviste (solo para vos, solo hoy)</span>
            </p>
            {/* Solo en escritorio: en el celular la fila son dos renglones y unos
                títulos de columna sobre un layout que ya no es una tabla serían
                un rótulo apuntando al lugar equivocado. */}
            <div className="hidden sm:flex items-center gap-2.5 pl-[41px] pr-3 pt-1.5 text-[10px] font-bold uppercase tracking-[.14em]"
              style={{ color: MC.tinta45 }}>
              <span className="flex-1 min-w-0">Producto</span>
              <span className="shrink-0 w-[74px] text-right">Stock</span>
              <span className="shrink-0 w-16 text-right">Alcanza</span>
              <span className="shrink-0 w-[62px] pl-2.5 text-right" style={{ color: MC.tinta70 }}>Pedir</span>
            </div>
          </div>
        )}

        {/* BUSCANDO → lista plana. Con un nombre tipeado el dueño ya sabe qué
            quiere; repartir cuatro resultados en cuatro encabezados es ruido. */}
        {!loading && buscando && filtrados.length > 0 && (
          <div className="rounded-xl border overflow-hidden" style={{ borderColor: MC.linea }}>
            {filtrados.map(p => fila(p))}
          </div>
        )}
        {!loading && buscando && filtrados.length > 0 && (
          <p className="text-[11.5px]" style={{ color: MC.tinta45 }}>
            <b className="tabular-nums" style={{ color: MC.tinta70 }}>{filtrados.length}</b>
            {filtrados.length === 1 ? ' resultado' : ' resultados'} para «{busqueda.trim()}»
            {filtro !== 'atencion' && ` dentro de «${etiquetaFiltro}»`}. Borrá el buscador para volver a la cola de decisiones.
          </p>
        )}

        {/* LA COLA DE DECISIONES. Un grupo vacío no se dibuja: su pastilla de
            arriba ya lo dice en gris, y una tarjeta vacía por grupo serían seis
            cajas pidiendo atención para no decir nada. */}
        {!loading && !buscando && GRUPOS.map(g => {
          const items = grupos.get(g.id)!
          if (items.length === 0) return null

          // «Al día» arranca plegado a propósito: es el montón que no reclama.
          // Salvo que el dueño haya pedido justamente ese filtro, en cuyo caso
          // plegarlo dejaría la pantalla en blanco.
          // «sinmin» también desactiva el plegado: un producto sin mínimo y con
          // stock sano evalúa a «ok» y caía en «Al día» — o sea el destino de
          // «Verlos uno por uno» escondía sus propios resultados detrás de un
          // «Sin novedades. Nada que decidir hoy» sobre las filas pedidas.
          const plegado = g.id === 'aldia' && !verAlDia
            && filtro !== 'ok' && filtro !== 'todos' && filtro !== 'sinmin'
          if (plegado) return (
            <button key={g.id} id={`g-${g.id}`} onClick={() => setVerAlDia(true)}
              className="w-full flex items-center gap-3 rounded-xl border px-3 py-2.5 text-left scroll-mt-14"
              style={{ borderColor: MC.linea, background: MC.papel }}>
              <span className="w-1.5 self-stretch rounded-full shrink-0" style={{ background: g.c, opacity: .5 }} />
              <span className="flex-1 min-w-0 text-[12px]" style={{ color: MC.tinta45 }}>
                <b className="uppercase tracking-[.12em] text-[11.5px]" style={{ color: MC.tinta70 }}>{g.h}</b>
                {' — '}{g.sub}
              </span>
              <span className="text-lg font-bold tabular-nums shrink-0" style={{ color: MC.tinta45 }}>{items.length} ▾</span>
            </button>
          )

          return (
            <section key={g.id} id={`g-${g.id}`} className="rounded-xl border overflow-hidden scroll-mt-14"
              style={{ borderColor: MC.linea, background: MC.papel }}>
              <div className="grid grid-cols-[1fr_auto] gap-x-3 items-center px-3 py-2.5 border-b"
                style={{ borderBottomColor: MC.linea, borderLeft: `4px solid ${g.c}` }}>
                <h2 className="text-[12px] font-bold uppercase tracking-[.12em]" style={{ color: MC.negro }}>
                  {g.h}
                </h2>
                <span className="row-span-2 text-[22px] font-bold tabular-nums leading-none" style={{ color: g.c }}>
                  {items.length}
                </span>
                <p className="col-start-1 text-[11.5px] mt-0.5" style={{ color: MC.tinta45 }}>
                  {g.sub}
                  {/* El chip de vencimiento vive en la fila del grupo que le
                      tocó, así que este encabezado dice cuántos hay afuera: sin
                      esta frase, «Se vence 1» contradiría al total de siempre. */}
                  {g.id === 'vence' && venceEnOtros > 0 &&
                    ` Otros ${venceEnOtros} con lote por vencer están más arriba, con su fecha en la fila.`}
                  {g.id === 'aldia' && ' Ocupan una sola línea a propósito.'}
                </p>
              </div>

              {items.map(p => fila(p, g.id))}

              {/* El aviso de mínimos: dentro del grupo que existe por su causa. */}
              {g.id === 'ojo' && avisoUmbrales && (
                <div className="px-3 py-2 border-t" style={{ borderTopColor: MC.linea }}>{avisoMinimos}</div>
              )}

              {/* El botón del pedido, en el ESCRITORIO. En el celular vive en la
                  barra fija de abajo (`sm:hidden`) y las dos nunca se ven a la
                  vez. Un solo botón, un solo número. */}
              {g.id === grupoConBoton && paraPedir.length > 0 && (
                <div className="hidden sm:flex items-center gap-3 px-3 py-2.5 border-t"
                  style={{ borderTopColor: MC.linea, background: MC.fondo }}>
                  <button onClick={irAPedido}
                    className="rounded-full px-4 py-2 text-[13px] font-bold"
                    style={{ background: MC.negro, color: MC.crema }}>
                    Armar pedido · {paraPedir.length}
                  </button>
                  {/* Qué entra en ese número, dicho una vez y no en cada fila. */}
                  <span className="text-[11.5px]" style={{ color: MC.tinta45 }}>
                    Compra hoy + a ojo + pedir pronto, sin lo que ya tachaste. Lo que está
                    en negativo y lo que se prepara no van al pedido. Abre la sugerencia
                    por proveedor, con el texto listo para WhatsApp.
                  </span>
                </div>
              )}
            </section>
          )
        })}
      </div>

      {/* BARRA FIJA — solo celular. Misma acción y MISMO número que el botón del
          escritorio: los dos leen `paraPedir`. */}
      {!loading && !buscando && paraPedir.length > 0 && !seleccionado && !verMinimos && (
        <div className="sm:hidden fixed left-0 right-0 bottom-0 z-30 px-4 pt-3"
          style={{ background: `linear-gradient(rgba(247,242,231,0), ${MC.crema} 42%)`,
                   paddingBottom: 'calc(0.75rem + env(safe-area-inset-bottom, 0px))' }}>
          <button onClick={irAPedido}
            className="w-full rounded-full py-3.5 text-[14.5px] font-bold"
            style={{ background: MC.negro, color: MC.crema }}>
            Armar pedido · {paraPedir.length}
          </button>
        </div>
      )}

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
