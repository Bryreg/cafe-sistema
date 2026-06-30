import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import { Receipt, Upload, X, Save, Loader2 } from 'lucide-react'

interface Config {
  nombre_negocio: string
  nit:            string
  telefono:       string
  direccion:      string
  logo_url:       string | null
  mensaje_footer: string
  ancho_papel_mm: number
  escala_fuente:  'small' | 'normal' | 'large'
}

const EMPTY: Config = {
  nombre_negocio: '',
  nit:            '',
  telefono:       '',
  direccion:      '',
  logo_url:       null,
  mensaje_footer: '',
  ancho_papel_mm: 80,
  escala_fuente:  'normal',
}

export default function ConfigTicketPage() {
  const { user } = useAuth()
  // No defaultear a la tienda 1: un admin sin sede asignada estaría leyendo/sobrescribiendo
  // en silencio la config de otra tienda. Mejor null + guard explícito.
  const tiendaId = user?.tienda_id ?? null
  const fileRef  = useRef<HTMLInputElement>(null)

  const [cfg,          setCfg]          = useState<Config>(EMPTY)
  const [original,     setOriginal]     = useState<Config>(EMPTY)
  const [loading,      setLoading]      = useState(true)
  const [saving,       setSaving]       = useState(false)
  const [uploadingLogo,setUploadingLogo]= useState(false)
  const [saved,        setSaved]        = useState(false)
  const [error,        setError]        = useState('')

  useEffect(() => {
    if (!tiendaId) {
      setError('Tu cuenta de admin no tiene una sede asignada. Asigná una sede en Usuarios para configurar el ticket.')
      setLoading(false)
      return
    }
    setLoading(true)
    api.get(`/config-ticket/${tiendaId}`)
      .then(({ data }) => {
        const loaded: Config = {
          nombre_negocio: data.nombre_negocio ?? '',
          nit:            data.nit            ?? '',
          telefono:       data.telefono       ?? '',
          direccion:      data.direccion      ?? '',
          logo_url:       data.logo_url       ?? null,
          mensaje_footer: data.mensaje_footer ?? '',
          ancho_papel_mm: data.ancho_papel_mm ?? 80,
          escala_fuente:  data.escala_fuente  ?? 'normal',
        }
        setCfg(loaded)
        setOriginal(loaded)
      })
      .catch(() => setError('Error al cargar la configuración'))
      .finally(() => setLoading(false))
  }, [tiendaId])

  const set = (k: keyof Config, v: string) => {
    setCfg(prev => ({ ...prev, [k]: v }))
    setSaved(false)
  }

  const handleSave = async () => {
    if (!tiendaId) return
    setSaving(true); setError('')
    try {
      await api.put(`/config-ticket/${tiendaId}`, {
        nombre_negocio: cfg.nombre_negocio || null,
        nit:            cfg.nit            || null,
        telefono:       cfg.telefono       || null,
        direccion:      cfg.direccion      || null,
        mensaje_footer: cfg.mensaje_footer || null,
        ancho_papel_mm: cfg.ancho_papel_mm,
        escala_fuente:  cfg.escala_fuente,
      })
      setOriginal(cfg)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch {
      setError('Error al guardar')
    } finally {
      setSaving(false)
    }
  }

  const handleLogo = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !tiendaId) return
    setUploadingLogo(true); setError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post(`/config-ticket/${tiendaId}/logo`, form)
      setCfg(prev => ({ ...prev, logo_url: data.logo_url }))
      setOriginal(prev => ({ ...prev, logo_url: data.logo_url }))
    } catch {
      setError('Error al subir el logo')
    } finally {
      setUploadingLogo(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleRemoveLogo = async () => {
    if (!tiendaId) return
    setUploadingLogo(true)
    try {
      await api.delete(`/config-ticket/${tiendaId}/logo`)
      setCfg(prev => ({ ...prev, logo_url: null }))
      setOriginal(prev => ({ ...prev, logo_url: null }))
    } catch {
      setError('Error al eliminar el logo')
    } finally {
      setUploadingLogo(false)
    }
  }

  const dirty = JSON.stringify(cfg) !== JSON.stringify(original)

  if (loading) return (
    <div className="flex justify-center py-16">
      <Loader2 size={20} className="animate-spin text-warm-400" />
    </div>
  )

  return (
    <div className="space-y-5 pb-10">

      {/* Header */}
      <div className="flex items-center gap-3 pt-2">
        <div className="w-9 h-9 rounded-xl flex items-center justify-center"
          style={{ background: 'oklch(94% 0.04 155)' }}>
          <Receipt size={17} style={{ color: 'oklch(38% 0.10 155)' }} />
        </div>
        <div>
          <h1 className="text-bark-800" style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>
            Ticket de venta
          </h1>
          <p className="text-warm-500" style={{ fontSize: 11, margin: 0 }}>
            Datos que aparecen en el comprobante impreso
          </p>
        </div>
      </div>

      {error && (
        <div className="text-danger-700 bg-danger-50 border border-danger-200 rounded-xl px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {/* Logo */}
      <div className="bg-white border border-warm-200 rounded-2xl overflow-hidden">
        <div className="px-4 pt-4 pb-3 border-b border-warm-100">
          <p className="text-warm-500" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', margin: 0 }}>
            Logo
          </p>
        </div>
        <div className="p-4 flex items-center gap-4">
          {cfg.logo_url ? (
            <>
              <img
                src={cfg.logo_url}
                alt="Logo"
                className="rounded-xl border border-warm-200 object-contain bg-warm-50"
                style={{ width: 72, height: 72 }}
              />
              <div className="flex flex-col gap-2">
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={uploadingLogo}
                  className="flex items-center gap-1.5 text-sm font-semibold px-3 py-2 rounded-xl border border-warm-200 text-warm-700 hover:bg-warm-50 disabled:opacity-50 transition-colors"
                >
                  <Upload size={13} /> Cambiar
                </button>
                <button
                  onClick={handleRemoveLogo}
                  disabled={uploadingLogo}
                  className="flex items-center gap-1.5 text-sm font-semibold px-3 py-2 rounded-xl border border-danger-200 text-danger-600 hover:bg-danger-50 disabled:opacity-50 transition-colors"
                >
                  <X size={13} /> Eliminar
                </button>
              </div>
            </>
          ) : (
            <button
              onClick={() => fileRef.current?.click()}
              disabled={uploadingLogo}
              className="flex items-center gap-2 px-4 py-3 rounded-xl border-2 border-dashed border-warm-300 text-warm-500 hover:border-forest-400 hover:text-forest-600 transition-colors text-sm font-semibold disabled:opacity-50"
            >
              {uploadingLogo
                ? <Loader2 size={15} className="animate-spin" />
                : <Upload size={15} />}
              {uploadingLogo ? 'Subiendo...' : 'Subir logo'}
            </button>
          )}
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleLogo}
          />
        </div>
        {cfg.logo_url && (
          <p className="px-4 pb-3 text-warm-400" style={{ fontSize: 10.5 }}>
            El logo se imprimirá centrado en la parte superior del ticket.
          </p>
        )}
      </div>

      {/* Datos del negocio */}
      <div className="bg-white border border-warm-200 rounded-2xl overflow-hidden">
        <div className="px-4 pt-4 pb-3 border-b border-warm-100">
          <p className="text-warm-500" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', margin: 0 }}>
            Datos del negocio
          </p>
        </div>
        <div className="divide-y divide-warm-100">
          {([
            { key: 'nombre_negocio', label: 'Nombre del negocio', placeholder: 'AZ CAFE', maxLen: 150 },
            { key: 'nit',            label: 'NIT',                placeholder: 'XX.XXX.XXX-X', maxLen: 30 },
            { key: 'telefono',       label: 'Teléfono',           placeholder: '601 123 4567', maxLen: 30 },
            { key: 'direccion',      label: 'Dirección',          placeholder: 'Cra. 7 #45-12, Bogotá', maxLen: 250 },
          ] as const).map(({ key, label, placeholder, maxLen }) => (
            <div key={key} className="px-4 py-3">
              <label className="block text-warm-500 mb-1" style={{ fontSize: 11, fontWeight: 600 }}>
                {label}
              </label>
              <input
                value={(cfg as any)[key]}
                onChange={e => set(key as keyof Config, e.target.value)}
                placeholder={placeholder}
                maxLength={maxLen}
                className="w-full rounded-xl border border-warm-200 px-3 py-2 text-bark-700 outline-none focus:border-forest transition-colors"
                style={{ fontSize: 14 }}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Mensaje pie */}
      <div className="bg-white border border-warm-200 rounded-2xl overflow-hidden">
        <div className="px-4 pt-4 pb-3 border-b border-warm-100">
          <p className="text-warm-500" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', margin: 0 }}>
            Mensaje de cierre
          </p>
        </div>
        <div className="p-4">
          <input
            value={cfg.mensaje_footer}
            onChange={e => set('mensaje_footer', e.target.value)}
            placeholder="¡Gracias por tu compra!"
            maxLength={300}
            className="w-full rounded-xl border border-warm-200 px-3 py-2 text-bark-700 outline-none focus:border-forest transition-colors"
            style={{ fontSize: 14 }}
          />
          <p className="text-warm-400 mt-1" style={{ fontSize: 10.5 }}>
            Aparece al final del ticket, centrado.
          </p>
        </div>
      </div>

      {/* Dimensiones de impresión */}
      <div className="bg-white border border-warm-200 rounded-2xl overflow-hidden">
        <div className="px-4 pt-4 pb-3 border-b border-warm-100">
          <p className="text-warm-500" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', margin: 0 }}>
            Dimensiones de impresión
          </p>
        </div>
        <div className="divide-y divide-warm-100">

          {/* Ancho del papel */}
          <div className="px-4 py-3">
            <label className="block text-warm-500 mb-2" style={{ fontSize: 11, fontWeight: 600 }}>
              Ancho del papel térmico
            </label>
            <div className="flex gap-2">
              {([58, 72, 80] as const).map(w => (
                <button
                  key={w}
                  onClick={() => { setCfg(prev => ({ ...prev, ancho_papel_mm: w })); setSaved(false) }}
                  className="flex-1 py-2.5 rounded-xl text-sm font-semibold border-2 transition-all"
                  style={{
                    borderColor: cfg.ancho_papel_mm === w ? 'oklch(48% 0.12 155)' : 'oklch(90% 0.008 75)',
                    background:  cfg.ancho_papel_mm === w ? 'oklch(96% 0.025 155)' : 'transparent',
                    color:       cfg.ancho_papel_mm === w ? 'oklch(35% 0.10 155)' : 'oklch(58% 0.01 60)',
                  }}
                >
                  {w} mm
                </button>
              ))}
            </div>
            <p className="text-warm-400 mt-1.5" style={{ fontSize: 10.5 }}>
              El más común es <strong>80 mm</strong>. Si el ticket se ve cortado, probá 58 mm.
            </p>
          </div>

          {/* Tamaño de fuente */}
          <div className="px-4 py-3">
            <label className="block text-warm-500 mb-2" style={{ fontSize: 11, fontWeight: 600 }}>
              Tamaño de letra
            </label>
            <div className="flex gap-2">
              {([
                { key: 'small',  label: 'Pequeño',  hint: '82%' },
                { key: 'normal', label: 'Normal',   hint: '100%' },
                { key: 'large',  label: 'Grande',   hint: '122%' },
              ] as const).map(({ key, label, hint }) => (
                <button
                  key={key}
                  onClick={() => { setCfg(prev => ({ ...prev, escala_fuente: key })); setSaved(false) }}
                  className="flex-1 py-2.5 rounded-xl text-sm font-semibold border-2 transition-all flex flex-col items-center gap-0.5"
                  style={{
                    borderColor: cfg.escala_fuente === key ? 'oklch(48% 0.12 155)' : 'oklch(90% 0.008 75)',
                    background:  cfg.escala_fuente === key ? 'oklch(96% 0.025 155)' : 'transparent',
                    color:       cfg.escala_fuente === key ? 'oklch(35% 0.10 155)' : 'oklch(58% 0.01 60)',
                  }}
                >
                  <span>{label}</span>
                  <span style={{ fontSize: 9, opacity: 0.6, fontWeight: 400 }}>{hint}</span>
                </button>
              ))}
            </div>
            <p className="text-warm-400 mt-1.5" style={{ fontSize: 10.5 }}>
              Si el ticket sale muy pequeño, seleccioná <strong>Grande</strong>. Funciona mejor en Chrome.
            </p>
          </div>

        </div>
      </div>

      {/* Preview */}
      <div className="bg-white border border-warm-200 rounded-2xl overflow-hidden">
        <div className="px-4 pt-4 pb-3 border-b border-warm-100">
          <p className="text-warm-500" style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', textTransform: 'uppercase', margin: 0 }}>
            Vista previa del encabezado
          </p>
        </div>
        <div className="p-4">
          <div
            style={{
              fontFamily: '"Courier New", Courier, monospace',
              fontSize: 11,
              lineHeight: 1.5,
              background: '#fff',
              border: '1px dashed #ccc',
              borderRadius: 8,
              padding: '12px 16px',
              textAlign: 'center',
              color: '#000',
            }}
          >
            {cfg.logo_url && (
              <img src={cfg.logo_url} alt="" style={{ maxHeight: 48, maxWidth: 120, objectFit: 'contain', display: 'block', margin: '0 auto 6px' }} />
            )}
            <div style={{ fontWeight: 'bold', fontSize: 14, letterSpacing: 2 }}>
              {cfg.nombre_negocio || 'NOMBRE DEL NEGOCIO'}
            </div>
            {cfg.nit && <div style={{ fontSize: 10 }}>NIT: {cfg.nit}</div>}
            {cfg.telefono && <div style={{ fontSize: 10 }}>Tel: {cfg.telefono}</div>}
            {cfg.direccion && <div style={{ fontSize: 10 }}>{cfg.direccion}</div>}
            <div style={{ borderBottom: '1px dashed #000', margin: '6px 0' }} />
            <div style={{ fontSize: 9, color: '#555' }}>Documento de Ingreso — NO reemplaza la factura</div>
          </div>
        </div>
      </div>

      {/* Save button */}
      <button
        onClick={handleSave}
        disabled={saving || !dirty}
        className="w-full flex items-center justify-center gap-2 py-3.5 rounded-2xl text-sm font-semibold text-white disabled:opacity-40 transition-all"
        style={{ background: saved ? 'oklch(48% 0.12 155)' : 'oklch(38% 0.10 155)' }}
      >
        {saving
          ? <><Loader2 size={16} className="animate-spin" /> Guardando...</>
          : saved
            ? <>✓ Guardado</>
            : <><Save size={15} /> Guardar cambios</>}
      </button>
    </div>
  )
}
