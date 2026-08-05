import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  AlertTriangle, CheckCircle2, ChevronDown, Layers,
  Search, RotateCcw, Download, Check, Package,
} from 'lucide-react'
import NivelEnvase from '../components/NivelEnvase'

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

function diasLabel(d: number | null) {
  if (d === null) return '—'
  if (d < 1) return `${Math.round(d * 24)}h`
  return `${d.toFixed(1)}d`
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

// ─── ProductRow ───────────────────────────────────────────────────────────────

function ProductRow({ p, tiendaId, onSaved }: {
  p: ProductoInventario; tiendaId: number; onSaved: () => void
}) {
  const [open, setOpen] = useState(false)

  const [adjCantidad, setAdjCantidad] = useState('')
  const [adjMotivo, setAdjMotivo]     = useState('')
  const [savingAdj, setSavingAdj]     = useState(false)
  const [savedAdj, setSavedAdj]       = useState(false)

  const [critico,  setCritico]  = useState(String(p.stock_critico ?? 0))
  const [minimo,   setMinimo]   = useState(String(p.stock_minimo))
  const [ideal,    setIdeal]    = useState(String(p.stock_ideal ?? 0))
  const [leadTime, setLeadTime] = useState(String(p.lead_time_dias))
  const [savingThr, setSavingThr] = useState(false)
  const [savedThr,  setSavedThr]  = useState(false)

  const cfg = ESTADO_CFG[p.estado] ?? ESTADO_CFG.ok
  const barPct = p.stock_ideal > 0
    ? Math.min(100, Math.round((p.stock_actual / p.stock_ideal) * 100))
    : 0

  const thrDirty =
    Number(critico)  !== (p.stock_critico ?? 0) ||
    Number(minimo)   !== p.stock_minimo          ||
    Number(ideal)    !== (p.stock_ideal ?? 0)    ||
    Number(leadTime) !== p.lead_time_dias

  const borderClass =
    p.estado === 'agotado' || p.estado === 'urgente' ? 'border-l-4 border-l-red-400 border-red-200'  :
    p.estado === 'pronto'                             ? 'border-l-4 border-l-amber-400 border-amber-100' :
    p.estado === 'bajo'                               ? 'border-l-4 border-l-yellow-400 border-yellow-100' :
    'border-gray-200'

  async function submitAdj(e: React.FormEvent) {
    e.preventDefault()
    const cantidad = parseFloat(adjCantidad)
    if (isNaN(cantidad) || cantidad < 0) return
    setSavingAdj(true)
    try {
      await api.post('/inventario/movimiento', {
        tienda_id: tiendaId, producto_id: p.producto_id,
        tipo: 'ajuste', cantidad, motivo: adjMotivo.trim() || 'Ajuste manual',
      })
      setSavedAdj(true)
      setAdjCantidad('')
      setAdjMotivo('')
      setTimeout(() => { setSavedAdj(false); onSaved() }, 1000)
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
      setTimeout(() => { setSavedThr(false); onSaved() }, 1200)
    } catch { alert('Error al guardar umbrales') }
    finally { setSavingThr(false) }
  }

  return (
    <div className={`bg-white border rounded-xl overflow-hidden ${borderClass}`}>
      {/* Main row */}
      <button
        className="w-full text-left px-4 py-3 hover:bg-gray-50/60 transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        <div className="flex items-center gap-3">
          <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${cfg.dot}`} />

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-sm font-semibold text-gray-800">{p.nombre}</span>
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${cfg.bg} ${cfg.color}`}>
                {cfg.label}
              </span>
              {p.barista_alerto && (
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">
                  🔔 barista
                </span>
              )}
            </div>
            <p className="text-xs text-gray-400 mt-0.5">
              {p.categoria}{p.proveedor ? ` · ${p.proveedor}` : ''}
            </p>
          </div>

          {p.fraccionable && (
            <div className="shrink-0" title={`Nivel de la ${p.envase || 'bolsa'} en uso`}>
              <NivelEnvase readOnly envase={p.envase === 'botella' ? 'botella' : 'bolsa'}
                nivel={p.stock_actual <= 0 ? 0 : (p.stock_actual % 1 === 0 ? 1 : p.stock_actual % 1)} />
            </div>
          )}
          <div className="shrink-0 text-right hidden sm:block">
            <p className="text-sm font-bold text-gray-800">
              {p.stock_actual} <span className="font-normal text-gray-400 text-xs">{p.unidad}</span>
            </p>
            <p className={`text-xs font-semibold ${
              p.dias_restantes !== null && p.dias_restantes <= p.lead_time_dias
                ? 'text-red-600' : 'text-gray-400'
            }`}>
              {diasLabel(p.dias_restantes)}
            </p>
          </div>

          {/* CUÁNTO PEDIR. El backend ya lo calcula (services/pedidos.py: consumo
              diario × (lead time + colchón) − stock) y esta pantalla lo recibía y lo
              tiraba: estaba declarado en el tipo y no se pintaba en ningún lado.
              Sin este número la pantalla dice que algo falta pero no cuánto traer,
              que es justo la decisión que hay que tomar. */}
          {p.cantidad_sugerida > 0 && (
            <div className="shrink-0 text-right px-2 py-1 rounded-lg bg-amber-50 border border-amber-200"
                 title={`Sugerido para cubrir ${p.lead_time_dias} día(s) de entrega${p.proveedor ? ` · ${p.proveedor}` : ''}`}>
              <p className="text-[10px] font-bold uppercase tracking-wide text-amber-600 leading-none">Pedir</p>
              <p className="text-sm font-bold text-amber-800 leading-tight">
                {p.cantidad_sugerida} <span className="font-normal text-amber-500 text-xs">{p.unidad}</span>
              </p>
            </div>
          )}

          <ChevronDown
            size={14}
            className={`text-gray-400 shrink-0 transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
          />
        </div>

        {p.stock_ideal > 0 && (
          <div className="mt-2 ml-6">
            <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${cfg.bar}`} style={{ width: `${barPct}%` }} />
            </div>
            <p className="text-[10px] text-gray-400 mt-0.5">
              {p.stock_actual} / {p.stock_ideal} {p.unidad}
              {p.consumo_diario > 0 && <> · consumo {p.consumo_diario} {p.unidad}/día</>}
            </p>
          </div>
        )}
      </button>

      {open && (
        <div className="border-t border-gray-100 bg-gray-50/80 px-4 py-4 space-y-5">

          {/* Quick adjustment */}
          <div>
            <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-2">
              Ajuste de stock
            </p>
            <form onSubmit={submitAdj} className="flex gap-2 flex-wrap items-end">
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  Cantidad real en bodega ({p.unidad})
                </label>
                <input
                  type="number" min={0} step={0.5}
                  value={adjCantidad}
                  onChange={e => setAdjCantidad(e.target.value)}
                  placeholder={String(p.stock_actual)}
                  className="w-28 border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300"
                />
              </div>
              <div className="flex-1 min-w-[160px]">
                <label className="text-xs text-gray-500 block mb-1">Motivo</label>
                <input
                  type="text"
                  value={adjMotivo}
                  onChange={e => setAdjMotivo(e.target.value)}
                  placeholder="Conteo físico, merma descubierta…"
                  className="w-full border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300"
                />
              </div>
              <button
                type="submit"
                disabled={adjCantidad === '' || savingAdj || savedAdj}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-40 transition-colors"
              >
                {savedAdj ? <Check size={14} /> : savingAdj ? '…' : 'Confirmar'}
              </button>
            </form>
          </div>

          {/* Threshold calibration */}
          <div>
            <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-2">
              Umbrales y tiempo de entrega
            </p>
            <div className="flex gap-2 flex-wrap items-end">
              {[
                { label: `Crítico (${p.unidad})`, val: critico,  set: setCritico,  ring: 'focus:ring-red-200',    border: 'border-red-200'   },
                { label: `Mínimo (${p.unidad})`,  val: minimo,   set: setMinimo,   ring: 'focus:ring-amber-200',  border: 'border-amber-200' },
                { label: `Ideal (${p.unidad})`,   val: ideal,    set: setIdeal,    ring: 'focus:ring-green-200',  border: 'border-green-200' },
                { label: 'Entrega (días)',         val: leadTime, set: setLeadTime, ring: 'focus:ring-gray-200',   border: 'border-gray-300'  },
              ].map(({ label, val, set, ring, border }) => (
                <div key={label}>
                  <label className="text-xs text-gray-500 block mb-1">{label}</label>
                  <input
                    type="number" min={0} step={label.includes('días') ? 1 : 0.5}
                    value={val}
                    onChange={e => set(e.target.value)}
                    className={`w-20 text-center border ${border} rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 ${ring}`}
                  />
                </div>
              ))}
              <button
                onClick={saveThr}
                disabled={!thrDirty || savingThr || savedThr}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-gray-700 text-white hover:bg-gray-800 disabled:opacity-40 transition-colors"
              >
                {savedThr ? <Check size={14} /> : savingThr ? '…' : 'Guardar umbrales'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Stock mode ───────────────────────────────────────────────────────────────

function ModoStock({ tiendaId }: { tiendaId: number }) {
  const [sugerencia, setSugerencia] = useState<Sugerencia | null>(null)
  const [loading, setLoading]       = useState(false)
  const [busqueda, setBusqueda]     = useState('')
  const [catFiltro, setCatFiltro]   = useState('todas')

  const cargar = useCallback(() => {
    setLoading(true)
    api.get('/pedidos/sugerencia', { params: { tienda_id: tiendaId } })
      .then(r => setSugerencia(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tiendaId])

  useEffect(() => { cargar() }, [cargar])

  const allItems: ProductoInventario[] = sugerencia
    ? [...sugerencia.grupos_fijos.flatMap(g => g.productos), ...sugerencia.insumos_generales]
    : []

  const categorias = ['todas', ...Array.from(new Set(allItems.map(i => i.categoria))).sort()]

  const filtrados = allItems
    .filter(i => catFiltro === 'todas' || i.categoria === catFiltro)
    .filter(i => !busqueda || i.nombre.toLowerCase().includes(busqueda.toLowerCase()))
    .sort((a, b) =>
      (ESTADO_ORDER[a.estado] ?? 5) - (ESTADO_ORDER[b.estado] ?? 5) ||
      a.nombre.localeCompare(b.nombre)
    )

  return (
    <div className="space-y-4">
      {sugerencia && (
        <div className="grid grid-cols-4 gap-2">
          {[
            { label: 'Urgente',    val: sugerencia.total_urgentes, num: 'text-red-600',    bg: 'bg-red-50 border-red-200'     },
            { label: 'Pedir hoy', val: sugerencia.total_pronto,   num: 'text-amber-600',  bg: 'bg-amber-50 border-amber-200' },
            { label: 'Stock bajo', val: sugerencia.total_bajo,     num: 'text-yellow-600', bg: 'bg-yellow-50 border-yellow-200'},
            { label: 'OK',         val: sugerencia.total_ok,       num: 'text-green-600',  bg: 'bg-green-50 border-green-200' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl p-3 text-center ${k.bg}`}>
              <p className={`text-2xl font-bold ${k.num}`}>{k.val}</p>
              <p className="text-[11px] text-gray-500 font-medium uppercase tracking-wide mt-0.5">{k.label}</p>
            </div>
          ))}
        </div>
      )}

      {sugerencia && sugerencia.total_urgentes > 0 && (
        <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          <AlertTriangle size={16} />
          {sugerencia.total_urgentes} producto{sugerencia.total_urgentes !== 1 ? 's' : ''}{' '}
          se agotará{sugerencia.total_urgentes !== 1 ? 'n' : ''} antes de que llegue el próximo pedido
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2 flex-wrap items-center">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Buscar producto…"
            value={busqueda}
            onChange={e => setBusqueda(e.target.value)}
            className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-amber-300"
          />
        </div>
        <div className="flex gap-1 flex-wrap">
          {categorias.map(cat => (
            <button
              key={cat}
              onClick={() => setCatFiltro(cat)}
              className={`px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                catFiltro === cat
                  ? 'bg-gray-800 text-white'
                  : 'bg-white border border-gray-200 text-gray-600 hover:border-gray-400'
              }`}
            >
              {cat === 'todas' ? 'Todas' : cat}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando…</p>
      )}

      {!loading && sugerencia && filtrados.length === 0 && (
        <div className="flex items-center gap-2 text-sm text-green-600 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
          <CheckCircle2 size={16} />
          {busqueda || catFiltro !== 'todas'
            ? 'Sin productos con ese filtro.'
            : 'Todo el inventario tiene stock suficiente.'}
        </div>
      )}

      <div className="space-y-2">
        {filtrados.map(p => (
          <ProductRow key={p.producto_id} p={p} tiendaId={tiendaId} onSaved={cargar} />
        ))}
      </div>
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
    <div className="space-y-5 pb-10">
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
