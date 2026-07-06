import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { dark } from '../constants/darkTheme'
import { CheckCircle2, Clock, AlertTriangle, Camera, ChevronLeft, ChevronRight, Sparkles } from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface Sede { id: number; nombre: string }
interface EventoDia { fecha: string; barista: string; valor: number | null; nota: string | null; imagen_url: string | null }
interface RutinaDia {
  clave: string; nombre: string; every: number | null
  hechas: number; esperadas: number | null; pct: number | null
  ultimo: string | null; minutos: number | null; status: 'ok' | 'warn' | 'alert' | null
  eventos: EventoDia[]
}
interface CumplDia { fecha: string; es_hoy: boolean; ventana: { inicio: string | null; fin: string | null }; rutinas: RutinaDia[] }
interface TendDia { fecha: string; total: number; por_clave: Record<string, number> }
interface BaristaResumen { nombre: string; registros: number; pct: number }

// ─── Helpers ──────────────────────────────────────────────────────────────────
const parseUTC = (s: string) => {
  const t = s.replace(' ', 'T').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}
const fmtHora = (s: string) => parseUTC(s).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
const fmtHace = (min: number) => min < 60 ? `hace ${min} min` : `hace ${Math.floor(min / 60)}h ${min % 60 ? `${min % 60}m` : ''}`.trim()
const proximaHora = (ultimo: string, every: number) => {
  const d = parseUTC(ultimo); d.setMinutes(d.getMinutes() + every)
  return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
}
const isoLocal = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const fmtDiaLargo = (iso: string) => {
  const [a, m, d] = iso.split('-').map(Number)
  return new Date(a, m - 1, d).toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })
}

const STATUS: Record<'ok' | 'warn' | 'alert', { dot: string; label: string; bg: string; fg: string; Icon: typeof CheckCircle2 }> = {
  ok:    { dot: 'oklch(55% 0.16 145)', label: 'Al día',  bg: 'oklch(95% 0.05 145)', fg: 'oklch(35% 0.13 145)', Icon: CheckCircle2 },
  warn:  { dot: 'oklch(72% 0.15 65)',  label: 'Pronto',  bg: 'oklch(96% 0.06 70)',  fg: 'oklch(45% 0.14 55)',  Icon: Clock },
  alert: { dot: 'oklch(58% 0.19 25)',  label: 'Vencida', bg: 'oklch(95% 0.05 25)',  fg: 'oklch(48% 0.18 25)',  Icon: AlertTriangle },
}

