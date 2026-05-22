import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { DollarSign, ArrowRight, AlertTriangle, ChevronDown, ChevronUp, RefreshCw, CheckCircle } from 'lucide-react'
import BaristaLayout from '../components/BaristaLayout'

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

interface Venta {
  id: number; venta_total: number; nota_credito: number
  vales: number; tarjetas: number; efectivo_calculado: number
  fecha_registro: string; nota: string | null
}

export default function VentasDia() {
  const { user } = useAuth()
  const { turno, refresh } = useTurno()
  const navigate = useNavigate()
  const [ventas, setVentas] = useState<Venta[]>([])
  const [ventaTotal, setVentaTotal] = useState('')
  const [notaCredito, setNotaCredito] = useState('')
  const [vales, setVales] = useState('')
  const [tarjetas, setTarjetas] = useState('')
  const [nota, setNota] = useState('')
  const [showOpcionales, setShowOpcionales] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [saved, setSaved] = useState(false)

  const loadVentas = async () => {
    if (!turno?.id) return
    try {
      const { data } = await api.get(`/ventas/turno/${turno.id}`)
      setVentas(data)
    } catch {
      // no romper la UI si el historial falla
    }
  }

  useEffect(() => { loadVentas() }, [turno?.id])

  const total = Number(ventaTotal) || 0
  const nc = Number(notaCredito) || 0
  const v = Number(vales) || 0
  const tar = Number(tarjetas) || 0
  const efectivoCalculado = total - nc - v - tar
  const canSave = total > 0

  const registrar = async () => {
    setError(''); setLoading(true)
    try {
      await api.post('/ventas/', {
        tienda_id: user?.tienda_id,
        venta_total: total,
        nota_credito: nc,
        vales: v,
        tarjetas: tar,
        nota: nota || null,
      })
      setVentaTotal(''); setNotaCredito(''); setVales(''); setTarjetas(''); setNota('')
      setShowOpcionales(false)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
      await refresh()
      loadVentas()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar')
    } finally {
      setLoading(false)
    }
  }

  if (!turno) return (
    <BaristaLayout title="Ventas del día">
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 text-sm text-amber-700 text-center mt-8">
        No hay turno abierto. <button onClick={() => navigate('/apertura')} className="font-bold underline">Abrir caja →</button>
      </div>
    </BaristaLayout>
  )

  if (!turno.tiene_conteo_apertura) return (
    <BaristaLayout title="Ventas del día">
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 text-sm text-amber-700 text-center mt-8">
        Completa el conteo de apertura primero.
        <button onClick={() => navigate('/conteo-apertura')} className="block mx-auto mt-2 font-bold underline">
          Ir al conteo →
        </button>
      </div>
    </BaristaLayout>
  )

  const isAdmin = user?.rol === 'admin'

  return (
    <BaristaLayout title="Registrar ventas">
      <div className="space-y-5">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Ventas del día</h1>
        </div>

        {/* ── BARISTA: vista de solo lectura — ventas sincronizadas desde Siigo ── */}
        {!isAdmin && (
          <div className="space-y-4">
            {turno.total_ventas > 0 ? (
              <div className="bg-green-50 border border-green-200 rounded-2xl p-5 text-center">
                <CheckCircle size={28} className="mx-auto text-green-500 mb-2" />
                <p className="text-sm font-semibold text-green-800">Ventas sincronizadas desde Siigo</p>
                <p className="text-3xl font-bold text-green-900 mt-1">{fmt(turno.total_ventas)}</p>
                <div className="flex justify-center gap-4 mt-3 text-xs text-green-700">
                  <span>Efectivo <strong>{fmt(turno.total_efectivo)}</strong></span>
                  {turno.total_tarjeta > 0 && <span>Tarjeta <strong>{fmt(turno.total_tarjeta)}</strong></span>}
                </div>
              </div>
            ) : (
              <div className="bg-blue-50 border border-blue-200 rounded-2xl p-5 text-center">
                <RefreshCw size={24} className="mx-auto text-blue-400 mb-2" />
                <p className="text-sm font-semibold text-blue-800">Las ventas se sincronizan automáticamente desde Siigo</p>
                <p className="text-xs text-blue-600 mt-2">Aún no hay ventas registradas en este turno. El administrador las sincronizará al final del día.</p>
              </div>
            )}

            {/* Historial del turno */}
            {ventas.length > 0 && (
              <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
                <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Detalle del turno</p>
                  <span className="text-xs text-gray-400">{ventas.length}</span>
                </div>
                <div className="divide-y divide-gray-50">
                  {ventas.map(v => (
                    <div key={v.id} className="px-4 py-3 flex items-center justify-between">
                      <div>
                        <p className="text-sm font-bold text-gray-800">{fmt(v.venta_total)}</p>
                        <p className="text-xs text-gray-400">
                          Efect: <span className="text-green-600 font-medium">{fmt(v.efectivo_calculado)}</span>
                          {v.tarjetas > 0 && <> · Tarj: {fmt(v.tarjetas)}</>}
                          {v.nota_credito > 0 && <> · NC: {fmt(v.nota_credito)}</>}
                          {v.nota === 'sync:siigo' && <span className="ml-1 text-blue-400">· Siigo</span>}
                        </p>
                      </div>
                      <span className="text-xs text-gray-400">
                        {(() => { const t = v.fecha_registro.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z'); return new Date(t.endsWith('Z') ? t : t + 'Z') })().toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── ADMIN: formulario manual (fallback si Siigo no está disponible) ── */}
        {isAdmin && (
          <>
            <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5 text-xs text-amber-700">
              <AlertTriangle size={14} className="shrink-0" />
              Modo manual — solo para usar si Siigo no está disponible
            </div>

            {/* Resumen acumulado */}
            {turno.total_ventas > 0 && (
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-white rounded-xl border border-gray-200 p-3 text-center">
                  <p className="text-xs text-gray-400">Total</p>
                  <p className="text-sm font-bold text-gray-800">{fmt(turno.total_ventas)}</p>
                </div>
                <div className="bg-white rounded-xl border border-gray-200 p-3 text-center">
                  <p className="text-xs text-gray-400">Efectivo</p>
                  <p className="text-sm font-bold text-green-700">{fmt(turno.total_efectivo)}</p>
                </div>
                <div className="bg-white rounded-xl border border-gray-200 p-3 text-center">
                  <p className="text-xs text-gray-400">Tarjeta</p>
                  <p className="text-sm font-bold text-blue-700">{fmt(turno.total_tarjeta)}</p>
                </div>
              </div>
            )}

            {error && (
              <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm px-4 py-3 rounded-xl">
                <AlertTriangle size={14} /> {error}
              </div>
            )}

            {saved && (
              <div className="bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 rounded-xl text-center font-semibold">
                ✓ Ventas registradas
              </div>
            )}

            <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-2">
                  Total ventas brutas
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-2xl font-bold text-gray-300">$</span>
                  <input
                    type="number"
                    inputMode="numeric"
                    value={ventaTotal}
                    onChange={e => setVentaTotal(e.target.value)}
                    placeholder="0"
                    className="w-full pl-12 pr-4 py-4 text-4xl font-bold text-gray-900 border-2 border-gray-200 rounded-xl focus:outline-none focus:border-amber-400 transition-colors"
                    autoFocus
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-blue-600 uppercase tracking-wide block mb-1.5">
                  Datáfono Bold (tarjeta / transferencia)
                </label>
                <div className="relative">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-lg font-bold text-blue-300">$</span>
                  <input
                    type="number"
                    inputMode="numeric"
                    value={tarjetas}
                    onChange={e => setTarjetas(e.target.value)}
                    placeholder="0"
                    className="w-full pl-10 pr-4 py-3 text-2xl font-bold text-blue-700 border-2 border-blue-200 rounded-xl focus:outline-none focus:border-blue-400 transition-colors"
                  />
                </div>
              </div>

              {total > 0 && (
                <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 flex justify-between items-center">
                  <span className="text-sm text-green-700 font-medium">Efectivo calculado</span>
                  <span className="text-xl font-bold text-green-800">{fmt(efectivoCalculado)}</span>
                </div>
              )}

              <button onClick={() => setShowOpcionales(!showOpcionales)}
                className="w-full flex items-center justify-between py-2 text-sm text-gray-500 hover:text-gray-700 transition-colors">
                <span>Vales y notas crédito</span>
                {showOpcionales ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
              </button>

              {showOpcionales && (
                <div className="space-y-3 pt-1">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { label: 'Vales', val: vales, set: setVales },
                      { label: 'Nota crédito', val: notaCredito, set: setNotaCredito },
                    ].map(({ label, val, set }) => (
                      <div key={label}>
                        <label className="text-xs text-gray-400 block mb-1">{label}</label>
                        <input type="number" value={val} onChange={e => set(e.target.value)}
                          placeholder="0"
                          className="w-full border border-gray-200 rounded-lg px-2 py-2 text-sm text-right font-semibold focus:outline-none focus:ring-2 focus:ring-amber-400" />
                      </div>
                    ))}
                  </div>
                  <input value={nota} onChange={e => setNota(e.target.value)}
                    placeholder="Nota opcional"
                    className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
                </div>
              )}

              <button onClick={registrar} disabled={!canSave || loading}
                className="w-full bg-amber-600 hover:bg-amber-700 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-4 rounded-xl text-base flex items-center justify-center gap-2 transition-colors">
                <DollarSign size={18} />
                {loading ? 'Guardando...' : 'Registrar ventas'}
                {!loading && <ArrowRight size={18} />}
              </button>
            </div>

            {/* Historial del turno */}
            {ventas.length > 0 && (
              <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
                <div className="px-4 py-2.5 border-b border-gray-100 flex items-center justify-between">
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Registros del turno</p>
                  <span className="text-xs text-gray-400">{ventas.length}</span>
                </div>
                <div className="divide-y divide-gray-50">
                  {ventas.map(v => (
                    <div key={v.id} className="px-4 py-3 flex items-center justify-between">
                      <div>
                        <p className="text-sm font-bold text-gray-800">{fmt(v.venta_total)}</p>
                        <p className="text-xs text-gray-400">
                          Efect: <span className="text-green-600 font-medium">{fmt(v.efectivo_calculado)}</span>
                          {v.tarjetas > 0 && <> · Tarj: {fmt(v.tarjetas)}</>}
                          {v.nota_credito > 0 && <> · NC: {fmt(v.nota_credito)}</>}
                          {v.nota === 'sync:siigo' && <span className="ml-1 text-blue-400">· Siigo</span>}
                        </p>
                      </div>
                      <span className="text-xs text-gray-400">
                        {(() => { const t = v.fecha_registro.replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1').replace('+00:00', 'Z'); return new Date(t.endsWith('Z') ? t : t + 'Z') })().toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </BaristaLayout>
  )
}
