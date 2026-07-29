import { useEffect, useState } from 'react'
import api from '../api/client'
import {
  Package, Check, ChevronDown, ChevronUp, AlertTriangle, Store, Power,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface Sede { id: number; nombre: string }
interface ComboProducto { nombre: string; cantidad: number }
interface ComboOpcion { nombre: string; productos: ComboProducto[] }
interface ComboGrupo { nombre: string; opciones: ComboOpcion[] }
interface ComboAdmin {
  id: number
  nombre: string
  precio_venta: number
  activo: boolean
  orden: number
  tienda_ids: number[]
  grupos: ComboGrupo[]
}

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

/**
 * Administración de combos: en qué sedes se vende cada uno y si está prendido.
 *
 * Hasta ahora `combo_tiendas` no tenía endpoint — habilitar un combo en una sede
 * obligaba a insertar la fila a mano en la base. La composición (grupos/opciones)
 * es de sólo lectura acá: se define al crear el combo, no es una decisión del día a día.
 */
export default function CombosAdmin() {
  const [sedes, setSedes] = useState<Sede[]>([])
  const [combos, setCombos] = useState<ComboAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [guardando, setGuardando] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [expandido, setExpandido] = useState<number | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [s, c] = await Promise.all([
        api.get('/auth/tiendas'),
        api.get('/combos/admin'),
      ])
      setSedes(s.data)
      setCombos(c.data)
    } catch {
      setError('No se pudieron cargar los combos')
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  // Toggle de sede: manda la lista COMPLETA de sedes resultante (el server la
  // reemplaza entera, así no hay estados intermedios raros si hay dos pestañas).
  const toggleSede = async (combo: ComboAdmin, sedeId: number) => {
    const nuevas = combo.tienda_ids.includes(sedeId)
      ? combo.tienda_ids.filter(id => id !== sedeId)
      : [...combo.tienda_ids, sedeId]
    setGuardando(combo.id); setError('')
    try {
      const fd = new FormData()
      fd.append('tienda_ids', JSON.stringify(nuevas))
      await api.put(`/combos/${combo.id}/tiendas`, fd)
      setCombos(prev => prev.map(c =>
        c.id === combo.id ? { ...c, tienda_ids: nuevas.sort((a, b) => a - b) } : c
      ))
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo actualizar la sede')
    } finally { setGuardando(null) }
  }

  const toggleActivo = async (combo: ComboAdmin) => {
    setGuardando(combo.id); setError('')
    try {
      const fd = new FormData()
      fd.append('activo', String(!combo.activo))
      await api.patch(`/combos/${combo.id}/activo`, fd)
      setCombos(prev => prev.map(c =>
        c.id === combo.id ? { ...c, activo: !combo.activo } : c
      ))
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo cambiar el estado')
    } finally { setGuardando(null) }
  }

  if (loading) return <p className="text-sm text-gray-400 text-center py-12">Cargando combos...</p>

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Combos</h1>
        <p className="text-sm text-gray-500 mt-1">
          En qué sedes se vende cada combo. El cambio es inmediato — el POS lo toma al recargar la grilla.
        </p>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-red-600">
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      {combos.length === 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-10 text-center">
          <Package size={32} className="text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-400">No hay combos configurados</p>
        </div>
      )}

      <div className="space-y-3">
        {combos.map(combo => {
          const abierto = expandido === combo.id
          const sinSedes = combo.tienda_ids.length === 0
          const ocupado = guardando === combo.id

          return (
            <div key={combo.id}
              className={`bg-white rounded-2xl border-2 overflow-hidden transition-all ${
                !combo.activo ? 'border-gray-200 opacity-60'
                  : sinSedes ? 'border-amber-200' : 'border-gray-200'
              }`}>

              <div className="px-5 py-4 flex items-center gap-4 flex-wrap">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-bold text-gray-800">{combo.nombre}</p>
                    <span className="text-sm font-bold text-gray-900">{fmt(combo.precio_venta)}</span>
                    {!combo.activo && (
                      <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded-full font-semibold">
                        Apagado
                      </span>
                    )}
                    {combo.activo && sinSedes && (
                      <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">
                        Sin sedes — no se vende
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {combo.grupos.map(g => g.nombre).join(' + ') || 'Sin composición'}
                  </p>
                </div>

                <button onClick={() => toggleActivo(combo)} disabled={ocupado}
                  title={combo.activo ? 'Apagar en todas las sedes' : 'Prender'}
                  className={`flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-50 ${
                    combo.activo
                      ? 'text-gray-500 border-gray-200 hover:border-red-300 hover:text-red-600'
                      : 'text-green-700 border-green-300 bg-green-50 hover:bg-green-100'
                  }`}>
                  <Power size={13} /> {combo.activo ? 'Apagar' : 'Prender'}
                </button>

                <button onClick={() => setExpandido(abierto ? null : combo.id)}
                  className="text-gray-400 hover:text-gray-600 p-1">
                  {abierto ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
              </div>

              {/* Sedes — la decisión operativa, siempre visible */}
              <div className="px-5 pb-4 flex items-center gap-2 flex-wrap">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1">
                  <Store size={12} /> Sedes
                </span>
                {sedes.map(s => {
                  const on = combo.tienda_ids.includes(s.id)
                  return (
                    <button key={s.id} onClick={() => toggleSede(combo, s.id)} disabled={ocupado}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border-2 transition-colors disabled:opacity-50 ${
                        on ? 'bg-green-50 text-green-700 border-green-400'
                           : 'bg-white text-gray-500 border-gray-200 hover:border-green-300'
                      }`}>
                      <span className={`w-4 h-4 rounded flex items-center justify-center ${
                        on ? 'bg-green-600' : 'border-2 border-gray-300'
                      }`}>
                        {on && <Check size={11} strokeWidth={3} className="text-white" />}
                      </span>
                      {s.nombre}
                    </button>
                  )
                })}
                {ocupado && <span className="text-xs text-gray-400">guardando...</span>}
              </div>

              {/* Composición — sólo lectura */}
              {abierto && (
                <div className="border-t border-gray-100 px-5 py-4 space-y-3 bg-gray-50">
                  <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">
                    Qué lleva
                  </p>
                  {combo.grupos.map((g, gi) => (
                    <div key={gi}>
                      <p className="text-xs font-semibold text-gray-700">{g.nombre}</p>
                      <ul className="mt-1 space-y-0.5">
                        {g.opciones.map((o, oi) => (
                          <li key={oi} className="text-xs text-gray-500 pl-3">
                            · {o.nombre}
                            <span className="text-gray-400">
                              {' '}({o.productos.map(p => `${p.nombre}${p.cantidad > 1 ? ` ×${p.cantidad}` : ''}`).join(' + ')})
                            </span>
                          </li>
                        ))}
                      </ul>
                      {g.opciones.length === 1 && (
                        <p className="text-[11px] text-gray-400 pl-3 mt-0.5">
                          Grupo fijo: se auto-selecciona, la barista no elige.
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
