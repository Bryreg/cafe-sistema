import { useState } from 'react'
import { AlertTriangle, Check, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'

export default function PanelSalida() {
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()
  const [selected, setSelected] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  if (!turno) return null

  const salidas = turno.baristas_salidas ?? []
  const remaining = turno.baristas.filter(b => !salidas.includes(b))
  const isLast = selected.length > 0 && selected.length === remaining.length

  const toggle = (name: string) =>
    setSelected(prev =>
      prev.includes(name) ? prev.filter(b => b !== name) : [...prev, name]
    )

  const handleConfirm = async () => {
    if (selected.length === 0) return
    setSaving(true)
    setError('')
    try {
      if (isLast) {
        navigate('/conteo-cierre?kiosk=1')
      } else {
        for (const barista of selected) {
          const fd = new FormData()
          fd.append('barista_nombre', barista)
          await api.post(`/caja/${turno.id}/salida-barista`, fd)
        }
        await refresh()
        setDone(true)
      }
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar salida')
      setSaving(false)
    }
  }

  if (done) {
    const stillActive = remaining.filter(b => !selected.includes(b))
    return (
      <div className="flex flex-col items-center justify-center px-4 pt-14 pb-6 gap-4 min-h-[300px]">
        <div className="w-16 h-16 rounded-full flex items-center justify-center"
          style={{ background: dark.greenTint }}>
          <Check size={28} style={{ color: dark.green }} />
        </div>
        <p className="text-[17px] font-bold text-center" style={{ color: dark.ink }}>
          {selected.length === 1 ? 'Salida registrada' : 'Salidas registradas'}
        </p>
        {stillActive.length > 0 && (
          <p className="text-[13px] text-center" style={{ color: dark.inkSubtle }}>
            El turno continúa con {stillActive.join(' y ')}.
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col px-4 pt-14 pb-6 gap-5">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
          Salida de turno
        </p>
        <p className="text-[18px] font-bold mt-0.5" style={{ color: dark.ink }}>
          ¿Quién termina su turno?
        </p>
      </div>

      <div className="space-y-2">
        {remaining.length === 0 ? (
          <p className="text-[13px] text-center py-6" style={{ color: dark.inkSubtle }}>
            Todas las baristas ya registraron salida.
          </p>
        ) : (
          remaining.map(barista => {
            const sel = selected.includes(barista)
            return (
              <button
                key={barista}
                onClick={() => toggle(barista)}
                className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl transition-all"
                style={{
                  background: sel ? dark.amberTint : dark.surface,
                  border: `1px solid ${sel ? dark.amber : dark.border}`,
                }}
              >
                <div className="w-5 h-5 rounded-md flex items-center justify-center flex-shrink-0"
                  style={{
                    background: sel ? dark.amber : 'transparent',
                    border: `2px solid ${sel ? dark.amber : dark.border}`,
                  }}>
                  {sel && <Check size={12} className="text-white" />}
                </div>
                <User size={16} style={{ color: sel ? dark.amber : dark.inkSubtle }} />
                <span className="flex-1 text-left text-[15px] font-semibold" style={{ color: dark.ink }}>
                  {barista}
                </span>
              </button>
            )
          })
        )}
      </div>

      {selected.length > 0 && (
        <div className="rounded-2xl p-4" style={{ background: dark.amberTint, border: `1px solid ${dark.amberDim}` }}>
          <p className="text-[12px]" style={{ color: dark.amber }}>
            {isLast
              ? 'Última(s) barista(s) del turno — se hará conteo de inventario y cuadre de caja antes de cerrar.'
              : (() => {
                  const stays = remaining.filter(b => !selected.includes(b))
                  return `${stays.join(' y ')} continuará${stays.length > 1 ? 'n' : ''} con el turno.`
                })()
            }
          </p>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
          style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
          <AlertTriangle size={13} /> {error}
        </div>
      )}

      <button
        onClick={handleConfirm}
        disabled={selected.length === 0 || saving}
        className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40"
        style={{ background: isLast ? dark.danger : dark.amber }}
      >
        {saving
          ? 'Procesando...'
          : isLast
            ? 'Iniciar cierre del turno'
            : selected.length > 1
              ? `Confirmar ${selected.length} salidas`
              : 'Confirmar salida'
        }
      </button>
    </div>
  )
}
