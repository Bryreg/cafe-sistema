import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
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

// ─── Config ───────────────────────────────────────────────────────────────────

const ESTADO_CFG = {
  agotado: { label: 'AGOTADO', color: 'text-red-700',    bg: 'bg-red-100',    bar: 'bg-red-500',    dot: 'bg-red-500'    },
  urgente: { label: 'URGENTE', color: 'text-red-600',    bg: 'bg-red-50',     bar: 'bg-red-400',    dot: 'bg-red-400'    },
  pronto:  { label: 'PEDIR',   color: 'text-amber-700',  bg: 'bg-amber-50',   bar: 'bg-amber-400',  dot: 'bg-amber-400'  },
  bajo:    { label: 'BAJO',    color: 'text-yellow-700', bg: 'bg-yellow-50',  bar: 'bg-yellow-400', dot: 'bg-yellow-400' },
  ok:      { label: 'OK',      color: 'text-green-700',  bg: 'bg-green-50',   bar: 'bg-green-500',  dot: 'bg-green-500'  },
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
  { id: 'urgente',  label: 'Solo urgentes' },
  { id: 'pronto',   label: 'Solo pedir hoy' },
  { id: 'bajo',     label: 'Solo stock bajo' },
  { id: 'vence',    label: 'Solo se vence' },
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
    // «Necesita atención» tiene que incluir los CUATRO buckets que cuentan las
    // tarjetas de arriba, y «se vence» es uno de ellos. Sin esto, un insumo con
    // stock sano y un lote por vencer sumaba en la tarjeta naranja y no aparecía
    // en la lista con la que abre la pantalla: el número no mentía, el rótulo sí,
    // por omisión.
    default:        return p.estado !== 'ok' || !!venc[p.producto_id]   // atencion
  }
}

