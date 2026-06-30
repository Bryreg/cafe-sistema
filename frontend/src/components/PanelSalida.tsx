import { useRef, useState } from 'react'
import { AlertTriangle, Camera, Check, ChevronLeft, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import ContadorEfectivo from './ContadorEfectivo'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

export default function PanelSalida() {
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()
  const [selected, setSelected] = useState<string[]>([])
  const [step, setStep] = useState<'select' | 'cuadre'>('select')
  const [efectivoReal, setEfectivoReal] = useState(0)
  const [ventasTarjetaBold, setVentasTarjetaBold] = useState('')
  const [imagen, setImagen] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  if (!turno) return null

  const salidas = turno.baristas_salidas ?? []
  const remaining = turno.baristas.filter(b => !salidas.includes(b))
  const isLast = selected.length > 0 && selected.length === remaining.length

  const toggle = (name: string) =>
    setSelected(prev => prev.includes(name) ? prev.filter(b => b !== name) : [...prev, name])

  const handleNext = () => {
    if (isLast) {
      navigate('/conteo-cierre?kiosk=1')
    } else {
      setStep('cuadre')
    }
  }

  const handleConfirm = async () => {
    if (selected.length === 0 || !turno) return
    setSaving(true)
    setError('')
    try {
      const fd1 = new FormData()
      fd1.append('efectivo_real', String(efectivoReal))
      fd1.append('ventas_tarjeta_bold', String(Number(ventasTarjetaBold) || 0))
      if (imagen) fd1.append('imagen', imagen)
      await api.post(`/caja/${turno.id}/entrega`, fd1)

      for (const barista of selected) {
        const fd = new FormData()
        fd.append('barista_nombre', barista)
        await api.post(`/caja/${turno.id}/salida-barista`, fd)
      }

      await refresh()
      setDone(true)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar salida')
      setSaving(false)
    }
  }

  if (done) {
    const stillActive = remaining.filter(b => !selected.includes(b))
    return (
      <div className="flex flex-col items-center justify-center px-4 pt-14 pb-6 gap-4 min-h-[300px]">
        <div className="w-16 h-16 rounded-full flex items-center justify-center" style={{ background: dark.greenTint }}>
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

  const canCuadre = efectivoReal > 0 && ventasTarjetaBold.trim() !== ''

  if (step === 'select') {
    return (
      <div className="flex flex-col px-4 pt-14 pb-6 gap-5">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>Salida de turno</p>
          <p className="text-[18px] font-bold mt-0.5" style={{ color: dark.ink }}>¿Quién termina su turno?</p>
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
                <button key={barista} onClick={() => toggle(barista)}
                  className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl transition-all"
                  style={{
                    background: sel ? dark.amberTint : dark.surface,
                    border: `1px solid ${sel ? dark.amber : dark.border}`,
                  }}>
                  <div className="w-5 h-5 rounded-md flex items-center justify-center flex-shrink-0"
                    style={{ background: sel ? dark.amber : 'transparent', border: `2px solid ${sel ? dark.amber : dark.border}` }}>
                    {sel && <Check size={12} className="text-white" />}
                  </div>
                  <User size={16} style={{ color: sel ? dark.amber : dark.inkSubtle }} />
                  <span className="flex-1 text-left text-[15px] font-semibold" style={{ color: dark.ink }}>{barista}</span>
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

        <button onClick={handleNext} disabled={selected.length === 0 || saving}
          className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40"
          style={{ background: isLast ? dark.danger : dark.amber }}>
          {isLast ? 'Iniciar cierre del turno' : 'Siguiente — cuadre de caja'}
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col px-4 pt-14 pb-6 gap-4">
      <div className="flex items-center gap-2">
        <button onClick={() => setStep('select')}
          className="w-7 h-7 rounded-lg flex items-center justify-center"
          style={{ background: dark.surfaceAlt }}>
          <ChevronLeft size={16} style={{ color: dark.inkMuted }} />
        </button>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>Cuadre al salir</p>
          <p className="text-[15px] font-bold mt-0.5" style={{ color: dark.ink }}>
            {selected.join(', ')} — verificá la caja
          </p>
        </div>
      </div>

      <div className="rounded-2xl p-4" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
        <p className="text-[10px] font-bold uppercase tracking-widest mb-3" style={{ color: dark.inkSubtle }}>Estado esperado</p>
        <div className="grid grid-cols-2 gap-3">
          {[
            { l: 'Ventas del día',    v: fmt(turno.total_ventas ?? 0) },
            { l: 'Efectivo esperado', v: fmt(turno.efectivo_esperado_actual ?? 0) },
            { l: 'Tarjeta',           v: fmt(turno.total_tarjeta ?? 0) },
            { l: 'Efectivo ventas',   v: fmt(turno.total_efectivo ?? 0) },
          ].map(r => (
            <div key={r.l}>
              <p className="text-[10px]" style={{ color: dark.inkSubtle }}>{r.l}</p>
              <p className="text-[14px] font-semibold font-mono mt-0.5" style={{ color: dark.ink }}>{r.v}</p>
            </div>
          ))}
        </div>
      </div>

      <ContadorEfectivo onTotal={setEfectivoReal} />

      <div className="rounded-2xl p-4 space-y-2" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
        <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.inkSubtle }}>Ventas tarjeta Bold</p>
        <input
          type="number" min="0" step="100"
          value={ventasTarjetaBold}
          onChange={e => setVentasTarjetaBold(e.target.value)}
          placeholder="$0"
          className="w-full bg-transparent text-[18px] font-mono font-semibold outline-none"
          style={{ color: dark.ink }}
        />
      </div>

      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>Foto de comprobante</p>
        <input ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
          onChange={e => setImagen(e.target.files?.[0] ?? null)} />
        <button onClick={() => fileRef.current?.click()}
          className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl"
          style={{ background: dark.surface, border: `1px solid ${imagen ? dark.green : dark.border}` }}>
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

      <button onClick={handleConfirm} disabled={saving || !canCuadre}
        className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40 flex items-center justify-center gap-2"
        style={{ background: dark.amber }}>
        <Check size={18} strokeWidth={2.5} />
        {saving ? 'Procesando...' : 'Confirmar salida y cuadre'}
      </button>
    </div>
  )
}
