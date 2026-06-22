import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { AlertTriangle, Camera, Check, ChevronLeft, Lock, X } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import ContadorEfectivo from '../components/ContadorEfectivo'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`
const fmtSigned = (v: number) => (v === 0 ? '$0' : (v > 0 ? '+' : '') + fmt(Math.abs(v)))

function StepHeader({ n, title, done, active }: { n: number; title: string; done: boolean; active: boolean }) {
  return (
    <div className="flex items-center gap-2.5 mb-2.5">
      <div className="w-[22px] h-[22px] rounded-full flex items-center justify-center shrink-0 text-[11px] font-bold"
        style={{
          background: done ? dark.green : active ? dark.amber : dark.surfaceAlt,
          color: done || active ? '#fff' : dark.inkSubtle,
        }}>
        {done ? <Check size={12} strokeWidth={2.5} /> : n}
      </div>
      <span className="text-[13px] font-bold uppercase tracking-wide"
        style={{ color: done ? dark.green : active ? dark.amber : dark.inkSubtle }}>
        {title}
      </span>
      {active && (
        <span className="ml-auto text-[10px] font-bold uppercase tracking-wide" style={{ color: dark.amber }}>
          Paso actual
        </span>
      )}
    </div>
  )
}

export default function Entrega() {
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)

  const [efectivoReal, setEfectivoReal]           = useState('')
  const [ventasTarjetaBold, setVentasTarjetaBold] = useState('')
  const [imagen, setImagen]                       = useState<File | null>(null)
  const [preview, setPreview]                     = useState<string | null>(null)
  const [error, setError]                         = useState('')
  const [saving, setSaving]                       = useState(false)

  if (!turno) return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: dark.bg }}>
      <p className="text-sm text-center" style={{ color: dark.inkMuted }}>No hay turno activo.</p>
    </div>
  )

  const ef       = Number(efectivoReal) || 0
  const vt       = Number(ventasTarjetaBold) || 0
  const esperado = turno.efectivo_esperado_actual ?? 0

  const difEfectivo = efectivoReal.trim()      !== '' ? ef - esperado                 : null
  const difTarjeta  = ventasTarjetaBold.trim() !== '' ? vt - (turno.total_tarjeta ?? 0) : null

  const step1Done = ef > 0
  const step2Done = ventasTarjetaBold.trim() !== ''   // Verifica Bold
  const step3Done = imagen !== null                    // Foto
  const currentStep = !step1Done ? 1 : !step2Done ? 2 : 3

  const canSave = step1Done && step2Done

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setImagen(f)
    setPreview(URL.createObjectURL(f))
  }

  const confirmar = async () => {
    if (!canSave) return
    setSaving(true); setError('')
    try {
      const fd = new FormData()
      fd.append('efectivo_real', String(ef))
      fd.append('ventas_tarjeta_bold', String(vt))
      if (imagen) fd.append('imagen', imagen)
      await api.post(`/caja/${turno.id}/entrega`, fd)
      await refresh()
      navigate('/hub')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>

      {/* Header */}
      <header className="flex items-center gap-2.5 px-4 pb-2.5 pt-3 shrink-0" style={{ background: dark.bg }}>
        <button
          onClick={() => navigate('/hub')}
          className="w-7 h-7 rounded-lg flex items-center justify-center"
          style={{ background: dark.surfaceAlt, color: dark.inkMuted }}
        >
          <ChevronLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>
            Entrega de turno
          </p>
          <p className="text-[14px] font-bold leading-tight" style={{ color: dark.ink }}>
            Cuadre de caja
          </p>
        </div>
        <span className="text-[11px] font-mono font-semibold" style={{ color: dark.inkSubtle }}>
          {Math.min(currentStep - 1, 3)}/3
        </span>
      </header>

      {/* Body */}
      <div className="flex-1 overflow-auto px-4 pb-28 space-y-4 pt-1">

        {/* Hero */}
        <div className="rounded-2xl p-4"
          style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
          <p className="text-[10px] font-bold uppercase tracking-widest mb-2" style={{ color: dark.inkSubtle }}>
            Efectivo esperado en caja
          </p>
          <p className="text-[36px] font-bold font-mono leading-none mb-3"
            style={{ color: dark.ink, letterSpacing: '-1.5px' }}>
            {fmt(esperado)}
          </p>
          <div className="grid grid-cols-2 gap-2 pt-3" style={{ borderTop: `1px solid ${dark.border}` }}>
            {[
              { l: 'Base apertura', v: fmt(turno.base_real ?? 0) },
              { l: '+ Ventas ef.',  v: fmt(turno.total_efectivo ?? 0) },
              { l: '+ Ing. mov.',   v: fmt(turno.ingresos_movimientos ?? 0) },
              { l: '− Egr. mov.',   v: fmt(turno.egresos_movimientos ?? 0) },
            ].map(row => (
              <div key={row.l} className="flex justify-between items-baseline gap-2">
                <span className="text-[11px]" style={{ color: dark.inkSubtle }}>{row.l}</span>
                <span className="text-[12px] font-semibold font-mono" style={{ color: dark.ink }}>{row.v}</span>
              </div>
            ))}
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 rounded-xl px-3 py-2.5 text-[12px]"
            style={{ background: dark.dangerTint, border: `1px solid ${dark.dangerDim}`, color: dark.danger }}>
            <AlertTriangle size={13} /> {error}
          </div>
        )}

        {/* Paso 1 — Cuenta el efectivo */}
        <div className="space-y-2">
          <StepHeader n={1} title="Cuenta el efectivo" done={step1Done} active={currentStep === 1} />
          <ContadorEfectivo onTotal={t => setEfectivoReal(String(t))} />

          {difEfectivo !== null && (
            <div className="rounded-xl flex items-center justify-between px-4 py-2.5"
              style={{
                background: difEfectivo === 0 ? 'oklch(94% 0.05 155 / 0.5)' : 'oklch(95% 0.06 25 / 0.5)',
                border: `1px solid ${difEfectivo === 0 ? 'oklch(70% 0.10 155 / 0.7)' : 'oklch(72% 0.14 25 / 0.7)'}`,
              }}>
              <span className="text-[11px] flex items-center gap-1.5" style={{ color: dark.inkMuted }}>
                {difEfectivo === 0
                  ? <Check size={12} color={dark.green} />
                  : <AlertTriangle size={12} color={dark.danger} />}
                Diferencia vs esperado
              </span>
              <span className="text-[18px] font-bold font-mono"
                style={{ color: difEfectivo === 0 ? dark.green : dark.danger, letterSpacing: '-0.3px' }}>
                {fmtSigned(difEfectivo)}
              </span>
            </div>
          )}
        </div>

        {/* Paso 2 — Verifica Bold */}
        <div className="space-y-2">
          <StepHeader n={2} title="Verifica Bold" done={step2Done} active={currentStep === 2} />
          <div className="rounded-xl px-4 py-3 flex items-center justify-between gap-3"
            style={{ background: dark.surface, border: `1px solid ${currentStep === 2 ? dark.amberDim : dark.border}` }}>
            <div>
              <label htmlFor="entrega-bold" className="text-[12px] font-semibold" style={{ color: dark.ink }}>Ventas tarjeta Bold</label>
              <p className="text-[10px] mt-0.5" style={{ color: dark.inkSubtle }}>
                Sistema: {fmt(turno.total_tarjeta ?? 0)}
              </p>
            </div>
            <input
              id="entrega-bold"
              type="number" inputMode="numeric"
              value={ventasTarjetaBold} onChange={e => setVentasTarjetaBold(e.target.value)}
              placeholder="$ ___"
              className="text-[22px] font-bold font-mono text-right bg-transparent outline-none w-40"
              style={{ color: dark.amber }}
            />
          </div>

          {difTarjeta !== null && (
            <div className="rounded-xl flex items-center justify-between px-4 py-2.5"
              style={{
                background: difTarjeta === 0 ? 'oklch(94% 0.05 155 / 0.5)' : 'oklch(95% 0.06 25 / 0.5)',
                border: `1px solid ${difTarjeta === 0 ? 'oklch(70% 0.10 155 / 0.7)' : 'oklch(72% 0.14 25 / 0.7)'}`,
              }}>
              <span className="text-[11px] flex items-center gap-1.5" style={{ color: dark.inkMuted }}>
                {difTarjeta === 0
                  ? <Check size={12} color={dark.green} />
                  : <AlertTriangle size={12} color={dark.danger} />}
                Diferencia Bold
              </span>
              <span className="text-[18px] font-bold font-mono"
                style={{ color: difTarjeta === 0 ? dark.green : dark.danger, letterSpacing: '-0.3px' }}>
                {fmtSigned(difTarjeta)}
              </span>
            </div>
          )}
        </div>

        {/* Paso 3 — Foto */}
        <div className="space-y-2">
          <StepHeader n={3} title="Foto del cuadre" done={step3Done} active={currentStep === 3} />
          <input ref={fileRef} type="file" accept="image/*" capture="environment" onChange={onFile} className="hidden" />

          {preview ? (
            <div className="relative rounded-xl overflow-hidden">
              <img src={preview} alt="preview" className="w-full h-36 object-cover" />
              <button
                onClick={() => { setImagen(null); setPreview(null) }}
                className="absolute top-2 right-2 w-7 h-7 rounded-full flex items-center justify-center"
                style={{ background: 'rgba(0,0,0,0.6)', color: '#fff' }}
              >
                <X size={13} />
              </button>
            </div>
          ) : (
            <button
              onClick={() => fileRef.current?.click()}
              className="w-full h-24 rounded-xl flex flex-col items-center justify-center gap-2 transition-colors"
              style={{
                background: dark.surface,
                border: `1.5px dashed ${currentStep === 3 ? dark.amberDim : dark.border}`,
              }}
            >
              <Camera size={20} style={{ color: dark.inkSubtle }} />
              <span className="text-[12px]" style={{ color: dark.inkMuted }}>
                Fotografía el cuadre de caja
              </span>
              <span className="text-[10px]" style={{ color: dark.inkSubtle }}>opcional</span>
            </button>
          )}
        </div>

      </div>

      {/* CTA sticky */}
      <div className="fixed bottom-0 left-0 right-0 px-4 pt-3"
        style={{
          background: `linear-gradient(to top, ${dark.bg} 70%, transparent)`,
          borderTop: `1px solid ${dark.border}`,
          paddingBottom: 'env(safe-area-inset-bottom, 16px)',
        }}>
        <button
          onClick={canSave ? confirmar : undefined}
          disabled={!canSave || saving}
          className="w-full py-4 rounded-2xl text-[15px] font-bold flex items-center justify-center gap-2 transition-all"
          style={{
            background: canSave ? dark.green : dark.surfaceAlt,
            color: canSave ? '#fff' : dark.inkSubtle,
            opacity: !canSave || saving ? 0.55 : 1,
            cursor: !canSave ? 'not-allowed' : 'pointer',
          }}
        >
          {saving
            ? 'Registrando...'
            : !step1Done
              ? <><Lock size={14} /> Cuenta el efectivo primero</>
              : !step2Done
                ? <><Lock size={14} /> Ingresa el total Bold</>
                : <><Check size={16} strokeWidth={2.5} /> Registrar entrega</>
          }
        </button>
      </div>

    </div>
  )
}
