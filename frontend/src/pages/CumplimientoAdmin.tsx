import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { dark } from '../constants/darkTheme'

interface RutinaResumen { clave: string; nombre: string; total: number; track: boolean }
interface BaristaResumen { id: number; nombre: string; registros: number; pct: number }
interface Data {
  por_rutina: RutinaResumen[]
  por_barista: BaristaResumen[]
  total_eventos: number
}

const TONE = {
  ok:      { bg: 'oklch(48% 0.16 145)', fg: '#fff' },
  parcial: { bg: 'oklch(72% 0.14 65)',  fg: 'oklch(18% 0.01 55)' },
  bajo:    { bg: 'oklch(88% 0.06 30)',  fg: 'oklch(45% 0.16 25)' },
  none:    { bg: 'oklch(60% 0.16 25)',  fg: '#fff' },
}

function barTone(pct: number) {
  if (pct >= 80) return 'oklch(48% 0.16 145)'
  if (pct >= 50) return 'oklch(72% 0.14 65)'
  if (pct > 0)  return 'oklch(60% 0.16 25)'
  return '#e5e7eb'
}

const CLAVES_TRACKED = ['limpieza', 'surtido', 'vitrina']
const EXP_POR_DIA: Record<string, number> = { limpieza: 2, surtido: 2, vitrina: 1 }

