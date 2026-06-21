import { useState } from 'react'
import { X, Sparkles, Package, Eye, StickyNote, Trash2, CheckCircle } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import type { RutinaEstado } from '../hooks/useRutinasEstado'

interface Props {
  estados: RutinaEstado[]
  onRegistrar: (clave: string) => Promise<void>
  onClose: () => void
}

const RUTINAS = [
  { k: 'limpieza', label: 'Limpieza General', Icon: Sparkles, track: true },
  { k: 'surtido',  label: 'Surtido',          Icon: Package,  track: true },
  { k: 'vitrina',  label: 'Revisión Vitrina', Icon: Eye,      track: true },
  { k: 'novedad',  label: 'Novedad',           Icon: StickyNote, track: false },
  { k: 'merma_op', label: 'Merma rápida',      Icon: Trash2,   track: false },
]

function ago(m: number | null): string {
  if (m === null) return '—'
  if (m < 60) return `hace ${m}m`
  const h = Math.floor(m / 60)
  const r = m % 60
  return r > 0 ? `hace ${h}h ${r}m` : `hace ${h}h`
}

function dotColor(status: string | null): string {
  if (status === 'ok')    return '#22c55e'
  if (status === 'warn')  return '#f59e0b'
  if (status === 'alert') return '#ef4444'
  return '#9ca3af'
}

export default function PanelTurno({ estados, onRegistrar, onClose }: Props) {
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

  return (
    <div
      className="flex flex-col h-full"
      style={{ background: dark.bg }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 border-b flex-shrink-0"
        style={{ borderColor: dark.border, background: dark.surface }}
      >
        <span className="text-sm font-bold" style={{ color: dark.ink }}>
          Rutinas del turno
        </span>
        <button
          onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-full"
          style={{ background: dark.surfaceAlt, color: dark.inkSubtle }}
        >
          <X size={15} />
        </button>
      </div>

      {/* Botones de rutina */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="grid grid-cols-3 gap-3 mb-6">
          {RUTINAS.map(({ k, label, Icon, track }) => {
            const estado = byKey[k]
            const isFlash = flash === k
            const isBusy = tapping === k

            return (
              <button
                key={k}
                onClick={() => tap(k)}
                disabled={!!tapping}
                className="flex flex-col items-center justify-center gap-2 rounded-2xl border transition-all active:scale-95"
                style={{
                  padding: '16px 8px',
                  background: isFlash ? dark.greenTint : dark.surface,
                  borderColor: isFlash ? dark.green : dark.border,
                  opacity: isBusy ? 0.6 : 1,
                }}
              >
                {isFlash ? (
                  <CheckCircle size={22} style={{ color: dark.green }} />
                ) : (
                  <Icon size={22} style={{ color: dark.inkMuted }} />
                )}
                <span
                  className="text-center font-semibold leading-tight"
                  style={{ fontSize: 11, color: dark.ink }}
                >
                  {label}
                </span>
                {track && estado && (
                  <div className="flex items-center gap-1">
                    <span
                      className="rounded-full"
                      style={{
                        width: 7, height: 7,
                        background: dotColor(estado.status),
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ fontSize: 9, color: dark.inkSubtle }}>
                      {ago(estado.minutos)}
                    </span>
                  </div>
                )}
                {!track && (
                  <span style={{ fontSize: 9, color: dark.inkSubtle }}>
                    {estado?.minutos != null ? ago(estado.minutos) : 'sin registro'}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* Últimas rutinas */}
        {estados.some(e => e.ultimo) && (
          <div>
            <p
              className="text-xs font-bold mb-2 uppercase tracking-wide"
              style={{ color: dark.inkSubtle }}
            >
              Últimas en este turno
            </p>
            <div className="flex flex-col gap-1">
              {estados
                .filter(e => e.ultimo)
                .sort((a, b) => (a.minutos ?? 999) - (b.minutos ?? 999))
                .map(e => (
                  <div
                    key={e.clave}
                    className="flex items-center justify-between rounded-xl px-3 py-2"
                    style={{ background: dark.surface }}
                  >
                    <span className="text-xs font-medium" style={{ color: dark.ink }}>
                      {e.nombre}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {e.track && (
                        <span
                          className="rounded-full"
                          style={{
                            width: 6, height: 6,
                            background: dotColor(e.status),
                          }}
                        />
                      )}
                      <span className="text-xs" style={{ color: dark.inkSubtle }}>
                        {ago(e.minutos)}
                      </span>
                    </div>
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
