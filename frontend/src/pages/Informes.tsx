import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { BarChart2, ArrowUpDown, Package, ChevronDown, ChevronUp, UserCheck, Clock, AlertTriangle, Download } from 'lucide-react'
import DifferenceBadge from '../components/DifferenceBadge'

interface Sede { id: number; nombre: string }

// ─── Exportar Excel (lazy-load SheetJS) ──────────────────────────────────────
async function exportarExcel(nombre: string, cabeceras: string[], filas: (string | number | null)[][]) {
  const XLSX = await import('xlsx')
  const ws = XLSX.utils.aoa_to_sheet([cabeceras, ...filas])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Datos')
  XLSX.writeFile(wb, `${nombre}.xlsx`)
}

function BtnExcel({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white transition-colors"
      style={{ background: 'oklch(48% 0.15 155)' }}
      title="Descargar Excel"
    >
      <Download size={14} /> Excel
    </button>
  )
}

type Tab = 'ventas' | 'movimientos' | 'inventario' | 'cuadres' | 'turnos'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
const fmtN = (v: number, dec = 2) => v.toLocaleString('es-CO', { minimumFractionDigits: dec, maximumFractionDigits: dec })

function hoy() {
  return new Date().toISOString().slice(0, 10)
}
function inicioMes() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

// ─── Ventas ──────────────────────────────────────────────────────────────────
interface FilaVenta { fecha: string; venta_total: number; nota_credito: number; vales: number; tarjetas: number; efectivo: number; n_registros: number }
interface TotalesVenta { venta_total: number; nota_credito: number; vales: number; tarjetas: number; efectivo: number; n_registros: number }

function TabVentas({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaVenta[]>([])
  const [totales, setTotales] = useState<TotalesVenta | null>(null)
  const [loading, setLoading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/ventas', { params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta } })
      setFilas(data.filas)
      setTotales(data.totales)
    } finally { setLoading(false) }
  }

  const exportar = () => exportarExcel(
    `ventas_${desde}_${hasta}`,
    ['Fecha', 'Venta Total', 'Nota Crédito', 'Vales', 'Tarjetas', 'Efectivo', 'Registros'],
    [
      ...filas.map(f => [f.fecha, f.venta_total, f.nota_credito, f.vales, f.tarjetas, f.efectivo, f.n_registros]),
      ...(totales ? [['TOTAL', totales.venta_total, totales.nota_credito, totales.vales, totales.tarjetas, totales.efectivo, totales.n_registros]] : []),
    ]
  )

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {filas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Fecha</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Venta total</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">N. crédito</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Vales</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Tarjetas</th>
                  <th className="text-right px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Efectivo</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filas.map(f => (
                  <tr key={f.fecha} className="hover:bg-gray-50">
                    <td className="px-4 py-2.5 font-medium text-gray-700">{f.fecha}</td>
                    <td className="px-4 py-2.5 text-right font-bold text-gray-800">{fmt(f.venta_total)}</td>
                    <td className="px-4 py-2.5 text-right text-red-600">{f.nota_credito > 0 ? fmt(f.nota_credito) : '—'}</td>
                    <td className="px-4 py-2.5 text-right text-orange-600">{f.vales > 0 ? fmt(f.vales) : '—'}</td>
                    <td className="px-4 py-2.5 text-right text-blue-600">{f.tarjetas > 0 ? fmt(f.tarjetas) : '—'}</td>
                    <td className="px-4 py-2.5 text-right text-green-700 font-semibold">{fmt(f.efectivo)}</td>
                  </tr>
                ))}
              </tbody>
              {totales && (
                <tfoot>
                  <tr className="bg-amber-50 border-t-2 border-amber-200 font-bold">
                    <td className="px-4 py-2.5 text-xs text-amber-700 uppercase">Total ({totales.n_registros} registros)</td>
                    <td className="px-4 py-2.5 text-right text-amber-800">{fmt(totales.venta_total)}</td>
                    <td className="px-4 py-2.5 text-right text-red-700">{fmt(totales.nota_credito)}</td>
                    <td className="px-4 py-2.5 text-right text-orange-700">{fmt(totales.vales)}</td>
                    <td className="px-4 py-2.5 text-right text-blue-700">{fmt(totales.tarjetas)}</td>
                    <td className="px-4 py-2.5 text-right text-green-800">{fmt(totales.efectivo)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}

      {filas.length === 0 && totales && (
        <p className="text-sm text-gray-400 text-center py-6">Sin registros en el período seleccionado.</p>
      )}
    </div>
  )
}

