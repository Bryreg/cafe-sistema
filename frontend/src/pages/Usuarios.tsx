import { useEffect, useState } from 'react'
import api from '../api/client'
import { Check, KeyRound, Pencil, Plus, UserCheck, UserX, X } from 'lucide-react'

interface Tienda { id: number; nombre: string }
interface Usuario {
  id: number; nombre: string; email: string; rol: string
  tienda_id: number | null; tienda_nombre: string | null
  activo: boolean; ultimo_acceso: string | null; tiene_pin: boolean
}

const TINTS = [
  'oklch(50% 0.12 155)', 'oklch(48% 0.13 240)', 'oklch(50% 0.14 300)',
  'oklch(52% 0.16 30)',  'oklch(48% 0.14 340)', 'oklch(50% 0.12 200)',
]
const iniciales = (n: string) => n.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()
const fmtFecha = (s: string | null) => {
  if (!s) return 'Nunca'
  return new Date(s).toLocaleDateString('es-CO', { day: 'numeric', month: 'short', year: '2-digit' })
}

// ── Modal genérico ────────────────────────────────────────────────────────────
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <p className="font-bold text-gray-800">{title}</p>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}

// ── Formulario nuevo / editar usuario ─────────────────────────────────────────
function FormUsuario({
  inicial, tiendas, onGuardar, onClose,
}: {
  inicial?: Usuario | null
  tiendas: Tienda[]
  onGuardar: () => void
  onClose: () => void
}) {
  const editando = !!inicial
  const [nombre, setNombre]   = useState(inicial?.nombre ?? '')
  const [email, setEmail]     = useState(inicial?.email ?? '')
  const [rol, setRol]         = useState(inicial?.rol ?? 'barista')
  const [tienda, setTienda]   = useState<string>(String(inicial?.tienda_id ?? ''))
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')

  const guardar = async () => {
    if (!nombre.trim() || (!editando && !email.trim())) {
      setError('Nombre y email son obligatorios'); return
    }
    setSaving(true); setError('')
    try {
      if (editando) {
        await api.patch(`/auth/usuarios/${inicial!.id}`, {
          nombre: nombre.trim(),
          rol,
          tienda_id: tienda ? Number(tienda) : null,
        })
      } else {
        await api.post('/auth/usuarios', {
          nombre: nombre.trim(),
          email: email.trim().toLowerCase(),
          password: Math.random().toString(36).slice(2, 10),
          rol,
          tienda_id: tienda ? Number(tienda) : null,
        })
      }
      onGuardar()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Nombre</label>
        <input value={nombre} onChange={e => setNombre(e.target.value)}
          className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm outline-none focus:border-amber-400"
          placeholder="Nombre completo" />
      </div>
      {!editando && (
        <div>
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Email</label>
          <input value={email} onChange={e => setEmail(e.target.value)}
            type="email"
            className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm outline-none focus:border-amber-400"
            placeholder="correo@ejemplo.com" />
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Rol</label>
          <select value={rol} onChange={e => setRol(e.target.value)}
            className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm outline-none focus:border-amber-400 bg-white">
            <option value="barista">Barista</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div>
          <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Sede</label>
          <select value={tienda} onChange={e => setTienda(e.target.value)}
            className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm outline-none focus:border-amber-400 bg-white">
            <option value="">Sin sede</option>
            {tiendas.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
          </select>
        </div>
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
      <button onClick={guardar} disabled={saving}
        className="w-full bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white font-bold py-3 rounded-xl text-sm transition-colors">
        {saving ? 'Guardando...' : editando ? 'Guardar cambios' : 'Crear usuario'}
      </button>
    </div>
  )
}

// ── Modal PIN ─────────────────────────────────────────────────────────────────
function ModalPin({ usuario, onClose, onGuardar }: { usuario: Usuario; onClose: () => void; onGuardar: () => void }) {
  const [pin, setPin]     = useState('')
  const [saving, setSaving] = useState(false)
  const [ok, setOk]       = useState(false)
  const [error, setError] = useState('')

  const guardar = async () => {
    if (pin.length !== 4 || !/^\d{4}$/.test(pin)) {
      setError('El PIN debe ser 4 dígitos'); return
    }
    setSaving(true); setError('')
    try {
      await api.post(`/auth/usuarios/${usuario.id}/set-pin`, { pin })
      setOk(true)
      setTimeout(() => { onGuardar() }, 1000)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al guardar PIN')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Establece el PIN de 4 dígitos para <span className="font-semibold text-gray-800">{usuario.nombre}</span>.
        Este PIN se usará para iniciar sesión desde el celular.
      </p>
      <div>
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">PIN de 4 dígitos</label>
        <input
          value={pin} onChange={e => setPin(e.target.value.replace(/\D/g, '').slice(0, 4))}
          type="text" inputMode="numeric" maxLength={4}
          placeholder="0000"
          className="w-full border border-gray-200 rounded-xl px-3 py-3 text-2xl font-bold font-mono text-center tracking-[0.5em] outline-none focus:border-amber-400"
        />
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
      {ok && (
        <div className="flex items-center gap-2 text-green-600 text-sm">
          <Check size={14} /> PIN guardado correctamente
        </div>
      )}
      <button onClick={guardar} disabled={saving || ok || pin.length !== 4}
        className="w-full bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white font-bold py-3 rounded-xl text-sm transition-colors">
        {saving ? 'Guardando...' : 'Establecer PIN'}
      </button>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────────────
export default function Usuarios() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([])
  const [tiendas, setTiendas]   = useState<Tienda[]>([])
  const [modal, setModal]       = useState<'crear' | 'editar' | 'pin' | null>(null)
  const [seleccionado, setSeleccionado] = useState<Usuario | null>(null)
  const [loading, setLoading]   = useState(true)

  const cargar = async () => {
    const [u, t] = await Promise.all([
      api.get('/auth/admin/usuarios'),
      api.get('/auth/tiendas'),
    ])
    setUsuarios(u.data)
    setTiendas(t.data)
    setLoading(false)
  }

  useEffect(() => { cargar() }, [])

  const toggleActivo = async (u: Usuario) => {
    await api.patch(`/auth/usuarios/${u.id}`, { activo: !u.activo })
    cargar()
  }

  const onGuardar = () => { setModal(null); setSeleccionado(null); cargar() }

  const activos   = usuarios.filter(u => u.activo)
  const inactivos = usuarios.filter(u => !u.activo)

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Usuarios</h1>
          <p className="text-sm text-gray-500 mt-0.5">{activos.length} activos · {inactivos.length} inactivos</p>
        </div>
        <button
          onClick={() => { setSeleccionado(null); setModal('crear') }}
          className="flex items-center gap-2 bg-amber-500 hover:bg-amber-600 text-white font-semibold text-sm px-4 py-2.5 rounded-xl transition-colors"
        >
          <Plus size={15} /> Nuevo usuario
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400 text-center py-10">Cargando...</p>
      ) : (
        <div className="space-y-2">
          {activos.map((u, i) => (
            <div key={u.id} className="bg-white border border-gray-100 rounded-2xl px-4 py-3 flex items-center gap-4 shadow-sm">
              <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0 text-sm font-bold text-white"
                style={{ background: TINTS[i % TINTS.length] }}>
                {iniciales(u.nombre)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold text-gray-800 truncate">{u.nombre}</p>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full uppercase ${
                    u.rol === 'admin' ? 'bg-purple-100 text-purple-700' : 'bg-amber-100 text-amber-700'
                  }`}>{u.rol}</span>
                </div>
                <p className="text-xs text-gray-400 truncate">{u.email}</p>
                <div className="flex items-center gap-3 mt-0.5">
                  {u.tienda_nombre && (
                    <span className="text-[11px] text-gray-500">{u.tienda_nombre}</span>
                  )}
                  <span className={`text-[11px] flex items-center gap-1 ${u.tiene_pin ? 'text-green-600' : 'text-red-400'}`}>
                    <KeyRound size={10} />
                    {u.tiene_pin ? 'PIN configurado' : 'Sin PIN'}
                  </span>
                  <span className="text-[11px] text-gray-400">Acceso: {fmtFecha(u.ultimo_acceso)}</span>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => { setSeleccionado(u); setModal('pin') }}
                  title="Establecer PIN"
                  className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-amber-50 text-amber-500 transition-colors"
                >
                  <KeyRound size={15} />
                </button>
                <button
                  onClick={() => { setSeleccionado(u); setModal('editar') }}
                  title="Editar"
                  className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-gray-100 text-gray-500 transition-colors"
                >
                  <Pencil size={15} />
                </button>
                <button
                  onClick={() => toggleActivo(u)}
                  title="Desactivar"
                  className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-red-50 text-red-400 transition-colors"
                >
                  <UserX size={15} />
                </button>
              </div>
            </div>
          ))}

          {inactivos.length > 0 && (
            <>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide pt-4 pb-1 px-1">
                Inactivos
              </p>
              {inactivos.map((u, i) => (
                <div key={u.id} className="bg-gray-50 border border-gray-100 rounded-2xl px-4 py-3 flex items-center gap-4 opacity-60">
                  <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0 text-sm font-bold text-white bg-gray-400">
                    {iniciales(u.nombre)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-gray-600 truncate">{u.nombre}</p>
                    <p className="text-xs text-gray-400 truncate">{u.email}</p>
                  </div>
                  <button
                    onClick={() => toggleActivo(u)}
                    title="Reactivar"
                    className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-green-50 text-green-500 transition-colors"
                  >
                    <UserCheck size={15} />
                  </button>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {/* Modales */}
      {modal === 'crear' && (
        <Modal title="Nuevo usuario" onClose={() => setModal(null)}>
          <FormUsuario tiendas={tiendas} onGuardar={onGuardar} onClose={() => setModal(null)} />
        </Modal>
      )}
      {modal === 'editar' && seleccionado && (
        <Modal title="Editar usuario" onClose={() => setModal(null)}>
          <FormUsuario inicial={seleccionado} tiendas={tiendas} onGuardar={onGuardar} onClose={() => setModal(null)} />
        </Modal>
      )}
      {modal === 'pin' && seleccionado && (
        <Modal title="Configurar PIN" onClose={() => setModal(null)}>
          <ModalPin usuario={seleccionado} onClose={() => setModal(null)} onGuardar={onGuardar} />
        </Modal>
      )}
    </div>
  )
}
