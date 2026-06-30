import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Cake, AlertTriangle, Check, X } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface Producto { id: number; nombre: string; categoria: string }
interface Lote {
  id: number; tienda_id: number; tienda_nombre: string | null
  producto_id: number; producto_nombre: string; cantidad: number
  numero_lote: string | null; fecha_vencimiento: string | null
  fecha_registro: string; activo: boolean; estado: string
  dias_en_stock?: number; alerta_rotacion?: boolean
}

function parseUTC(s: string | null): Date | null {
  if (!s) return null
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

const ESTADO_CFG: Record<string, { label: string; bg: string; text: string }> = {
  vencido:    { label: 'Vencido',     bg: 'bg-red-100',    text: 'text-red-700' },
  por_vencer: { label: 'Por vencer',  bg: 'bg-amber-100',  text: 'text-amber-700' },
  vigente:    { label: 'Vigente',     bg: 'bg-green-100',  text: 'text-green-700' },
  sin_fecha:  { label: 'Sin fecha',   bg: 'bg-gray-100',   text: 'text-gray-500' },
}

function fmtFecha(s: string | null) {
  if (!s) return '—'
  const d = parseUTC(s)
  if (!d) return '—'
  return d.toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: '2-digit' })
}

function defaultFechaVencimiento() {
  const d = new Date()
  d.setDate(d.getDate() + 3)
  return d.toISOString().slice(0, 10)
}

