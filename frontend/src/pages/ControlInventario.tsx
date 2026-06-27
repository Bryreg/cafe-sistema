import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  AlertTriangle, CheckCircle2, TrendingUp, TrendingDown,
  ShoppingCart, RefreshCw, ChevronDown, ChevronUp, Layers, Settings2, Check,
} from 'lucide-react'

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
}

interface GrupoProveedor {
  proveedor: string
  productos: ProductoInventario[]
  estado_resumen: string
}

interface Sugerencia {
  grupos_fijos: GrupoProveedor[]
  insumos_generales: ProductoInventario[]
  total_urgentes: number
  total_pronto: number
  total_bajo: number
  total_ok: number
}

interface ProductoVenta {
  nombre: string
  codigo: string
  cantidad: number
  total: number
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const ESTADO_CFG = {
  agotado: { label: 'AGOTADO', bg: 'bg-red-100',    text: 'text-red-700',    border: 'border-red-300',    dot: 'bg-red-500'    },
  urgente: { label: 'URGENTE', bg: 'bg-red-50',     text: 'text-red-600',    border: 'border-red-200',    dot: 'bg-red-400'    },
  pronto:  { label: 'PEDIR',   bg: 'bg-amber-50',   text: 'text-amber-700',  border: 'border-amber-200',  dot: 'bg-amber-400'  },
  bajo:    { label: 'BAJO',    bg: 'bg-yellow-50',  text: 'text-yellow-700', border: 'border-yellow-200', dot: 'bg-yellow-400' },
  ok:      { label: 'OK',      bg: 'bg-green-50',   text: 'text-green-700',  border: 'border-green-200',  dot: 'bg-green-400'  },
}

function fmtCOP(n: number) {
  return '$' + Math.round(n).toLocaleString('es-CO')
}

function diasLabel(d: number | null) {
  if (d === null) return '—'
  if (d < 1) return `${Math.round(d * 24)}h`
  return `${d.toFixed(1)}d`
}

function isoHoy() {
  return new Date().toISOString().slice(0, 10)
}

function isoHace(dias: number) {
  const d = new Date()
  d.setDate(d.getDate() - dias)
  return d.toISOString().slice(0, 10)
}

const PERIODOS = [
  { label: '7d',  dias: 7  },
  { label: '14d', dias: 14 },
  { label: '30d', dias: 30 },
]

// ─── StockSection ─────────────────────────────────────────────────────────────

function StockSection({
  title, items, titleColor, defaultOpen,
}: {
  title: string
  items: ProductoInventario[]
  titleColor: string
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 transition-colors"
      >
        <span className={`text-sm font-bold ${titleColor}`}>
          {title}{' '}
          <span className="font-normal text-gray-400">({items.length})</span>
        </span>
        {open
          ? <ChevronUp size={15} className="text-gray-400" />
          : <ChevronDown size={15} className="text-gray-400" />
        }
      </button>

      {open && (
        <div className="overflow-x-auto border-t border-gray-100">
          <table className="w-full">
            <thead>
              <tr className="text-xs text-gray-400 uppercase bg-gray-50">
                <th className="px-4 py-1.5 text-left font-medium">Producto</th>
                <th className="px-2 py-1.5 text-center font-medium">Stock</th>
                <th className="px-2 py-1.5 text-center font-medium">Días</th>
                <th className="px-2 py-1.5 text-center font-medium">Consumo/día</th>
              </tr>
            </thead>
            <tbody>
              {items.map(p => {
                const cfg = ESTADO_CFG[p.estado as keyof typeof ESTADO_CFG] ?? ESTADO_CFG.ok
                return (
                  <tr
                    key={p.producto_id}
                    className="border-t border-gray-50 hover:bg-gray-50/50 transition-colors"
                  >
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-1.5">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
                        <span className="text-sm text-gray-800">{p.nombre}</span>
                        {p.barista_alerto && (
                          <span className="text-xs bg-purple-100 text-purple-700 px-1.5 rounded-full font-medium">
                            barista
                          </span>
                        )}
                      </div>
                      {p.proveedor && (
                        <p className="text-xs text-gray-400 ml-3.5 mt-0.5">{p.proveedor}</p>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span className="text-sm text-gray-700">{p.stock_actual}</span>
                      <span className="text-xs text-gray-400"> {p.unidad}</span>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span className={`text-sm font-semibold ${
                        p.dias_restantes !== null && p.dias_restantes <= p.lead_time_dias
                          ? 'text-red-600'
                          : 'text-gray-700'
                      }`}>
                        {diasLabel(p.dias_restantes)}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span className="text-sm text-gray-600">
                        {p.consumo_diario > 0 ? `${p.consumo_diario} ${p.unidad}` : '—'}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Calibración de mínimos ───────────────────────────────────────────────────

interface EditState { stock_minimo?: number; stock_ideal?: number; stock_critico?: number; lead_time_dias?: number }

function CalibracionSection({
  items, tiendaId, onSaved,
}: {
  items: ProductoInventario[]
  tiendaId: number
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false)
  const [edits, setEdits] = useState<Record<number, EditState>>({})
  const [saving, setSaving] = useState<Record<number, boolean>>({})
  const [saved, setSaved] = useState<Record<number, boolean>>({})

  function val(p: ProductoInventario, field: keyof EditState) {
    if (edits[p.producto_id]?.[field] !== undefined) return edits[p.producto_id][field]
    if (field === 'stock_minimo') return p.stock_minimo
    if (field === 'stock_ideal') return p.stock_ideal ?? 0
    if (field === 'stock_critico') return p.stock_critico ?? 0
    return p.lead_time_dias
  }

  function setEdit(id: number, field: keyof EditState, v: number) {
    setEdits(prev => ({ ...prev, [id]: { ...prev[id], [field]: v } }))
  }

  async function save(p: ProductoInventario) {
    const e = edits[p.producto_id]
    if (!e) return
    setSaving(prev => ({ ...prev, [p.producto_id]: true }))
    try {
      const ops: Promise<unknown>[] = []
      const umbralChanged = (
        (e.stock_minimo !== undefined && e.stock_minimo !== p.stock_minimo) ||
        (e.stock_ideal !== undefined && e.stock_ideal !== p.stock_ideal) ||
        (e.stock_critico !== undefined && e.stock_critico !== p.stock_critico)
      )
      if (umbralChanged) {
        ops.push(api.patch(`/inventario/tienda/${tiendaId}/producto/${p.producto_id}/umbrales`, {
          stock_minimo: e.stock_minimo,
          stock_ideal: e.stock_ideal,
          stock_critico: e.stock_critico,
        }))
      }
      if (e.lead_time_dias !== undefined && e.lead_time_dias !== p.lead_time_dias) {
        ops.push(api.patch(`/inventario/productos/${p.producto_id}`, {
          lead_time_dias: e.lead_time_dias,
        }))
      }
      await Promise.all(ops)
      setSaved(prev => ({ ...prev, [p.producto_id]: true }))
      setTimeout(() => setSaved(prev => ({ ...prev, [p.producto_id]: false })), 1500)
      onSaved()
    } catch {
      alert('Error al guardar')
    } finally {
      setSaving(prev => ({ ...prev, [p.producto_id]: false }))
    }
  }

  function coberturaLabel(minimo: number, consumo: number, leadTime: number) {
    if (consumo <= 0) return { text: 'sin datos', color: 'text-gray-400' }
    const dias = minimo / consumo
    if (dias < leadTime) return { text: `${dias.toFixed(1)}d ⚠`, color: 'text-red-600 font-semibold' }
    if (dias < leadTime * 2) return { text: `${dias.toFixed(1)}d`, color: 'text-amber-600' }
    return { text: `${dias.toFixed(1)}d`, color: 'text-green-600' }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-bold text-gray-600">
          <Settings2 size={15} />
          Calibrar mínimos y tiempos de entrega
        </span>
        {open ? <ChevronUp size={15} className="text-gray-400" /> : <ChevronDown size={15} className="text-gray-400" />}
      </button>

      {open && (
        <div className="overflow-x-auto border-t border-gray-100">
          <p className="px-4 py-2 text-xs text-gray-400 bg-gray-50 border-b border-gray-100">
            Ajustá los umbrales por producto. <strong>Crítico</strong>: alerta roja inmediata. <strong>Mínimo</strong>: dispara pedido. <strong>Ideal</strong>: nivel al que reponer. Estados: Agotado → Crítico → Bajo → Normal.
          </p>
          <table className="w-full">
            <thead>
              <tr className="text-xs text-gray-400 uppercase bg-gray-50">
                <th className="px-4 py-2 text-left font-medium">Producto</th>
                <th className="px-2 py-2 text-center font-medium">Consumo/día</th>
                <th className="px-2 py-2 text-center font-medium">Crítico</th>
                <th className="px-2 py-2 text-center font-medium">Mínimo</th>
                <th className="px-2 py-2 text-center font-medium">Ideal</th>
                <th className="px-2 py-2 text-center font-medium">Entrega (días)</th>
                <th className="px-2 py-2 text-center font-medium">Cobertura</th>
                <th className="px-2 py-2" />
              </tr>
            </thead>
            <tbody>
              {items.map(p => {
                const minimo = val(p, 'stock_minimo') as number
                const leadTime = val(p, 'lead_time_dias') as number
                const cob = coberturaLabel(minimo, p.consumo_diario, leadTime)
                const isDirty = edits[p.producto_id] !== undefined && (
                  (edits[p.producto_id].stock_minimo !== undefined && edits[p.producto_id].stock_minimo !== p.stock_minimo) ||
                  (edits[p.producto_id].stock_ideal !== undefined && edits[p.producto_id].stock_ideal !== p.stock_ideal) ||
                  (edits[p.producto_id].stock_critico !== undefined && edits[p.producto_id].stock_critico !== p.stock_critico) ||
                  (edits[p.producto_id].lead_time_dias !== undefined && edits[p.producto_id].lead_time_dias !== p.lead_time_dias)
                )
                return (
                  <tr key={p.producto_id} className="border-t border-gray-50 hover:bg-gray-50/50">
                    <td className="px-4 py-2">
                      <p className="text-sm text-gray-800">{p.nombre}</p>
                      {p.proveedor && <p className="text-xs text-gray-400">{p.proveedor}</p>}
                    </td>
                    <td className="px-2 py-2 text-center text-sm text-gray-500">
                      {p.consumo_diario > 0 ? `${p.consumo_diario} ${p.unidad}` : '—'}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <input
                        type="number"
                        min={0}
                        step={0.5}
                        value={val(p, 'stock_critico') as number}
                        onChange={e => setEdit(p.producto_id, 'stock_critico', parseFloat(e.target.value) || 0)}
                        className="w-16 text-center border border-orange-200 rounded-lg py-1 text-sm focus:outline-none focus:ring-2 focus:ring-orange-300"
                      />
                    </td>
                    <td className="px-2 py-2 text-center">
                      <input
                        type="number"
                        min={0}
                        step={0.5}
                        value={minimo}
                        onChange={e => setEdit(p.producto_id, 'stock_minimo', parseFloat(e.target.value) || 0)}
                        className="w-16 text-center border border-gray-300 rounded-lg py-1 text-sm focus:outline-none focus:ring-2 focus:ring-forest/40"
                      />
                    </td>
                    <td className="px-2 py-2 text-center">
                      <input
                        type="number"
                        min={0}
                        step={0.5}
                        value={val(p, 'stock_ideal') as number}
                        onChange={e => setEdit(p.producto_id, 'stock_ideal', parseFloat(e.target.value) || 0)}
                        className="w-16 text-center border border-green-200 rounded-lg py-1 text-sm focus:outline-none focus:ring-2 focus:ring-green-300"
                      />
                    </td>
                    <td className="px-2 py-2 text-center">
                      <input
                        type="number"
                        min={1}
                        max={14}
                        step={1}
                        value={leadTime}
                        onChange={e => setEdit(p.producto_id, 'lead_time_dias', parseInt(e.target.value) || 1)}
                        className="w-14 text-center border border-gray-300 rounded-lg py-1 text-sm focus:outline-none focus:ring-2 focus:ring-forest/40"
                      />
                    </td>
                    <td className={`px-2 py-2 text-center text-sm ${cob.color}`}>
                      {cob.text}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {saved[p.producto_id] ? (
                        <Check size={16} className="text-green-500 inline" />
                      ) : (
                        <button
                          onClick={() => save(p)}
                          disabled={!isDirty || saving[p.producto_id]}
                          className="text-xs font-medium px-2.5 py-1 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-default bg-forest text-white hover:bg-forest/90"
                        >
                          {saving[p.producto_id] ? '…' : 'Guardar'}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Página principal ─────────────────────────────────────────────────────────

export default function ControlInventario() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [sedes, setSedes] = useState<{ id: number; nombre: string }[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)

  const [sugerencia, setSugerencia] = useState<Sugerencia | null>(null)
  const [loadingInv, setLoadingInv] = useState(false)

  const [ventas, setVentas] = useState<ProductoVenta[] | null>(null)
  const [loadingVentas, setLoadingVentas] = useState(false)
  const [errorVentas, setErrorVentas] = useState<string | null>(null)
  const [periodo, setPeriodo] = useState(14)

  // Sedes
  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (tiendaId === null && r.data.length > 0) setTiendaId(r.data[0].id)
    }).catch(() => {})
  }, [])

  // Inventario
  useEffect(() => {
    if (tiendaId === null) return
    setLoadingInv(true)
    setSugerencia(null)
    api.get('/pedidos/sugerencia', { params: { tienda_id: tiendaId } })
      .then(r => setSugerencia(r.data))
      .catch(() => {})
      .finally(() => setLoadingInv(false))
  }, [tiendaId])

  // Ventas por producto (POS)
  useEffect(() => {
    setLoadingVentas(true)
    setErrorVentas(null)
    setVentas(null)
    api.get('/pos/analytics/productos-top', {
      params: { fecha_desde: isoHace(periodo), fecha_hasta: isoHoy() },
    })
      .then(r => setVentas((r.data ?? []).map((x: any) => ({
        nombre: x.nombre_producto, codigo: String(x.producto_id), cantidad: x.unidades, total: x.total,
      }))))
      .catch(e => setErrorVentas(e.response?.data?.detail ?? 'Error consultando ventas'))
      .finally(() => setLoadingVentas(false))
  }, [periodo])

  const topProductos = ventas
    ? [...ventas].sort((a, b) => b.total - a.total).slice(0, 15)
    : []

  const maxTotal = topProductos[0]?.total ?? 1

  const allItems: ProductoInventario[] = sugerencia
    ? [
        ...sugerencia.grupos_fijos.flatMap(g => g.productos),
        ...sugerencia.insumos_generales,
      ]
    : []

  const urgentes = allItems.filter(i => i.estado === 'agotado' || i.estado === 'urgente')
  const porPedir = allItems.filter(i => i.estado === 'pronto')
  const resto    = allItems.filter(i => i.estado === 'bajo' || i.estado === 'ok')

  return (
    <div className="space-y-5 pb-10">

      {/* Título */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-800 flex items-center gap-2">
            <Layers size={20} className="text-forest" />
            Control de Inventario
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Stock actual · consumo 14 días · ventas POS
          </p>
        </div>
        <button
          onClick={() => navigate('/pedidos-admin')}
          className="flex-shrink-0 flex items-center gap-1.5 bg-amber-500 hover:bg-amber-600 text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors shadow-sm"
        >
          <ShoppingCart size={15} />
          Generar pedido
        </button>
      </div>

      {/* Selector de sede */}
      {sedes.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {sedes.map(s => (
            <button
              key={s.id}
              onClick={() => setTiendaId(s.id)}
              className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
                tiendaId === s.id
                  ? 'bg-forest text-white shadow-sm'
                  : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
              }`}
            >
              {s.nombre}
            </button>
          ))}
        </div>
      )}

      {/* KPIs */}
      {sugerencia && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-center">
            <p className="text-2xl font-bold text-red-600">{sugerencia.total_urgentes}</p>
            <p className="text-xs text-red-500 font-medium uppercase tracking-wide mt-0.5">Urgente</p>
          </div>
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-center">
            <p className="text-2xl font-bold text-amber-600">{sugerencia.total_pronto}</p>
            <p className="text-xs text-amber-500 font-medium uppercase tracking-wide mt-0.5">Pedir hoy</p>
          </div>
          <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-3 text-center">
            <p className="text-2xl font-bold text-yellow-600">{sugerencia.total_bajo}</p>
            <p className="text-xs text-yellow-500 font-medium uppercase tracking-wide mt-0.5">Stock bajo</p>
          </div>
          <div className="bg-green-50 border border-green-200 rounded-xl p-3 text-center">
            <p className="text-2xl font-bold text-green-600">{sugerencia.total_ok}</p>
            <p className="text-xs text-green-500 font-medium uppercase tracking-wide mt-0.5">OK</p>
          </div>
        </div>
      )}

      {/* Alerta urgentes */}
      {sugerencia && sugerencia.total_urgentes > 0 && (
        <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          <AlertTriangle size={16} />
          {sugerencia.total_urgentes} producto{sugerencia.total_urgentes !== 1 ? 's' : ''} se{' '}
          agotará{sugerencia.total_urgentes !== 1 ? 'n' : ''} antes de que llegue el próximo pedido
        </div>
      )}

      {/* Dos columnas */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">

        {/* === Lo que más se vende (POS) === */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-bold text-gray-700 flex items-center gap-2">
              <TrendingUp size={16} className="text-forest" />
              Lo que más se vende
            </h2>
            <div className="flex gap-1">
              {PERIODOS.map(({ label, dias }) => (
                <button
                  key={dias}
                  onClick={() => setPeriodo(dias)}
                  className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
                    periodo === dias
                      ? 'bg-forest text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {loadingVentas && (
            <p className="text-sm text-gray-400 animate-pulse py-8 text-center">
              Consultando ventas…
            </p>
          )}

          {errorVentas && !loadingVentas && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
              {errorVentas}
            </div>
          )}

          {ventas && !loadingVentas && (
            <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-100 flex justify-between items-center">
                <span className="text-xs text-gray-500">
                  {ventas.length} productos
                </span>
                <span className="text-xs font-semibold text-gray-700">
                  {fmtCOP(ventas.reduce((s, p) => s + p.total, 0))} en {periodo} días
                </span>
              </div>
              <div className="divide-y divide-gray-50">
                {topProductos.map((p, i) => {
                  const pct = Math.round((p.total / maxTotal) * 100)
                  return (
                    <div key={p.codigo || p.nombre} className="px-4 py-2.5">
                      <div className="flex items-center justify-between gap-2 mb-1.5">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-xs font-bold text-gray-400 w-5 flex-shrink-0 text-right">
                            {i + 1}
                          </span>
                          <span className="text-sm text-gray-800 truncate">{p.nombre}</span>
                        </div>
                        <div className="flex-shrink-0 text-right">
                          <span className="text-sm font-semibold text-gray-700">
                            {fmtCOP(p.total)}
                          </span>
                          <span className="text-xs text-gray-400 ml-1.5">
                            {Math.round(p.cantidad)} un.
                          </span>
                        </div>
                      </div>
                      <div className="h-1 bg-gray-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-forest rounded-full"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        {/* === Estado del stock === */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-bold text-gray-700 flex items-center gap-2">
              <TrendingDown size={16} className="text-amber-600" />
              Estado del stock
            </h2>
            {loadingInv && (
              <RefreshCw size={14} className="text-gray-400 animate-spin" />
            )}
          </div>

          {loadingInv && (
            <p className="text-sm text-gray-400 animate-pulse py-8 text-center">Cargando…</p>
          )}

          {sugerencia && !loadingInv && (
            <div className="space-y-2">
              {urgentes.length > 0 && (
                <StockSection
                  title="Urgente / Agotado"
                  items={urgentes}
                  titleColor="text-red-600"
                  defaultOpen
                />
              )}

              {porPedir.length > 0 && (
                <StockSection
                  title="Pedir hoy"
                  items={porPedir}
                  titleColor="text-amber-600"
                  defaultOpen={urgentes.length === 0}
                />
              )}

              {resto.length > 0 && (
                <StockSection
                  title="Stock suficiente"
                  items={resto}
                  titleColor="text-gray-500"
                  defaultOpen={urgentes.length === 0 && porPedir.length === 0}
                />
              )}

              {urgentes.length === 0 && porPedir.length === 0 && (
                <div className="flex items-center gap-2 text-sm text-green-600 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
                  <CheckCircle2 size={16} />
                  Todo el inventario tiene stock suficiente para los próximos días
                </div>
              )}

              <button
                onClick={() => navigate('/pedidos-admin')}
                className="w-full flex items-center justify-center gap-2 border-2 border-amber-400 text-amber-700 font-semibold text-sm px-4 py-2.5 rounded-xl hover:bg-amber-50 transition-colors mt-1"
              >
                <ShoppingCart size={15} />
                Ver pedido sugerido →
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Calibración */}
      {sugerencia && tiendaId !== null && allItems.length > 0 && (
        <CalibracionSection
          items={allItems}
          tiendaId={tiendaId}
          onSaved={() => {
            // Refrescar sugerencia para reflejar nuevos mínimos
            api.get('/pedidos/sugerencia', { params: { tienda_id: tiendaId } })
              .then(r => setSugerencia(r.data))
              .catch(() => {})
          }}
        />
      )}
    </div>
  )
}