function diasLabel(d: number | null) {
  if (d === null) return '—'
  if (d < 1) return `${Math.round(d * 24)}h`
  return `${d.toFixed(1)}d`
}

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
function ProductRow({ p, venc, activo, onSelect }: {
  p: ProductoInventario
  venc?: VencInfo
  activo: boolean
  onSelect: () => void
}) {
  const cfg = ESTADO_CFG[p.estado] ?? ESTADO_CFG.ok
  const critico = p.dias_restantes !== null && p.dias_restantes <= p.lead_time_dias

  return (
    <button
      onClick={onSelect}
      title={`${p.categoria}${p.proveedor ? ` · ${p.proveedor}` : ''}`}
      className={`w-full flex items-center gap-2.5 text-left px-3 py-2 rounded-lg border transition-colors ${
        activo ? 'bg-amber-50 border-amber-300' : 'bg-white border-gray-200 hover:bg-gray-50'
      }`}
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />
      <span className="flex-1 min-w-0 truncate text-sm font-medium text-gray-800">
        {p.barista_alerto && '🔔 '}{p.nombre}
      </span>
      {venc && (
        <span className={`shrink-0 text-[11px] font-bold tabular-nums ${
          venc.estado === 'vencido' ? 'text-red-600' : 'text-amber-600'
        }`} title={venc.estado === 'vencido' ? 'Hay lote vencido' : 'Hay lote por vencer'}>
          ⚠ {ddmm(venc.fecha)}
        </span>
      )}
      <span className={`shrink-0 w-20 text-right text-sm font-bold tabular-nums ${critico ? 'text-red-600' : 'text-gray-800'}`}>
        {p.stock_actual}
        <span className="font-normal text-gray-400 text-[11px]"> {p.unidad}</span>
      </span>
      <span className="shrink-0 w-9 text-right text-[11px] text-gray-400 tabular-nums hidden sm:inline">
        {diasLabel(p.dias_restantes)}
      </span>
      {p.cantidad_sugerida > 0 && (
        <span className="shrink-0 text-[11px] font-bold text-amber-700 tabular-nums" title="Cuánto pedir">
          +{p.cantidad_sugerida}
        </span>
      )}
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

function PanelProducto({ producto: p, tiendaId, tab, onTab, onClose, sinConsumidor, onSaved }: {
  producto: ProductoInventario
  tiendaId: number
  tab: TabId
  onTab: (t: TabId) => void
  onClose: () => void
  sinConsumidor: boolean
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

// ─── Stock mode ───────────────────────────────────────────────────────────────

function ModoStock({ tiendaId }: { tiendaId: number }) {
  const [sugerencia, setSugerencia] = useState<Sugerencia | null>(null)
  const [loading, setLoading]       = useState(false)
  const [busqueda, setBusqueda]     = useState('')
  const [catFiltro, setCatFiltro]   = useState('todas')

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

  const allItems: ProductoInventario[] = useMemo(() => sugerencia
    ? [...sugerencia.grupos_fijos.flatMap(g => g.productos), ...sugerencia.insumos_generales]
    : [], [sugerencia])

  const categorias = useMemo(
    () => ['todas', ...Array.from(new Set(allItems.map(i => i.categoria))).sort()],
    [allItems])

  const totalVence = useMemo(() => allItems.filter(i => venc[i.producto_id]).length, [allItems, venc])

  const filtrados = useMemo(() => allItems
    .filter(i => pasaFiltro(i, filtro, venc))
    .filter(i => catFiltro === 'todas' || i.categoria === catFiltro)
    .filter(i => !busqueda || i.nombre.toLowerCase().includes(busqueda.toLowerCase()))
    .sort((a, b) =>
      (ESTADO_ORDER[a.estado] ?? 5) - (ESTADO_ORDER[b.estado] ?? 5) ||
      a.nombre.localeCompare(b.nombre)
    ), [allItems, filtro, venc, catFiltro, busqueda])

  const seleccionado = selId !== null ? allItems.find(i => i.producto_id === selId) ?? null : null

  // Las 4 tarjetas SON el filtro: tocar una filtra la lista, volver a tocarla
  // vuelve al default. Antes eran <div> decorativos y el banner rojo de urgentes
  // repetía el mismo número sin llevar a ningún lado.
  const kpis = sugerencia ? [
    { id: 'urgente' as const, label: 'Urgente',    val: sugerencia.total_urgentes, color: 'text-red-600',    ring: 'bg-red-50 border-red-200'       },
    { id: 'pronto'  as const, label: 'Pedir hoy',  val: sugerencia.total_pronto,   color: 'text-amber-600',  ring: 'bg-amber-50 border-amber-200'   },
    { id: 'bajo'    as const, label: 'Stock bajo', val: sugerencia.total_bajo,     color: 'text-yellow-600', ring: 'bg-yellow-50 border-yellow-200' },
    // Con el fetch de lotes caído no se sabe cuántos vencen: va «—», no 0. Y la
    // tarjeta deja de filtrar, porque filtrar por un mapa vacío daría una lista
    // vacía que se leería como «no hay ninguno».
    { id: 'vence'   as const, label: 'Se vence',   val: vencErr ? '—' : totalVence, color: 'text-orange-600', ring: 'bg-orange-50 border-orange-200', off: vencErr },
  ] : []

  return (
    <div className="space-y-3">
      <div className={seleccionado ? 'lg:mr-[420px] space-y-3 transition-all' : 'space-y-3 transition-all'}>
        {sugerencia && (
          <div className="grid grid-cols-4 gap-2">
            {kpis.map(k => (
              <button key={k.id} disabled={'off' in k && k.off}
                title={'off' in k && k.off ? 'No se pudo leer el listado de lotes: no se sabe qué vence.' : undefined}
                onClick={() => setSp2({ estado: filtro === k.id ? 'atencion' : k.id })}
                className={`border rounded-xl p-2.5 text-center transition-all ${k.ring} ${
                  filtro === k.id ? 'ring-2 ring-amber-400' : ''
                } ${'off' in k && k.off ? 'opacity-50 cursor-not-allowed' : ''}`}>
                <p className={`text-2xl font-bold tabular-nums ${k.color}`}>{k.val}</p>
                <p className="text-[10px] text-gray-500 font-medium uppercase tracking-wide">{k.label}</p>
              </button>
            ))}
          </div>
        )}

        <div className="flex gap-2 flex-wrap items-center">
          <div className="relative flex-1 min-w-[180px]">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text" placeholder="Buscar producto…" value={busqueda}
              onChange={e => setBusqueda(e.target.value)}
              className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-amber-300"
            />
          </div>
          {/* Los N chips de categoría eran N botones siempre visibles. Un select
              dice lo mismo con un nodo y no crece con el catálogo. */}
          <select value={filtro} onChange={e => setSp2({ estado: e.target.value })}
            className="py-2 px-2.5 text-sm border border-gray-200 rounded-xl bg-white focus:outline-none focus:ring-2 focus:ring-amber-300">
            {FILTROS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
          </select>
          <select value={catFiltro} onChange={e => setCatFiltro(e.target.value)}
            className="py-2 px-2.5 text-sm border border-gray-200 rounded-xl bg-white focus:outline-none focus:ring-2 focus:ring-amber-300">
            {categorias.map(c => <option key={c} value={c}>{c === 'todas' ? 'Todas las categorías' : c}</option>)}
          </select>
        </div>

        {vencTruncado && (
          <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
            El listado de lotes viene recortado (tope de 800). La columna de
            vencimiento puede estar incompleta para los productos más antiguos.
          </p>
        )}

        {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando…</p>}

        {!loading && sugerencia && filtrados.length === 0 && (
          <p className="text-sm text-gray-500 text-center py-6">
            Nada con este filtro.{' '}
            <button onClick={() => setSp2({ estado: 'todos' })} className="font-semibold text-amber-700 underline">
              Ver todo
            </button>
          </p>
        )}

        <div className="space-y-1">
          {filtrados.map(p => (
            <ProductRow
              key={p.producto_id}
              p={p}
              venc={venc[p.producto_id]}
              activo={selId === p.producto_id}
              onSelect={() => setSp2({ p: String(p.producto_id), tab: 'hoy' }, true)}
            />
          ))}
        </div>
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
          onSaved={cargar}
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