export default function CumplimientoAdmin() {
  const { tiendaId } = useAuth()
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tid, setTid] = useState<number | null>(tiendaId ?? null)
  const [fecha, setFecha] = useState(isoLocal(new Date()))
  const [dia, setDia] = useState<CumplDia | null>(null)
  const [tend, setTend] = useState<TendDia[]>([])
  const [baristas, setBaristas] = useState<BaristaResumen[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [foto, setFoto] = useState<string | null>(null)

  useEffect(() => {
    api.get('/auth/tiendas').then(({ data }) => {
      setSedes(data)
      if (tid == null && data.length > 0) setTid(data[0].id)
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (tid == null) { setLoading(false); setError('Tu cuenta no tiene una sede asignada.'); return }
    setLoading(true); setError('')
    Promise.all([
      api.get<CumplDia>('/rutinas/cumplimiento-dia', { params: { tienda_id: tid, fecha } }),
      api.get<TendDia[]>('/rutinas/cumplimiento-tendencia', { params: { tienda_id: tid, dias: 7 } }),
      api.get<{ por_barista: BaristaResumen[] }>('/rutinas/cumplimiento-semana', { params: { tienda_id: tid } }),
    ])
      .then(([d, t, s]) => { setDia(d.data); setTend(t.data); setBaristas(s.data.por_barista) })
      .catch(() => setError('No se pudo cargar el cumplimiento'))
      .finally(() => setLoading(false))
  }, [tid, fecha])

  const maxTend = useMemo(() => Math.max(...tend.map(t => t.total), 1), [tend])
  const maxBar = useMemo(() => Math.max(...baristas.map(b => b.registros), 1), [baristas])

  const cambiarDia = (delta: number) => {
    const [a, m, d] = fecha.split('-').map(Number)
    const nd = new Date(a, m - 1, d + delta)
    if (isoLocal(nd) <= isoLocal(new Date())) setFecha(isoLocal(nd))
  }

  const card: React.CSSProperties = { background: dark.surface, border: `1px solid ${dark.border}`, borderRadius: 16 }
  const labelCss: React.CSSProperties = { margin: 0, fontSize: 10, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase', color: dark.inkSubtle }

  return (
    <div className="flex flex-col gap-5 p-6 max-w-5xl">
      {/* Header + selectores */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-extrabold m-0" style={{ color: dark.ink }}>Limpieza y rutinas</h1>
          <p className="text-sm mt-0.5 m-0" style={{ color: dark.inkSubtle }}>
            Cómo va la operación del día — cuándo se hizo cada rutina y qué está al día
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {sedes.length > 1 && sedes.map(s => (
            <button key={s.id} onClick={() => setTid(s.id)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors"
              style={tid === s.id
                ? { background: 'oklch(52% 0.14 50)', color: '#fff', borderColor: 'oklch(52% 0.14 50)' }
                : { background: dark.surface, color: dark.inkMuted, borderColor: dark.border }}>
              {s.nombre}
            </button>
          ))}
        </div>
      </div>

      {/* Selector de día */}
      <div className="flex items-center gap-2 flex-wrap rounded-xl px-3 py-2.5" style={card}>
        <button onClick={() => cambiarDia(-1)} className="p-1 rounded-lg" style={{ color: dark.inkMuted }} title="Día anterior">
          <ChevronLeft size={16} />
        </button>
        <span className="text-sm font-bold capitalize" style={{ color: dark.ink, minWidth: 190 }}>
          {dia ? fmtDiaLargo(dia.fecha) : '—'}{dia?.es_hoy ? ' · hoy' : ''}
        </span>
        <button onClick={() => cambiarDia(1)} disabled={fecha >= isoLocal(new Date())}
          className="p-1 rounded-lg disabled:opacity-30" style={{ color: dark.inkMuted }} title="Día siguiente">
          <ChevronRight size={16} />
        </button>
        <input type="date" value={fecha} max={isoLocal(new Date())} onChange={e => setFecha(e.target.value)}
          className="ml-auto border rounded-lg px-2 py-1 text-xs" style={{ borderColor: dark.border, color: dark.ink, background: dark.surface }} />
        {fecha !== isoLocal(new Date()) && (
          <button onClick={() => setFecha(isoLocal(new Date()))}
            className="px-2.5 py-1 rounded-lg text-xs font-semibold" style={{ background: dark.surfaceAlt, color: dark.inkMuted }}>Hoy</button>
        )}
      </div>

      {loading ? (
        <p className="text-sm animate-pulse py-10 text-center" style={{ color: dark.inkSubtle }}>Cargando…</p>
      ) : error ? (
        <p className="text-sm py-6" style={{ color: dark.danger }}>{error}</p>
      ) : !dia ? null : (
        <>
          {/* ── Estado por rutina: cuándo, última, próxima, semáforo + timeline del día ── */}
          <div className="flex flex-col gap-3">
            {dia.rutinas.map(r => {
              const st = r.status ? STATUS[r.status] : null
              const gapMin = (a: string, b: string) => Math.round((parseUTC(b).getTime() - parseUTC(a).getTime()) / 60000)
              return (
                <div key={r.clave} style={card} className="p-4">
                  {/* Cabecera de la rutina */}
                  <div className="flex items-center gap-3 flex-wrap">
                    {st && <span style={{ width: 10, height: 10, borderRadius: 999, background: st.dot, flexShrink: 0 }} />}
                    <span className="font-bold" style={{ fontSize: 14, color: dark.ink }}>{r.nombre}</span>
                    {r.every && (
                      <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: dark.surfaceAlt, color: dark.inkSubtle }}>
                        cada {r.every % 60 === 0 ? `${r.every / 60}h` : `${r.every}min`}
                      </span>
                    )}
                    {st && (
                      <span className="text-xs font-bold px-2 py-0.5 rounded-full flex items-center gap-1" style={{ background: st.bg, color: st.fg }}>
                        <st.Icon size={11} /> {st.label}
                      </span>
                    )}
                    <span className="ml-auto text-sm font-bold tabular-nums" style={{ color: dark.ink }}>
                      {r.hechas}{r.esperadas != null && <span style={{ color: dark.inkSubtle, fontWeight: 500 }}> / {r.esperadas}</span>}
                      <span className="text-xs font-medium" style={{ color: dark.inkSubtle }}> hechas hoy</span>
                    </span>
                  </div>

                  {/* Última / próxima */}
                  <div className="flex items-center gap-4 flex-wrap mt-2 text-xs" style={{ color: dark.inkMuted }}>
                    {r.ultimo ? (
                      <>
                        <span>Última: <strong style={{ color: dark.ink }}>{fmtHora(r.ultimo)}</strong>{r.minutos != null && <span style={{ color: dark.inkSubtle }}> · {fmtHace(r.minutos)}</span>}</span>
                        {dia.es_hoy && r.every && <span>Próxima esperada: <strong style={{ color: dark.ink }}>{proximaHora(r.ultimo, r.every)}</strong></span>}
                      </>
                    ) : (
                      <span style={{ color: dia.es_hoy ? 'oklch(48% 0.18 25)' : dark.inkSubtle }}>
                        {dia.es_hoy ? 'Todavía no se registró hoy' : 'No se registró este día'}
                      </span>
                    )}
                  </div>

                  {/* Línea de tiempo: cada evento con su hora + barista, huecos en rojo */}
                  {r.eventos.length > 0 && (
                    <div className="flex items-center gap-1.5 flex-wrap mt-3">
                      {r.eventos.map((e, i) => {
                        const hueco = i > 0 && r.every ? gapMin(r.eventos[i - 1].fecha, e.fecha) : 0
                        const saltos = r.every ? Math.floor(hueco / r.every) - 1 : 0
                        return (
                          <span key={i} className="flex items-center gap-1.5">
                            {saltos > 0 && (
                              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: 'oklch(95% 0.05 25)', color: 'oklch(48% 0.18 25)' }}
                                title={`${Math.round(hueco / 60 * 10) / 10}h sin registrar`}>
                                ⋯ {saltos} sin hacer
                              </span>
                            )}
                            <span className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg"
                              style={{ background: dark.surfaceAlt, color: dark.ink }}
                              title={`${e.barista}${e.nota ? ' · ' + e.nota : ''}${e.valor != null ? ' · ' + e.valor : ''}`}>
                              <strong className="tabular-nums">{fmtHora(e.fecha)}</strong>
                              <span style={{ color: dark.inkSubtle }}>{e.barista}</span>
                              {e.imagen_url && (
                                <button onClick={() => setFoto(e.imagen_url!)} style={{ color: 'oklch(55% 0.08 155)' }}><Camera size={11} /></button>
                              )}
                            </span>
                          </span>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* ── Tendencia: actividad de limpieza por día (últimos 7) ── */}
          <div style={card} className="p-4">
            <p style={labelCss} className="mb-3">Actividad de los últimos 7 días</p>
            <div className="flex items-end gap-2" style={{ height: 90 }}>
              {tend.map(t => {
                const h = Math.round((t.total / maxTend) * 100)
                const esSel = t.fecha === dia.fecha
                const [ay, mo, dd] = t.fecha.split('-').map(Number)
                const wd = new Date(ay, mo - 1, dd)
                return (
                  <button key={t.fecha} onClick={() => setFecha(t.fecha)}
                    className="flex-1 flex flex-col items-center gap-1 justify-end" style={{ height: '100%' }} title={`${t.total} registros`}>
                    <span className="text-[10px] font-bold tabular-nums" style={{ color: dark.inkSubtle }}>{t.total}</span>
                    <div style={{ width: '100%', maxWidth: 34, height: `${Math.max(h, t.total > 0 ? 6 : 2)}%`,
                      background: esSel ? 'oklch(52% 0.14 50)' : 'oklch(65% 0.10 155)', borderRadius: '4px 4px 0 0' }} />
                    <span className="text-[10px] capitalize" style={{ color: esSel ? dark.ink : dark.inkSubtle, fontWeight: esSel ? 700 : 400 }}>
                      {wd.toLocaleDateString('es-CO', { weekday: 'short' })} {dd}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* ── Quién limpió (nombres reales) ── */}
          <div style={card} className="p-4">
            <p style={labelCss} className="mb-3">Quién registró rutinas · últimos 7 días</p>
            {baristas.length === 0 ? (
              <p className="text-sm m-0" style={{ color: dark.inkSubtle }}>Sin registros en el período.</p>
            ) : (
              <div className="flex flex-col gap-3">
                {baristas.map(b => (
                  <div key={b.nombre}>
                    <div className="flex justify-between items-center mb-1.5">
                      <span className="font-bold" style={{ fontSize: 13, color: dark.ink }}>{b.nombre}</span>
                      <span className="font-mono font-bold tabular-nums" style={{ fontSize: 13, color: dark.ink }}>{b.registros}</span>
                    </div>
                    <div className="rounded-full overflow-hidden" style={{ height: 8, background: dark.border }}>
                      <div className="h-full rounded-full" style={{ width: `${b.registros / maxBar * 100}%`, background: 'oklch(55% 0.12 155)' }} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {dia.rutinas.every(r => r.hechas === 0) && (
            <div className="rounded-2xl border p-4 flex gap-3 items-start" style={{ background: 'oklch(94% 0.04 50)', borderColor: 'oklch(88% 0.07 50)' }}>
              <Sparkles size={18} style={{ color: 'oklch(55% 0.14 55)', flexShrink: 0, marginTop: 2 }} />
              <div>
                <p className="m-0 font-extrabold" style={{ fontSize: 14, color: dark.ink }}>Sin rutinas registradas este día</p>
                <p className="m-0 mt-1" style={{ fontSize: 13, color: dark.inkMuted }}>
                  Las baristas registran limpieza, surtido y vitrina desde el Panel de Turno en el POS. Si el día tuvo operación y no hay registros, conviene recordarles.
                </p>
              </div>
            </div>
          )}
        </>
      )}

      {/* Modal foto */}
      {foto && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,.8)' }} onClick={() => setFoto(null)}>
          <img src={foto} alt="" className="max-w-lg w-full rounded-2xl" onClick={e => e.stopPropagation()} />
        </div>
      )}
    </div>
  )
}