// ─── Vista Admin ───────────────────────────────────────────────────────────────
function PasteleriaAdmin() {
  const [lotes, setLotes] = useState<Lote[]>([])
  const [loading, setLoading] = useState(true)
  const [filtro, setFiltro] = useState<'todos' | 'alertas'>('todos')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/pasteleria/admin/lotes')
      setLotes(data)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const lotesVis = filtro === 'alertas'
    ? lotes.filter(l => l.estado === 'vencido' || l.estado === 'por_vencer' || l.alerta_rotacion)
    : lotes

  const vencidos = lotes.filter(l => l.estado === 'vencido').length
  const porVencer = lotes.filter(l => l.estado === 'por_vencer').length

  if (loading) return <div className="flex justify-center py-16"><p className="text-sm text-gray-400">Cargando...</p></div>

  return (
    <div className="space-y-4">
      {/* KPIs */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-white border border-gray-200 rounded-xl p-3 text-center">
          <p className="text-xs text-gray-400">Lotes activos</p>
          <p className="text-xl font-bold text-gray-800">{lotes.length}</p>
        </div>
        <div className={`border rounded-xl p-3 text-center ${vencidos > 0 ? 'bg-red-50 border-red-200' : 'bg-white border-gray-200'}`}>
          <p className="text-xs text-gray-400">Vencidos</p>
          <p className={`text-xl font-bold ${vencidos > 0 ? 'text-red-700' : 'text-green-700'}`}>{vencidos}</p>
        </div>
        <div className={`border rounded-xl p-3 text-center ${porVencer > 0 ? 'bg-amber-50 border-amber-200' : 'bg-white border-gray-200'}`}>
          <p className="text-xs text-gray-400">Por vencer</p>
          <p className={`text-xl font-bold ${porVencer > 0 ? 'text-amber-700' : 'text-green-700'}`}>{porVencer}</p>
        </div>
      </div>

      {/* Filtro */}
      <div className="flex gap-2">
        {(['todos', 'alertas'] as const).map(f => (
          <button key={f} onClick={() => setFiltro(f)}
            className={`text-xs px-3 py-1.5 rounded-lg font-semibold transition-colors ${
              filtro === f ? 'bg-amber-600 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
            }`}>
            {f === 'todos' ? 'Todos' : 'Con alertas'}
          </button>
        ))}
      </div>

      {lotesVis.length === 0 && (
        <p className="text-sm text-gray-400 text-center py-8">
          {filtro === 'alertas' ? 'Sin alertas activas.' : 'Sin lotes registrados.'}
        </p>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-400 uppercase">Producto</th>
                <th className="text-left px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Sede</th>
                <th className="text-right px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Cant.</th>
                <th className="text-left px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Lote</th>
                <th className="text-center px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Vencimiento</th>
                <th className="text-center px-3 py-2.5 text-xs font-semibold text-gray-400 uppercase">Estado</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {lotesVis.map(l => {
                const cfg = ESTADO_CFG[l.estado] ?? ESTADO_CFG.sin_fecha
                return (
                  <tr key={l.id} className={`hover:bg-gray-50 ${l.estado === 'vencido' ? 'bg-red-50' : ''}`}>
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-800">{l.producto_nombre}</p>
                      {l.alerta_rotacion && (
                        <p className="text-xs text-orange-500 font-medium">{l.dias_en_stock}d en stock</p>
                      )}
                    </td>
                    <td className="px-3 py-3 text-xs text-gray-500">{l.tienda_nombre ?? `T${l.tienda_id}`}</td>
                    <td className="px-3 py-3 text-right font-mono text-gray-700">{l.cantidad}</td>
                    <td className="px-3 py-3 text-xs text-gray-600 font-mono">{l.numero_lote ?? '—'}</td>
                    <td className="px-3 py-3 text-center text-xs font-semibold text-gray-700">{fmtFecha(l.fecha_vencimiento)}</td>
                    <td className="px-3 py-3 text-center">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${cfg.bg} ${cfg.text}`}>
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
    </div>
  )
}

// ─── Vista Barista ─────────────────────────────────────────────────────────────
function PasteleriaBarista() {
  const { user } = useAuth()
  const [productos, setProductos] = useState<Producto[]>([])
  const [registros, setRegistros] = useState<Lote[]>([])
  const [productoId, setProductoId] = useState('')
  const [cantidad, setCantidad] = useState('')
  const [numeroLote, setNumeroLote] = useState('')
  const [fechaVenc, setFechaVenc] = useState(defaultFechaVencimiento())
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)
  const [cerrandoId, setCerrandoId] = useState<number | null>(null)

  const loadRegistros = async () => {
    if (!user?.tienda_id) return
    // /activos filtra activo==True (y trae campos de rotación); el endpoint sin /activos
    // ignora el flag, así que un lote recién cerrado reaparecía al recargar.
    const { data } = await api.get(`/pasteleria/tienda/${user.tienda_id}/activos`)
    setRegistros(data)
  }

  useEffect(() => {
    api.get('/inventario/productos')
      .then(r => setProductos(r.data.filter((p: Producto) => p.categoria === 'pasteleria')))
    loadRegistros()
  }, [user?.tienda_id])

  const registrar = async () => {
    setError(''); setSaving(true)
    try {
      await api.post('/pasteleria/', {
        tienda_id: user?.tienda_id,
        producto_id: Number(productoId),
        cantidad: Number(cantidad),
        numero_lote: numeroLote.trim() || null,
        fecha_vencimiento: new Date(fechaVenc + 'T23:59:00').toISOString(),
      })
      setProductoId(''); setCantidad(''); setNumeroLote('')
      setFechaVenc(defaultFechaVencimiento())
      setSaved(true); setTimeout(() => setSaved(false), 2000)
      loadRegistros()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
    finally { setSaving(false) }
  }

  const cerrar = async (id: number) => {
    setCerrandoId(id)
    try {
      await api.patch(`/pasteleria/${id}/cerrar?tienda_id=${user?.tienda_id}`)
      loadRegistros()
    } finally { setCerrandoId(null) }
  }

  const vencidos = registros.filter(r => r.estado === 'vencido')
  const porVencer = registros.filter(r => r.estado === 'por_vencer')

  return (
    <BaristaLayout title="Pastelería">
      <div className="space-y-5">
        <h1 className="text-xl font-bold text-gray-900">Pastelería</h1>

        {(vencidos.length > 0 || porVencer.length > 0) && (
          <div className="bg-amber-50 border border-amber-200 rounded-2xl px-4 py-3">
            <div className="flex items-center gap-2">
              <AlertTriangle size={14} className="text-amber-600" />
              <p className="text-xs font-bold text-amber-700">
                {vencidos.length > 0 && `${vencidos.length} vencido${vencidos.length > 1 ? 's' : ''}`}
                {vencidos.length > 0 && porVencer.length > 0 && ' · '}
                {porVencer.length > 0 && `${porVencer.length} por vencer`}
              </p>
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}
        {saved && (
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">
            <Check size={14} /> Registro guardado
          </div>
        )}

        {/* Formulario */}
        <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
          <p className="text-sm font-semibold text-gray-700">Nuevo lote</p>

          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Producto</label>
            <select value={productoId} onChange={e => setProductoId(e.target.value)}
              className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-amber-400 bg-white transition-colors">
              <option value="">Selecciona...</option>
              {productos.map(p => <option key={p.id} value={p.id}>{p.nombre}</option>)}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Cantidad</label>
            <input type="number" inputMode="numeric" step="1" min="0" value={cantidad} onChange={e => setCantidad(e.target.value)}
              placeholder="0"
              className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-xl font-bold text-center focus:outline-none focus:border-amber-400 transition-colors" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Número de lote</label>
              <input type="text" value={numeroLote} onChange={e => setNumeroLote(e.target.value)}
                placeholder="Ej: L-240, 001..."
                className="w-full border-2 border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400 transition-colors" />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Fecha de vencimiento</label>
              <input type="date" value={fechaVenc} onChange={e => setFechaVenc(e.target.value)}
                className="w-full border-2 border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400 transition-colors" />
            </div>
          </div>

          <button onClick={registrar} disabled={!productoId || !cantidad || !fechaVenc || saving}
            className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-3.5 rounded-xl text-sm flex items-center justify-center gap-2 transition-colors">
            <Cake size={16} />
            {saving ? 'Guardando...' : 'Registrar lote'}
          </button>
        </div>

        {/* Lotes activos */}
        {registros.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Lotes activos</p>
            </div>
            <div className="divide-y divide-gray-50">
              {registros.map(r => {
                const cfg = ESTADO_CFG[r.estado] ?? ESTADO_CFG.sin_fecha
                return (
                  <div key={r.id} className={`px-4 py-3 flex items-center gap-3 ${
                    r.estado === 'vencido' ? 'bg-red-50' : r.estado === 'por_vencer' ? 'bg-amber-50' : ''
                  }`}>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-gray-800">{r.producto_nombre}</p>
                      <p className="text-xs text-gray-400">
                        {r.cantidad} ud
                        {r.numero_lote && <> · Lote: <span className="font-mono">{r.numero_lote}</span></>}
                        {r.fecha_vencimiento && <> · Vence: {fmtFecha(r.fecha_vencimiento)}</>}
                      </p>
                    </div>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${cfg.bg} ${cfg.text}`}>
                      {cfg.label}
                    </span>
                    <button
                      onClick={() => cerrar(r.id)}
                      disabled={cerrandoId === r.id}
                      title="Marcar lote como terminado"
                      className="w-7 h-7 rounded-lg bg-gray-100 hover:bg-red-100 text-gray-400 hover:text-red-500 flex items-center justify-center shrink-0 transition-colors">
                      <X size={13} />
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </BaristaLayout>
  )
}

export default function Pasteleria() {
  const { user } = useAuth()
  if (user?.rol === 'admin') return <PasteleriaAdmin />
  return <PasteleriaBarista />
}
