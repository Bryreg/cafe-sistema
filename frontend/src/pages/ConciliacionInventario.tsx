import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'
import { Scale, Download, TrendingUp, TrendingDown, Minus, AlertTriangle, RotateCcw, Cpu, Users, ListChecks } from 'lucide-react'
import { hoyLocal } from '../utils/fechaLocal'

// ── Doble inventario del día (tabla Detalle) ─────────────────────────────────
interface CeldaConteo { real: number; diferencia: number; sistema: number }
interface FilaDiaria {
  producto_id: number; nombre: string; unidad: string
  sistema: number; apertura: CeldaConteo | null; entradas: number; cierre: CeldaConteo | null
}
interface CierrePrevio {
  fecha: string; barista: string | null; atajo: boolean
  por_producto: Record<number, { real: number; diferencia: number }>
}
interface Reincidente {
  producto_id: number; nombre: string; unidad: string
  dias_con_faltante: number; total_faltante: number; valor_faltante: number
}
interface ConciliacionDiaria {
  tiene_apertura: boolean; tiene_cierre: boolean
  apertura_barista: string | null; cierre_barista: string | null
  apertura_atajo?: boolean; cierre_atajo?: boolean
  items: FilaDiaria[]
  cierres_previos: CierrePrevio[]
  resumen: { faltante_valor: number; faltante_productos: number; sobrante_valor: number; sobrante_productos: number } | null
  reincidentes: Reincidente[]
  cierres_en_ventana: number
  atajos_en_ventana: number
}

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

  // ── Doble inventario del día ──────────────────────────────────────────────
  const [dia, setDia] = useState(hoyLocal())
  const [diaria, setDiaria] = useState<ConciliacionDiaria | null>(null)
  const [loadingDia, setLoadingDia] = useState(false)

  useEffect(() => {
    if (!tiendaId) return
    setLoadingDia(true)
    api.get<ConciliacionDiaria>(`/conteos/conciliacion-diaria/${tiendaId}`, { params: { fecha: dia } })
      .then(r => setDiaria(r.data))
      .catch(() => setDiaria(null))
      .finally(() => setLoadingDia(false))
  }, [tiendaId, dia])

  // Cierres previos en orden CRONOLÓGICO (el más viejo primero): van a la
  // izquierda de la apertura, como línea de tiempo que termina en hoy.
  const prevAsc = useMemo(() => [...(diaria?.cierres_previos ?? [])].reverse(), [diaria])

  // La tabla arranca desplazada al PRESENTE (extremo derecho): la historia
  // queda detrás, deslizando hacia atrás.
  const scrollTabla = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scrollTabla.current
    if (!el) return
    requestAnimationFrame(() => { el.scrollLeft = el.scrollWidth })
  }, [diaria])

  // Default: la lista COMPLETA del turno (sistema vivo + ultima apertura + cierre
  // cuando exista). El toggle de diferencias es opcional, para revisar dias viejos.
  const [soloDif, setSoloDif] = useState(false)
  const filasDia = useMemo(() => (diaria?.items ?? []).filter(i =>
    !soloDif ||
    (i.apertura !== null && i.apertura.diferencia !== 0) ||
    (i.cierre !== null && i.cierre.diferencia !== 0)
  ), [diaria, soloDif])

  const [reiniciando, setReiniciando] = useState(false)
  const reiniciarMes = async () => {
    if (!tiendaId) return
    if (!window.confirm(`¿Reiniciar el conteo de ${MESES[mes - 1]} de esta sede? Se borra el avance del mes y se vuelve a sembrar con el conteo del sistema ACTUAL (en gramos). Los meses cerrados no se tocan.`)) return
    setReiniciando(true)
    try {
      await api.post('/inventario-mensual/reiniciar', null, { params: { tienda_id: tiendaId, anio, mes } })
      const r = await api.get<Conciliacion | null>('/inventario-mensual/conciliacion', { params: { tienda_id: tiendaId, anio, mes } })
      setData(r.data)
      alert('Mes reiniciado — re-sembrado con el conteo del sistema actual.')
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo reiniciar')
    } finally { setReiniciando(false) }
  }

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
          <button onClick={reiniciarMes} disabled={reiniciando || !tiendaId || data?.estado === 'cerrado'}
            title="Borra el avance del mes en proceso y re-siembra con el conteo del sistema actual"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-amber-500 hover:bg-amber-600 disabled:opacity-40 text-white">
            <RotateCcw size={14} /> {reiniciando ? 'Reiniciando…' : 'Reiniciar mes'}
          </button>
          <button onClick={exportarCSV} disabled={!data}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white">
            <Download size={14} /> Excel
          </button>
        </div>
      </div>

      {/* Doble inventario: cómo se lee este panel bajo el modelo nuevo */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="bg-white rounded-2xl border border-gray-200 p-4 flex items-start gap-3">
          <span className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center shrink-0"><Cpu size={17} className="text-blue-600" /></span>
          <div>
            <p className="text-sm font-bold text-gray-800">Conteo del sistema</p>
            <p className="text-xs text-gray-500 mt-0.5">Corre solo, por movimientos: ventas del POS (con recetas en gramos), ingresos por factura, mermas y salidas.</p>
          </div>
        </div>
        <div className="bg-white rounded-2xl border border-gray-200 p-4 flex items-start gap-3">
          <span className="w-9 h-9 rounded-xl bg-amber-50 flex items-center justify-center shrink-0"><Users size={17} className="text-amber-600" /></span>
          <div>
            <p className="text-sm font-bold text-gray-800">Conteo de las baristas</p>
            <p className="text-xs text-gray-500 mt-0.5">Físico, en apertura y cierre. No modifica el inventario: se compara contra el sistema y las diferencias quedan registradas.</p>
          </div>
        </div>
        <Link to="/conteos-admin" className="bg-white rounded-2xl border border-gray-200 p-4 flex items-start gap-3 hover:border-forest transition-colors">
          <span className="w-9 h-9 rounded-xl bg-green-50 flex items-center justify-center shrink-0"><ListChecks size={17} className="text-green-700" /></span>
          <div>
            <p className="text-sm font-bold text-gray-800">Diferencias del día →</p>
            <p className="text-xs text-gray-500 mt-0.5">Monitor de Conteos: sistema vs contado por conteo, verificaciones y "Aplicar al inventario". Este panel es la foto MENSUAL.</p>
          </div>
        </Link>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {tiendas.map(t => (
          <button key={t.id} onClick={() => setTiendaId(t.id)}
            className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${tiendaId === t.id ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'}`}>{t.nombre}</button>
        ))}
      </div>

      {/* ── Señales de decisión: ¿a dónde se está yendo el producto? ── */}
      {diaria && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1 flex items-center gap-1">
                <TrendingDown size={12} className="text-red-500" /> Faltante del cierre
              </p>
              {diaria.tiene_cierre && diaria.resumen ? (
                <>
                  <p className="text-xl font-bold text-red-600 font-mono">{fmt(diaria.resumen.faltante_valor)}</p>
                  <p className="text-xs text-gray-400">{diaria.resumen.faltante_productos} productos · {dia}</p>
                </>
              ) : (
                <>
                  <p className="text-xl font-bold text-gray-300 font-mono">—</p>
                  <p className="text-xs text-gray-400">sin cierre aún</p>
                </>
              )}
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1 flex items-center gap-1">
                <TrendingUp size={12} className="text-blue-500" /> Sobrante del cierre
              </p>
              {diaria.tiene_cierre && diaria.resumen ? (
                <>
                  <p className="text-xl font-bold text-blue-600 font-mono">{fmt(diaria.resumen.sobrante_valor)}</p>
                  <p className="text-xs text-gray-400">{diaria.resumen.sobrante_productos} productos</p>
                </>
              ) : (
                <>
                  <p className="text-xl font-bold text-gray-300 font-mono">—</p>
                  <p className="text-xs text-gray-400">sin cierre aún</p>
                </>
              )}
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Fugas recurrentes</p>
              <p className={`text-xl font-bold font-mono ${diaria.reincidentes.filter(r => r.dias_con_faltante >= 2).length > 0 ? 'text-red-600' : 'text-green-700'}`}>
                {diaria.reincidentes.filter(r => r.dias_con_faltante >= 2).length}
              </p>
              <p className="text-xs text-gray-400">productos con faltante repetido (8 días)</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Calidad de conteos</p>
              <p className={`text-xl font-bold font-mono ${diaria.atajos_en_ventana > 0 ? 'text-amber-600' : 'text-green-700'}`}>
                {diaria.cierres_en_ventana} <span className="text-sm font-medium text-gray-400">reales</span>
              </p>
              <p className="text-xs text-gray-400">
                {diaria.atajos_en_ventana > 0 ? `⚡ ${diaria.atajos_en_ventana} con "Todo coincide"` : 'sin atajos en la ventana'}
              </p>
            </div>
          </div>

          {/* ¿A dónde se va el producto? — reincidencia = señal de fuga */}
          <div className="bg-white rounded-2xl border border-gray-200 p-4">
            <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">¿A dónde se va el producto?</p>
            <p className="text-xs text-gray-400 mb-3">
              Faltantes en los cierres de los últimos 8 días (los conteos con "Todo coincide" no cuentan).
              Un día con faltante es ruido; varios días seguidos es un patrón para investigar.
            </p>
            {diaria.reincidentes.length === 0 ? (
              <p className="text-sm text-green-700 font-medium">✓ Sin faltantes en los cierres de la ventana</p>
            ) : (
              <div className="space-y-1.5">
                {diaria.reincidentes.map(r => (
                  <div key={r.producto_id} className="flex items-center gap-2 text-sm">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${r.dias_con_faltante >= 3 ? 'bg-red-500' : r.dias_con_faltante === 2 ? 'bg-amber-400' : 'bg-gray-300'}`} />
                    <span className="flex-1 font-medium text-gray-700 truncate">{r.nombre}</span>
                    <span className="text-xs text-gray-400">
                      faltó en {r.dias_con_faltante} de {diaria.cierres_en_ventana} cierre{diaria.cierres_en_ventana !== 1 ? 's' : ''}
                    </span>
                    <span className="text-xs font-mono text-red-500 w-24 text-right">{num(r.total_faltante)} {r.unidad}</span>
                    <span className="font-mono font-bold w-24 text-right text-red-600">{r.valor_faltante > 0 ? `≈ ${fmt(r.valor_faltante)}` : ''}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Detalle: doble inventario del día */}
          <div className="flex items-center gap-3 flex-wrap">
            <p className="text-sm font-semibold text-gray-600">Detalle — doble inventario del día</p>
            <input type="date" value={dia} max={hoyLocal()} onChange={e => setDia(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 focus:outline-none focus:border-forest" />
            {diaria && (
              <span className="text-[11px] text-gray-400 flex items-center gap-1.5 flex-wrap">
                <span>{diaria.tiene_apertura ? `Abrió: ${diaria.apertura_barista ?? 's/n'}` : 'Sin conteo de apertura'}</span>
                {diaria.apertura_atajo && (
                  <span className="bg-amber-100 text-amber-700 font-bold px-1.5 py-0.5 rounded-full" title='La apertura se registró con el botón "Todo coincide con sistema" — no es un conteo físico'>
                    ⚡ Todo coincide
                  </span>
                )}
                <span>· {diaria.tiene_cierre ? `Cerró: ${diaria.cierre_barista ?? 's/n'}` : 'Sin conteo de cierre'}</span>
                {diaria.cierre_atajo && (
                  <span className="bg-amber-100 text-amber-700 font-bold px-1.5 py-0.5 rounded-full" title='El cierre se registró con el botón "Todo coincide con sistema" — no es un conteo físico'>
                    ⚡ Todo coincide
                  </span>
                )}
              </span>
            )}
            <span className="ml-auto flex items-center gap-3">
              {(diaria?.cierres_previos?.length ?? 0) > 0 && (
                <span className="text-[11px] text-gray-400 hidden sm:inline">
                  ← Deslizá la tabla hacia atrás para ver los cierres de días anteriores
                </span>
              )}
              <button onClick={() => setSoloDif(v => !v)}
                className={`text-xs px-3 py-1 rounded-lg font-semibold transition-colors ${
                  soloDif ? 'bg-gray-700 text-white' : 'bg-gray-100 text-gray-500'
                }`}>
                {soloDif ? '✓ Solo diferencias' : 'Solo diferencias'}
              </button>
            </span>
          </div>
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="overflow-x-auto" ref={scrollTabla}>
              {/* Línea de tiempo: los cierres de días anteriores van A LA IZQUIERDA de la
                  apertura (el pasado atrás). La tabla arranca desplazada al presente:
                  las 7 columnas principales llenan el ancho visible y se desliza hacia
                  atrás para ver la historia. */}
              <table className="text-sm"
                style={{ width: `calc(100% + ${(diaria?.cierres_previos?.length ?? 0) * 140}px)` }}>
                <thead>
                  <tr className="text-[11px] uppercase tracking-wide text-gray-400">
                    {/* Columnas 1-3 FIJAS: el scroll horizontal solo mueve el resto */}
                    <th className="text-left px-3 py-2 font-bold sticky left-0 z-10 bg-gray-50 min-w-[180px]">Producto</th>
                    <th className="text-right px-3 py-2 font-bold sticky left-[180px] z-10 bg-gray-50 min-w-[100px]">Dif. apertura</th>
                    <th className="text-right px-3 py-2 font-bold sticky left-[280px] z-10 bg-gray-50 min-w-[90px] border-r-2 border-gray-200">Sistema</th>
                    {prevAsc.map((cp, idx) => (
                      <th key={cp.fecha} className={`text-right px-3 py-2 font-bold bg-gray-50 w-[140px] min-w-[140px] whitespace-nowrap ${idx === prevAsc.length - 1 ? 'border-r-2 border-gray-200' : ''}`}>
                        Cierre {cp.fecha.slice(8, 10)}/{cp.fecha.slice(5, 7)}{cp.atajo ? ' ⚡' : ''}
                      </th>
                    ))}
                    <th className="text-right px-3 py-2 font-bold bg-gray-50 min-w-[110px]">Conteo apertura</th>
                    <th className="text-right px-3 py-2 font-bold bg-gray-50 min-w-[100px]">Ingresos del día</th>
                    <th className="text-right px-3 py-2 font-bold bg-gray-50 min-w-[120px]">Conteo cierre</th>
                    <th className="text-right px-3 py-2 font-bold bg-gray-50 min-w-[110px]">Dif. apertura → cierre</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {loadingDia ? (
                    <tr><td colSpan={7 + (diaria?.cierres_previos?.length ?? 0)} className="px-3 py-8 text-center text-sm text-gray-400 animate-pulse">Cargando día…</td></tr>
                  ) : filasDia.map(i => {
                    const celda = (c: CeldaConteo | null, conDif: boolean) => c === null
                      ? <span className="text-gray-300">—</span>
                      : (
                        <span className={c.diferencia !== 0 ? (c.diferencia < 0 ? 'text-red-600' : 'text-blue-600') : 'text-gray-800'}>
                          <span className="font-bold">{num(c.real)}</span>
                          {conDif && c.diferencia !== 0 && (
                            <span className="text-[11px] ml-1">({c.diferencia > 0 ? '+' : ''}{num(c.diferencia)})</span>
                          )}
                        </span>
                      )
                    const difAp = i.apertura?.diferencia ?? null
                    const cambioDia = i.apertura !== null && i.cierre !== null
                      ? i.cierre.real - i.apertura.real : null
                    return (
                      <tr key={i.producto_id} className="hover:bg-gray-50">
                        <td className="px-3 py-2 font-medium text-gray-700 sticky left-0 z-10 bg-white">{i.nombre}
                          <span className="text-xs text-gray-400 ml-1">{i.unidad}</span></td>
                        <td className={`px-3 py-2 text-right font-mono font-bold sticky left-[180px] z-10 bg-white ${
                          difAp === null ? 'text-gray-300' : difAp === 0 ? 'text-green-600' : difAp < 0 ? 'text-red-600' : 'text-blue-600'
                        }`}>
                          {difAp === null ? '—' : difAp === 0 ? '✓ 0' : `${difAp > 0 ? '+' : ''}${num(difAp)}`}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-gray-500 sticky left-[280px] z-10 bg-white border-r-2 border-gray-200">{num(i.sistema)}</td>
                        {prevAsc.map((cp, idx) => {
                          const d = cp.por_producto[i.producto_id]
                          return (
                            <td key={cp.fecha} className={`px-3 py-2 text-right font-mono w-[140px] min-w-[140px] ${idx === prevAsc.length - 1 ? 'border-r-2 border-gray-100' : ''}`}>
                              {d === undefined
                                ? <span className="text-gray-300">—</span>
                                : (
                                  <span className={d.diferencia !== 0 ? (d.diferencia < 0 ? 'text-red-600' : 'text-blue-600') : 'text-gray-600'}>
                                    {num(d.real)}
                                    {d.diferencia !== 0 && (
                                      <span className="text-[11px] ml-1">({d.diferencia > 0 ? '+' : ''}{num(d.diferencia)})</span>
                                    )}
                                  </span>
                                )}
                            </td>
                          )
                        })}
                        <td className="px-3 py-2 text-right font-mono">{celda(i.apertura, false)}</td>
                        <td className={`px-3 py-2 text-right font-mono ${i.entradas > 0 ? 'text-green-600 font-bold' : 'text-gray-300'}`}>
                          {i.entradas > 0 ? `+${num(i.entradas)}` : '0'}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{celda(i.cierre, true)}</td>
                        <td className={`px-3 py-2 text-right font-mono font-bold ${
                          cambioDia === null ? 'text-gray-300' : 'text-gray-700'
                        }`}>
                          {cambioDia === null ? '—' : `${cambioDia > 0 ? '+' : ''}${num(cambioDia)}`}
                        </td>
                      </tr>
                    )
                  })}
                  {!loadingDia && filasDia.length === 0 && (
                    <tr><td colSpan={7 + (diaria?.cierres_previos?.length ?? 0)} className="px-3 py-8 text-center text-sm text-gray-400">
                      {soloDif
                        ? 'Sin diferencias este día — los conteos clavaron con el sistema. Desactivá "Solo diferencias" para ver la lista completa.'
                        : 'Sin datos para este día.'}
                    </td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <p className="px-3 py-2 text-[11px] text-gray-400 border-t border-gray-50">
              Sistema = conteo interno (ventas con recetas, facturas, mermas). "Dif. apertura vs sistema" compara contra el sistema al momento de abrir; en el cierre, el paréntesis es su diferencia contra el sistema al cerrar. "Dif. apertura → cierre" es cuánto cambió el producto durante el día según las baristas. Los conteos nunca modifican el inventario.
            </p>
          </div>
        </>
      )}
    </div>
  )
}
