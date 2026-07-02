import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { ChevronDown, ChevronUp, Download, ListChecks, Sun, Moon, User } from 'lucide-react'
import { hoyLocal, haceDiasLocal } from '../utils/fechaLocal'

// ─── Tipos ───────────────────────────────────────────────────────────────────

interface ConteoItem {
  producto_id: number
  nombre: string
  unidad: string
  sistema: number
  real: number
  diferencia: number
}

interface Conteo {
  id: number
  turno_id: number
  tipo: string // apertura | cierre
  fecha_registro: string | null
  barista_nombre: string | null
  n_items: number
  n_diferencias: number
  items: ConteoItem[]
}

interface Sede { id: number; nombre: string }

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmtN = (v: number) => Number.isInteger(v) ? String(v) : v.toFixed(2)

function parseUTC(s: string): Date {
  const t = s.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}
const fmtFechaHora = (s: string | null) => {
  if (!s) return '—'
  const d = parseUTC(s)
  return `${d.toLocaleDateString('es-CO', { weekday: 'short', day: '2-digit', month: 'short' })} · ${d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}`
}

async function exportarExcel(nombre: string, cabeceras: string[], filas: (string | number | null)[][]) {
  const XLSX = await import('xlsx')
  const ws = XLSX.utils.aoa_to_sheet([cabeceras, ...filas])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Conteos')
  XLSX.writeFile(wb, `${nombre}.xlsx`)
}

// ─── Página ──────────────────────────────────────────────────────────────────

/**
 * Monitor de conteos físicos (hub admin): cada conteo de apertura/cierre con sus
 * items, resaltando las diferencias contra el sistema. Los conteos ajustan el
 * stock al confirmarse — esta pantalla es la trazabilidad de esos ajustes.
 */