export default function CumplimientoAdmin() {
  const { tiendaId } = useAuth()
  const [data, setData] = useState<Data | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!tiendaId) return
    setLoading(true)
    api
      .get<Data>('/rutinas/cumplimiento-semana', { params: { tienda_id: tiendaId } })
      .then(r => setData(r.data))
      .catch(() => setError('No se pudo cargar el cumplimiento'))
      .finally(() => setLoading(false))
  }, [tiendaId])

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <p className="text-sm animate-pulse" style={{ color: dark.inkSubtle }}>Cargando…</p>
    </div>
  )
  if (error) return (
    <div className="p-6 text-sm" style={{ color: dark.danger }}>{error}</div>
  )
  if (!data) return null

  const byKey = Object.fromEntries(data.por_rutina.map(r => [r.clave, r]))
  const maxBar = Math.max(...data.por_barista.map(b => b.registros), 1)

  return (
    <div className="flex flex-col gap-6 p-6 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-xl font-extrabold m-0" style={{ color: dark.ink }}>Cumplimiento operativo</h1>
        <p className="text-sm mt-0.5 m-0" style={{ color: dark.inkSubtle }}>
          Frecuencia real de ejecución — últimos 7 días
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        {[
          { label: 'Eventos registrados', value: data.total_eventos, sub: '7 días' },
          { label: 'Baristas activos',    value: data.por_barista.filter(b => b.registros > 0).length, sub: 'con registros' },
          { label: 'Tipos de rutina',     value: data.por_rutina.filter(r => r.total > 0).length,      sub: 'ejecutados' },
        ].map(k => (
          <div key={k.label} className="rounded-2xl border p-4" style={{ background: dark.surface, borderColor: dark.border }}>
            <p className="m-0 mb-1 font-extrabold uppercase tracking-wide" style={{ fontSize: 10, color: dark.inkSubtle }}>{k.label}</p>
            <p className="m-0 font-bold tabular-nums" style={{ fontSize: 26, color: dark.ink, fontFamily: 'JetBrains Mono, monospace' }}>{k.value}</p>
            <p className="m-0 mt-1" style={{ fontSize: 12, color: dark.inkSubtle }}>{k.sub}</p>
          </div>
        ))}
      </div>

      {/* Tabla rutinas × tipo */}
      <div className="rounded-2xl border" style={{ background: dark.surface, borderColor: dark.border }}>
        <div className="px-5 pt-4 pb-3 border-b" style={{ borderColor: dark.border }}>
          <p className="m-0 font-extrabold uppercase tracking-wide" style={{ fontSize: 10, color: dark.inkSubtle }}>
            Frecuencia por rutina · semana completa
          </p>
        </div>
        <div className="px-5 py-3 flex flex-col gap-3">
          {data.por_rutina.filter(r => r.track || r.total > 0).map(r => {
            const exp = CLAVES_TRACKED.includes(r.clave) ? (EXP_POR_DIA[r.clave] ?? 1) * 7 : null
            const ratio = exp ? Math.min(r.total / exp, 1) : null
            const tone = ratio == null ? TONE.ok
              : ratio >= 1 ? TONE.ok
              : ratio >= 0.7 ? TONE.parcial
              : ratio > 0 ? TONE.bajo
              : TONE.none

            return (
              <div key={r.clave} className="flex items-center gap-4">
                <span className="font-semibold flex-shrink-0" style={{ fontSize: 13, color: dark.ink, minWidth: 120 }}>
                  {r.nombre}
                </span>
                {exp != null ? (
                  <div
                    className="flex items-center justify-center rounded-xl font-bold tabular-nums"
                    style={{ minWidth: 60, height: 32, background: tone.bg, color: tone.fg, fontSize: 13 }}
                  >
                    {r.total}<span style={{ opacity: .5, fontSize: 10, margin: '0 2px' }}>/</span><span style={{ opacity: .7, fontSize: 11 }}>{exp}</span>
                  </div>
                ) : (
                  <div
                    className="flex items-center justify-center rounded-xl font-bold tabular-nums"
                    style={{ minWidth: 60, height: 32, background: dark.surfaceAlt, color: dark.ink, fontSize: 13 }}
                  >
                    {r.total}
                  </div>
                )}
                {exp != null && (
                  <div className="flex-1 rounded-full overflow-hidden" style={{ height: 6, background: dark.border }}>
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${Math.min((r.total / exp) * 100, 100)}%`, background: tone.bg }}
                    />
                  </div>
                )}
                {exp != null && (
                  <span className="flex-shrink-0 font-mono" style={{ fontSize: 11, color: dark.inkSubtle, minWidth: 36, textAlign: 'right' }}>
                    c/{(CLAVES_TRACKED.includes(r.clave) && r.clave === 'vitrina') ? '3h' : '2h'}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Baristas */}
      <div className="rounded-2xl border" style={{ background: dark.surface, borderColor: dark.border }}>
        <div className="px-5 pt-4 pb-3 border-b" style={{ borderColor: dark.border }}>
          <p className="m-0 font-extrabold uppercase tracking-wide" style={{ fontSize: 10, color: dark.inkSubtle }}>
            Registros por barista · 7 días
          </p>
        </div>
        <div className="px-5 py-3 flex flex-col gap-4">
          {data.por_barista.length === 0 && (
            <p className="text-sm m-0" style={{ color: dark.inkSubtle }}>Sin baristas con registros en este período.</p>
          )}
          {data.por_barista.map(b => (
            <div key={b.id}>
              <div className="flex justify-between items-center mb-1.5">
                <span className="font-bold" style={{ fontSize: 13, color: dark.ink }}>{b.nombre}</span>
                <span className="font-mono font-bold tabular-nums" style={{ fontSize: 13, color: dark.ink }}>{b.registros}</span>
              </div>
              <div className="rounded-full overflow-hidden" style={{ height: 8, background: dark.border }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${b.registros / maxBar * 100}%`, background: barTone(b.pct) }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recomendación */}
      {data.total_eventos === 0 && (
        <div
          className="rounded-2xl border p-4 flex gap-3 items-start"
          style={{ background: 'oklch(94% 0.04 50)', borderColor: 'oklch(88% 0.07 50)' }}
        >
          <div style={{ fontSize: 20, flexShrink: 0 }}>💡</div>
          <div>
            <p className="m-0 font-extrabold" style={{ fontSize: 14, color: dark.ink }}>Sin datos aún</p>
            <p className="m-0 mt-1" style={{ fontSize: 13, color: dark.inkMuted }}>
              Los baristas no han registrado rutinas en los últimos 7 días. Abrí un turno y usá el Panel de Turno desde el POS para empezar a registrar.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
