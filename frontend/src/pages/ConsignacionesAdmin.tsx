import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Banknote, User, Calendar, ImageIcon, Check, X, ZoomIn } from 'lucide-react'

interface Consignacion {
  id: number
  valor: number
  imagen_url: string | null
  estado: string
  fecha: string
  usuario_nombre: string | null
  usuario_id: number | null
}

const fmt = (v: number) => `$${v.toLocaleString('es-CO')}`

const fmtFecha = (f: string) => {
  const d = new Date(f)
  return d.toLocaleString('es-CO', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function ConsignacionesAdmin() {
  const { user } = useAuth()
  const [lista, setLista] = useState<Consignacion[]>([])
  const [loading, setLoading] = useState(true)
  const [fotoModal, setFotoModal] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState<number | null>(null)

  const load = async () => {
    if (!user?.tienda_id) return
    setLoading(true)
    try {
      const { data } = await api.get(`/consignaciones/tienda/${user.tienda_id}`)
      setLista(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [user])

  const confirmar = async (id: number) => {
    setConfirmando(id)
    try {
      await api.patch(`/consignaciones/${id}/confirmar`)
      setLista(prev => prev.map(c => c.id === id ? { ...c, estado: 'realizada' } : c))
    } finally {
      setConfirmando(null)
    }
  }

  const pendientes = lista.filter(c => c.estado === 'pendiente')
  const realizadas = lista.filter(c => c.estado === 'realizada')
  const totalPendiente = pendientes.reduce((s, c) => s + c.valor, 0)
  const totalRealizado = realizadas.reduce((s, c) => s + c.valor, 0)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Consignaciones</h1>
        <p className="text-sm text-gray-500 mt-1">Revisión y confirmación de consignaciones de la tienda</p>
      </div>

      {/* Resumen */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
          <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide">Pendientes</p>
          <p className="text-2xl font-bold text-amber-800 mt-1">{fmt(totalPendiente)}</p>
          <p className="text-xs text-amber-600 mt-0.5">{pendientes.length} consignación{pendientes.length !== 1 ? 'es' : ''}</p>
        </div>
        <div className="bg-green-50 border border-green-200 rounded-2xl p-4">
          <p className="text-xs font-semibold text-green-600 uppercase tracking-wide">Confirmadas</p>
          <p className="text-2xl font-bold text-green-800 mt-1">{fmt(totalRealizado)}</p>
          <p className="text-xs text-green-600 mt-0.5">{realizadas.length} consignación{realizadas.length !== 1 ? 'es' : ''}</p>
        </div>
      </div>

      {loading && (
        <p className="text-sm text-gray-400 text-center py-8">Cargando...</p>
      )}

      {!loading && lista.length === 0 && (
        <div className="bg-white rounded-2xl border border-gray-200 p-10 text-center">
          <Banknote size={32} className="text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-400">No hay consignaciones registradas</p>
        </div>
      )}

      {/* Pendientes primero */}
      {pendientes.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Por confirmar</p>
          <div className="space-y-3">
            {pendientes.map(c => (
              <ConsignacionCard
                key={c.id}
                c={c}
                onConfirmar={confirmar}
                confirmando={confirmando === c.id}
                onVerFoto={setFotoModal}
              />
            ))}
          </div>
        </div>
      )}

      {/* Realizadas */}
      {realizadas.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Confirmadas</p>
          <div className="space-y-3">
            {realizadas.map(c => (
              <ConsignacionCard
                key={c.id}
                c={c}
                onConfirmar={confirmar}
                confirmando={false}
                onVerFoto={setFotoModal}
              />
            ))}
          </div>
        </div>
      )}

      {/* Modal foto */}
      {fotoModal && (
        <div
          className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
          onClick={() => setFotoModal(null)}
        >
          <div className="relative max-w-lg w-full" onClick={e => e.stopPropagation()}>
            <button
              onClick={() => setFotoModal(null)}
              className="absolute -top-10 right-0 text-white/70 hover:text-white"
            >
              <X size={24} />
            </button>
            <img
              src={fotoModal}
              alt="Comprobante"
              className="w-full rounded-2xl shadow-2xl"
            />
          </div>
        </div>
      )}
    </div>
  )
}

function ConsignacionCard({
  c,
  onConfirmar,
  confirmando,
  onVerFoto,
}: {
  c: Consignacion
  onConfirmar: (id: number) => void
  confirmando: boolean
  onVerFoto: (url: string) => void
}) {
  const isPendiente = c.estado === 'pendiente'

  return (
    <div className={`bg-white rounded-2xl border ${isPendiente ? 'border-amber-200' : 'border-gray-200'} p-4`}>
      <div className="flex gap-4">
        {/* Foto */}
        <div className="flex-shrink-0">
          {c.imagen_url ? (
            <button
              onClick={() => onVerFoto(c.imagen_url!)}
              className="relative group w-20 h-20 rounded-xl overflow-hidden border border-gray-200 block"
            >
              <img
                src={c.imagen_url}
                alt="Comprobante"
                className="w-full h-full object-cover"
              />
              <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                <ZoomIn size={18} className="text-white" />
              </div>
            </button>
          ) : (
            <div className="w-20 h-20 rounded-xl bg-gray-100 flex items-center justify-center border border-gray-200">
              <ImageIcon size={20} className="text-gray-300" />
            </div>
          )}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xl font-bold text-gray-900">{fmt(c.valor)}</p>
            <span className={`text-xs font-semibold px-2.5 py-1 rounded-full flex-shrink-0 ${
              isPendiente ? 'bg-amber-100 text-amber-700' : 'bg-green-100 text-green-700'
            }`}>
              {isPendiente ? 'Pendiente' : 'Confirmada'}
            </span>
          </div>

          <div className="mt-2 space-y-1">
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <User size={12} className="flex-shrink-0" />
              <span className="font-medium text-gray-700">{c.usuario_nombre || 'Desconocido'}</span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <Calendar size={12} className="flex-shrink-0" />
              <span>{fmtFecha(c.fecha)}</span>
            </div>
          </div>

          {isPendiente && (
            <button
              onClick={() => onConfirmar(c.id)}
              disabled={confirmando}
              className="mt-3 flex items-center gap-1.5 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
            >
              <Check size={13} />
              {confirmando ? 'Confirmando...' : 'Confirmar consignación'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
