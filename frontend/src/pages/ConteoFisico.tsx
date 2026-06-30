import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { ClipboardList } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface InvItem {
  id: number
  producto_id: number
  producto_nombre: string
  unidad_medida: string
  stock_actual: number
  categoria: string
}

interface Turno {
  id: number
  tiene_conteo_apertura: boolean
  tiene_ventas: boolean
  tiene_conteo_cierre: boolean
}

export default function ConteoFisico() {
  const { user } = useAuth()
  const [turno, setTurno] = useState<Turno | null>(null)
  const [items, setItems] = useState<InvItem[]>([])
  const [conteos, setConteos] = useState<Record<number, string>>({})
  const [tipo, setTipo] = useState<'apertura' | 'cierre'>('apertura')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const tienda_id = user?.tienda_id

  const load = async () => {
    if (!tienda_id) return
    // Cargas separadas: si falla SOLO el inventario, no anular el turno (antes un try
    // único ponía turno=null y mostraba "no hay turno abierto" con el turno abierto).
    try {
      const turnoRes = await api.get(`/caja/activo/${tienda_id}`)
      setTurno(turnoRes.data)
      // Determinar tipo de conteo automáticamente
      if (!turnoRes.data?.tiene_conteo_apertura) setTipo('apertura')
      else if (!turnoRes.data?.tiene_conteo_cierre) setTipo('cierre')
    } catch { setTurno(null) }
    try {
      const invRes = await api.get(`/inventario/tienda/${tienda_id}`)
      setItems(invRes.data)
    } catch { setError('No se pudo cargar el inventario. Reintentá.') }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [tienda_id])

  const registrar = async () => {
    setError(''); setSuccess('')
    try {
      const itemsList = items.map(item => ({
        producto_id: item.producto_id,
        cantidad_real: Math.round(Number(conteos[item.producto_id] ?? item.stock_actual)),
      }))
      await api.post('/conteos/', {
        tienda_id,
        tipo,
        items: itemsList,
      })
      setSuccess(`Conteo de ${tipo} registrado`)
      setConteos({})
      load()
    } catch (e: any) { setError(e.response?.data?.detail || 'Error') }
  }

  if (loading) return <BaristaLayout title="Conteos"><p className="text-sm text-gray-400 py-8 text-center">Cargando...</p></BaristaLayout>

  if (!turno) return (
    <BaristaLayout title="Conteos">
    <div className="space-y-4">
      <h1 className="text-base font-bold text-gray-800">Conteo físico</h1>
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-700">
        No hay turno abierto. Abre la caja primero.
      </div>
    </div>
    </BaristaLayout>
  )

  if (turno.tiene_conteo_apertura && turno.tiene_conteo_cierre) {
    return (
      <BaristaLayout title="Conteos">
      <div className="space-y-4">
        <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-sm text-green-700">
          Ambos conteos del turno fueron completados ✓
        </div>
      </div>
      </BaristaLayout>
    )
  }

  if (tipo === 'cierre' && !turno.tiene_ventas) return (
    <BaristaLayout title="Conteos">
    <div className="space-y-4">
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-700">
        Debes registrar las ventas antes del conteo de cierre.
      </div>
    </div>
    </BaristaLayout>
  )

  return (
    <BaristaLayout title="Conteo físico">
    <div className="space-y-4">
      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">{error}</div>}
      {success && <div className="bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl">{success}</div>}

      {/* Selector de tipo */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Tipo de conteo</p>
        <div className="flex gap-2">
          {(['apertura', 'cierre'] as const).map(t => {
            const done = t === 'apertura' ? turno.tiene_conteo_apertura : turno.tiene_conteo_cierre
            const blocked = t === 'cierre' && !turno.tiene_ventas
            return (
              <button key={t} onClick={() => { if (!done && !blocked) setTipo(t) }}
                disabled={done || blocked}
                className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                  tipo === t && !done ? 'bg-amber-100 border-amber-300 text-amber-700' :
                  done ? 'bg-green-50 border-green-200 text-green-600 line-through' :
                  blocked ? 'bg-gray-50 border-gray-200 text-gray-300 cursor-not-allowed' :
                  'border-gray-200 text-gray-500 hover:bg-gray-50'
                }`}>
                {done ? '✓ ' : ''}{t}
              </button>
            )
          })}
        </div>
      </div>

      {/* Tabla de productos */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-2.5 border-b border-gray-100">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
            Conteo de {tipo} — ingresa las cantidades reales
          </p>
        </div>
        <div className="divide-y divide-gray-50">
          {items.map(item => (
            <div key={item.id} className="flex items-center gap-3 px-4 py-3">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800">{item.producto_nombre}</p>
                <p className="text-xs text-gray-400">
                  Sistema: {Math.round(item.stock_actual)} {item.unidad_medida}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  step="1"
                  min="0"
                  value={conteos[item.producto_id] ?? ''}
                  onChange={e => setConteos(prev => ({ ...prev, [item.producto_id]: e.target.value }))}
                  placeholder={String(Math.round(item.stock_actual))}
                  className="w-20 border border-gray-200 rounded-lg px-2 py-1.5 text-sm text-right focus:outline-none focus:ring-2 focus:ring-amber-400"
                />
                <span className="text-xs text-gray-400 w-8">{item.unidad_medida}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <button onClick={registrar}
        className="w-full bg-amber-600 hover:bg-amber-700 text-white font-semibold py-3 rounded-xl text-sm flex items-center justify-center gap-2">
        <ClipboardList size={15} /> Confirmar conteo de {tipo}
      </button>
    </div>
    </BaristaLayout>
  )
}
