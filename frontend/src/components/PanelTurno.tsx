import { useState } from 'react'
import {
  X, Sparkles, Package, Eye, StickyNote, Trash2, CheckCircle,
  Check, Lock, AlertTriangle, Circle,
} from 'lucide-react'
import { dark } from '../constants/darkTheme'
import type { RutinaEstado, BitacoraEntry } from '../hooks/useRutinasEstado'
import type { Turno } from '../contexts/TurnoContext'

interface Props {
  turno: Turno
  estados: RutinaEstado[]
  bitacora: BitacoraEntry[]
  onRegistrar: (clave: string) => Promise<void>
  onClose: () => void
}

const RUTINAS = [
  { k: 'limpieza', label: 'Limpieza',  Icon: Sparkles,   track: true },
  { k: 'surtido',  label: 'Surtido',   Icon: Package,    track: true },
  { k: 'vitrina',  label: 'Vitrina',   Icon: Eye,        track: true },
  { k: 'novedad',  label: 'Novedad',   Icon: StickyNote, track: false },
  { k: 'merma_op', label: 'Merma',     Icon: Trash2,     track: false },
]

function ago(m: number | null): string {
  if (m === null) return '—'
  if (m === 0) return 'recién'
  if (m < 60) return `hace ${m}m`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r > 0 ? `hace ${h}h ${r}m` : `hace ${h}h`
}

function fmtHora(iso: string): string {
  try {
    const s = iso.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
    const d = new Date(s.endsWith('Z') ? s : s + 'Z')
    return d.toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso.slice(11, 16)
  }
}

function dotColor(status: string | null): string {
  if (status === 'ok')    return '#22c55e'
  if (status === 'warn')  return '#f59e0b'
  if (status === 'alert') return '#ef4444'
  return '#cbd5e1'
}

function TipoLabel({ tipo }: { tipo: string | null }) {
  const map: Record<string, string> = { apertura: 'Apertura', intermedio: 'Intermedio', cierre: 'Cierre' }
  return <>{map[tipo ?? ''] ?? 'Turno'}</>
}

const LBL = { fontSize: 10, fontWeight: 800, textTransform: 'uppercase' as const, letterSpacing: '.05em', color: dark.inkSubtle, margin: 0 }

