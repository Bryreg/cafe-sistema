import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { CheckCircle2, Circle, ArrowRight, AlertTriangle, ClipboardCheck } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface InvItem {
  producto_id: number
  producto_nombre: string
  unidad_medida: string
  stock_actual: number
  categoria: string
}

export default function ConteoApertura() {
  const { user } = useAuth()
  const { refresh } = useTurno()
  const navigate = useNavigate()
  const [items, setItems] = useState<InvItem[]>([])
  const [conteos, setConteos] = useState<Record<number, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!user?.tienda_id) return
    api.get(`/inventario/tienda/${user.tienda_id}`)
      .then(r => setItems(r.data))
      .finally(() => setLoading(false))
  }, [user])

  const getVal = (id: number, ref: number) => conteos[id] !== undefined ? Number(conteos[id]) : ref
  const getDiff = (id: number, ref: number) => getVal(id, ref) - ref

  const todoOk = () => {
    const filled: Record<number, string> = {}
    items.forEach(i => { filled[i.producto_id] = String(i.stock_actual) })
    setConteos(filled)
  }

  const confirmar = async () => {
    setSaving(true); setError('')
    try {
      const itemsList = items.map(i => ({
        producto_id: i.producto_id,
        cantidad_real: getVal(i.producto_id, i.stock_actual),
      }))
      await api.post('/conteos/', { tienda_id: user?.tienda_id, tipo: 'apertura', items: itemsList })
      await refresh()
      navigate('/hub')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar conteo')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return (
    <BaristaLayout backTo="/apertura">
      <div className="flex items-center justify-center py-16">
        <p className="text-sm text-gray-400">Cargando productos...</p>
      </div>
    </BaristaLayout>
  )

  const totalDifs = items.filter(i => conteos[i.producto_id] !== undefined && getDiff(i.producto_id, i.stock_actual) !== 0).length

  return (
    <BaristaLayout backTo="/apertura">
      <div className="space-y-5">
        <div>
          <p className="text-xs font-semibold text-amber-600 uppercase tracking-widest mb-1">Paso 2 de 5</p>
          <h1 className="text-xl font-bold text-gray-900">Conteo de apertura</h1>
          <p className="text-sm text-gray-500">Verifica el stock físico contra el sistema.</p>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* Botón todo OK */}
        <button onClick={todoOk}
          className="w-full py-3 border-2 border-dashed border-green-300 text-green-700 font-semibold rounded-xl text-sm hover:bg-green-50 transition-colors flex items-center justify-center gap-2">
          <CheckCircle2 size={16} /> Todo coincide con sistema
        </button>

        {/* Lista de productos */}
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden divide-y divide-gray-50">
          {items.map(item => {
            const val = conteos[item.producto_id]
            const diff = val !== undefined ? Number(val) - item.stock_actual : null
            const filled = val !== undefined

            return (
              <div key={item.producto_id} className={`px-4 py-3.5 ${diff !== null && diff !== 0 ? 'bg-red-50' : ''}`}>
                <div className="flex items-center gap-3">
                  <div className="shrink-0">
                    {filled && diff === 0
                      ? <CheckCircle2 size={18} className="text-green-500" />
                      : filled && diff !== 0
                      ? <AlertTriangle size={18} className="text-red-500" />
                      : <Circle size={18} className="text-gray-300" />
                    }
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-800 leading-tight">{item.producto_nombre}</p>
                    <p className="text-xs text-gray-400">Sistema: {item.stock_actual} {item.unidad_medida}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <input
                      type="number"
                      value={val ?? ''}
                      onChange={e => setConteos(prev => ({ ...prev, [item.producto_id]: e.target.value }))}
                      placeholder={String(item.stock_actual)}
                      className={`w-20 text-right border-2 rounded-lg px-2 py-1.5 text-sm font-bold focus:outline-none transition-colors ${
                        diff !== null && diff !== 0
                          ? 'border-red-300 text-red-700 focus:border-red-400 bg-white'
                          : diff === 0
                          ? 'border-green-300 text-green-700 bg-green-50'
                          : 'border-gray-200 focus:border-amber-400'
                      }`}
                    />
                    <span className="text-xs text-gray-400 w-7 text-left">{item.unidad_medida}</span>
                  </div>
                </div>
                {diff !== null && diff !== 0 && (
                  <p className="text-xs text-red-600 font-medium mt-1 ml-7">
                    Diferencia: {diff > 0 ? '+' : ''}{diff} {item.unidad_medida}
                  </p>
                )}
              </div>
            )
          })}
        </div>

        {totalDifs > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-700">
            <strong>{totalDifs} diferencia{totalDifs > 1 ? 's' : ''}</strong> registradas. Se guardará en el reporte.
          </div>
        )}

        <button onClick={confirmar} disabled={saving}
          className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-bold py-4 rounded-xl text-base flex items-center justify-center gap-2 transition-colors">
          <ClipboardCheck size={18} />
          {saving ? 'Guardando...' : 'Confirmar conteo de apertura'}
          {!saving && <ArrowRight size={18} />}
        </button>
      </div>
    </BaristaLayout>
  )
}
