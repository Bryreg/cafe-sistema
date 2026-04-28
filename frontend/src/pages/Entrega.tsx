import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { CheckCircle2, AlertTriangle, ArrowLeft } from 'lucide-react'
import MoneyInput from '../components/MoneyInput'
import DifferenceBadge from '../components/DifferenceBadge'
import ImageUploader from '../components/ImageUploader'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

function SectionCard({ title, children, accent = 'amber' }: {
  title: string
  children: React.ReactNode
  accent?: 'amber' | 'green' | 'blue'
}) {
  const colors: Record<string, string> = {
    amber: 'border-amber-700/40 bg-amber-900/10',
    green: 'border-green-700/40 bg-green-900/10',
    blue: 'border-blue-700/40 bg-blue-900/10',
  }
  const titleColors: Record<string, string> = {
    amber: 'text-amber-400',
    green: 'text-green-400',
    blue: 'text-blue-400',
  }

  return (
    <div className={`rounded-2xl border p-5 space-y-4 ${colors[accent]}`}>
      <p className={`text-xs font-bold uppercase tracking-widest ${titleColors[accent]}`}>{title}</p>
      {children}
    </div>
  )
}

export default function Entrega() {
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()

  const [efectivoReal, setEfectivoReal] = useState('')
  const [ventasEfectivoSiigo, setVentasEfectivoSiigo] = useState('')
  const [ventasTarjetaBold, setVentasTarjetaBold] = useState('')
  const [imagen, setImagen] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (!turno) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center p-6">
        <p className="text-gray-400 text-sm">No hay turno abierto.</p>
      </div>
    )
  }

  const efectivoEsperado = turno.efectivo_esperado_actual
  const ef = Number(efectivoReal) || 0
  const vs = Number(ventasEfectivoSiigo) || 0
  const vt = Number(ventasTarjetaBold) || 0

  const difEfectivo = efectivoReal.trim() !== '' ? ef - efectivoEsperado : null
  const difSiigo = ventasEfectivoSiigo.trim() !== '' ? vs - turno.total_efectivo : null
  const difTarjeta = ventasTarjetaBold.trim() !== '' ? vt - turno.total_tarjeta : null

  const efectivoDigitado = efectivoReal.trim() !== ''
  const siigoDigitado = ventasEfectivoSiigo.trim() !== ''
  const boldDigitado = ventasTarjetaBold.trim() !== ''
  const siigoCuadra = difSiigo === 0
  const canSave = efectivoDigitado && siigoDigitado && boldDigitado && ef >= 0 && vt >= 0 && siigoCuadra

  const confirmar = async () => {
    if (!canSave) return
    setError('')
    setLoading(true)
    try {
      const fd = new FormData()
      fd.append('efectivo_real', String(ef))
      fd.append('ventas_efectivo_siigo', String(vs))
      fd.append('ventas_tarjeta_bold', String(vt))
      if (imagen) fd.append('imagen', imagen)

      await api.post(`/caja/${turno.id}/entrega`, fd)
      await refresh()
      navigate('/hub')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-900 text-white">
      <div className="max-w-lg mx-auto px-4 py-6 space-y-5">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/hub')} className="text-gray-500 hover:text-gray-300">
            <ArrowLeft size={20} />
          </button>
          <div>
            <p className="text-xs font-semibold text-amber-500 uppercase tracking-widest">Cuadre de llegada</p>
            <h1 className="text-xl font-bold text-white">Registro de turno</h1>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <div className="bg-gray-800 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Base apertura</p>
            <p className="text-sm font-bold text-gray-100">{fmt(turno.base_real)}</p>
          </div>
          <div className="bg-gray-800 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Ventas ef.</p>
            <p className="text-sm font-bold text-green-400">{fmt(turno.total_efectivo)}</p>
          </div>
          <div className="bg-gray-800 rounded-xl p-3 text-center">
            <p className="text-xs text-gray-400">Tarjeta</p>
            <p className="text-sm font-bold text-blue-400">{fmt(turno.total_tarjeta)}</p>
          </div>
        </div>

        {(turno.ingresos_movimientos > 0 || turno.egresos_movimientos > 0) && (
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-gray-800 rounded-xl p-3 text-center">
              <p className="text-xs text-gray-400">Ingresos mov.</p>
              <p className="text-sm font-bold text-green-400">{fmt(turno.ingresos_movimientos)}</p>
            </div>
            <div className="bg-gray-800 rounded-xl p-3 text-center">
              <p className="text-xs text-gray-400">Egresos mov.</p>
              <p className="text-sm font-bold text-red-400">{fmt(turno.egresos_movimientos)}</p>
            </div>
          </div>
        )}

        <SectionCard title="1 - Cuadre efectivo" accent="green">
          <div className="bg-gray-900/60 rounded-xl px-4 py-3 flex items-center justify-between">
            <span className="text-sm text-gray-400">Efectivo esperado</span>
            <span className="text-xl font-bold text-gray-100">{fmt(efectivoEsperado)}</span>
          </div>

          <MoneyInput
            label="Efectivo real en caja"
            value={efectivoReal}
            onChange={setEfectivoReal}
            hint="Cuenta el efectivo fisico total en caja"
            dark
          />

          {difEfectivo !== null && (
            <div className={`rounded-xl px-4 py-3 flex items-center justify-between ${
              difEfectivo === 0 ? 'bg-green-900/30 border border-green-700/40' : 'bg-red-900/20 border border-red-700/40'
            }`}>
              <span className="text-sm text-gray-400">Diferencia</span>
              <div className="flex items-center gap-2">
                <span className={`text-lg font-bold ${difEfectivo === 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {difEfectivo > 0 ? '+' : ''}{fmt(difEfectivo)}
                </span>
                <DifferenceBadge diferencia={difEfectivo} dark showZero={false} />
              </div>
            </div>
          )}
        </SectionCard>

        <SectionCard title="2 - Siigo y Bold" accent="blue">
          <MoneyInput
            label="Ventas efectivo Siigo"
            value={ventasEfectivoSiigo}
            onChange={setVentasEfectivoSiigo}
            hint={`Debe coincidir con el sistema: ${fmt(turno.total_efectivo)}`}
            dark
            size="sm"
          />

          {difSiigo !== null && (
            <div className={`rounded-xl px-4 py-3 flex items-center justify-between ${
              difSiigo === 0 ? 'bg-blue-900/30 border border-blue-700/40' : 'bg-red-900/20 border border-red-700/40'
            }`}>
              <div>
                <p className="text-xs text-gray-500">Efectivo sistema: {fmt(turno.total_efectivo)}</p>
                <p className="text-xs text-gray-500">Diferencia Siigo</p>
              </div>
              <span className={`text-lg font-bold ${difSiigo === 0 ? 'text-blue-400' : 'text-red-400'}`}>
                {difSiigo > 0 ? '+' : ''}{fmt(difSiigo)}
              </span>
            </div>
          )}

          <div className="space-y-2">
            <MoneyInput
              label="Ventas tarjeta Bold"
              value={ventasTarjetaBold}
              onChange={setVentasTarjetaBold}
              hint="Total en el datafono Bold"
              dark
              size="sm"
            />

            {difTarjeta !== null && (
              <div className={`rounded-xl px-4 py-3 flex items-center justify-between ${
                difTarjeta === 0 ? 'bg-blue-900/30 border border-blue-700/40' : 'bg-red-900/20 border border-red-700/40'
              }`}>
                <div>
                  <p className="text-xs text-gray-500">Tarjeta sistema: {fmt(turno.total_tarjeta)}</p>
                  <p className="text-xs text-gray-500">Diferencia</p>
                </div>
                <span className={`text-lg font-bold ${difTarjeta === 0 ? 'text-blue-400' : 'text-red-400'}`}>
                  {difTarjeta > 0 ? '+' : ''}{fmt(difTarjeta)}
                </span>
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="3 - Evidencia fotografica" accent="amber">
          <ImageUploader onFileChange={setImagen} dark />
        </SectionCard>

        {error && (
          <div className="flex items-center gap-2 bg-red-900/30 border border-red-700 text-red-400 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        <button
          onClick={confirmar}
          disabled={!canSave || loading}
          className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-4 rounded-2xl text-base flex items-center justify-center gap-2 transition-colors"
        >
          <CheckCircle2 size={18} />
          {loading ? 'Registrando...' : 'Confirmar cuadre de llegada'}
        </button>

        {!imagen && (
          <p className="text-center text-xs text-gray-500">
            Sin foto: se recomienda adjuntar evidencia del cuadre
          </p>
        )}

        {!siigoCuadra && siigoDigitado && (
          <p className="text-center text-xs text-red-400">
            La entrega solo se puede guardar si el efectivo de Siigo coincide con las ventas registradas del turno.
          </p>
        )}
      </div>
    </div>
  )
}
