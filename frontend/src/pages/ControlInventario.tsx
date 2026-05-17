import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  AlertTriangle, CheckCircle2, TrendingUp, TrendingDown,
  ShoppingCart, RefreshCw, ChevronDown, ChevronUp, Layers,
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

interface VentasSiigo {
  productos: Record<string, ProductoVenta>
  total_ventas: number
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

// ─── Página principal ─────────────────────────────────────────────────────────

export default function ControlInventario() {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [sedes, setSedes] = useState<{ id: number; nombre: string }[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)

  const [sugerencia, setSugerencia] = useState<Sugerencia | null>(null)
  const [loadingInv, setLoadingInv] = useState(false)

  const [ventas, setVentas] = useState<VentasSiigo | null>(null)
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

  // Siigo ventas
  useEffect(() => {
    setLoadingVentas(true)
    setErrorVentas(null)
    setVentas(null)
    api.get('/siigo/ventas-por-producto', {
      params: { fecha_desde: isoHace(periodo), fecha_hasta: isoHoy() },
    })
      .then(r => setVentas(r.data))
      .catch(e => setErrorVentas(e.response?.data?.detail ?? 'Error consultando Siigo'))
      .finally(() => setLoadingVentas(false))
  }, [periodo])

  const topProductos = ventas
    ? Object.values(ventas.productos)
        .sort((a, b) => b.total - a.total)
        .slice(0, 15)
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
            Stock actual · consumo 14 días · ventas Siigo
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

        {/* === Lo que más se vende (Siigo) === */}
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
              Consultando Siigo…
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
                  {Object.keys(ventas.productos).length} productos
                </span>
                <span className="text-xs font-semibold text-gray-700">
                  {fmtCOP(ventas.total_ventas)} en {periodo} días
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
    </div>
  )
}
