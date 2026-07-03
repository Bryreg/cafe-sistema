import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import { Boxes, Search, Calendar, AlertTriangle, Truck, Download, ChevronDown, ChevronUp, History } from 'lucide-react'

interface Lote {
  id: number; producto_id: number; producto_nombre: string; unidad_medida: string
  tienda_id: number; tienda_nombre: string | null
  proveedor: string | null; numero_lote: string | null; factura_id: number | null
  cantidad_inicial: number; cantidad_restante: number; consumido_pct: number
  fecha_entrada: string | null; fecha_fabricacion: string | null
  fecha_vencimiento: string | null; fecha_agotado: string | null
  estado: 'activo' | 'por_vencer' | 'vencido' | 'agotado'
}
interface Tienda { id: number; nombre: string }

const ESTADO: Record<string, { label: string; cls: string }> = {
  activo:     { label: 'Activo',     cls: 'bg-green-100 text-green-700' },
  por_vencer: { label: 'Por vencer', cls: 'bg-amber-100 text-amber-700' },
  vencido:    { label: 'Vencido',    cls: 'bg-red-100 text-red-700' },
  agotado:    { label: 'Agotado',    cls: 'bg-gray-100 text-gray-500' },
}
const fmtF = (s: string | null) => s ? new Date(s).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: '2-digit' }) : '—'

