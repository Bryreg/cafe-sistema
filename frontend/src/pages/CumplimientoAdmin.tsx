import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { dark } from '../constants/darkTheme'
import { CheckCircle2, Circle, Clock, AlertTriangle, Camera, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Sparkles, Brush } from 'lucide-react'

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
interface TareaLimp { id: number; key: string; label: string; activa: boolean; orden: number }
interface RegistroLimp { id: number; tarea_key: string; fecha: string; semana: number; usuario_nombre: string; barista_nombre?: string | null; creado?: string | null }

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
const semanaDeIso = (iso: string) => Math.min(Math.floor((Number(iso.split('-')[2]) - 1) / 7) + 1, 4)
const MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
const fmtDiaLargo = (iso: string) => {
  const [a, m, d] = iso.split('-').map(Number)
  return new Date(a, m - 1, d).toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' })
}
// Minuto del día LOCAL de un timestamp UTC (para posicionar en el timeline).
const minutoDia = (iso: string) => { const d = parseUTC(iso); return d.getHours() * 60 + d.getMinutes() }

const STATUS: Record<'ok' | 'warn' | 'alert', { dot: string; label: string; bg: string; fg: string; Icon: typeof CheckCircle2 }> = {
  ok:    { dot: 'oklch(55% 0.16 145)', label: 'Al día',  bg: 'oklch(96% 0.04 145)', fg: 'oklch(35% 0.13 145)', Icon: CheckCircle2 },
  warn:  { dot: 'oklch(72% 0.15 65)',  label: 'Pronto',  bg: 'oklch(96% 0.06 70)',  fg: 'oklch(45% 0.14 55)',  Icon: Clock },
  alert: { dot: 'oklch(58% 0.19 25)',  label: 'Vencida', bg: 'oklch(96% 0.04 25)',  fg: 'oklch(48% 0.18 25)',  Icon: AlertTriangle },
}

// ─── Avatar de barista: color estable por nombre (hash→hue), 2 iniciales ───────
const hueDe = (s: string) => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360; return h }
const inicialesDe = (n: string) => { const p = n.trim().split(/\s+/); return (((p[0]?.[0] ?? '') + (p[1]?.[0] ?? '')).toUpperCase()) || '—' }
function BaristaAvatar({ nombre, size = 22 }: { nombre: string; size?: number }) {
  const h = hueDe(nombre)
  return (
    <span title={nombre} style={{
      width: size, height: size, borderRadius: 999, flexShrink: 0,
      background: `oklch(90% 0.05 ${h})`, color: `oklch(40% 0.13 ${h})`,
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.round(size * 0.42), fontWeight: 800, letterSpacing: '-0.03em',
      border: `1px solid oklch(80% 0.06 ${h})`,
    }}>{inicialesDe(nombre)}</span>
  )
}

const GREEN_TINT = 'oklch(96% 0.04 145)'
const AMBER = 'oklch(72% 0.15 65)'