export default function PanelTurno({ turno, estados, bitacora, onRegistrar, onClose }: Props) {
  const [tapping, setTapping] = useState<string | null>(null)
  const [flash, setFlash] = useState<string | null>(null)

  const tap = async (k: string) => {
    if (tapping) return
    setTapping(k)
    try {
      await onRegistrar(k)
      setFlash(k)
      setTimeout(() => setFlash(null), 1800)
    } finally {
      setTapping(null)
    }
  }

  const byKey = Object.fromEntries(estados.map(e => [e.clave, e]))
  const alerts = estados.filter(e => e.track && e.status === 'alert')

  // Obligatorios de apertura
  const obligAp = [
    { k: 'cuadre',  label: 'Cuadre de llegada',    done: turno.tiene_cuadre_llegada,    ts: turno.fecha_apertura },
    { k: 'conteo',  label: 'Conteo de apertura',   done: turno.tiene_conteo_apertura,   ts: turno.ts_conteo_apertura ?? turno.fecha_apertura },
  ]
  const obligCierre = [
    { k: 'conteo_c', label: 'Conteo de cierre',     done: turno.tiene_conteo_cierre, ts: turno.ts_conteo_cierre },
    { k: 'cuadre_c', label: 'Cuadre de caja',       done: false,                     ts: null },
    { k: 'entrega',  label: 'Entrega de efectivo',  done: false,                     ts: null },
    { k: 'cierre_t', label: 'Cierre de turno',      done: turno.estado === 'cerrado', ts: null },
  ]
  const apDone  = obligAp.filter(o => o.done).length
  const cierreDone = obligCierre.filter(o => o.done).length
  const total = obligAp.length + obligCierre.length
  const done  = apDone + cierreDone

  return (
    <div className="flex flex-col h-full" style={{ background: dark.bg }}>

      {/* ── Header ── */}
      <div
        className="flex-shrink-0 px-5 py-4"
        style={{ background: 'oklch(18% 0.01 55)', color: '#f8f5f0' }}
      >
        <div className="flex items-center justify-between">
          <span style={{ fontSize: 15, fontWeight: 800 }}>Panel de Turno</span>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-full"
            style={{ background: 'rgba(255,255,255,.1)', color: '#d4cfc9' }}
          >
            <X size={14} />
          </button>
        </div>
        <div className="flex items-center gap-2 mt-3 flex-wrap">
          <span style={{ fontSize: 13, fontWeight: 700 }}><TipoLabel tipo={turno.tipo_turno} /></span>
          <span style={{ fontSize: 12, opacity: .6 }}>· inició {fmtHora(turno.fecha_apertura)}</span>
          {turno.baristas.length > 0 && (
            <>
              <span style={{ width: 3, height: 3, borderRadius: 99, background: 'rgba(255,255,255,.3)', flexShrink: 0 }} />
              {turno.baristas.map(b => (
                <span key={b} style={{ fontSize: 11, fontWeight: 600, background: 'rgba(255,255,255,.12)', borderRadius: 999, padding: '2px 8px' }}>
                  {b}
                </span>
              ))}
            </>
          )}
        </div>
      </div>

      {/* ── Body scrollable ── */}
      <div className="flex-1 overflow-y-auto" style={{ padding: 16 }}>
        <div className="flex flex-col gap-5">

          {/* Alertas */}
          {alerts.length > 0 && (
            <section className="flex flex-col gap-2">
              {alerts.map(a => (
                <div
                  key={a.clave}
                  className="flex items-center gap-3 rounded-2xl border"
                  style={{ padding: '11px 14px', background: dark.dangerTint, borderColor: '#fecaca' }}
                >
                  <AlertTriangle size={16} style={{ color: dark.danger, flexShrink: 0 }} />
                  <div className="flex-1 min-w-0">
                    <p className="m-0 font-bold" style={{ fontSize: 13, color: '#7f1d1d' }}>{a.nombre} pendiente</p>
                    <p className="m-0 mt-0.5" style={{ fontSize: 11, color: '#b91c1c' }}>
                      sin registrar {ago(a.minutos)} · esperado c/{a.every ? `${Math.round(a.every / 60)}h` : '—'}
                    </p>
                  </div>
                  <button
                    onClick={() => tap(a.clave)}
                    disabled={!!tapping}
                    className="rounded-xl font-bold text-white transition-all active:scale-95"
                    style={{ padding: '5px 10px', fontSize: 11, background: dark.danger }}
                  >
                    Registrar
                  </button>
                </div>
              ))}
            </section>
          )}

          {/* Obligatorios */}
          <section>
            <div className="flex items-center justify-between mb-2.5">
              <p style={LBL}>Procesos obligatorios</p>
              <span
                className="rounded-full font-bold tabular-nums"
                style={{
                  fontSize: 10, padding: '2px 7px',
                  background: done === total ? dark.greenTint : dark.amberTint,
                  color: done === total ? dark.green : dark.amber,
                }}
              >
                {done}/{total}
              </span>
            </div>
            <div
              className="rounded-2xl border"
              style={{ background: dark.surface, borderColor: dark.border, padding: '4px 14px' }}
            >
              <p className="mt-2 mb-1" style={{ fontSize: 11, fontWeight: 800, color: dark.green }}>
                ☀ Apertura{apDone === obligAp.length ? ' · completa' : ''}
              </p>
              {obligAp.map(o => (
                <div key={o.k} className="flex items-center gap-2.5" style={{ padding: '7px 0', borderTop: '1px solid oklch(94% 0.006 75)' }}>
                  <span
                    className="flex items-center justify-center rounded-lg flex-shrink-0"
                    style={{
                      width: 22, height: 22,
                      background: o.done ? dark.greenTint : dark.surfaceAlt,
                      color: o.done ? dark.green : dark.inkSubtle,
                    }}
                  >
                    {o.done ? <Check size={12} /> : <Circle size={12} />}
                  </span>
                  <span className="flex-1 font-semibold" style={{ fontSize: 13, color: dark.ink }}>{o.label}</span>
                  {o.done && o.ts && (
                    <span className="font-mono" style={{ fontSize: 11, color: dark.inkSubtle }}>{fmtHora(o.ts)}</span>
                  )}
                </div>
              ))}

              <p className="mt-3 mb-1" style={{ fontSize: 11, fontWeight: 800, color: dark.inkSubtle }}>
                🌙 Cierre · al finalizar
              </p>
              {obligCierre.map(o => (
                <div key={o.k} className="flex items-center gap-2.5" style={{ padding: '7px 0', borderTop: '1px solid oklch(94% 0.006 75)' }}>
                  <span
                    className="flex items-center justify-center rounded-lg flex-shrink-0"
                    style={{ width: 22, height: 22, background: o.done ? dark.greenTint : dark.surfaceAlt, color: o.done ? dark.green : dark.inkSubtle }}
                  >
                    {o.done ? <Check size={12} /> : <Lock size={11} />}
                  </span>
                  <span className="flex-1 font-semibold" style={{ fontSize: 13, color: o.done ? dark.ink : dark.inkSubtle }}>
                    {o.label}
                  </span>
                  {o.done && o.ts && (
                    <span className="font-mono" style={{ fontSize: 11, color: dark.inkSubtle }}>{fmtHora(o.ts)}</span>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* Botones rápidos — solo rutinas reales (Novedad/Merma viven en su propia herramienta) */}
          <section>
            <p style={{ ...LBL, marginBottom: 10 }}>Registrar rutina · 1 clic</p>
            <div className="grid grid-cols-3 gap-2.5">
              {RUTINAS.filter(d => d.track).map(({ k, label, Icon, track }) => {
                const estado = byKey[k]
                const isAlert = track && estado?.status === 'alert'
                const isFlash = flash === k
                const isBusy = tapping === k
                return (
                  <button
                    key={k}
                    onClick={() => tap(k)}
                    disabled={!!tapping}
                    className="flex flex-col items-center justify-center gap-2 rounded-2xl border-2 transition-all active:scale-95"
                    style={{
                      padding: '13px 6px',
                      background: isFlash ? dark.greenTint : isAlert ? dark.dangerTint : dark.surface,
                      borderColor: isFlash ? dark.green : isAlert ? '#fca5a5' : dark.border,
                      opacity: isBusy ? 0.55 : 1,
                    }}
                  >
                    {isFlash
                      ? <CheckCircle size={20} style={{ color: dark.green }} />
                      : <Icon size={20} style={{ color: isAlert ? dark.danger : dark.inkMuted }} />
                    }
                    <span style={{ fontSize: 11, fontWeight: 700, color: dark.ink, textAlign: 'center', lineHeight: 1.2 }}>
                      {label}
                    </span>
                  </button>
                )
              })}
            </div>
          </section>

          {/* Últimas rutinas */}
          <section>
            <p style={{ ...LBL, marginBottom: 10 }}>Últimas rutinas</p>
            <div
              className="rounded-2xl border"
              style={{ background: dark.surface, borderColor: dark.border, padding: '4px 14px' }}
            >
              {RUTINAS.filter(d => d.track).map(({ k, label }) => {
                const e = byKey[k]
                return (
                  <div key={k} className="flex items-center gap-3" style={{ padding: '10px 0', borderTop: '1px solid oklch(94% 0.006 75)' }}>
                    <span className="rounded-full flex-shrink-0" style={{ width: 8, height: 8, background: dotColor(e?.status ?? null) }} />
                    <span className="flex-1 font-semibold" style={{ fontSize: 13, color: dark.ink }}>{label}</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: dotColor(e?.status ?? null) }}>
                      {ago(e?.minutos ?? null)}
                    </span>
                  </div>
                )
              })}
              <div className="flex gap-5" style={{ padding: '10px 0', borderTop: '1px solid oklch(94% 0.006 75)' }}>
                <span style={{ fontSize: 12, color: dark.inkMuted }}>
                  Novedades: <strong style={{ color: dark.ink }}>{byKey['novedad']?.count ?? 0}</strong>
                </span>
                <span style={{ fontSize: 12, color: dark.inkMuted }}>
                  Mermas: <strong style={{ color: dark.ink }}>{byKey['merma_op']?.count ?? 0}</strong>
                </span>
              </div>
            </div>
          </section>

          {/* Bitácora */}
          {bitacora.length > 0 && (
            <section>
              <p style={{ ...LBL, marginBottom: 12 }}>Bitácora del turno</p>
              <div style={{ position: 'relative', paddingLeft: 20 }}>
                <div
                  style={{
                    position: 'absolute', left: 5, top: 4, bottom: 4,
                    width: 2, background: dark.border, borderRadius: 1,
                  }}
                />
                {bitacora.map((e, i) => (
                  <div key={i} style={{ position: 'relative', paddingBottom: 12 }}>
                    <span
                      style={{
                        position: 'absolute', left: -20, top: 3,
                        width: 10, height: 10, borderRadius: 99,
                        background: e.hito ? dark.green : 'oklch(68% 0.15 65)',
                        border: `2px solid ${dark.bg}`,
                      }}
                    />
                    <div className="flex gap-2 items-baseline">
                      <span className="font-mono font-bold flex-shrink-0" style={{ fontSize: 11, color: dark.inkSubtle, minWidth: 36 }}>
                        {fmtHora(e.fecha)}
                      </span>
                      <span style={{ fontSize: 13, color: dark.ink, fontWeight: e.hito ? 700 : 500 }}>
                        {e.txt}
                        {e.by && <span style={{ color: dark.inkSubtle, fontWeight: 400 }}> · {e.by}</span>}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
