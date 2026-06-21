import { dark } from '../constants/darkTheme'
import type { RutinaEstado } from '../hooks/useRutinasEstado'

interface Props {
  estados: RutinaEstado[]
  onOpen: () => void
}

const TRACKED = ['limpieza', 'surtido', 'vitrina'] as const
const LABELS: Record<string, string> = {
  limpieza: 'Limpieza',
  surtido:  'Surtido',
  vitrina:  'Vitrina',
}

function dotColor(status: string | null): string {
  if (status === 'ok')    return '#22c55e'
  if (status === 'warn')  return '#f59e0b'
  if (status === 'alert') return '#ef4444'
  return '#cbd5e1'
}

function ago(m: number | null): string {
  if (m === null) return '—'
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r > 0 ? `${h}h ${r}m` : `${h}h`
}

export default function BannerOperativo({ estados, onOpen }: Props) {
  const byKey = Object.fromEntries(estados.map(e => [e.clave, e]))

  const alertCount = estados.filter(e => e.track && e.status === 'alert').length

  return (
    <button
      onClick={onOpen}
      className="fixed left-0 right-0 flex items-center gap-3 px-4 border-t border-b text-left transition-colors"
      style={{
        bottom: 60,
        height: 46,
        background: dark.surface,
        borderColor: dark.border,
        zIndex: 25,
      }}
    >
      {/* Label */}
      <span
        className="font-bold uppercase tracking-widest flex-shrink-0"
        style={{ fontSize: 9, color: dark.inkSubtle }}
      >
        Rutinas
      </span>

      {/* Status dots */}
      <div className="flex items-center gap-3 flex-1 min-w-0">
        {TRACKED.map(k => {
          const e = byKey[k]
          return (
            <div key={k} className="flex items-center gap-1 min-w-0">
              <span
                className="rounded-full flex-shrink-0"
                style={{ width: 8, height: 8, background: dotColor(e?.status ?? null) }}
              />
              <span
                className="truncate"
                style={{ fontSize: 10, color: dark.inkMuted }}
              >
                {LABELS[k]}
                {e?.minutos != null ? ` · ${ago(e.minutos)}` : ''}
              </span>
            </div>
          )
        })}
      </div>

      {/* Alert badge */}
      {alertCount > 0 && (
        <span
          className="flex-shrink-0 rounded-full flex items-center justify-center font-bold text-white"
          style={{
            width: 18, height: 18, fontSize: 10,
            background: dark.danger,
          }}
        >
          {alertCount}
        </span>
      )}
    </button>
  )
}