export default function CumplimientoAdmin() {
  const { tiendaId } = useAuth()
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tid, setTid] = useState<number | null>(tiendaId ?? null)
  const [fecha, setFecha] = useState(isoLocal(new Date()))
  const [dia, setDia] = useState<CumplDia | null>(null)
  const [tend, setTend] = useState<TendDia[]>([])
  const [baristas, setBaristas] = useState<BaristaResumen[]>([])
  const [tareasLimp, setTareasLimp] = useState<TareaLimp[]>([])
  const [registrosLimp, setRegistrosLimp] = useState<RegistroLimp[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [foto, setFoto] = useState<string | null>(null)
  const [verMas, setVerMas] = useState(false)

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

  // Limpieza semanal (las 13 tareas de aseo profundo) — todo el mes del día elegido.
  useEffect(() => {
    if (tid == null) return
    const [a, m] = fecha.split('-').map(Number)
    let cancel = false
    Promise.all([
      api.get<TareaLimp[]>(`/limpieza/${tid}/tareas`).then(r => r.data).catch(() => [] as TareaLimp[]),
      api.get<RegistroLimp[]>(`/limpieza/${tid}/semanal`, { params: { mes: m, anio: a } }).then(r => r.data).catch(() => [] as RegistroLimp[]),
    ]).then(([tt, rr]) => { if (!cancel) { setTareasLimp(tt); setRegistrosLimp(rr) } })
    return () => { cancel = true }
  }, [tid, fecha])

  const maxTend = useMemo(() => Math.max(...tend.map(t => t.total), 1), [tend])
  const maxBar = useMemo(() => Math.max(...baristas.map(b => b.registros), 1), [baristas])

  const tareasLimpActivas = useMemo(() => [...tareasLimp].filter(t => t.activa).sort((a, b) => a.orden - b.orden), [tareasLimp])
  // Registros de aseo agrupados por semana (1-4) y tarea — para la matriz.
  const regsPorSemana = useMemo(() => {
    const w: Record<number, Record<string, RegistroLimp>> = { 1: {}, 2: {}, 3: {}, 4: {} }
    registrosLimp.forEach(r => { const s = Math.min(r.semana || 1, 4); w[s][r.tarea_key] = r })
    return w
  }, [registrosLimp])
  const hechasSemana = (s: number) => tareasLimpActivas.filter(t => regsPorSemana[s]?.[t.key]).length

  // KPIs del día
  const rutHechas = dia ? dia.rutinas.reduce((s, r) => s + r.hechas, 0) : 0
  const rutEsp = dia ? dia.rutinas.reduce((s, r) => s + (r.esperadas ?? 0), 0) : 0
  const vencidas = dia ? dia.rutinas.filter(r => r.status === 'alert').length : 0
  const registros7d = tend.reduce((s, t) => s + t.total, 0)

  // Ventana horaria del timeline (min→max de eventos, fallback 07–21, mínimo 2h).
  const win = useMemo(() => {
    const mins = dia ? dia.rutinas.flatMap(r => r.eventos.map(e => minutoDia(e.fecha))) : []
    let lo = mins.length ? Math.floor(Math.min(...mins) / 60) * 60 : 7 * 60
    let hi = mins.length ? Math.ceil(Math.max(...mins) / 60) * 60 : 21 * 60
    if (hi - lo < 120) hi = lo + 120
    return { lo, hi }
  }, [dia])
  const posX = (m: number) => Math.max(0, Math.min(100, ((m - win.lo) / (win.hi - win.lo)) * 100))
  const ticks = useMemo(() => {
    const out: number[] = []
    for (let h = Math.ceil(win.lo / 60); h * 60 <= win.hi; h += 2) out.push(h * 60)
    return out
  }, [win])

  const cambiarDia = (delta: number) => {
    const [a, m, d] = fecha.split('-').map(Number)
    const nd = new Date(a, m - 1, d + delta)
    if (isoLocal(nd) <= isoLocal(new Date())) setFecha(isoLocal(nd))
  }

  const card: React.CSSProperties = { background: dark.surface, border: `1px solid ${dark.border}`, borderRadius: 16 }
  const labelCss: React.CSSProperties = { margin: 0, fontSize: 10, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase', color: dark.inkSubtle }
  const secTitle: React.CSSProperties = { ...labelCss, fontSize: 11 }

  const hoyIso = isoLocal(new Date())
  const esMesActual = fecha.slice(0, 7) === hoyIso.slice(0, 7)
  const semanaHoy = semanaDeIso(hoyIso)
  const [anioSel, mesSel] = fecha.split('-').map(Number)

  return (
    <div className="flex flex-col gap-5 p-6 max-w-7xl">
      {/* ═══ HEADER ═══ */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-extrabold m-0" style={{ color: dark.ink }}>Limpieza y rutinas</h1>
          <p className="text-sm mt-0.5 m-0" style={{ color: dark.inkSubtle }}>
            Quién hizo qué y cuándo — rutinas por hora y aseo profundo semanal
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

      {/* ═══ BARRA DE PERIODO + KPIs ═══ */}
      <div className="flex flex-col lg:flex-row gap-3">
        <div className="flex items-center gap-2 flex-wrap rounded-xl px-3 py-2.5 lg:flex-1" style={card}>
          <button onClick={() => cambiarDia(-1)} className="p-1 rounded-lg" style={{ color: dark.inkMuted }} title="Día anterior"><ChevronLeft size={16} /></button>
          <span className="text-sm font-bold capitalize" style={{ color: dark.ink, minWidth: 180 }}>
            {dia ? fmtDiaLargo(dia.fecha) : '—'}{dia?.es_hoy ? ' · hoy' : ''}
          </span>
          <button onClick={() => cambiarDia(1)} disabled={fecha >= hoyIso} className="p-1 rounded-lg disabled:opacity-30" style={{ color: dark.inkMuted }} title="Día siguiente"><ChevronRight size={16} /></button>
          <input type="date" value={fecha} max={hoyIso} onChange={e => setFecha(e.target.value)}
            className="ml-auto border rounded-lg px-2 py-1 text-xs" style={{ borderColor: dark.border, color: dark.ink, background: dark.surface }} />
          {fecha !== hoyIso && (
            <button onClick={() => setFecha(hoyIso)} className="px-2.5 py-1 rounded-lg text-xs font-semibold" style={{ background: dark.surfaceAlt, color: dark.inkMuted }}>Hoy</button>
          )}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 lg:w-auto">
          {[
            { label: 'Rutinas hoy', val: `${rutHechas}/${rutEsp}`, color: dark.ink },
            { label: `Aseo semana ${semanaDeIso(fecha)}`, val: `${hechasSemana(semanaDeIso(fecha))}/${tareasLimpActivas.length || 0}`, color: hechasSemana(semanaDeIso(fecha)) === tareasLimpActivas.length && tareasLimpActivas.length > 0 ? 'oklch(45% 0.13 145)' : dark.ink },
            { label: 'Vencidas ahora', val: `${vencidas}`, color: vencidas > 0 ? 'oklch(48% 0.18 25)' : dark.ink },
            { label: 'Registros 7 días', val: `${registros7d}`, color: dark.ink },
          ].map(k => (
            <div key={k.label} className="px-3 py-2.5 rounded-xl" style={{ ...card, minWidth: 118 }}>
              <p style={labelCss}>{k.label}</p>
              <p className="font-extrabold tabular-nums m-0 mt-0.5" style={{ fontSize: 22, color: k.color }}>{k.val}</p>
            </div>
          ))}
        </div>
      </div>

      {loading ? (
        <p className="text-sm animate-pulse py-10 text-center" style={{ color: dark.inkSubtle }}>Cargando…</p>
      ) : error ? (
        <p className="text-sm py-6" style={{ color: dark.danger }}>{error}</p>
      ) : !dia ? null : (
        <>
          {/* ═══ SECCIÓN 3 — BOARD "ESTADO AHORA" (3 rutinas por hora) ═══ */}
          <div>
            <p style={secTitle} className="mb-2">{dia.es_hoy ? 'Estado ahora' : 'Rutinas del día'}</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {dia.rutinas.map(r => {
                const st = r.status ? STATUS[r.status] : null
                const quienes = Array.from(new Set(r.eventos.map(e => e.barista)))
                return (
                  <div key={r.clave} className="p-4 rounded-2xl" style={{ ...card, borderLeft: `4px solid ${st ? st.dot : dark.border}`, background: st ? st.bg : dark.surface }}>
                    <div className="flex items-center gap-2 flex-wrap">
                      {st && <st.Icon size={15} style={{ color: st.fg }} />}
                      <span className="font-bold" style={{ fontSize: 14, color: dark.ink }}>{r.nombre}</span>
                      {r.every && <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: dark.surface, color: dark.inkSubtle }}>cada {r.every % 60 === 0 ? `${r.every / 60}h` : `${r.every}min`}</span>}
                      {st && <span className="ml-auto text-[11px] font-bold px-2 py-0.5 rounded-full" style={{ background: dark.surface, color: st.fg }}>{st.label}</span>}
                    </div>
                    <p className="m-0 mt-2 font-extrabold tabular-nums" style={{ fontSize: 30, color: dark.ink, lineHeight: 1 }}>
                      {r.hechas}{r.esperadas != null && <span style={{ fontSize: 18, color: dark.inkSubtle, fontWeight: 700 }}> / {r.esperadas}</span>}
                      <span className="text-xs font-semibold ml-1" style={{ color: dark.inkSubtle }}>hechas</span>
                    </p>
                    <p className="m-0 mt-1.5 text-xs" style={{ color: dark.inkMuted }}>
                      {r.ultimo ? (
                        <>Última <strong style={{ color: dark.ink }}>{fmtHora(r.ultimo)}</strong>{r.minutos != null && ` · ${fmtHace(r.minutos)}`}
                          {dia.es_hoy && r.every && <> · próxima <strong style={{ color: dark.ink }}>{proximaHora(r.ultimo, r.every)}</strong></>}</>
                      ) : (<span style={{ color: dia.es_hoy ? 'oklch(48% 0.18 25)' : dark.inkSubtle }}>{dia.es_hoy ? 'Todavía no se registró hoy' : 'No se registró este día'}</span>)}
                    </p>
                    {quienes.length > 0 && (
                      <div className="flex items-center gap-1 mt-2.5">
                        {quienes.slice(0, 5).map((q, i) => <span key={i} style={{ marginLeft: i ? -6 : 0 }}><BaristaAvatar nombre={q} size={22} /></span>)}
                        {quienes.length > 5 && <span className="text-[11px] ml-1" style={{ color: dark.inkSubtle }}>+{quienes.length - 5}</span>}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* ═══ SECCIÓN 4 — TIMELINE DEL DÍA (quién/cuándo intradía, visual) ═══ */}
          {dia.rutinas.some(r => r.eventos.length > 0) && (
            <div style={card} className="p-4">
              <p style={secTitle} className="mb-3">Quién hizo qué y cuándo · a lo largo del día</p>
              <div className="flex flex-col gap-2">
                {dia.rutinas.map(r => { const every = r.every; return (
                  <div key={r.clave} className="flex items-center gap-2">
                    <span className="text-[11px] font-semibold shrink-0 flex items-center gap-1.5" style={{ width: 128, color: dark.inkMuted }}>
                      <span style={{ width: 7, height: 7, borderRadius: 999, background: r.status ? STATUS[r.status].dot : dark.inkSubtle }} />
                      {r.nombre}
                    </span>
                    <div className="relative flex-1" style={{ height: 34, background: dark.surfaceAlt, borderRadius: 8 }}>
                      {/* huecos: tramos > cadencia entre eventos consecutivos */}
                      {every != null && r.eventos.map((e, i) => {
                        if (i === 0) return null
                        const gap = minutoDia(e.fecha) - minutoDia(r.eventos[i - 1].fecha)
                        if (gap <= every * 1.5) return null
                        const x1 = posX(minutoDia(r.eventos[i - 1].fecha)), x2 = posX(minutoDia(e.fecha))
                        return <div key={`g${i}`} title={`${Math.round(gap / 6) / 10}h sin registrar`} style={{ position: 'absolute', left: `${x1}%`, width: `${x2 - x1}%`, top: 0, bottom: 0, background: 'oklch(95% 0.05 25)', borderRadius: 4 }} />
                      })}
                      {/* pins */}
                      {r.eventos.map((e, i) => (
                        <button key={i} onClick={() => e.imagen_url && setFoto(e.imagen_url)}
                          title={`${fmtHora(e.fecha)} · ${e.barista}${e.nota ? ' · ' + e.nota : ''}`}
                          style={{ position: 'absolute', left: `${posX(minutoDia(e.fecha))}%`, top: '50%', transform: 'translate(-50%,-50%)' }}>
                          <BaristaAvatar nombre={e.barista} size={20} />
                        </button>
                      ))}
                      {r.eventos.length === 0 && <span className="absolute inset-0 flex items-center justify-center text-[10px]" style={{ color: dark.inkSubtle }}>sin registros</span>}
                    </div>
                  </div>
                ) })}
                {/* eje de horas */}
                <div className="relative" style={{ height: 14, marginLeft: 136 }}>
                  {ticks.map(m => (
                    <span key={m} className="absolute text-[10px]" style={{ left: `${posX(m)}%`, transform: 'translateX(-50%)', color: dark.inkSubtle }}>
                      {String(Math.floor(m / 60)).padStart(2, '0')}h
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ═══ SECCIÓN 5 — MATRIZ DE ASEO PROFUNDO (13 tareas × 4 semanas) ═══ */}
          {tareasLimpActivas.length > 0 && (
            <div style={card} className="overflow-hidden">
              <div className="px-4 pt-4 pb-3 flex items-center justify-between">
                <p style={secTitle} className="flex items-center gap-1.5"><Brush size={13} /> Aseo profundo · {MESES[mesSel - 1]} {anioSel}</p>
                <div className="flex items-center gap-3 text-[10px]" style={{ color: dark.inkSubtle }}>
                  <span className="flex items-center gap-1"><CheckCircle2 size={11} style={{ color: 'oklch(55% 0.16 145)' }} /> hecha</span>
                  <span className="flex items-center gap-1"><Circle size={11} style={{ color: dark.inkSubtle }} /> pendiente</span>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse" style={{ minWidth: 640 }}>
                  <thead>
                    <tr>
                      <th className="sticky left-0 z-10 text-left px-4 py-2" style={{ background: dark.surfaceAlt, minWidth: 240, borderBottom: `1px solid ${dark.border}` }}>
                        <span style={labelCss}>Tarea</span>
                      </th>
                      {[1, 2, 3, 4].map(s => {
                        const esActual = esMesActual && s === semanaHoy
                        const hs = hechasSemana(s)
                        return (
                          <th key={s} className="px-3 py-2 text-center" style={{ minWidth: 150, borderBottom: `1px solid ${dark.border}`, borderLeft: `1px solid ${dark.border}`, background: esActual ? 'oklch(97% 0.03 70)' : dark.surface }}>
                            <p className="m-0 text-[11px] font-bold" style={{ color: esActual ? 'oklch(45% 0.14 55)' : dark.inkMuted }}>Semana {s}{esActual ? ' · hoy' : ''}</p>
                            <div className="mt-1 mx-auto rounded-full overflow-hidden" style={{ height: 5, width: '80%', background: dark.border }}>
                              <div style={{ height: '100%', width: `${tareasLimpActivas.length ? (hs / tareasLimpActivas.length) * 100 : 0}%`, background: hs === tareasLimpActivas.length && tareasLimpActivas.length ? 'oklch(55% 0.16 145)' : hs > 0 ? AMBER : dark.border }} />
                            </div>
                            <p className="m-0 mt-0.5 text-[10px] font-bold tabular-nums" style={{ color: dark.inkSubtle }}>{hs}/{tareasLimpActivas.length}</p>
                          </th>
                        )
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {tareasLimpActivas.map((t, i) => (
                      <tr key={t.id}>
                        <td className="sticky left-0 z-10 px-4 py-2.5" style={{ background: dark.surface, borderBottom: `1px solid ${dark.border}` }}>
                          <span className="text-[10px] font-bold mr-1.5" style={{ color: dark.inkSubtle }}>{String(i + 1).padStart(2, '0')}</span>
                          <span className="text-[13px]" style={{ color: dark.ink }}>{t.label}</span>
                        </td>
                        {[1, 2, 3, 4].map(s => {
                          const reg = regsPorSemana[s]?.[t.key]
                          const futura = esMesActual && s > semanaHoy
                          const quien = reg ? (reg.barista_nombre || reg.usuario_nombre) : null
                          return (
                            <td key={s} className="px-2 py-2 text-center align-middle" style={{ borderBottom: `1px solid ${dark.border}`, borderLeft: `1px solid ${dark.border}`, background: reg ? GREEN_TINT : futura ? dark.surfaceAlt : dark.surface }}
                              title={reg ? `${quien} · ${fmtDiaLargo(reg.fecha)}${reg.creado ? ' · ' + fmtHora(reg.creado) : ''}` : ''}>
                              {reg ? (
                                <div className="flex items-center justify-center gap-1.5">
                                  <BaristaAvatar nombre={quien!} size={22} />
                                  {reg.creado && <span className="text-[10px] tabular-nums" style={{ color: dark.inkMuted }}>{fmtHora(reg.creado)}</span>}
                                </div>
                              ) : (
                                <Circle size={15} style={{ color: futura ? 'oklch(88% 0.01 75)' : dark.inkSubtle, margin: '0 auto' }} />
                              )}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ═══ SECCIÓN 6 — PIE CONTEXTO (colapsable) ═══ */}
          <div>
            <button onClick={() => setVerMas(v => !v)} className="flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg" style={{ background: dark.surface, border: `1px solid ${dark.border}`, color: dark.inkMuted }}>
              {verMas ? <ChevronUp size={14} /> : <ChevronDown size={14} />} Ranking de baristas y actividad de 7 días
            </button>
            {verMas && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-3">
                {/* Quién registró rutinas · 7 días */}
                <div style={card} className="p-4">
                  <p style={secTitle} className="mb-3">Quién registró rutinas · 7 días</p>
                  {baristas.length === 0 ? (
                    <p className="text-sm m-0" style={{ color: dark.inkSubtle }}>Sin registros en el período.</p>
                  ) : (
                    <div className="flex flex-col gap-3">
                      {baristas.map(b => (
                        <div key={b.nombre} className="flex items-center gap-2.5">
                          <BaristaAvatar nombre={b.nombre} size={26} />
                          <div className="flex-1 min-w-0">
                            <div className="flex justify-between items-center mb-1">
                              <span className="font-bold text-[13px]" style={{ color: dark.ink }}>{b.nombre}</span>
                              <span className="font-mono font-bold tabular-nums text-[13px]" style={{ color: dark.ink }}>{b.registros}</span>
                            </div>
                            <div className="rounded-full overflow-hidden" style={{ height: 7, background: dark.border }}>
                              <div className="h-full rounded-full" style={{ width: `${b.registros / maxBar * 100}%`, background: 'oklch(55% 0.12 155)' }} />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {/* Actividad 7 días */}
                <div style={card} className="p-4">
                  <p style={secTitle} className="mb-3">Actividad de los últimos 7 días</p>
                  <div className="flex items-end gap-2" style={{ height: 90 }}>
                    {tend.map(t => {
                      const h = Math.round((t.total / maxTend) * 100)
                      const esSel = t.fecha === dia.fecha
                      const [ay, mo, dd] = t.fecha.split('-').map(Number)
                      const wd = new Date(ay, mo - 1, dd)
                      return (
                        <button key={t.fecha} onClick={() => setFecha(t.fecha)} className="flex-1 flex flex-col items-center gap-1 justify-end" style={{ height: '100%' }} title={`${t.total} registros`}>
                          <span className="text-[10px] font-bold tabular-nums" style={{ color: dark.inkSubtle }}>{t.total}</span>
                          <div style={{ width: '100%', maxWidth: 34, height: `${Math.max(h, t.total > 0 ? 6 : 2)}%`, background: esSel ? 'oklch(52% 0.14 50)' : 'oklch(65% 0.10 155)', borderRadius: '4px 4px 0 0' }} />
                          <span className="text-[10px] capitalize" style={{ color: esSel ? dark.ink : dark.inkSubtle, fontWeight: esSel ? 700 : 400 }}>{wd.toLocaleDateString('es-CO', { weekday: 'short' })} {dd}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}
          </div>

          {dia.rutinas.every(r => r.hechas === 0) && tareasLimpActivas.every(t => !regsPorSemana[semanaDeIso(fecha)]?.[t.key]) && (
            <div className="rounded-2xl border p-4 flex gap-3 items-start" style={{ background: 'oklch(97% 0.03 70)', borderColor: 'oklch(88% 0.07 70)' }}>
              <Sparkles size={18} style={{ color: 'oklch(55% 0.14 55)', flexShrink: 0, marginTop: 2 }} />
              <div>
                <p className="m-0 font-extrabold" style={{ fontSize: 14, color: dark.ink }}>Sin registros este día/semana</p>
                <p className="m-0 mt-1" style={{ fontSize: 13, color: dark.inkMuted }}>
                  Las baristas registran las rutinas desde el Panel de Turno (POS) y el aseo profundo desde Menú → Limpieza. Si hubo operación y no hay registros, conviene recordarles.
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
