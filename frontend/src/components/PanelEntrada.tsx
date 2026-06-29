import { useEffect, useRef, useState } from 'react'
import { Camera, Check, AlertTriangle } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'

interface Barista { id: number; nombre: string }
const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

export default function PanelEntrada({ onClose }: { onClose: () => void }) {
  const { turno, refresh } = useTurno()
  const [baristas, setBaristas] = useState<Barista[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [imagen, setImagen] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.get<Barista[]>('/auth/baristas').then(({ data }) => {
      const enTurno = new Set(turno?.baristas ?? [])
      setBaristas(data.filter(b => !enTurno.has(b.nombre)))
    }).catch(() => {})
  }, [turno])

  const confirmar = async () => {
    if (!turno || selected === null) return
    setSaving(true)
    setError('')
    try {
      const fd = new FormData()
      fd.append('barista_id', String(selected))
      if (imagen) fd.append('imagen', imagen)
      await api.post(`/caja/${turno.id}/entrada`, fd)
      await refresh()
      setDone(true)
      setTimeout(onClose, 1400)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar entrada')
    } finally {
      setSaving(false)
    }
  }

  if (!turno) return null

  if (done) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 px-6 pt-14">
        <div className="w-14 h-14 rounded-full flex items-center justify-center"
          style={{ background: dark.greenTint }}>
          <Check size={28} style={{ color: dark.green }} strokeWidth={2.5} />
        </div>
        <p className="text-[15px] font-bold text-center" style={{ color: dark.ink }}>
          ¡Entrada registrada!
        </p>
        <p className="text-[12px] text-center" style={{ color: dark.inkSubtle }}>
          {baristas.find(b => b.id === selected)?.nombre ?? ''} ya figura en el turno
        </p>
      </div>
    )
  }

  const selectedBarista = baristas.find(b => b.id === selected)

  return (
    <div className="flex flex-col px-4 pt-14 pb-6 gap-4">
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
          Entrada de barista
        </p>
        <p className="text-[18px] font-bold mt-0.5" style={{ color: dark.ink }}>
          ¿Quién entra al turno?
        </p>
      </div>

      {/* Barista selector */}
      {baristas.length === 0 ? (
        <div className="rounded-2xl p-4 text-center" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <p className="text-[13px]" style={{ color: dark.inkSubtle }}>
            Todas las baristas ya están en el turno
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {baristas.map(b => (
            <button
              key={b.id}
              onClick={() => setSelected(b.id)}
              className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl transition-all active:scale-[0.99]"
              style={{
                background: selected === b.id ? dark.greenTint : dark.surface,
                border: `1px solid ${selected === b.id ? dark.green : dark.border}`,
              }}
            >
              <div className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0"
                style={{ background: selected === b.id ? dark.green : dark.surfaceAlt, color: '#fff' }}>
                {selected === b.id ? <Check size={16} strokeWidth={2.5} /> : b.nombre[0]}
              </div>
              <span className="flex-1 text-left text-[14px] font-semibold" style={{ color: dark.ink }}>
                {b.nombre}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Cash snapshot (read-only) */}
      <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
        <p className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: dark.inkSubtle }}>
          Estado de caja al entrar
        </p>
        <div className="grid grid-cols-2 gap-3">
          {[
            { l: 'Ventas del día', v: fmt(turno.total_ventas ?? 0) },
            { l: 'En caja (efectivo)', v: fmt(turno.efectivo_esperado_actual ?? 0) },
            { l: 'Tarjeta', v: fmt(turno.total_tarjeta ?? 0) },
            { l: 'Efectivo ventas', v: fmt(turno.total_efectivo ?? 0) },
          ].map(r => (
            <div key={r.l}>
              <p className="text-[10px]" style={{ color: dark.inkSubtle }}>{r.l}</p>
              <p className="text-[14px] font-semibold font-mono mt-0.5" style={{ color: dark.ink }}>{r.v}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Photo */}
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
          Foto de comprobante
        </p>
        <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
          onChange={e => setImagen(e.target.files?.[0] ?? null)} />
        <button
          onClick={() => fileRef.current?.click()}
          className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl"
          style={{ background: dark.surface, border: `1px solid ${imagen ? dark.green : dark.border}` }}
        >
          <Camera size={18} style={{ color: imagen ? dark.green : dark.inkSubtle }} />
          <span className="flex-1 text-left text-[13px]" style={{ color: imagen ? dark.green : dark.inkSubtle }}>
            {imagen ? imagen.name : 'Foto de pantalla + datáfono (opcional)'}
          </span>
          {imagen && <Check size={14} style={{ color: dark.green }} />}
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
          style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
          <AlertTriangle size={13} /> {error}
        </div>
      )}

      <button
        onClick={confirmar}
        disabled={saving || selected === null}
        className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40 flex items-center justify-center gap-2"
        style={{ background: dark.green }}
      >
        <Check size={18} strokeWidth={2.5} />
        {saving
          ? 'Registrando...'
          : selectedBarista
            ? `Registrar entrada — ${selectedBarista.nombre}`
            : 'Seleccioná una barista'}
      </button>
    </div>
  )
}
