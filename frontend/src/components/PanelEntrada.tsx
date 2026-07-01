import { useEffect, useRef, useState } from 'react'
import { Camera, Check, AlertTriangle, ChevronLeft } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import ContadorEfectivo from './ContadorEfectivo'
import DesgloseEfectivo, { MovimientoDesglose } from './DesgloseEfectivo'
import DiferenciaCaja from './DiferenciaCaja'

interface Barista { id: number; nombre: string }
const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

export default function PanelEntrada({ onClose }: { onClose: () => void }) {
  const { turno, refresh } = useTurno()
  const [baristas, setBaristas] = useState<Barista[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [step, setStep] = useState<'select' | 'cuadre'>('select')
  const [efectivoReal, setEfectivoReal] = useState(0)
  const [ventasTarjetaBold, setVentasTarjetaBold] = useState('')
  const [imagen, setImagen] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [movimientos, setMovimientos] = useState<MovimientoDesglose[]>([])

  useEffect(() => {
    api.get<Barista[]>('/auth/baristas').then(({ data }) => {
      const enTurno = new Set(turno?.baristas ?? [])
      setBaristas(data.filter(b => !enTurno.has(b.nombre)))
    }).catch(() => {})
  }, [turno])

  useEffect(() => {
    if (!turno) return
    api.get(`/caja/${turno.id}/movimientos`)
      .then(r => setMovimientos((r.data ?? []).map((m: any) => ({ tipo: m.tipo, concepto: m.concepto, valor: m.valor, fecha: m.fecha }))))
      .catch(() => setMovimientos([]))
  }, [turno?.id])

  const confirmar = async () => {
    if (!turno || selected === null) return
    setSaving(true)
    setError('')
    try {
      const fd1 = new FormData()
      fd1.append('efectivo_real', String(efectivoReal))
      fd1.append('ventas_tarjeta_bold', String(Number(ventasTarjetaBold) || 0))
      if (imagen) fd1.append('imagen', imagen)
      await api.post(`/caja/${turno.id}/entrega`, fd1)

      const fd2 = new FormData()
      fd2.append('barista_id', String(selected))
      await api.post(`/caja/${turno.id}/entrada`, fd2)

      await refresh()
      setDone(true)
      setTimeout(onClose, 1400)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar')
    } finally {
      setSaving(false)
    }
  }

  if (!turno) return null

  if (done) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 px-6 pt-14">
        <div className="w-14 h-14 rounded-full flex items-center justify-center" style={{ background: dark.greenTint }}>
          <Check size={28} style={{ color: dark.green }} strokeWidth={2.5} />
        </div>
        <p className="text-[15px] font-bold text-center" style={{ color: dark.ink }}>¡Entrada registrada!</p>
        <p className="text-[12px] text-center" style={{ color: dark.inkSubtle }}>
          {baristas.find(b => b.id === selected)?.nombre ?? ''} ya figura en el turno
        </p>
      </div>
    )
  }

  const selectedBarista = baristas.find(b => b.id === selected)
  const canCuadre = efectivoReal > 0 && ventasTarjetaBold.trim() !== '' && imagen !== null

  if (step === 'select') {
    return (
      <div className="flex flex-col px-4 pt-14 pb-6 gap-4">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>Entrada de barista</p>
          <p className="text-[18px] font-bold mt-0.5" style={{ color: dark.ink }}>¿Quién entra al turno?</p>
        </div>

        {baristas.length === 0 ? (
          <div className="rounded-2xl p-4 text-center" style={{ background: dark.surface, border: `1px solid ${dark.border}` }}>
            <p className="text-[13px]" style={{ color: dark.inkSubtle }}>Todas las baristas ya están en el turno</p>
          </div>
        ) : (
          <div className="space-y-2">
            {baristas.map(b => (
              <button key={b.id} onClick={() => setSelected(b.id)}
                className="w-full flex items-center gap-3 px-4 py-3.5 rounded-2xl transition-all active:scale-[0.99]"
                style={{
                  background: selected === b.id ? dark.greenTint : dark.surface,
                  border: `1px solid ${selected === b.id ? dark.green : dark.border}`,
                }}>
                <div className="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold shrink-0"
                  style={{ background: selected === b.id ? dark.green : dark.surfaceAlt, color: '#fff' }}>
                  {selected === b.id ? <Check size={16} strokeWidth={2.5} /> : b.nombre[0]}
                </div>
                <span className="flex-1 text-left text-[14px] font-semibold" style={{ color: dark.ink }}>{b.nombre}</span>
              </button>
            ))}
          </div>
        )}

        <button onClick={() => setStep('cuadre')} disabled={selected === null}
          className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40"
          style={{ background: dark.green }}>
          {selectedBarista ? `Siguiente — cuadre de caja` : 'Seleccioná una barista'}
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
          <p className="text-[10px] font-bold uppercase tracking-widest" style={{ color: dark.amber }}>Cuadre al entrar</p>
          <p className="text-[15px] font-bold mt-0.5" style={{ color: dark.ink }}>
            {selectedBarista?.nombre} — verificá la caja
          </p>
        </div>
      </div>

      <DesgloseEfectivo
        base={turno.base_real ?? 0}
        ventasEfectivo={turno.total_efectivo ?? 0}
        ingresos={turno.ingresos_movimientos ?? 0}
        egresos={turno.egresos_movimientos ?? 0}
        esperado={turno.efectivo_esperado_actual ?? 0}
        movimientos={movimientos}
      />
      <div className="flex items-center justify-between px-1 -mt-1">
        <span className="text-[11px]" style={{ color: dark.inkSubtle }}>Ventas del día {fmt(turno.total_ventas ?? 0)}</span>
        <span className="text-[11px]" style={{ color: dark.inkSubtle }}>Tarjeta esperada {fmt(turno.total_tarjeta ?? 0)}</span>
      </div>

      <ContadorEfectivo onTotal={setEfectivoReal} />

      <DiferenciaCaja contado={efectivoReal} esperado={turno.efectivo_esperado_actual ?? 0} />

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
            {imagen ? imagen.name : 'Foto de pantalla + datáfono (obligatoria)'}
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

      <button onClick={confirmar} disabled={saving || !canCuadre}
        className="w-full py-4 rounded-2xl font-bold text-[15px] text-white disabled:opacity-40 flex items-center justify-center gap-2"
        style={{ background: dark.green }}>
        <Check size={18} strokeWidth={2.5} />
        {saving ? 'Registrando...' : 'Confirmar entrada y cuadre'}
      </button>
    </div>
  )
}
