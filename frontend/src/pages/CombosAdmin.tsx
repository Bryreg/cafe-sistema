import { useEffect, useState } from 'react'
import api from '../api/client'
import {
  Package, Check, ChevronDown, ChevronUp, AlertTriangle, Store, Power,
  Plus, Trash2, Pencil, X,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface Sede { id: number; nombre: string }
interface ProductoOpt { id: number; nombre: string; precio_venta: number }
interface ComboProducto { producto_id?: number; nombre: string; cantidad: number }
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

/** Borrador del formulario: los ids y cantidades viven como string mientras se
 *  edita (un campo a medio escribir no es un número) y se convierten al guardar. */
interface BorradorProducto { producto_id: number; cantidad: string }
interface BorradorOpcion { nombre: string; productos: BorradorProducto[] }
interface BorradorGrupo { nombre: string; opciones: BorradorOpcion[] }

/**
 * Alta y edición de un combo.
 *
 * Antes esto no existía: un combo SOLO se podía crear corriendo
 * `cargar_combos.py` contra la base, o sea entrando al servidor. Dar de alta el
 * combo de una sede era una tarea de infraestructura y quedaba pendiente días.
 *
 * El formulario muestra el precio suelto de lo que lleva y el descuento que
 * implica el precio del combo. No es decoración: es lo que delata un producto
 * mal elegido —el sabor equivocado de una bebida, el tamaño de más— antes de
 * que el combo salga a la venta y empiece a descontar el insumo errado.
 */
function ComboEditor({ combo, sedes, onClose, onGuardado }: {
  combo: ComboAdmin | null       // null = alta
  sedes: Sede[]
  onClose: () => void
  onGuardado: () => void
}) {
  const [productos, setProductos] = useState<ProductoOpt[]>([])
  const [nombre, setNombre] = useState(combo?.nombre ?? '')
  const [precio, setPrecio] = useState(combo ? String(Math.round(combo.precio_venta)) : '')
  const [orden, setOrden] = useState(String(combo?.orden ?? 0))
  const [tiendaIds, setTiendaIds] = useState<number[]>(combo?.tienda_ids ?? [])
  const [grupos, setGrupos] = useState<BorradorGrupo[]>([])
  const [cargando, setCargando] = useState(true)
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.get<ProductoOpt[]>('/pos/productos')
      .then(r => {
        // La sombra de un combo tiene precio 0 y no se puede meter dentro de
        // otro combo: no descuenta nada y el anidado no está soportado.
        setProductos((r.data ?? []).filter(p => Number(p.precio_venta) > 0)
          .sort((a, b) => a.nombre.localeCompare(b.nombre)))
      })
      .catch(() => setError('No se pudieron cargar los productos'))
      .finally(() => setCargando(false))
  }, [])

  // El combo que se edita llega con NOMBRES de producto; el formulario necesita
  // ids. Se resuelven cuando ya está la lista de productos.
  useEffect(() => {
    if (!productos.length) return
    if (combo) {
      const porNombre = new Map(productos.map(p => [p.nombre.toLowerCase(), p.id]))
      setGrupos(combo.grupos.map(g => ({
        nombre: g.nombre,
        opciones: g.opciones.map(o => ({
          nombre: o.nombre,
          productos: o.productos.map(pr => ({
            producto_id: pr.producto_id ?? porNombre.get(pr.nombre.toLowerCase()) ?? 0,
            cantidad: String(pr.cantidad),
          })),
        })),
      })))
    } else {
      setGrupos([{ nombre: 'Bebida', opciones: [{ nombre: '', productos: [{ producto_id: 0, cantidad: '1' }] }] }])
    }
  }, [productos, combo])

  const precioNum = Number(precio.replace(/[^\d]/g, '')) || 0
  const precioDe = (id: number) => productos.find(p => p.id === id)?.precio_venta ?? 0
  const nombreDe = (id: number) => productos.find(p => p.id === id)?.nombre ?? ''

  /** Lo que costaría suelto eligiendo la PRIMERA opción de cada grupo — la
   *  referencia con la que se compara el precio del combo. */
  const sueltoReferencia = grupos.reduce((tot, g) => {
    const o = g.opciones[0]
    if (!o) return tot
    return tot + o.productos.reduce(
      (t, p) => t + precioDe(p.producto_id) * (Number(p.cantidad) || 0), 0)
  }, 0)
  const descuento = sueltoReferencia - precioNum

  const setGrupo = (gi: number, patch: Partial<BorradorGrupo>) =>
    setGrupos(gs => gs.map((g, i) => i === gi ? { ...g, ...patch } : g))
  const setOpcion = (gi: number, oi: number, patch: Partial<BorradorOpcion>) =>
    setGrupos(gs => gs.map((g, i) => i !== gi ? g : {
      ...g, opciones: g.opciones.map((o, j) => j === oi ? { ...o, ...patch } : o),
    }))

  const guardar = async () => {
    setError('')
    // Validación en la pantalla ANTES de mandar: el servidor rechaza lo mismo,
    // pero decirlo acá evita perder el formulario entero por un renglón.
    if (!nombre.trim()) return setError('Ponele nombre al combo')
    if (precioNum <= 0) return setError('El precio tiene que ser mayor a 0')
    if (!combo && !tiendaIds.length) return setError('Elegí al menos una sede: un combo sin sede no se vende')
    if (!grupos.length) return setError('El combo necesita al menos un grupo')
    for (const g of grupos) {
      if (!g.nombre.trim()) return setError('Todos los grupos necesitan nombre')
      if (!g.opciones.length) return setError(`El grupo «${g.nombre}» no tiene opciones`)
      for (const o of g.opciones) {
        const prods = o.productos.filter(p => p.producto_id > 0)
        if (!prods.length) {
          return setError(`Una opción de «${g.nombre}» no tiene productos: quien la elija `
            + 'pagaría el combo y no se descontaría nada')
        }
        if (prods.some(p => !(Number(p.cantidad) > 0))) {
          return setError(`Las cantidades de «${g.nombre}» tienen que ser mayores a 0`)
        }
      }
    }

    const payload = {
      nombre: nombre.trim(),
      precio: precioNum,
      orden: Number(orden) || 0,
      grupos: grupos.map(g => ({
        nombre: g.nombre.trim(),
        // El nombre de la opción cae al del producto cuando está vacío: en un
        // grupo fijo nadie la ve, así que pedirlo sería un campo de relleno.
        opciones: g.opciones.map(o => {
          const prods = o.productos.filter(p => p.producto_id > 0)
          return {
            nombre: o.nombre.trim() || prods.map(p => nombreDe(p.producto_id)).join(' + '),
            productos: prods.map(p => ({ producto_id: p.producto_id, cantidad: Number(p.cantidad) })),
          }
        }),
      })),
    }

    setGuardando(true)
    try {
      if (combo) await api.put(`/combos/${combo.id}`, payload)
      else await api.post('/combos', { ...payload, tienda_ids: tiendaIds })
      onGuardado()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo guardar el combo')
      setGuardando(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl w-full max-w-2xl my-6">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white rounded-t-2xl">
          <h3 className="text-sm font-bold text-gray-800">
            {combo ? `Editar ${combo.nombre}` : 'Nuevo combo'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>

        <div className="p-5 space-y-5">
          {cargando && <p className="text-xs text-gray-400 text-center py-4">Cargando productos...</p>}

          {!cargando && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2">
                  <label className="block text-xs font-semibold text-gray-500 mb-1">Nombre</label>
                  <input value={nombre} onChange={e => setNombre(e.target.value)}
                    placeholder="Combo Borondo"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-500 mb-1">Precio</label>
                  <input value={precio} inputMode="numeric"
                    onChange={e => setPrecio(e.target.value.replace(/[^\d]/g, ''))}
                    placeholder="18000"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-right font-mono" />
                </div>
              </div>

              {/* Precio suelto vs combo: lo que delata un producto mal elegido */}
              {sueltoReferencia > 0 && (
                <div className={`text-xs px-3 py-2 rounded-lg border ${
                  descuento < 0 ? 'bg-red-50 border-red-200 text-red-700'
                                : 'bg-gray-50 border-gray-200 text-gray-600'}`}>
                  Suelto: <strong>{fmt(sueltoReferencia)}</strong>
                  {precioNum > 0 && (descuento >= 0
                    ? <> · el combo descuenta <strong>{fmt(descuento)}</strong>
                        {' '}({Math.round(descuento / sueltoReferencia * 100)}%)</>
                    : <> · ojo: el combo sale <strong>{fmt(-descuento)}</strong> MÁS CARO que suelto</>)}
                  {grupos.some(g => g.opciones.length > 1) && (
                    <span className="text-gray-400"> — calculado con la primera opción de cada grupo</span>
                  )}
                </div>
              )}

              {!combo && (
                <div>
                  <label className="block text-xs font-semibold text-gray-500 mb-1">
                    Sedes donde se vende
                  </label>
                  <div className="flex gap-2 flex-wrap">
                    {sedes.map(s => {
                      const on = tiendaIds.includes(s.id)
                      return (
                        <button key={s.id} type="button"
                          onClick={() => setTiendaIds(ids =>
                            on ? ids.filter(i => i !== s.id) : [...ids, s.id])}
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border-2 ${
                            on ? 'bg-green-50 text-green-700 border-green-400'
                               : 'bg-white text-gray-500 border-gray-200 hover:border-green-300'}`}>
                          <span className={`w-4 h-4 rounded flex items-center justify-center ${
                            on ? 'bg-green-600' : 'border-2 border-gray-300'}`}>
                            {on && <Check size={11} strokeWidth={3} className="text-white" />}
                          </span>
                          {s.nombre}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
              {combo && (
                <p className="text-xs text-gray-400">
                  Las sedes se cambian con los botones de la tarjeta, no acá: quitar una sede
                  es otra decisión que cambiar lo que lleva el combo.
                </p>
              )}

              {/* Grupos */}
              <div className="space-y-3">
                {grupos.map((g, gi) => (
                  <div key={gi} className="border border-gray-200 rounded-xl p-3 space-y-2">
                    <div className="flex items-center gap-2">
                      <input value={g.nombre} onChange={e => setGrupo(gi, { nombre: e.target.value })}
                        placeholder="Bebida"
                        className="flex-1 border border-gray-300 rounded-lg px-2 py-1.5 text-xs font-semibold" />
                      <button type="button" onClick={() => setGrupos(gs => gs.filter((_, i) => i !== gi))}
                        className="text-red-400 hover:text-red-600"><Trash2 size={13} /></button>
                    </div>

                    {g.opciones.map((o, oi) => (
                      <div key={oi} className="pl-3 border-l-2 border-gray-100 space-y-1.5">
                        <div className="flex items-center gap-2">
                          <input value={o.nombre} onChange={e => setOpcion(gi, oi, { nombre: e.target.value })}
                            placeholder="Nombre de la opción (opcional)"
                            className="flex-1 border border-gray-200 rounded-lg px-2 py-1 text-xs" />
                          {g.opciones.length > 1 && (
                            <button type="button"
                              onClick={() => setGrupo(gi, { opciones: g.opciones.filter((_, j) => j !== oi) })}
                              className="text-red-300 hover:text-red-600"><Trash2 size={12} /></button>
                          )}
                        </div>
                        {o.productos.map((pr, pi) => (
                          <div key={pi} className="flex items-center gap-2">
                            <select value={pr.producto_id}
                              onChange={e => setOpcion(gi, oi, {
                                productos: o.productos.map((x, k) => k === pi
                                  ? { ...x, producto_id: Number(e.target.value) } : x),
                              })}
                              className="flex-1 min-w-0 border border-gray-200 rounded-lg px-2 py-1 text-xs">
                              <option value={0}>Elegir producto…</option>
                              {productos.map(pp => (
                                <option key={pp.id} value={pp.id}>{pp.nombre} — {fmt(pp.precio_venta)}</option>
                              ))}
                            </select>
                            <input value={pr.cantidad} inputMode="decimal"
                              onChange={e => setOpcion(gi, oi, {
                                productos: o.productos.map((x, k) => k === pi
                                  ? { ...x, cantidad: e.target.value.replace(/[^\d.,]/g, '').replace(',', '.') } : x),
                              })}
                              className="w-16 border border-gray-200 rounded-lg px-2 py-1 text-xs text-right font-mono" />
                            {o.productos.length > 1 && (
                              <button type="button"
                                onClick={() => setOpcion(gi, oi, {
                                  productos: o.productos.filter((_, k) => k !== pi),
                                })}
                                className="text-red-300 hover:text-red-600"><Trash2 size={12} /></button>
                            )}
                          </div>
                        ))}
                        <button type="button"
                          onClick={() => setOpcion(gi, oi, {
                            productos: [...o.productos, { producto_id: 0, cantidad: '1' }],
                          })}
                          className="text-[11px] text-gray-400 hover:text-gray-700">
                          + otro producto en esta opción
                        </button>
                      </div>
                    ))}

                    <div className="flex items-center gap-3 pt-1">
                      <button type="button"
                        onClick={() => setGrupo(gi, {
                          opciones: [...g.opciones, { nombre: '', productos: [{ producto_id: 0, cantidad: '1' }] }],
                        })}
                        className="text-[11px] font-semibold text-gray-500 hover:text-gray-800">
                        + opción a elegir
                      </button>
                      {g.opciones.length === 1 && (
                        <span className="text-[11px] text-gray-400">
                          Grupo fijo: se auto-selecciona, la barista no elige.
                        </span>
                      )}
                    </div>
                  </div>
                ))}
                <button type="button"
                  onClick={() => setGrupos(gs => [...gs, {
                    nombre: '', opciones: [{ nombre: '', productos: [{ producto_id: 0, cantidad: '1' }] }],
                  }])}
                  className="text-xs font-semibold text-gray-600 hover:text-gray-900 flex items-center gap-1">
                  <Plus size={13} /> Agregar grupo
                </button>
              </div>

              {error && (
                <div className="flex items-start gap-2 text-xs px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {error}
                </div>
              )}

              <div className="flex gap-2 justify-end pt-1">
                <button onClick={onClose}
                  className="px-4 py-2 rounded-lg text-xs font-semibold text-gray-500 border border-gray-200">
                  Cancelar
                </button>
                <button onClick={guardar} disabled={guardando}
                  className="px-4 py-2 rounded-lg text-xs font-bold text-white bg-forest disabled:opacity-50"
                  style={{ background: 'oklch(48% 0.12 155)' }}>
                  {guardando ? 'Guardando...' : combo ? 'Guardar cambios' : 'Crear combo'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}


/**
 * Administración de combos: en qué sedes se vende cada uno y si está prendido.
 *
 * Antes de esto, un combo SOLO se podía crear corriendo `cargar_combos.py` contra
 * la base —o sea entrando al servidor— y habilitarlo en una sede obligaba a
 * insertar la fila de `combo_tiendas` a mano. Dar de alta un combo era una tarea
 * de infraestructura y quedaba pendiente días.
 */
export default function CombosAdmin() {
  const [sedes, setSedes] = useState<Sede[]>([])
  const [combos, setCombos] = useState<ComboAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [guardando, setGuardando] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [expandido, setExpandido] = useState<number | null>(null)
  // null = cerrado; {combo: null} = alta; {combo} = edición
  const [editor, setEditor] = useState<{ combo: ComboAdmin | null } | null>(null)

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
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Combos</h1>
          <p className="text-sm text-gray-500 mt-1">
            Qué lleva cada combo y en qué sedes se vende. El cambio es inmediato — el POS lo toma al recargar la grilla.
          </p>
        </div>
        <button onClick={() => setEditor({ combo: null })}
          className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold text-white shrink-0"
          style={{ background: 'oklch(48% 0.12 155)' }}>
          <Plus size={14} /> Nuevo combo
        </button>
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
          <button onClick={() => setEditor({ combo: null })}
            className="mt-3 text-xs font-bold" style={{ color: 'oklch(48% 0.12 155)' }}>
            Crear el primero
          </button>
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

                <button onClick={() => setEditor({ combo })}
                  title="Cambiar nombre, precio o lo que lleva"
                  className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:border-gray-400 hover:text-gray-700">
                  <Pencil size={13} /> Editar
                </button>

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

              {/* Composición — se edita con «Editar» */}
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

      {editor && (
        <ComboEditor combo={editor.combo} sedes={sedes}
          onClose={() => setEditor(null)}
          onGuardado={() => { setEditor(null); load() }} />
      )}
    </div>
  )
}
