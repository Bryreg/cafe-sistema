import { CheckCircle, AlertTriangle } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import type { RutinaEstado } from '../hooks/useRutinasEstado'

interface Props {
  estados: RutinaEstado[]
  panelOpen: boolean
  onOpen: () => void
}

const TRACKED = ['limpieza', 'surtido', 'vitrina'] as const
const LABELS: Record<string, string> = { limpieza: 'Limpieza', surtido: 'Surtido', vitrina: 'Vitrina' }

function dotColor(status: string | null): string {
  if (status === 'ok')    return '#22c55e'
  if (status === 'warn')  return '#f59e0b'
  if (status === 'alert') return '#ef4444'
  return '#cbd5e1'
}

function ago(m: number | null): string {
  if (m === null) return '—'
  if (m === 0) return 'recién'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r > 0 ? `${h}h ${r}m` : `${h}h`
}

export default function BannerOperativo({ estados, panelOpen, onOpen }: Props) {
  const byKey = Object.fromEntries(estados.map(e => [e.clave, e]))
  const alertCount = estados.filter(e => e.track && e.status === 'alert').length
  const novedades = byKey['novedad']?.count ?? 0
  const mermas    = byKey['merma_op']?.count ?? 0

  return (
    <div
      className="fixed left-0 right-0 flex items-center gap-3 px-4 border-t"
      style={{
        bottom: 60, height: 46,
        background: panelOpen ? dark.surfaceAlt : dark.surface,
        borderColor: dark.border,
        zIndex: 25,
      }}
    >
      {/* Label */}
      <span className="font-bold uppercase tracking-widest flex-shrink-0" style={{ fontSize: 9, color: dark.inkSubtle }}>
        Rutinas
      </span>

      {/* Status dots */}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {TRACKED.map(k => {
          const e = byKey[k]
          return (
            <div key={k} className="flex items-center gap-1 min-w-0">
              <span className="rounded-full flex-shrink-0" style={{ width: 8, height: 8, background: dotColor(e?.status ?? null) }} />
              <span className="truncate" style={{ fontSize: 10, color: dark.inkMuted }}>
                {LABELS[k]}{e?.minutos != null ? ` · ${ago(e.minutos)}` : ''}
              </span>
            </div>
          )
        })}
      </div>

      {/* Novedades / mermas */}
      {(novedades > 0 || mermas > 0) && (
        <>
          <span style={{ width: 1, height: 18, background: dark.border, flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: dark.inkMuted, flexShrink: 0, whiteSpace: 'nowrap' }}>
            {novedades > 0 && <>Nov <strong style={{ color: dark.ink }}>{novedades}</strong></>}
            {novedades > 0 && mermas > 0 && ' · '}
            {mermas > 0 && <>Mer <strong style={{ color: dark.ink }}>{mermas}</strong></>}
          </span>
        </>
      )}

      {/* Status pill */}
      <button
        onClick={onOpen}
        className="flex-shrink-0 flex items-center gap-1.5 rounded-full font-bold transition-all active:scale-95"
        style={{
          padding: '5px 10px', fontSize: 11,
          background: alertCount ? dark.dangerTint : dark.greenTint,
          color: alertCount ? dark.danger : dark.green,
        }}
      >
        {alertCount
          ? <><AlertTriangle size={12} /> {alertCount === 1 ? `1 alerta` : `${alertCount} alertas`}</>
          : <><CheckCircle size={12} /> Al día</>
        }
      </button>
    </div>
  )
}