export default function ConteosAdmin() {
  const { user } = useAuth()
  const tiendaDefault = user?.tienda_id ?? 1

  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number>(tiendaDefault)
  const [desde, setDesde] = useState(haceDiasLocal(7))
  const [hasta, setHasta] = useState(hoyLocal())
  const [conteos, setConteos] = useState<Conteo[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [abierto, setAbierto] = useState<number | null>(null)
  const [soloDif, setSoloDif] = useState(true)

  useEffect(() => {
    api.get('/auth/tiendas').then(({ data }) => {
      setSedes(data)
      if (data.length > 0) setTiendaId(data[0].id)
    }).catch(() => {})
  }, [])

  const cargar = async () => {
    setLoading(true)
    try {
      const { data } = await api.get(`/conteos/tienda/${tiendaId}`, {
        params: { fecha_desde: desde, fecha_hasta: hasta },
      })
      setConteos(data ?? [])
      setAbierto(null)
    } finally { setLoading(false) }
  }

  useEffect(() => { cargar() }, [tiendaId, desde, hasta]) // eslint-disable-line react-hooks/exhaustive-deps

  const exportar = () => {
    if (!conteos) return
    const filas: (string | number | null)[][] = []
    for (const c of conteos) {
      for (const i of c.items) {
        filas.push([fmtFechaHora(c.fecha_registro), c.tipo, c.barista_nombre ?? '', c.turno_id,
          i.nombre, i.unidad, i.sistema, i.real, i.diferencia])
      }
    }
    exportarExcel(`conteos_${desde}_${hasta}`,
      ['Fecha', 'Tipo', 'Barista', 'Turno', 'Producto', 'Unidad', 'Sistema', 'Contado', 'Diferencia'], filas)
  }

  return (
    <div className="min-h-screen" style={{ background: '#f5f3ef', fontFamily: '"Plus Jakarta Sans", -apple-system, system-ui, sans-serif' }}>
      <div style={{ maxWidth: 760, margin: '0 auto', padding: '16px 16px 40px' }}>

        <div className="flex items-center gap-2 mb-3">
          <ListChecks size={18} style={{ color: 'oklch(45% 0.1 155)' }} />
          <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: 'oklch(22% 0.02 60)' }}>Conteos de inventario</h1>
        </div>

        {/* Filtros */}
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {sedes.length > 1 && sedes.map(s => (
            <button key={s.id} onClick={() => setTiendaId(s.id)}
              className="px-3 py-1 rounded-full text-xs font-bold"
              style={tiendaId === s.id
                ? { background: 'oklch(30% 0.06 155)', color: '#fff' }
                : { background: 'oklch(94% 0.005 75)', color: 'oklch(50% 0.01 60)' }}>
              {s.nombre}
            </button>
          ))}
          <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
            className="text-xs px-2 py-1 rounded-lg border bg-white" style={{ borderColor: 'oklch(88% 0.006 75)' }} />
          <span className="text-xs text-gray-400">→</span>
          <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
            className="text-xs px-2 py-1 rounded-lg border bg-white" style={{ borderColor: 'oklch(88% 0.006 75)' }} />
          <label className="flex items-center gap-1.5 text-xs font-semibold text-gray-500 ml-auto cursor-pointer">
            <input type="checkbox" checked={soloDif} onChange={e => setSoloDif(e.target.checked)} />
            Solo diferencias
          </label>
          {conteos && conteos.length > 0 && (
            <button onClick={exportar}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
              style={{ background: 'oklch(48% 0.15 155)' }}>
              <Download size={12} /> Excel
            </button>
          )}
        </div>

        {/* Lista */}
        {loading ? (
          <p className="text-sm text-gray-400 text-center py-10">Cargando...</p>
        ) : !conteos || conteos.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-10">Sin conteos en el período.</p>
        ) : (
          <div className="space-y-2">
            {conteos.map(c => {
              const esApertura = c.tipo === 'apertura'
              const visibles = soloDif ? c.items.filter(i => Math.round(i.diferencia * 1000) !== 0) : c.items
              const abiertoEste = abierto === c.id
              return (
                <div key={c.id} className="bg-white rounded-2xl border overflow-hidden" style={{ borderColor: 'oklch(92% 0.008 75)' }}>
                  <button onClick={() => setAbierto(abiertoEste ? null : c.id)}
                    className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50">
                    <span className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0"
                      style={{ background: esApertura ? 'oklch(95% 0.04 145)' : 'oklch(96% 0.04 30)' }}>
                      {esApertura
                        ? <Sun size={15} style={{ color: 'oklch(40% 0.12 145)' }} />
                        : <Moon size={15} style={{ color: 'oklch(45% 0.15 30)' }} />}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-bold text-gray-800">
                        Conteo de {c.tipo} <span className="text-xs font-medium text-gray-400">· turno #{c.turno_id}</span>
                      </p>
                      <p className="text-xs text-gray-500 flex items-center gap-2">
                        {fmtFechaHora(c.fecha_registro)}
                        {c.barista_nombre && <span className="inline-flex items-center gap-1"><User size={10} />{c.barista_nombre}</span>}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs text-gray-400">{c.n_items} ítems</p>
                      {c.n_diferencias > 0
                        ? <p className="text-xs font-bold text-red-600">{c.n_diferencias} con diferencia</p>
                        : <p className="text-xs font-bold text-green-600">✓ sin diferencias</p>}
                    </div>
                    {abiertoEste ? <ChevronUp size={15} className="text-gray-400 shrink-0" /> : <ChevronDown size={15} className="text-gray-400 shrink-0" />}
                  </button>

                  {abiertoEste && (
                    <div style={{ borderTop: '1px solid oklch(95% 0.005 75)' }}>
                      {visibles.length === 0 ? (
                        <p className="text-xs text-gray-400 text-center py-4">
                          {soloDif ? 'Sin diferencias — todo coincidió con el sistema.' : 'Sin ítems.'}
                        </p>
                      ) : (
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="text-gray-400" style={{ background: 'oklch(98% 0.004 75)' }}>
                              <th className="text-left px-4 py-2 font-semibold">Producto</th>
                              <th className="text-right px-2 py-2 font-semibold">Sistema</th>
                              <th className="text-right px-2 py-2 font-semibold">Contado</th>
                              <th className="text-right px-4 py-2 font-semibold">Dif.</th>
                            </tr>
                          </thead>
                          <tbody>
                            {visibles.map(i => {
                              const hayDif = Math.round(i.diferencia * 1000) !== 0
                              return (
                                <tr key={i.producto_id} style={{ borderTop: '1px solid oklch(97% 0.004 75)' }}>
                                  <td className="px-4 py-1.5 text-gray-700">{i.nombre} <span className="text-gray-300">{i.unidad}</span></td>
                                  <td className="px-2 py-1.5 text-right font-mono text-gray-500">{fmtN(i.sistema)}</td>
                                  <td className="px-2 py-1.5 text-right font-mono font-semibold text-gray-800">{fmtN(i.real)}</td>
                                  <td className={`px-4 py-1.5 text-right font-mono font-bold ${!hayDif ? 'text-gray-300' : i.diferencia > 0 ? 'text-green-700' : 'text-red-600'}`}>
                                    {hayDif ? (i.diferencia > 0 ? '+' : '') + fmtN(i.diferencia) : '='}
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
