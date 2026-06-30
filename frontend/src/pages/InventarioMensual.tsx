import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Boxes, Check, Save, AlertTriangle, Lock } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

interface Item {
  id: number; producto_id: number; producto_nombre: string
  categoria: string; unidad_medida: string
  cantidad_sistema: number; cantidad_real: number | null
  diferencia: number; valor_unitario: number; valor_diferencia: number
}
interface Inv {
  id: number; anio: number; mes: number; estado: string
  valor_diferencia_total: number; items: Item[]
}

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const CAT_LABEL: Record<string, string> = { pasteleria: 'Pastelería', bebida: 'Bebidas', insumo: 'Insumos' }
const CAT_ORDER = ['insumo', 'pasteleria', 'bebida']

export default function InventarioMensual() {
  const { user } = useAuth()
  const now = new Date()
  const [inv, setInv] = useState<Inv | null>(null)
  const [loading, setLoading] = useState(true)
  const [valores, setValores] = useState<Record<number, string>>({})  // itemId → física (string)
  const [guardando, setGuardando] = useState(false)
  const [cerrando, setCerrando] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!user?.tienda_id) { setLoading(false); setMsg('No se pudo determinar la sede'); return }
    api.post<Inv>('/inventario-mensual/iniciar', null, { params: { tienda_id: user.tienda_id, anio: now.getFullYear(), mes: now.getMonth() + 1 } })
      .then(r => {
        setInv(r.data)
        const v: Record<number, string> = {}
        r.data.items.forEach(it => { if (it.cantidad_real != null) v[it.id] = String(it.cantidad_real) })
        setValores(v)
      })
      .catch(() => setMsg('No se pudo iniciar el conteo'))
      .finally(() => setLoading(false))
  }, [user?.tienda_id])  // eslint-disable-line

  const cerrado = inv?.estado === 'cerrado'
  const grupos = useMemo(() => {
    const g: Record<string, Item[]> = {}
    ;(inv?.items ?? []).forEach(it => { (g[it.categoria] ??= []).push(it) })
    return CAT_ORDER.filter(c => g[c]?.length).map(c => ({ cat: c, items: g[c].sort((a, b) => a.producto_nombre.localeCompare(b.producto_nombre)) }))
  }, [inv])

  const contados = useMemo(() => Object.values(valores).filter(v => v !== '').length, [valores])

  const dif = (it: Item) => {
    const v = valores[it.id]
    if (v === undefined || v === '') return null
    return Number(v) - it.cantidad_sistema
  }

  const guardar = async () => {
    if (!inv) return
    setGuardando(true); setMsg('')
    try {
      const items = Object.entries(valores)
        .filter(([, v]) => v !== '')
        .map(([id, v]) => ({ id: Number(id), cantidad_real: Number(v) }))
      const { data } = await api.patch<Inv>(`/inventario-mensual/${inv.id}/guardar`, items)
      setInv(data); setMsg('Guardado')
      setTimeout(() => setMsg(''), 1500)
    } catch { setMsg('Error al guardar') } finally { setGuardando(false) }
  }

  const cerrar = async () => {
    if (!inv || !window.confirm('¿Cerrar el conteo del mes? No se podrá editar después.')) return
    setCerrando(true); setMsg('')
    try {
      await guardar()
      const { data } = await api.post<Inv>(`/inventario-mensual/${inv.id}/cerrar`)
      setInv(data)
    } catch { setMsg('Error al cerrar') } finally { setCerrando(false) }
  }

  return (
    <BaristaLayout title="Inventario mensual">
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Boxes size={20} className="text-forest" />
          <div>
            <h1 className="text-lg font-bold text-gray-800">Inventario mensual</h1>
            <p className="text-xs text-gray-400">{inv ? `${MESES[inv.mes - 1]} ${inv.anio}` : ''}</p>
          </div>
        </div>

        {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Preparando el conteo...</p>}

        {!loading && inv && (
          <>
            {/* Estado / progreso */}
            <div className={`rounded-xl px-4 py-3 flex items-center gap-2 text-sm ${cerrado ? 'bg-green-50 border border-green-200 text-green-700' : 'bg-amber-50 border border-amber-200 text-amber-700'}`}>
              {cerrado ? <Lock size={15} /> : <AlertTriangle size={15} />}
              {cerrado
                ? <span>Conteo <b>cerrado</b>. Diferencia neta: <b>${Math.round(inv.valor_diferencia_total).toLocaleString('es-CO')}</b></span>
                : <span><b>{contados}</b> de {inv.items.length} productos contados</span>}
            </div>

            {/* Grupos por categoría */}
            {grupos.map(({ cat, items }) => (
              <div key={cat} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
                <div className="px-4 py-2 bg-gray-50 border-b border-gray-100">
                  <p className="text-xs font-bold uppercase tracking-wide text-gray-500">{CAT_LABEL[cat] ?? cat}</p>
                </div>
                <div className="divide-y divide-gray-50">
                  {items.map(it => {
                    const d = cerrado ? it.diferencia : dif(it)
                    return (
                      <div key={it.id} className="flex items-center gap-3 px-4 py-2.5">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-800 truncate">{it.producto_nombre}</p>
                          <p className="text-xs text-gray-400">Sistema: {Math.round(it.cantidad_sistema)} {it.unidad_medida}</p>
                        </div>
                        {cerrado ? (
                          <div className="text-right">
                            <p className="text-sm font-bold text-gray-800 font-mono">{Math.round(it.cantidad_real ?? 0)}</p>
                          </div>
                        ) : (
                          <input type="number" inputMode="numeric" value={valores[it.id] ?? ''}
                            onChange={e => setValores(p => ({ ...p, [it.id]: e.target.value }))}
                            placeholder="—"
                            className="w-20 border-2 border-gray-200 rounded-xl px-2 py-1.5 text-center font-mono font-bold focus:outline-none focus:border-forest" />
                        )}
                        <div className="w-14 text-right">
                          {d != null && d !== 0 && (
                            <span className={`text-xs font-bold font-mono ${d > 0 ? 'text-blue-600' : 'text-red-600'}`}>
                              {d > 0 ? '+' : ''}{Math.round(d)}
                            </span>
                          )}
                          {d === 0 && <Check size={14} className="text-green-500 inline" />}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}

            {msg && <p className="text-sm text-center text-gray-500">{msg}</p>}

            {/* CTA */}
            {!cerrado && (
              <div className="flex gap-2 sticky bottom-2">
                <button onClick={guardar} disabled={guardando}
                  className="flex-1 flex items-center justify-center gap-2 bg-white border-2 border-gray-200 text-gray-600 font-bold py-3 rounded-xl text-sm disabled:opacity-40">
                  <Save size={16} /> {guardando ? 'Guardando...' : 'Guardar avance'}
                </button>
                <button onClick={cerrar} disabled={cerrando}
                  className="flex-1 flex items-center justify-center gap-2 bg-forest hover:bg-forest-700 text-white font-bold py-3 rounded-xl text-sm disabled:opacity-40">
                  <Check size={16} /> {cerrando ? 'Cerrando...' : 'Cerrar conteo'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </BaristaLayout>
  )
}