export default function LotesTrazabilidad() {
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(null)
  const [lotes, setLotes] = useState<Lote[]>([])
  const [loading, setLoading] = useState(false)
  const [estado, setEstado] = useState('')
  const [proveedor, setProveedor] = useState('')
  const [busqueda, setBusqueda] = useState('')

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas').then(r => setTiendas(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    setLoading(true)
    const params: Record<string, string | number> = {}
    if (tiendaId) params.tienda_id = tiendaId
    if (estado) params.estado = estado
    api.get<Lote[]>('/inventario/lotes-trazabilidad', { params })
      .then(r => setLotes(r.data)).catch(() => setLotes([])).finally(() => setLoading(false))
  }, [tiendaId, estado])

  const proveedores = useMemo(() => [...new Set(lotes.map(l => l.proveedor).filter(Boolean))].sort() as string[], [lotes])
  const filtrados = useMemo(() => lotes.filter(l =>
    (!proveedor || l.proveedor === proveedor) &&
    (!busqueda || l.producto_nombre.toLowerCase().includes(busqueda.toLowerCase())
      || (l.numero_lote || '').toLowerCase().includes(busqueda.toLowerCase())
      || (l.proveedor || '').toLowerCase().includes(busqueda.toLowerCase()))
  ), [lotes, proveedor, busqueda])

  const porVencer = lotes.filter(l => l.estado === 'por_vencer' || l.estado === 'vencido').length

  // Vista por PRODUCTO: agrupa los lotes filtrados; al desplegar se ven sus lotes.
  const [abierto, setAbierto] = useState<string | null>(null)
  const RANGO_ESTADO: Record<string, number> = { vencido: 3, por_vencer: 2, activo: 1, agotado: 0 }
  const grupos = useMemo(() => {
    const map = new Map<string, { key: string; nombre: string; unidad: string; restante: number; venceProximo: string | null; peorEstado: string; lotes: Lote[] }>()
    for (const l of filtrados) {
      const key = `${l.producto_id}`
      const g = map.get(key) ?? { key, nombre: l.producto_nombre, unidad: l.unidad_medida, restante: 0, venceProximo: null, peorEstado: 'agotado', lotes: [] }
      g.lotes.push(l)
      g.restante += l.cantidad_restante
      if (l.cantidad_restante > 0 && l.fecha_vencimiento && (!g.venceProximo || l.fecha_vencimiento < g.venceProximo)) g.venceProximo = l.fecha_vencimiento
      if ((RANGO_ESTADO[l.estado] ?? 0) > (RANGO_ESTADO[g.peorEstado] ?? 0) && l.cantidad_restante > 0) g.peorEstado = l.estado
      map.set(key, g)
    }
    const arr = [...map.values()]
    for (const g of arr) g.lotes.sort((a, b) => (a.fecha_entrada ?? '').localeCompare(b.fecha_entrada ?? ''))
    arr.sort((a, b) => a.nombre.localeCompare(b.nombre))
    return arr
  }, [filtrados])

  // Historial rápido: últimas entradas de lotes (más reciente primero).
  const historial = useMemo(() =>
    [...filtrados].sort((a, b) => (b.fecha_entrada ?? '').localeCompare(a.fecha_entrada ?? '')).slice(0, 15),
  [filtrados])

  const exportarCSV = () => {
    if (!filtrados.length) return
    const cabeceras = ['Producto', 'Sede', 'Proveedor', 'Lote', 'Estado', 'Cant. inicial', 'Cant. restante', 'Unidad', 'Entrada', 'Vencimiento', '% consumido']
    const filas = filtrados.map(l => [
      l.producto_nombre,
      l.tienda_nombre ?? '',
      l.proveedor ?? '',
      l.numero_lote ?? '',
      ESTADO[l.estado]?.label ?? l.estado,
      l.cantidad_inicial,
      l.cantidad_restante,
      l.unidad_medida,
      l.fecha_entrada ?? '',
      l.fecha_vencimiento ?? '',
      l.consumido_pct,
    ])
    const csv = [cabeceras, ...filas].map(r => r.join(',')).join('\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `lotes_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Boxes size={20} className="text-forest" />
          <h1 className="text-lg font-bold text-gray-800">Lotes y Trazabilidad</h1>
        </div>
        {porVencer > 0 && (
          <span className="flex items-center gap-1 text-xs font-bold text-amber-700 bg-amber-50 border border-amber-200 px-2.5 py-1 rounded-full">
            <AlertTriangle size={12} /> {porVencer} por vencer / vencidos
          </span>
        )}
        <div className="ml-auto">
          <button
            onClick={exportarCSV}
            disabled={filtrados.length === 0}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white transition-colors disabled:opacity-40"
            style={{ background: 'oklch(48% 0.15 155)' }}
            title="Descargar CSV"
          >
            <Download size={14} /> CSV
          </button>
        </div>
      </div>

      {/* Sede */}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={() => setTiendaId(null)}
          className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${tiendaId === null ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'}`}>Todas</button>
        {tiendas.map(t => (
          <button key={t.id} onClick={() => setTiendaId(t.id)}
            className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${tiendaId === t.id ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'}`}>{t.nombre}</button>
        ))}
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input value={busqueda} onChange={e => setBusqueda(e.target.value)} placeholder="Buscar producto, lote o proveedor…"
            className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm" />
        </div>
        <select value={proveedor} onChange={e => setProveedor(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">Todos los proveedores</option>
          {proveedores.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <select value={estado} onChange={e => setEstado(e.target.value)} className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">Todo estado</option>
          <option value="activo">Activos</option>
          <option value="por_vencer">Por vencer</option>
          <option value="vencido">Vencidos</option>
          <option value="agotado">Agotados</option>
        </select>
      </div>

      {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando lotes...</p>}

      {!loading && filtrados.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl px-4 py-10 text-center">
          <Boxes size={26} className="text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No hay lotes con esos filtros</p>
        </div>
      )}

      {!loading && filtrados.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">

          {/* ── Por producto (desplegable a sus lotes) ── */}
          <div className="lg:col-span-2 space-y-2">
            {grupos.map(g => {
              const abiertoG = abierto === g.key
              const venceCls = g.peorEstado === 'vencido' ? 'text-red-600'
                : g.peorEstado === 'por_vencer' ? 'text-amber-600' : 'text-gray-500'
              return (
                <div key={g.key} className="bg-white border border-gray-200 rounded-2xl overflow-hidden">
                  <button onClick={() => setAbierto(abiertoG ? null : g.key)}
                    className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-bold text-gray-800 truncate">{g.nombre}</p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {g.lotes.length} lote{g.lotes.length !== 1 ? 's' : ''}
                        {g.venceProximo && <span className={venceCls}> · vence {fmtF(g.venceProximo)}</span>}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-sm font-bold font-mono text-gray-800">{Math.round(g.restante)} {g.unidad}</p>
                      <p className="text-[10px] text-gray-400">restante</p>
                    </div>
                    {abiertoG ? <ChevronUp size={15} className="text-gray-400 shrink-0" /> : <ChevronDown size={15} className="text-gray-400 shrink-0" />}
                  </button>

                  {abiertoG && (
                    <div className="border-t border-gray-100 divide-y divide-gray-50">
                      {g.lotes.map(l => {
                        const e = ESTADO[l.estado]
                        return (
                          <div key={l.id} className="px-4 py-2.5">
                            <div className="flex items-center gap-2 flex-wrap text-xs text-gray-500">
                              <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold shrink-0 ${e.cls}`}>{e.label}</span>
                              {l.proveedor && <span className="flex items-center gap-1"><Truck size={11} /> {l.proveedor}</span>}
                              {l.numero_lote && <span>· Lote {l.numero_lote}</span>}
                              {tiendaId === null && l.tienda_nombre && <span>· {l.tienda_nombre}</span>}
                              <span className="flex items-center gap-1"><Calendar size={11} className="text-gray-400" /> Entró <b className="text-gray-700">{fmtF(l.fecha_entrada)}</b></span>
                              {l.fecha_vencimiento && <span>· Vence <b className={l.estado === 'vencido' ? 'text-red-600' : l.estado === 'por_vencer' ? 'text-amber-600' : 'text-gray-700'}>{fmtF(l.fecha_vencimiento)}</b></span>}
                              {l.fecha_agotado && <span>· Agotado {fmtF(l.fecha_agotado)}</span>}
                            </div>
                            <div className="flex items-center gap-3 mt-1.5">
                              <div className="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden">
                                <div className="h-full bg-forest" style={{ width: `${Math.min(100, l.consumido_pct)}%` }} />
                              </div>
                              <span className="text-[11px] font-mono text-gray-500 shrink-0">
                                {Math.round(l.cantidad_restante)}/{Math.round(l.cantidad_inicial)} {l.unidad_medida} · {l.consumido_pct}% consumido
                              </span>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* ── Historial rápido: últimas entradas ── */}
          <div className="bg-white border border-gray-200 rounded-2xl p-4">
            <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-3 flex items-center gap-1.5">
              <History size={13} /> Historial rápido
            </p>
            <div className="space-y-2.5">
              {historial.map(l => (
                <div key={l.id} className="text-xs">
                  <p className="text-gray-700">
                    Entró <b>{Math.round(l.cantidad_inicial)} {l.unidad_medida}</b> de <b>{l.producto_nombre}</b>
                  </p>
                  <p className="text-[11px] text-gray-400 mt-0.5">
                    {fmtF(l.fecha_entrada)}
                    {l.proveedor ? ` · ${l.proveedor}` : ''}
                    {tiendaId === null && l.tienda_nombre ? ` · ${l.tienda_nombre}` : ''}
                  </p>
                </div>
              ))}
              {historial.length === 0 && <p className="text-xs text-gray-400">Sin entradas registradas</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