// ─── Movimientos ─────────────────────────────────────────────────────────────
interface Movimiento {
  fecha: string; tipo: string; subtipo: string | null
  producto: string; unidad: string; cantidad: number
  usuario: string; motivo: string
}

const MOV_CFG: Record<string, { label: string; bg: string; text: string; sign: string }> = {
  entrada:    { label: 'Entrada',    bg: '#dcfce7', text: '#166534', sign: '+' },
  ajuste:     { label: 'Ajuste',     bg: '#dbeafe', text: '#1d4ed8', sign: '='  },
  merma:      { label: 'Merma',      bg: '#fee2e2', text: '#dc2626', sign: '−' },
  pasteleria: { label: 'Pastelería', bg: '#f3e8ff', text: '#7c3aed', sign: '−' },
}
const MOV_SUBTIPO: Record<string, string> = { consumo: 'Consumo', traslado: 'Traslado', 'daño': 'Daño' }
const FILTROS_MOV = [
  { key: 'todos',      label: 'Todos'      },
  { key: 'entrada',    label: 'Entradas'   },
  { key: 'merma',      label: 'Mermas'     },
  { key: 'ajuste',     label: 'Ajustes'    },
  { key: 'pasteleria', label: 'Pastelería' },
]

function TabMovimientos({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [movimientos, setMovimientos] = useState<Movimiento[] | null>(null)
  const [conteos, setConteos] = useState<Record<string, number>>({})
  const [filtro, setFiltro] = useState<string>('todos')
  const [loading, setLoading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/movimientos', {
        params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta },
      })
      setMovimientos(data.movimientos)
      setConteos(data.conteos)
      setFiltro('todos')
    } finally { setLoading(false) }
  }

  const filtrados = movimientos?.filter(m => filtro === 'todos' || m.tipo === filtro) ?? []

  const exportar = () => {
    if (!filtrados.length) return
    exportarExcel(`movimientos_${desde}_${hasta}`,
      ['Fecha', 'Tipo', 'Subtipo', 'Producto', 'Unidad', 'Cantidad', 'Usuario', 'Motivo'],
      filtrados.map(m => [m.fecha, m.tipo, m.subtipo ?? '', m.producto, m.unidad, m.cantidad, m.usuario, m.motivo]))
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filtrados.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {/* Chips de filtro */}
      {movimientos !== null && (
        <div className="flex gap-1.5 flex-wrap">
          {FILTROS_MOV.filter(f => f.key === 'todos' || (conteos[f.key] ?? 0) > 0).map(f => (
            <button key={f.key}
              onClick={() => setFiltro(f.key)}
              className={`px-3 py-1 rounded-full text-xs font-semibold border transition-all ${
                filtro === f.key
                  ? 'bg-gray-800 text-white border-gray-800'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'
              }`}>
              {f.label}{(conteos[f.key] ?? 0) > 0 ? ` (${conteos[f.key]})` : ''}
            </button>
          ))}
        </div>
      )}

      {/* Timeline */}
      {filtrados.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-50">
          {filtrados.map((m, i) => {
            const cfg = MOV_CFG[m.tipo] ?? { label: m.tipo, bg: '#f3f4f6', text: '#374151', sign: '' }
            return (
              <div key={i} className="px-4 py-3 flex items-start gap-3">
                <div className="shrink-0 pt-0.5">
                  <span className="text-xs px-2 py-0.5 rounded-full font-semibold whitespace-nowrap"
                    style={{ background: cfg.bg, color: cfg.text }}>
                    {cfg.label}{m.subtipo ? ` · ${MOV_SUBTIPO[m.subtipo] ?? m.subtipo}` : ''}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-800">{m.producto}</p>
                  <p className="text-xs text-gray-400">{m.fecha} · {m.usuario}</p>
                  {m.motivo && <p className="text-xs text-gray-500 truncate">{m.motivo}</p>}
                </div>
                <span className="text-sm font-bold font-mono shrink-0" style={{ color: cfg.text }}>
                  {cfg.sign}{m.cantidad} {m.unidad}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {movimientos !== null && filtrados.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin movimientos en el período.</p>
      )}
    </div>
  )
}

// ─── Inventario (Rotación de stock) ─────────────────────────────────────────
function TabInventario({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [rotFilas, setRotFilas] = useState<FilaRotacion[] | null>(null)
  const [resumen, setResumen] = useState<ResumenRotacion | null>(null)
  const [filtroEstado, setFiltroEstado] = useState<string>('todos')
  const [loading, setLoading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/rotacion', {
        params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta },
      })
      setRotFilas(data.filas)
      setResumen(data.resumen)
      setFiltroEstado('todos')
    } finally { setLoading(false) }
  }

  const rotFiltradas = rotFilas?.filter(f => filtroEstado === 'todos' || f.estado === filtroEstado) ?? []

  const exportar = () => {
    if (!rotFilas) return
    exportarExcel(`inventario_${desde}_${hasta}`,
      ['Producto', 'Unidad', 'Stock actual', 'Stock mínimo', 'Entradas', 'Salidas', 'Rotación', 'Estado'],
      rotFilas.map(f => [f.producto, f.unidad, f.stock_actual, f.stock_minimo, f.entradas, f.salidas, f.rotacion ?? '', f.estado]))
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {rotFilas && rotFilas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {resumen && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              { key: 'activos',        label: 'Activos',        val: resumen.activos,        color: 'text-green-700' },
              { key: 'estancados',     label: 'Estancados',     val: resumen.estancados,     color: resumen.estancados > 0 ? 'text-orange-600' : 'text-gray-800' },
              { key: 'sin_movimiento', label: 'Sin movimiento', val: resumen.sin_movimiento, color: 'text-gray-500' },
              { key: 'bajo_minimo',    label: 'Bajo mínimo',    val: resumen.bajo_minimo,    color: resumen.bajo_minimo > 0 ? 'text-red-600' : 'text-gray-800' },
            ].map(({ key, label, val, color }) => (
              <button key={key}
                onClick={() => setFiltroEstado(filtroEstado === key ? 'todos' : key)}
                className={`bg-white border rounded-xl p-3 text-center transition-all ${filtroEstado === key ? 'border-amber-400' : 'border-gray-200'}`}>
                <p className="text-xs text-gray-400">{label}</p>
                <p className={`text-lg font-bold font-mono ${color}`}>{val}</p>
              </button>
            ))}
          </div>

          {rotFilas !== null && (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-400 uppercase">Producto</th>
                      <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Stock</th>
                      <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Entradas</th>
                      <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Salidas</th>
                      <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Rotación</th>
                      <th className="px-3 py-2.5"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {rotFiltradas.length === 0 && (
                      <tr><td colSpan={6} className="text-center text-sm text-gray-400 py-6">Sin productos con este filtro.</td></tr>
                    )}
                    {rotFiltradas.map(f => {
                      const cfg = ESTADO_CFG[f.estado] || ESTADO_CFG.sin_movimiento
                      return (
                        <tr key={f.producto_id} className="hover:bg-gray-50">
                          <td className="px-4 py-2.5">
                            <p className="font-medium text-gray-800 text-sm">{f.producto}</p>
                            <p className="text-xs text-gray-400">{f.unidad}</p>
                          </td>
                          <td className={`px-3 py-2.5 text-right font-mono font-bold text-sm ${f.alerta_min ? 'text-red-600' : 'text-gray-700'}`}>
                            {fmtN(f.stock_actual, 0)}
                            {f.alerta_min && <AlertTriangle size={10} className="inline ml-1 text-red-500" />}
                          </td>
                          <td className="px-3 py-2.5 text-right font-mono text-sm text-green-700">{fmtN(f.entradas, 0)}</td>
                          <td className="px-3 py-2.5 text-right font-mono text-sm text-blue-700">{fmtN(f.salidas, 0)}</td>
                          <td className="px-3 py-2.5 text-right font-mono text-sm text-gray-600">
                            {f.rotacion !== null ? `${f.rotacion}x` : '—'}
                          </td>
                          <td className="px-3 py-2.5">
                            <span className="text-xs px-1.5 py-0.5 rounded-md font-semibold whitespace-nowrap"
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
        </>
      )}

      {rotFilas !== null && rotFilas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin movimientos en el período.</p>
      )}
    </div>
  )
}

// ─── Cuadres + Baristas ───────────────────────────────────────────────────────
interface FilaEntrega {
  id: number; fecha_hora: string; usuario: string
  efectivo_esperado: number; efectivo_real: number; diferencia_efectivo: number
  ventas_tarjeta_bold: number; diferencia_tarjeta: number; imagen_url: string | null
}
interface TotalesEntrega { n_entregas: number; con_diferencia_efectivo: number; con_diferencia_tarjeta: number }
interface FilaBarista {
  usuario_id: number; nombre: string
  n_recibos: number; n_cierres: number
  n_diff_efectivo: number; n_diff_tarjeta: number
  suma_diff_efectivo: number; peor_diferencia: number
  ultimo_cuadre: string | null
}

function TabCuadres({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [cuadresFilas, setCuadresFilas] = useState<FilaEntrega[] | null>(null)
  const [cuadresTotales, setCuadresTotales] = useState<TotalesEntrega | null>(null)
  const [baristasFilas, setBaristasFilas] = useState<FilaBarista[] | null>(null)
  const [loading, setLoading] = useState(false)

  const cargar = async () => {
    setLoading(true)
    try {
      const params = { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta }
      const [entRes, barRes] = await Promise.all([
        api.get('/informes/entregas', { params }),
        api.get('/informes/baristas', { params }),
      ])
      setCuadresFilas(entRes.data.filas)
      setCuadresTotales(entRes.data.totales)
      setBaristasFilas(barRes.data.filas)
    } finally { setLoading(false) }
  }

  const exportar = () => {
    if (!cuadresFilas) return
    exportarExcel(`cuadres_llegada_${desde}_${hasta}`,
      ['Fecha/Hora', 'Barista', 'Efectivo esperado', 'Efectivo real', 'Diferencia efectivo', 'Total Bold', 'Diferencia Bold'],
      cuadresFilas.map(f => [f.fecha_hora, f.usuario, f.efectivo_esperado, f.efectivo_real, f.diferencia_efectivo, f.ventas_tarjeta_bold, f.diferencia_tarjeta]))
  }

  const totalCuadres = (f: FilaBarista) => f.n_recibos + f.n_cierres
  const pctDiff = (f: FilaBarista) => totalCuadres(f) > 0
    ? Math.round((f.n_diff_efectivo / totalCuadres(f)) * 100) : 0

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {cuadresFilas && cuadresFilas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {/* ── Desempeño por barista ── */}
      {baristasFilas !== null && baristasFilas.length > 0 && (
        <>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Desempeño por barista</p>
          <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
            {baristasFilas.map((f, i) => (
              <div key={f.usuario_id} className="px-4 py-3 flex items-center gap-3">
                <span className="text-sm font-mono text-gray-300 w-5 shrink-0">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-gray-800">{f.nombre}</p>
                  <p className="text-xs text-gray-400">
                    {f.n_recibos} llegadas · {f.n_cierres} cierres
                    {f.ultimo_cuadre && <span> · último {f.ultimo_cuadre}</span>}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  {f.n_diff_efectivo === 0 ? (
                    <span className="text-xs font-bold text-green-600 bg-green-50 px-2 py-0.5 rounded-full">Sin diferencias</span>
                  ) : (
                    <>
                      <span className="text-xs font-bold text-red-600 bg-red-50 px-2 py-0.5 rounded-full">
                        {f.n_diff_efectivo} diff · {pctDiff(f)}%
                      </span>
                      <span className="text-xs text-gray-500">
                        Σ {fmt(f.suma_diff_efectivo)} · peor {fmt(f.peor_diferencia)}
                      </span>
                    </>
                  )}
                  {f.n_diff_tarjeta > 0 && (
                    <span className="text-xs text-blue-500">{f.n_diff_tarjeta} diff Bold</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* ── Cuadres de llegada ── */}
      {cuadresTotales && (
        <>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mt-2">Cuadres de llegada</p>
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
              <p className="text-xs text-gray-400">Total cuadres</p>
              <p className="text-lg font-bold text-gray-800">{cuadresTotales.n_entregas}</p>
            </div>
            <div className={`border rounded-xl p-3 text-center ${cuadresTotales.con_diferencia_efectivo > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
              <p className="text-xs text-gray-400">Diff. efectivo</p>
              <p className={`text-lg font-bold ${cuadresTotales.con_diferencia_efectivo > 0 ? 'text-red-700' : 'text-green-700'}`}>{cuadresTotales.con_diferencia_efectivo}</p>
            </div>
            <div className={`border rounded-xl p-3 text-center ${cuadresTotales.con_diferencia_tarjeta > 0 ? 'bg-red-50 border-red-200' : 'bg-green-50 border-green-200'}`}>
              <p className="text-xs text-gray-400">Diff. Bold</p>
              <p className={`text-lg font-bold ${cuadresTotales.con_diferencia_tarjeta > 0 ? 'text-red-700' : 'text-green-700'}`}>{cuadresTotales.con_diferencia_tarjeta}</p>
            </div>
          </div>
        </>
      )}

      {cuadresFilas !== null && cuadresFilas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="divide-y divide-gray-50">
            {cuadresFilas.map(f => (
              <div key={f.id} className="px-4 py-3 flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-400">{f.fecha_hora}</p>
                  <p className="text-sm font-semibold text-gray-700">{f.usuario}</p>
                  <p className="text-xs text-gray-500">
                    Real: <span className="font-semibold text-gray-800">{fmt(f.efectivo_real)}</span>
                    {' '}· esp: {fmt(f.efectivo_esperado)}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <DifferenceBadge diferencia={f.diferencia_efectivo} />
                  {f.diferencia_tarjeta !== 0 && (
                    <span className="text-xs text-red-600 font-semibold">
                      Bold Δ{f.diferencia_tarjeta > 0 ? '+' : ''}{fmt(f.diferencia_tarjeta)}
                    </span>
                  )}
                  {f.imagen_url && (
                    <a href={f.imagen_url} target="_blank" rel="noreferrer"
                      className="text-xs text-blue-500 hover:underline">foto</a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {cuadresFilas !== null && cuadresFilas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin cuadres de llegada en el período.</p>
      )}
    </div>
  )
}

// ─── Turnos ───────────────────────────────────────────────────────────────────
interface FilaTurno {
  id: number; fecha_apertura: string; fecha_cierre: string
  usuario_apertura: string; usuario_cierre: string
  base_real: number; total_ventas: number; total_efectivo: number; total_tarjeta: number
  diferencia_cierre: number; diferencia_tarjeta: number; justificacion_cierre: string | null
}
interface TotalesTornos {
  n_turnos: number; total_ventas: number; total_efectivo: number; total_tarjeta: number; con_diferencia: number
}

function TabTurnos({ tiendaId }: { tiendaId: number }) {
  const [desde, setDesde] = useState(inicioMes())
  const [hasta, setHasta] = useState(hoy())
  const [filas, setFilas] = useState<FilaTurno[] | null>(null)
  const [totales, setTotales] = useState<TotalesTornos | null>(null)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/informes/turnos', { params: { tienda_id: tiendaId, fecha_desde: desde, fecha_hasta: hasta } })
      setFilas(data.filas)
      setTotales(data.totales)
      setExpanded(new Set())
    } finally { setLoading(false) }
  }

  const toggle = (id: number) => setExpanded(prev => {
    const s = new Set(prev)
    s.has(id) ? s.delete(id) : s.add(id)
    return s
  })

  const exportar = () => {
    if (!filas) return
    exportarExcel(`turnos_${desde}_${hasta}`,
      ['Apertura', 'Cierre', 'Abrió', 'Cerró', 'Base real', 'Total ventas', 'Efectivo', 'Tarjeta', 'Diff. cierre', 'Diff. Bold', 'Justificación'],
      filas.map(f => [f.fecha_apertura, f.fecha_cierre, f.usuario_apertura, f.usuario_cierre,
        f.base_real, f.total_ventas, f.total_efectivo, f.total_tarjeta,
        f.diferencia_cierre, f.diferencia_tarjeta, f.justificacion_cierre ?? '']))
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap items-end">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Desde</label>
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <div>
          <label className="text-xs text-gray-500 block mb-1">Hasta</label>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>
        <button onClick={cargar} disabled={loading}
          className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-4 py-2 rounded-lg text-sm">
          {loading ? 'Cargando...' : 'Consultar'}
        </button>
        {filas && filas.length > 0 && <BtnExcel onClick={exportar} />}
      </div>

      {totales && totales.n_turnos > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Turnos</p>
            <p className="text-lg font-bold text-gray-800">{totales.n_turnos}</p>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Ventas totales</p>
            <p className="text-base font-bold text-gray-800">{fmt(totales.total_ventas)}</p>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Efectivo</p>
            <p className="text-base font-bold text-green-700">{fmt(totales.total_efectivo)}</p>
          </div>
          <div className={`border rounded-xl p-3 text-center ${totales.con_diferencia > 0 ? 'bg-red-50 border-red-200' : 'bg-white border-gray-200'}`}>
            <p className="text-xs text-gray-400">Con diferencia</p>
            <p className={`text-lg font-bold ${totales.con_diferencia > 0 ? 'text-red-700' : 'text-green-700'}`}>{totales.con_diferencia}</p>
          </div>
        </div>
      )}

      {filas !== null && filas.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
          {filas.map(f => (
            <div key={f.id}>
              <button onClick={() => toggle(f.id)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 text-left">
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-400">{f.fecha_apertura} → {f.fecha_cierre}</p>
                  <p className="text-sm font-semibold text-gray-700 truncate">{f.usuario_apertura}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-sm font-bold text-gray-800">{fmt(f.total_ventas)}</span>
                  {f.diferencia_cierre !== 0
                    ? <span className="text-xs font-bold text-red-600">Δ{fmt(f.diferencia_cierre)}</span>
                    : <span className="text-xs font-bold text-green-600">✓</span>
                  }
                  {expanded.has(f.id) ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                </div>
              </button>
              {expanded.has(f.id) && (
                <div className="bg-gray-50 border-t border-gray-100 px-4 py-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                  <div><span className="text-gray-400">Base real:</span> <span className="font-semibold">{fmt(f.base_real)}</span></div>
                  <div><span className="text-gray-400">Efectivo:</span> <span className="font-semibold text-green-700">{fmt(f.total_efectivo)}</span></div>
                  <div><span className="text-gray-400">Tarjeta:</span> <span className="font-semibold text-blue-700">{fmt(f.total_tarjeta)}</span></div>
                  <div><span className="text-gray-400">Diff. Bold:</span> <span className={`font-semibold ${f.diferencia_tarjeta !== 0 ? 'text-red-600' : 'text-green-600'}`}>{f.diferencia_tarjeta !== 0 ? fmt(f.diferencia_tarjeta) : '✓'}</span></div>
                  <div><span className="text-gray-400">Cierre:</span> <span className="font-semibold">{f.usuario_cierre}</span></div>
                  {f.justificacion_cierre && (
                    <div className="col-span-2"><span className="text-gray-400">Justif.:</span> <span className="italic text-gray-600">{f.justificacion_cierre}</span></div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {filas !== null && filas.length === 0 && !loading && (
        <p className="text-sm text-gray-400 text-center py-6">Sin turnos cerrados en el período.</p>
      )}
    </div>
  )
}

// ─── Rotación (interfaces usadas por TabInventario) ───────────────────────────
interface FilaRotacion {
  producto_id: number; producto: string; categoria: string; unidad: string
  stock_actual: number; stock_minimo: number; entradas: number; salidas: number
  rotacion: number | null; estado: string; alerta_min: boolean
}
interface ResumenRotacion { activos: number; estancados: number; sin_movimiento: number; agotados: number; bajo_minimo: number }

const ESTADO_CFG: Record<string, { label: string; bg: string; text: string }> = {
  activo:          { label: 'Activo',         bg: 'oklch(93% 0.015 155)', text: 'oklch(30% 0.10 155)' },
  estancado:       { label: 'Estancado',       bg: 'oklch(95% 0.015 60)',  text: 'oklch(38% 0.12 55)'  },
  agotado:         { label: 'Agotado',         bg: 'oklch(96% 0.015 20)',  text: 'oklch(38% 0.16 25)'  },
  sin_movimiento:  { label: 'Sin movimiento',  bg: 'oklch(95% 0.005 60)',  text: 'oklch(55% 0.01 60)'  },
}




// ─── Página principal ─────────────────────────────────────────────────────────
export default function Informes() {
  const { user } = useAuth()
  const isAdmin = user?.rol === 'admin'
  const [tab, setTab] = useState<Tab>('ventas')
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)

  useEffect(() => {
    if (isAdmin) {
      api.get('/auth/tiendas').then(({ data }) => {
        setSedes(data)
        if (!tiendaId && data.length > 0) setTiendaId(data[0].id)
      }).catch(() => {})
    }
  }, [isAdmin])

  if (!tiendaId) return (
    <div className="text-center py-12 text-sm text-gray-400">Cargando sedes…</div>
  )

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'ventas',       label: 'Ventas',       icon: <BarChart2 size={14} /> },
    { id: 'turnos',       label: 'Turnos',       icon: <Clock size={14} /> },
    { id: 'cuadres',      label: 'Cuadres',      icon: <UserCheck size={14} /> },
    { id: 'movimientos',  label: 'Movimientos',  icon: <ArrowUpDown size={14} /> },
    { id: 'inventario',   label: 'Inventario',   icon: <Package size={14} /> },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-base font-bold text-gray-800">Informes</h1>

        {/* Selector de sede (solo admin) */}
        {isAdmin && sedes.length > 1 && (
          <div className="flex gap-1.5">
            {sedes.map(s => (
              <button key={s.id} onClick={() => setTiendaId(s.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                  tiendaId === s.id
                    ? 'bg-amber-600 text-white border-amber-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-amber-400'
                }`}>
                {s.nombre}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              tab === t.id ? 'border-amber-500 text-amber-700' : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {tab === 'ventas'      && <TabVentas      key={tiendaId} tiendaId={tiendaId} />}
      {tab === 'turnos'      && <TabTurnos      key={tiendaId} tiendaId={tiendaId} />}
      {tab === 'cuadres'     && <TabCuadres     key={tiendaId} tiendaId={tiendaId} />}
      {tab === 'movimientos' && <TabMovimientos key={tiendaId} tiendaId={tiendaId} />}
      {tab === 'inventario'  && <TabInventario  key={tiendaId} tiendaId={tiendaId} />}
    </div>
  )
}
