import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { RotateCcw, X, Check } from 'lucide-react'

interface Item { id: number; producto_id: number; nombre_producto: string; cantidad: number; subtotal: number }
interface Ticket { id: number; fecha: string; total: number; metodo_pago: string; estado: string; items: Item[] }
interface Sede { id: number; nombre: string }

const fmt = (v: number) => `$${(v || 0).toLocaleString('es-CO')}`
const fmtFecha = (iso: string) =>
  new Date(iso.endsWith('Z') ? iso : iso + 'Z').toLocaleString('es-CO', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })

export default function NotaCredito() {
  const { user } = useAuth()
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [loading, setLoading] = useState(false)
  const [target, setTarget] = useState<Ticket | null>(null)

  useEffect(() => {
    api.get('/auth/tiendas').then(r => {
      setSedes(r.data)
      if (!tiendaId && r.data[0]) setTiendaId(r.data[0].id)
    })
  }, []) // eslint-disable-line

  const cargar = () => {
    if (!tiendaId) return
    setLoading(true)
    api.get(`/pos/tickets/recientes?tienda_id=${tiendaId}`)
      .then(r => setTickets(r.data)).finally(() => setLoading(false))
  }
  useEffect(() => { cargar() }, [tiendaId]) // eslint-disable-line

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-5 gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-warm-800">Notas de crédito</h1>
          <p className="text-sm text-warm-500">
            Revertir una venta. Por producto elegís si se usó (queda descontado) o no (vuelve al inventario).
          </p>
        </div>
        <select value={tiendaId ?? ''} onChange={e => setTiendaId(Number(e.target.value))}
          className="rounded-xl border border-warm-200 px-3 py-2 text-sm bg-white">
          {sedes.map(s => <option key={s.id} value={s.id}>{s.nombre}</option>)}
        </select>
      </div>

      {loading ? (
        <p className="text-warm-500 text-sm">Cargando...</p>
      ) : (
        <div className="rounded-2xl border border-warm-200 overflow-hidden bg-white">
          <table className="w-full text-sm">
            <thead className="bg-warm-50 text-warm-500 text-xs uppercase">
              <tr>
                <th className="text-left px-4 py-3">Ticket</th>
                <th className="text-left px-4 py-3">Fecha</th>
                <th className="text-right px-4 py-3">Total</th>
                <th className="text-left px-4 py-3">Pago</th>
                <th className="text-left px-4 py-3">Estado</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {tickets.map(t => (
                <tr key={t.id} className="border-t border-warm-100">
                  <td className="px-4 py-3 font-mono font-semibold text-warm-700">#{t.id}</td>
                  <td className="px-4 py-3 text-warm-500">{fmtFecha(t.fecha)}</td>
                  <td className="px-4 py-3 text-right font-mono font-semibold text-warm-800">{fmt(t.total)}</td>
                  <td className="px-4 py-3 capitalize text-warm-600">{t.metodo_pago}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                      t.estado === 'reversado' ? 'bg-red-50 text-red-600'
                        : t.estado === 'anulado' ? 'bg-warm-100 text-warm-500'
                        : 'bg-green-50 text-green-700'}`}>
                      {t.estado}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {t.estado === 'completado' && (
                      <button onClick={() => setTarget(t)}
                        className="inline-flex items-center gap-1.5 text-xs font-semibold text-green-700 hover:underline">
                        <RotateCcw size={13} /> Revertir
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {tickets.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-warm-400">Sin tickets recientes.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {target && <RevertModal ticket={target} onClose={() => setTarget(null)} onDone={() => { setTarget(null); cargar() }} />}
    </div>
  )
}

function RevertModal({ ticket, onClose, onDone }: { ticket: Ticket; onClose: () => void; onDone: () => void }) {
  const [motivo, setMotivo] = useState('')
  // Indexado por id de la LÍNEA del ticket: dos líneas del mismo combo comparten
  // producto_id (sombra) y deben marcarse independiente.
  const [usado, setUsado] = useState<Record<number, boolean>>(
    Object.fromEntries(ticket.items.map(i => [i.id, true])) // default: usado (no devuelve)
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const confirmar = async () => {
    if (!motivo.trim()) { setError('El motivo es obligatorio'); return }
    setSaving(true); setError('')
    try {
      await api.post(`/pos/ticket/${ticket.id}/revertir`, {
        motivo: motivo.trim(),
        items: ticket.items.map(i => ({ item_id: i.id, producto_id: i.producto_id, producto_usado: usado[i.id] })),
      })
      onDone()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al revertir')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-md p-5" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-bold text-warm-800">Revertir venta #{ticket.id} · {fmt(ticket.total)}</h2>
          <button onClick={onClose} className="text-warm-400 hover:text-warm-600"><X size={18} /></button>
        </div>
        <input value={motivo} onChange={e => setMotivo(e.target.value)} placeholder="Motivo de la reversión"
          className="w-full rounded-xl border border-warm-200 px-3 py-2.5 text-sm mb-4 outline-none focus:border-green-600" />
        <p className="text-xs font-semibold text-warm-500 uppercase mb-2">¿Se usó el producto?</p>
        <div className="space-y-2 mb-3">
          {ticket.items.map(i => (
            <div key={i.id} className="flex items-center gap-3">
              <span className="flex-1 text-sm text-warm-700">
                {i.nombre_producto} <span className="text-warm-400">×{i.cantidad}</span>
              </span>
              <div className="flex rounded-lg overflow-hidden border border-warm-200 text-xs font-semibold">
                <button onClick={() => setUsado(p => ({ ...p, [i.id]: true }))}
                  className={usado[i.id] ? 'px-3 py-1.5 bg-warm-700 text-white' : 'px-3 py-1.5 bg-white text-warm-500'}>
                  Sí, se usó
                </button>
                <button onClick={() => setUsado(p => ({ ...p, [i.id]: false }))}
                  className={!usado[i.id] ? 'px-3 py-1.5 bg-green-700 text-white' : 'px-3 py-1.5 bg-white text-warm-500'}>
                  No, vuelve
                </button>
              </div>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-warm-400 mb-4">
          Devuelve la plata siempre. El inventario solo recupera lo marcado "No, vuelve".
        </p>
        {error && <p className="text-sm text-red-500 mb-3">{error}</p>}
        <button onClick={confirmar} disabled={saving}
          className="w-full py-3 rounded-xl bg-green-700 text-white font-bold text-sm flex items-center justify-center gap-2 disabled:opacity-50">
          <Check size={16} /> {saving ? 'Revirtiendo...' : 'Confirmar Nota Crédito'}
        </button>
      </div>
    </div>
  )
}
