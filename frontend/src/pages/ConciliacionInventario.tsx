import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import { Scale, Download, TrendingUp, TrendingDown, Minus, AlertTriangle } from 'lucide-react'

interface Item {
  id: number; producto_nombre: string; categoria: string; unidad_medida: string
  cantidad_sistema: number; cantidad_real: number | null
  diferencia: number; valor_unitario: number; valor_diferencia: number
}
interface Cat { categoria: string; valor_diferencia: number; items: number; con_diferencia: number }
interface Conciliacion {
  id: number; anio: number; mes: number; estado: string
  valor_diferencia_total: number; items: Item[]
  resumen: { positivas: number; negativas: number; sin_diferencia: number; valor_positivo: number; valor_negativo: number; valor_neto: number }
  por_categoria: Cat[]; ranking: Item[]
}
interface Tienda { id: number; nombre: string }

const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const CAT_LABEL: Record<string, string> = { pasteleria: 'Pastelería', bebida: 'Bebidas', insumo: 'Insumos' }
const fmt = (v: number) => '$' + Math.round(v || 0).toLocaleString('es-CO')
const num = (v: number) => Math.round(v || 0).toLocaleString('es-CO')

export default function ConciliacionInventario() {
  const now = new Date()
  const [anio, setAnio] = useState(now.getFullYear())
  const [mes, setMes] = useState(now.getMonth() + 1)
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(null)
  const [data, setData] = useState<Conciliacion | null>(null)
  const [loading, setLoading] = useState(false)
  const [filtro, setFiltro] = useState<'todos' | 'con_diferencia'>('con_diferencia')

  useEffect(() => {
    api.get<Tienda[]>('/auth/tiendas').then(r => { setTiendas(r.data); setTiendaId(p => p ?? (r.data[0]?.id ?? null)) }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!tiendaId) return
    setLoading(true)
    api.get<Conciliacion | null>('/inventario-mensual/conciliacion', { params: { tienda_id: tiendaId, anio, mes } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [tiendaId, anio, mes])

  const items = useMemo(() => (data?.items ?? []).filter(i => filtro === 'todos' || i.diferencia !== 0), [data, filtro])

  const exportarCSV = () => {
    if (!data) return
    const head = ['Producto', 'Categoria', 'Unidad', 'Sistema', 'Fisico', 'Diferencia', 'Valor unit', 'Valor diferencia']
    const filas = data.items.map(i => [i.producto_nombre, i.categoria, i.unidad_medida, i.cantidad_sistema, i.cantidad_real ?? 0, i.diferencia, i.valor_unitario, i.valor_diferencia])
    const csv = [head, ...filas].map(r => r.join(';')).join('\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `conciliacion-${anio}-${String(mes).padStart(2, '0')}.csv`
    a.click()
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Scale size={20} className="text-forest" />
          <h1 className="text-lg font-bold text-gray-800">Conciliación de Inventario</h1>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <select value={mes} onChange={e => setMes(Number(e.target.value))} className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white">
            {MESES.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select value={anio} onChange={e => setAnio(Number(e.target.value))} className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white">
            {Array.from({ length: 5 }, (_, i) => now.getFullYear() - i).map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <button onClick={exportarCSV} disabled={!data}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white">
            <Download size={14} /> Excel
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {tiendas.map(t => (
          <button key={t.id} onClick={() => setTiendaId(t.id)}
            className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${tiendaId === t.id ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'}`}>{t.nombre}</button>
        ))}
      </div>

      {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando conciliación...</p>}

      {!loading && !data && (
        <div className="bg-white border border-gray-200 rounded-2xl px-4 py-12 text-center">
          <AlertTriangle size={26} className="text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No hay conteo mensual cerrado para {MESES[mes - 1]} {anio} en esta sede</p>
        </div>
      )}

      {!loading && data && (
        <>
          {/* KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Diferencia neta</p>
              <p className={`text-xl font-bold font-mono ${data.resumen.valor_neto < 0 ? 'text-red-600' : 'text-gray-800'}`}>{fmt(data.resumen.valor_neto)}</p>
              <p className="text-xs text-gray-400">{data.estado === 'cerrado' ? 'cerrado' : 'en proceso'}</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1 flex items-center gap-1"><TrendingDown size={12} className="text-red-500" /> Faltantes</p>
              <p className="text-xl font-bold text-red-600 font-mono">{fmt(Math.abs(data.resumen.valor_negativo))}</p>
              <p className="text-xs text-gray-400">{data.resumen.negativas} productos</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1 flex items-center gap-1"><TrendingUp size={12} className="text-blue-500" /> Sobrantes</p>
              <p className="text-xl font-bold text-blue-600 font-mono">{fmt(data.resumen.valor_positivo)}</p>
              <p className="text-xs text-gray-400">{data.resumen.positivas} productos</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1 flex items-center gap-1"><Minus size={12} className="text-green-500" /> Sin diferencia</p>
              <p className="text-xl font-bold text-green-700 font-mono">{data.resumen.sin_diferencia}</p>
            </div>
          </div>

          {/* Por categoría + ranking */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-3">Por categoría</p>
              <div className="space-y-2">
                {data.por_categoria.map(c => (
                  <div key={c.categoria} className="flex items-center gap-2 text-sm">
                    <span className="flex-1 font-medium text-gray-700">{CAT_LABEL[c.categoria] ?? c.categoria}</span>
                    <span className="text-xs text-gray-400">{c.con_diferencia}/{c.items} con dif.</span>
                    <span className={`font-mono font-bold w-24 text-right ${c.valor_diferencia < 0 ? 'text-red-600' : c.valor_diferencia > 0 ? 'text-blue-600' : 'text-gray-400'}`}>{fmt(c.valor_diferencia)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-3">Mayores diferencias</p>
              <div className="space-y-1.5">
                {data.ranking.slice(0, 8).map(i => (
                  <div key={i.id} className="flex items-center gap-2 text-sm">
                    <span className="flex-1 font-medium text-gray-700 truncate">{i.producto_nombre}</span>
                    <span className={`text-xs font-mono ${i.diferencia < 0 ? 'text-red-500' : 'text-blue-500'}`}>{i.diferencia > 0 ? '+' : ''}{num(i.diferencia)}</span>
                    <span className={`font-mono font-bold w-24 text-right ${i.valor_diferencia < 0 ? 'text-red-600' : 'text-blue-600'}`}>{fmt(i.valor_diferencia)}</span>
                  </div>
                ))}
                {data.ranking.length === 0 && <p className="text-sm text-gray-400">Sin diferencias</p>}
              </div>
            </div>
          </div>

          {/* Tabla detalle */}
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-gray-600">Detalle</p>
            <div className="ml-auto flex gap-1">
              {(['con_diferencia', 'todos'] as const).map(f => (
                <button key={f} onClick={() => setFiltro(f)}
                  className={`text-xs px-3 py-1 rounded-lg font-semibold ${filtro === f ? 'bg-gray-700 text-white' : 'bg-gray-100 text-gray-500'}`}>
                  {f === 'todos' ? 'Todos' : 'Solo con diferencia'}
                </button>
              ))}
            </div>
          </div>
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 text-[11px] uppercase tracking-wide text-gray-400">
                    <th className="text-left px-3 py-2 font-bold">Producto</th>
                    <th className="text-right px-3 py-2 font-bold">Teórico</th>
                    <th className="text-right px-3 py-2 font-bold">Físico</th>
                    <th className="text-right px-3 py-2 font-bold">Diferencia</th>
                    <th className="text-right px-3 py-2 font-bold hidden sm:table-cell">Valor unit.</th>
                    <th className="text-right px-3 py-2 font-bold">Valor dif.</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {items.map(i => (
                    <tr key={i.id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium text-gray-700">{i.producto_nombre}
                        <span className="text-xs text-gray-400 ml-1">{i.unidad_medida}</span></td>
                      <td className="px-3 py-2 text-right font-mono text-gray-500">{num(i.cantidad_sistema)}</td>
                      <td className="px-3 py-2 text-right font-mono text-gray-800 font-bold">{num(i.cantidad_real ?? 0)}</td>
                      <td className={`px-3 py-2 text-right font-mono font-bold ${i.diferencia < 0 ? 'text-red-600' : i.diferencia > 0 ? 'text-blue-600' : 'text-gray-300'}`}>{i.diferencia > 0 ? '+' : ''}{num(i.diferencia)}</td>
                      <td className="px-3 py-2 text-right font-mono text-gray-400 hidden sm:table-cell">{fmt(i.valor_unitario)}</td>
                      <td className={`px-3 py-2 text-right font-mono font-bold ${i.valor_diferencia < 0 ? 'text-red-600' : i.valor_diferencia > 0 ? 'text-blue-600' : 'text-gray-300'}`}>{fmt(i.valor_diferencia)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
