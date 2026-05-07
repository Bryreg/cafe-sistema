import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { ArrowRight, AlertTriangle, Coffee, LogOut, Repeat2, Moon } from 'lucide-react'
import MoneyInput from '../components/MoneyInput'
import DifferenceBadge from '../components/DifferenceBadge'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

export default function CuadreLlegada() {
  const { user, logout, tipo_turno, setCuadreLlegadaDone } = useAuth()
  const { turno, loading } = useTurno()
  const navigate = useNavigate()
  const [efectivoReal, setEfectivoReal] = useState('')
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  if (loading) return (
    <div className="min-h-screen bg-warm-50 flex items-center justify-center">
      <p className="text-sm text-warm-400 animate-pulse">Consultando turno...</p>
    </div>
  )

  if (!turno) return (
    <div className="min-h-screen bg-warm-50 flex items-center justify-center p-6">
      <p className="text-sm text-warm-500 text-center">No hay turno activo para esta sede.<br />Contacta al encargado de apertura.</p>
    </div>
  )

  const ef = Number(efectivoReal) || 0
  const esperado = turno.efectivo_esperado_actual
  const diff = efectivoReal.trim() !== '' ? ef - esperado : null
  const canSubmit = ef > 0

  const esCierre = tipo_turno === 'cierre'
  const Icon = esCierre ? Moon : Repeat2
  const iconColor = esCierre ? 'text-purple-500' : 'text-blue-500'
  const accentColor = esCierre ? 'text-purple-700' : 'text-blue-600'

  const guardar = async () => {
    setSaving(true); setError('')
    try {
      const form = new FormData()
      form.append('efectivo_real', String(ef))
      form.append('tipo_turno', tipo_turno ?? 'intermedio')
      if (nota.trim()) form.append('nota', nota.trim())
      await api.post(`/caja/${turno.id}/cuadre-llegada`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setCuadreLlegadaDone(turno.id)
      navigate('/hub', { replace: true })
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar cuadre')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-warm-50 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 bg-white sticky top-0 z-10 border-b border-warm-200">
        <div className="flex items-center gap-2">
          <Coffee size={18} className="text-forest" />
          <span className="text-sm font-bold text-warm-700">Sistema Café</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-warm-500">{user?.nombre}</span>
          <button
            onClick={() => { logout(); navigate('/login') }}
            className="text-xs text-warm-400 hover:text-red-500 flex items-center gap-1 transition-colors"
          >
            <LogOut size={13} /> Salir
          </button>
        </div>
      </div>

      <div className="flex-1 px-4 pb-10 max-w-md mx-auto w-full space-y-5 pt-5">
        {/* Title */}
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${esCierre ? 'bg-purple-100' : 'bg-blue-100'}`}>
            <Icon size={18} className={iconColor} />
          </div>
          <div>
            <p className={`text-xs font-semibold uppercase tracking-widest ${accentColor}`}>
              Turno {esCierre ? 'de Cierre' : 'Intermedio'}
            </p>
            <h1 className="text-xl font-bold text-warm-700">Cuadre de llegada</h1>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* Expected cash card */}
        <div className="bg-white rounded-2xl border border-warm-200 p-5 shadow-sm">
          <p className="text-xs font-semibold text-warm-400 uppercase tracking-wide mb-1">
            Efectivo esperado en caja
          </p>
          <p className="text-3xl font-bold text-warm-700 font-mono">{fmt(esperado)}</p>
          <p className="text-xs text-warm-400 mt-1.5">
            Base apertura · ventas efectivo · movimientos del turno
          </p>
        </div>

        {/* Count input */}
        <div className="bg-white rounded-2xl border border-warm-200 p-5 shadow-sm space-y-4">
          <MoneyInput
            label="Total que contaste en caja"
            value={efectivoReal}
            onChange={setEfectivoReal}
            placeholder="0"
          />

          {diff !== null && (
            <DifferenceBadge diferencia={diff} />
          )}

          <div>
            <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-2">
              Observaciones (opcional)
            </label>
            <textarea
              value={nota}
              onChange={e => setNota(e.target.value)}
              placeholder="Ej: faltaban $5.000 en el cajón..."
              rows={2}
              className="w-full border-2 border-warm-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-forest resize-none transition-colors"
            />
          </div>

          <button
            onClick={guardar}
            disabled={!canSubmit || saving}
            className="w-full disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-4 rounded-xl text-base flex items-center justify-center gap-2 transition-colors"
            style={{ background: 'oklch(35% 0.05 155)' }}
          >
            {saving ? 'Registrando...' : <>Confirmar llegada <ArrowRight size={18} /></>}
          </button>
        </div>
      </div>
    </div>
  )
}
