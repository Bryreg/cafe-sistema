import { useEffect, useState } from 'react'
import api from '../api/client'
import { Check, KeyRound, Lock, Pencil, Plus, UserCheck, UserX, X } from 'lucide-react'

interface Tienda { id: number; nombre: string }
interface Usuario {
  id: number; nombre: string; email: string; rol: string
  tienda_id: number | null; tienda_nombre: string | null
  activo: boolean; ultimo_acceso: string | null
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

// ── Tarjeta: PIN de kiosko (acceso de dispositivo) ─────────────────────────────
function KioskPinCard() {
  const [pinActual, setPinActual] = useState<string>('')
  const [editando, setEditando] = useState(false)
  const [nuevo, setNuevo] = useState('')
  const [saving, setSaving] = useState(false)
  const [ok, setOk] = useState(false)
  const [error, setError] = useState('')

  const cargar = () => {
    api.get('/auth/config/kiosk-pin').then(r => setPinActual(r.data.pin ?? '')).catch(() => {})
  }
  useEffect(() => { cargar() }, [])

  const guardar = async () => {
    if (nuevo.trim().length < 4) { setError('El PIN debe tener al menos 4 caracteres'); return }
    setSaving(true); setError('')
    try {
      await api.put('/auth/config/kiosk-pin', { pin: nuevo.trim() })
      setOk(true); setEditando(false); setNuevo(''); cargar()
      setTimeout(() => setOk(false), 1800)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo guardar el PIN')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white border border-gray-100 rounded-2xl px-4 py-3.5 shadow-sm mb-4">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full flex items-center justify-center shrink-0 text-white"
          style={{ background: 'oklch(62% 0.18 50)' }}>
          <Lock size={17} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-800">PIN de kiosko</p>
          <p className="text-xs text-gray-400">Se usa para activar la caja en cada dispositivo</p>
        </div>
        {!editando && (
          <div className="flex items-center gap-3 shrink-0">
            <span className="text-base font-bold font-mono tracking-widest text-gray-700">{pinActual || '—'}</span>
            <button onClick={() => { setEditando(true); setNuevo('') }}
              className="text-xs font-semibold text-amber-600 hover:text-amber-700">Cambiar</button>
          </div>
        )}
      </div>

      {editando && (
        <div className="mt-3 flex items-center gap-2">
          <input
            value={nuevo} onChange={e => setNuevo(e.target.value)}
            type="text" inputMode="numeric" placeholder="Nuevo PIN"
            className="flex-1 border border-gray-200 rounded-xl px-3 py-2.5 text-sm font-mono tracking-widest outline-none focus:border-amber-400"
          />
          <button onClick={guardar} disabled={saving}
            className="bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white font-bold px-4 py-2.5 rounded-xl text-sm">
            {saving ? '...' : 'Guardar'}
          </button>
          <button onClick={() => { setEditando(false); setError('') }}
            className="text-gray-400 hover:text-gray-600 px-2"><X size={18} /></button>
        </div>
      )}
      {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
      {ok && <p className="text-xs text-green-600 mt-2 flex items-center gap-1"><Check size={13} /> PIN actualizado</p>}
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
          password: Array.from(crypto.getRandomValues(new Uint8Array(8))).map(b => b.toString(16).padStart(2, '0')).join(''),
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

// ── Modal contraseña (acceso de admin) ─────────────────────────────────────────
function ModalPassword({ usuario, onClose, onGuardar }: { usuario: Usuario; onClose: () => void; onGuardar: () => void }) {
  const [pass, setPass]     = useState('')
  const [saving, setSaving] = useState(false)
  const [ok, setOk]         = useState(false)
  const [error, setError]   = useState('')

  const guardar = async () => {
    if (pass.length < 6) { setError('La contraseña debe tener al menos 6 caracteres'); return }
    setSaving(true); setError('')
    try {
      await api.post(`/auth/usuarios/${usuario.id}/set-password`, { password: pass })
      setOk(true)
      setTimeout(() => { onGuardar() }, 1000)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al guardar la contraseña')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Nueva contraseña para <span className="font-semibold text-gray-800">{usuario.nombre}</span>.
        Se usará para iniciar sesión en el panel de administración.
      </p>
      <div>
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Contraseña</label>
        <input
          value={pass} onChange={e => setPass(e.target.value)}
          type="text" autoComplete="new-password"
          placeholder="Mínimo 6 caracteres"
          className="w-full border border-gray-200 rounded-xl px-3 py-3 text-sm outline-none focus:border-amber-400"
        />
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
      {ok && (
        <div className="flex items-center gap-2 text-green-600 text-sm">
          <Check size={14} /> Contraseña actualizada
        </div>
      )}
      <button onClick={guardar} disabled={saving || ok || pass.length < 6}
        className="w-full bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white font-bold py-3 rounded-xl text-sm transition-colors">
        {saving ? 'Guardando...' : 'Cambiar contraseña'}
      </button>
    </div>
  )
}

// ── Página principal ──────────────────────────────────────────────────────────
export default function Usuarios() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([])
  const [tiendas, setTiendas]   = useState<Tienda[]>([])
  const [modal, setModal]       = useState<'crear' | 'editar' | 'password' | null>(null)
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

      <KioskPinCard />

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
                  <span className="text-[11px] text-gray-400">Acceso: {fmtFecha(u.ultimo_acceso)}</span>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {u.rol === 'admin' && (
                  <button
                    onClick={() => { setSeleccionado(u); setModal('password') }}
                    title="Cambiar contraseña"
                    className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-amber-50 text-amber-500 transition-colors"
                  >
                    <KeyRound size={15} />
                  </button>
                )}
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
      {modal === 'password' && seleccionado && (
        <Modal title="Cambiar contraseña" onClose={() => setModal(null)}>
          <ModalPassword usuario={seleccionado} onClose={() => setModal(null)} onGuardar={onGuardar} />
        </Modal>
      )}
    </div>
  )
}
