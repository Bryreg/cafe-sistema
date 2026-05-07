import { useEffect, useState } from 'react'
import api from '../api/client'
import {
  Banknote, User, ImageIcon, Check, X, ZoomIn,
  ChevronDown, ChevronUp, AlertTriangle, CheckCircle2,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface MovDetalle { concepto: string; valor: number; fecha: string }
interface ConsignacionItem {
  id: number; valor: number; estado: string; fecha: string
  imagen_url: string | null; usuario_nombre: string | null
}
interface ResumenDia {
  turno_id: number
  tienda_id: number
  tienda_nombre: string
  fecha_apertura: string
  fecha_cierre: string
  total_efectivo: number
  efectivo_final_real: number
  base_real: number
  total_egresos: number
  total_ingresos_mov: number
  esperado_consignar: number
  total_consignado: number
  diferencia: number
  egresos_detalle: MovDetalle[]
  ingresos_detalle: MovDetalle[]
  consignaciones: ConsignacionItem[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`

const parseUTC = (f: string) => {
  const s = f.replace(' ', 'T').replace('+00:00', 'Z')
  return new Date(s.endsWith('Z') ? s : s + 'Z')
}

const fmtFecha = (f: string) =>
  parseUTC(f).toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })

const fmtHora = (f: string) =>
  parseUTC(f).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })

// ─── Componente principal ─────────────────────────────────────────────────────

export default function ConsignacionesAdmin() {
  const [dias, setDias] = useState<ResumenDia[]>([])
  const [loading, setLoading] = useState(true)
  const [fotoModal, setFotoModal] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState<number | null>(null)
  const [expandido, setExpandido] = useState<number | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/consignaciones/resumen-admin')
      setDias(data)
      // Auto-expand first day with pending consignaciones
      const primero = data.find((d: ResumenDia) =>
        d.consignaciones.some((c: ConsignacionItem) => c.estado === 'pendiente')
      )
      if (primero) setExpandido(primero.turno_id)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const confirmar = async (id: number) => {
    setConfirmando(id)
    try {
      await api.patch(`/consignaciones/${id}/confirmar`)
      setDias(prev => prev.map(d => ({
        ...d,
        consignaciones: d.consignaciones.map(c =>
          c.id === id ? { ...c, estado: 'realizada' } : c
        ),
      })))
    } finally { setConfirmando(null) }
  }

  // Totales globales
  const totalEsperado = dias.reduce((s, d) => s + d.esperado_consignar, 0)
  const totalConsignado = dias.reduce((s, d) => s + d.total_consignado, 0)
  const diasConDiferencia = dias.filter(d => Math.abs(d.diferencia) > 0.5).length

  if (loading) return <p className="text-sm text-gray-400 text-center py-12">Cargando...</p>

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Consignaciones</h1>
        <p className="text-sm text-gray-500 mt-1">
          Reconciliación de efectivo por día — ventas en cash ± movimientos = debe consignarse
        </p>
      </div>

      {/* Resumen global */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-blue-50 border border-blue-200 rounded-2xl p-4">
          <p className="text-xs font-semibold text-blue-600 uppercase tracking-wide">Esperado</p>
          <p className="text-xl font-bold text-blue-800 mt-1">{fmt(totalEsperado)}</p>
        </div>
        <div className="bg-green-50 border border-green-200 rounded-2xl p-4">
          <p className="text-xs font-semibold text-green-600 uppercase tracking-wide">Consignado</p>
          <p className="text-xl font-bold text-green-800 mt-1">{fmt(totalConsignado)}</p>
        </div>
        <div className={`border rounded-2xl p-4 ${diasConDiferencia > 0 ? 'bg-red-50 border-red-200' : 'bg-gray-50 border-gray-200'}`}>
          <p className={`text-xs font-semibold uppercase tracking-wide ${diasConDiferencia > 0 ? 'text-red-600' : 'text-gray-500'}`}>
            Diferencias
          </p>
          <p className={`text-xl font-bold mt-1 ${diasConDiferencia > 0 ? 'text-red-700' : 'text-gray-400'}`}>
            {diasConDiferencia} {diasConDiferencia === 1 ? 'día' : 'días'}
          </p>
        </div>
      </div>

      {/* Lista de días */}
      {dias.length === 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-10 text-center">
          <Banknote size={32} className="text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-400">No hay turnos cerrados aún</p>
        </div>
      )}

      <div className="space-y-3">
        {dias.map(dia => {
          const abierto = expandido === dia.turno_id
          const pendientes = dia.consignaciones.filter(c => c.estado === 'pendiente')
          const ok = Math.abs(dia.diferencia) <= 0.5
          const hayEgresos = dia.egresos_detalle.length > 0
          const hayIngresos = dia.ingresos_detalle.length > 0

          return (
            <div key={dia.turno_id}
              className={`bg-white rounded-2xl border-2 overflow-hidden transition-all ${
                !ok ? 'border-red-200' : pendientes.length > 0 ? 'border-amber-200' : 'border-gray-200'
              }`}>

              {/* Cabecera del día — siempre visible */}
              <button
                className="w-full px-5 py-4 flex items-center gap-4 hover:bg-gray-50 transition-colors text-left"
                onClick={() => setExpandido(abierto ? null : dia.turno_id)}
              >
                {/* Indicador estado */}
                <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                  !ok ? 'bg-red-500' : pendientes.length > 0 ? 'bg-amber-400' : 'bg-green-400'
                }`} />

                {/* Fecha + sede */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-bold text-gray-800 capitalize">{fmtFecha(dia.fecha_cierre)}</p>
                    <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full font-medium">
                      {dia.tienda_nombre}
                    </span>
                    {pendientes.length > 0 && (
                      <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">
                        {pendientes.length} pendiente{pendientes.length !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Cierre {fmtHora(dia.fecha_cierre)} · Efectivo ventas {fmt(dia.total_efectivo)}
                  </p>
                </div>

                {/* Diferencia */}
                <div className="text-right shrink-0">
                  <p className={`text-base font-bold ${ok ? 'text-green-600' : 'text-red-600'}`}>
                    {ok ? '✓ Cuadrado' : fmt(dia.diferencia)}
                  </p>
                  <p className="text-xs text-gray-400">{fmt(dia.total_consignado)} consignado</p>
                </div>

                {abierto ? <ChevronUp size={16} className="text-gray-400 shrink-0" /> : <ChevronDown size={16} className="text-gray-400 shrink-0" />}
              </button>

              {/* Detalle expandible */}
              {abierto && (
                <div className="border-t border-gray-100 px-5 py-4 space-y-4">

                  {/* Fórmula de reconciliación */}
                  <div className="bg-gray-50 rounded-xl p-4 space-y-2 text-sm">
                    <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">Reconciliación del día</p>

                    <div className="flex justify-between">
                      <span className="text-gray-600">Ventas en efectivo</span>
                      <span className="font-semibold text-gray-800">{fmt(dia.total_efectivo)}</span>
                    </div>

                    {hayIngresos && dia.ingresos_detalle.map((m, i) => (
                      <div key={i} className="flex justify-between text-green-700">
                        <span className="text-xs pl-3">+ {m.concepto}</span>
                        <span className="text-xs font-semibold">{fmt(m.valor)}</span>
                      </div>
                    ))}

                    {hayEgresos && dia.egresos_detalle.map((m, i) => (
                      <div key={i} className="flex justify-between text-red-600">
                        <span className="text-xs pl-3">− {m.concepto} <span className="text-gray-400">({fmtHora(m.fecha)})</span></span>
                        <span className="text-xs font-semibold">{fmt(m.valor)}</span>
                      </div>
                    ))}

                    <div className="border-t border-gray-200 pt-2 flex justify-between font-bold">
                      <span className="text-gray-700">Debe consignarse</span>
                      <span className="text-blue-700">{fmt(dia.esperado_consignar)}</span>
                    </div>

                    <div className="flex justify-between">
                      <span className="text-gray-600">Total consignado</span>
                      <span className="font-semibold text-gray-800">{fmt(dia.total_consignado)}</span>
                    </div>

                    <div className={`flex justify-between font-bold pt-1 border-t border-gray-200 ${ok ? 'text-green-600' : 'text-red-600'}`}>
                      <span>Diferencia</span>
                      <span className="flex items-center gap-1">
                        {ok
                          ? <><CheckCircle2 size={14} /> Sin diferencia</>
                          : <><AlertTriangle size={14} /> {fmt(dia.diferencia)}</>
                        }
                      </span>
                    </div>
                  </div>

                  {/* Consignaciones */}
                  {dia.consignaciones.length === 0 ? (
                    <div className="text-center py-4">
                      <p className="text-sm text-red-500 font-semibold flex items-center justify-center gap-1">
                        <AlertTriangle size={14} /> Sin consignaciones registradas
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">
                        Consignaciones ({dia.consignaciones.length})
                      </p>
                      {dia.consignaciones.map(c => (
                        <div key={c.id}
                          className={`flex items-center gap-3 p-3 rounded-xl border ${
                            c.estado === 'pendiente' ? 'border-amber-200 bg-amber-50' : 'border-gray-100 bg-white'
                          }`}>
                          {/* Foto */}
                          {c.imagen_url ? (
                            <button onClick={() => setFotoModal(c.imagen_url!)}
                              className="relative group w-12 h-12 rounded-lg overflow-hidden border border-gray-200 shrink-0">
                              <img src={c.imagen_url} alt="" className="w-full h-full object-cover" />
                              <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                                <ZoomIn size={14} className="text-white" />
                              </div>
                            </button>
                          ) : (
                            <div className="w-12 h-12 rounded-lg bg-gray-100 flex items-center justify-center shrink-0 border border-gray-200">
                              <ImageIcon size={14} className="text-gray-300" />
                            </div>
                          )}

                          <div className="flex-1 min-w-0">
                            <p className="text-base font-bold text-gray-900">{fmt(c.valor)}</p>
                            <div className="flex items-center gap-1 text-xs text-gray-500 mt-0.5">
                              <User size={11} />
                              <span>{c.usuario_nombre || '—'}</span>
                              <span className="text-gray-300">·</span>
                              <span>{fmtHora(c.fecha)}</span>
                            </div>
                          </div>

                          {c.estado === 'pendiente' ? (
                            <button onClick={() => confirmar(c.id)} disabled={confirmando === c.id}
                              className="flex items-center gap-1 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors shrink-0">
                              <Check size={12} />
                              {confirmando === c.id ? '...' : 'Confirmar'}
                            </button>
                          ) : (
                            <span className="text-xs bg-green-100 text-green-700 px-2 py-1 rounded-full font-semibold shrink-0">
                              Confirmada
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Modal foto */}
      {fotoModal && (
        <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
          onClick={() => setFotoModal(null)}>
          <div className="relative max-w-lg w-full" onClick={e => e.stopPropagation()}>
            <button onClick={() => setFotoModal(null)}
              className="absolute -top-10 right-0 text-white/70 hover:text-white">
              <X size={24} />
            </button>
            <img src={fotoModal} alt="Comprobante" className="w-full rounded-2xl shadow-2xl" />
          </div>
        </div>
      )}
    </div>
  )
}
