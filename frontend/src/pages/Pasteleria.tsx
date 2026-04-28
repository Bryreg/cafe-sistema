import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Cake, AlertTriangle, Check } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface Producto { id: number; nombre: string; categoria: string }
interface Registro {
  id: number; producto_nombre: string; cantidad: number
  fecha_frescura: string; fecha_registro: string
}

function parseUTC(s: string): Date {
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

function frescoLabel(fecha: string) {
  const diff = (parseUTC(fecha).getTime() - Date.now()) / 1000 / 60 / 60
  if (diff < 0) return { label: 'Vencido', color: 'text-red-600 bg-red-100' }
  if (diff < 4) return { label: 'Por vencer', color: 'text-amber-700 bg-amber-100' }
  return { label: 'Fresco', color: 'text-green-700 bg-green-100' }
}

function defaultFrescura() {
  const d = new Date()
  d.setHours(d.getHours() + 8)
  return d.toISOString().slice(0, 16)
}

export default function Pasteleria() {
  const { user } = useAuth()
  const [productos, setProductos] = useState<Producto[]>([])
  const [registros, setRegistros] = useState<Registro[]>([])
  const [productoId, setProductoId] = useState('')
  const [cantidad, setCantidad] = useState('')
  const [fechaFrescura, setFechaFrescura] = useState(defaultFrescura())
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)

  const loadRegistros = async () => {
    if (!user?.tienda_id) return
    const { data } = await api.get(`/pasteleria/tienda/${user.tienda_id}`)
    setRegistros(data)
  }

  useEffect(() => {
    api.get('/inventario/productos')
      .then(r => setProductos(r.data.filter((p: Producto) => p.categoria === 'pasteleria')))
    loadRegistros()
  }, [user])

  const registrar = async () => {
    setError(''); setSaving(true)
    try {
      await api.post('/pasteleria/', {
        tienda_id: user?.tienda_id,
        producto_id: Number(productoId),
        cantidad: Number(cantidad),
        fecha_frescura: new Date(fechaFrescura).toISOString(),
      })
      setProductoId(''); setCantidad(''); setFechaFrescura(defaultFrescura())
      setSaved(true); setTimeout(() => setSaved(false), 2000)
      loadRegistros()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
    finally { setSaving(false) }
  }

  const vencidos = registros.filter(r => parseUTC(r.fecha_frescura) < new Date())
  const porVencer = registros.filter(r => {
    const diff = (parseUTC(r.fecha_frescura).getTime() - Date.now()) / 3600000
    return diff >= 0 && diff < 4
  })

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
          <p className="text-sm font-semibold text-gray-700">Nuevo registro</p>

          <div>
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Producto</label>
            <select value={productoId} onChange={e => setProductoId(e.target.value)}
              className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-amber-400 bg-white transition-colors">
              <option value="">Selecciona...</option>
              {productos.map(p => <option key={p.id} value={p.id}>{p.nombre}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Cantidad</label>
              <input type="number" value={cantidad} onChange={e => setCantidad(e.target.value)}
                placeholder="0"
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-3 text-xl font-bold text-center focus:outline-none focus:border-amber-400 transition-colors" />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">Frescura hasta</label>
              <input type="datetime-local" value={fechaFrescura} onChange={e => setFechaFrescura(e.target.value)}
                className="w-full border-2 border-gray-200 rounded-xl px-3 py-2.5 text-xs focus:outline-none focus:border-amber-400 transition-colors" />
            </div>
          </div>

          <button onClick={registrar} disabled={!productoId || !cantidad || !fechaFrescura || saving}
            className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-3.5 rounded-xl text-sm flex items-center justify-center gap-2 transition-colors">
            <Cake size={16} />
            {saving ? 'Guardando...' : 'Registrar'}
          </button>
        </div>

        {/* Registros del día */}
        {registros.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Registros de hoy</p>
            </div>
            <div className="divide-y divide-gray-50">
              {registros.map(r => {
                const estado = frescoLabel(r.fecha_frescura)
                return (
                  <div key={r.id} className={`px-4 py-3 flex items-center justify-between ${
                    estado.label === 'Vencido' ? 'bg-red-50' :
                    estado.label === 'Por vencer' ? 'bg-amber-50' : ''
                  }`}>
                    <div>
                      <p className="text-sm font-semibold text-gray-800">{r.producto_nombre}</p>
                      <p className="text-xs text-gray-400">
                        {r.cantidad} ud · hasta {new Date(r.fecha_frescura).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                      </p>
                    </div>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${estado.color}`}>
                      {estado.label}
                    </span>
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
