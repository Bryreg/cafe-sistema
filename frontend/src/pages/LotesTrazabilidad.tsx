import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import { Boxes, Search, Calendar, AlertTriangle, Truck, Download } from 'lucide-react'

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

      <div className="space-y-2">
        {filtrados.map(l => {
          const e = ESTADO[l.estado]
          return (
            <div key={l.id} className="bg-white border border-gray-200 rounded-2xl p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-bold text-gray-800 truncate">{l.producto_nombre}</p>
                  <p className="text-xs text-gray-400 flex items-center gap-1.5 flex-wrap mt-0.5">
                    {l.proveedor && <span className="flex items-center gap-1"><Truck size={11} /> {l.proveedor}</span>}
                    {l.numero_lote && <span>· Lote {l.numero_lote}</span>}
                    {l.tienda_nombre && <span>· {l.tienda_nombre}</span>}
                  </p>
                </div>
                <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold shrink-0 ${e.cls}`}>{e.label}</span>
              </div>

              {/* Fechas */}
              <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 flex-wrap">
                <span className="flex items-center gap-1"><Calendar size={11} className="text-gray-400" /> Entró: <b className="text-gray-700">{fmtF(l.fecha_entrada)}</b></span>
                {l.fecha_vencimiento && <span>Vence: <b className={l.estado === 'vencido' ? 'text-red-600' : l.estado === 'por_vencer' ? 'text-amber-600' : 'text-gray-700'}>{fmtF(l.fecha_vencimiento)}</b></span>}
                {l.fecha_agotado && <span>Agotado: <b className="text-gray-700">{fmtF(l.fecha_agotado)}</b></span>}
              </div>

              {/* Consumo */}
              <div className="flex items-center gap-3 mt-2">
                <div className="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">
                  <div className="h-full bg-forest" style={{ width: `${Math.min(100, l.consumido_pct)}%` }} />
                </div>
                <span className="text-xs font-mono text-gray-500 shrink-0">
                  {Math.round(l.cantidad_restante)}/{Math.round(l.cantidad_inicial)} {l.unidad_medida} · {l.consumido_pct}% consumido
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
