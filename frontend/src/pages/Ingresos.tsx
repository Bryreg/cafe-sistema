import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useEmbedded } from '../contexts/PanelContext'
import api from '../api/client'
import { conMiles, soloDigitos } from '../utils/plata'
import {
  ArrowLeft, ChevronDown, ChevronRight, Search, Plus, X,
  Check, Trash2, Croissant, Box, Upload, ScanLine, Loader2, AlertTriangle,
} from 'lucide-react'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Producto {
  id: number
  nombre: string
  categoria: string
  unidad_medida: string
  contenido_por_empaque?: number | null
}

// Productos a granel: se registran en gr/ml, nunca en botellas o frascos.
const esGranel = (u: string) => ['gr', 'g', 'gramos', 'ml'].includes((u || '').toLowerCase())

// Espejo EXACTO del guard anti-unidades del backend: _MAX_EMPAQUES_PLAUSIBLE
// (backend/app/services/factura_ocr.py) y el guard estricto `cantidad < 50` de
// services/facturas.py. La comparación es ESTRICTA (<), igual que allá.
// SYNC: si cambia el umbral en el backend, cambiarlo acá (y viceversa).
const MAX_EMPAQUES_PLAUSIBLE = 50

interface ProveedorHistorial {
  proveedor: string
  frecuencia: number
  total_gastado: number
  ultima: string | null
}

interface ItemForm {
  producto_id: number     // 0 = renglón del escaneo SIN producto: pendiente de asignar
  nombre: string
  unidad_medida: string
  categoria: string
  cantidad: string        // si en_empaques: nº de empaques; si no: gr/ml o unidades
  en_empaques: boolean    // el backend convierte empaques → gr/ml (× contenido_por_empaque)
  contenido_por_empaque?: number | null   // solo para mostrar la equivalencia
  numero_lote: string
  fecha_vencimiento: string
  // Solo lo llena el escaneo (ya ajustado a la unidad final del inventario);
  // la carga manual lo deja en null, igual que siempre.
  precio_unitario?: number | null
  // Fase 2 (aliases): texto TAL CUAL del renglón de la factura. Viaja en el
  // payload para que el registro entrene el alias descripcion→producto.
  descripcion_original?: string | null
  // Cómo se resolvió el producto: 'alias' | 'ia' | 'fuzzy' (lo sugirió el
  // escaneo) o 'correccion' (la barista lo asignó/cambió acá).
  origen_match?: string | null
  // Solo renglones PENDIENTES del escaneo (producto_id=0): cantidad y unidad
  // TAL CUAL la factura (kg/lt/caja). Al asignar producto, el SERVER convierte
  // (POST /facturas/convertir-cantidad) — nunca se precarga la cifra cruda
  // como si ya estuviera en la unidad del inventario.
  cantidad_factura?: number | null
  unidad_factura?: string | null
}

// Respuesta de POST /facturas/analizar-foto (extracción + mapeo al catálogo).
interface ScanItem {
  descripcion: string
  cantidad_factura: number | null   // cantidad TAL CUAL la factura (sin convertir)
  unidad_factura: string | null
  producto_id: number | null
  producto_nombre: string | null
  unidad_medida: string | null
  categoria: string | null
  contenido_por_empaque: number | null
  cantidad: number | null
  en_empaques: boolean
  precio_unitario: number | null
  numero_lote: string | null
  fecha_vencimiento: string | null
  advertencia: string | null
  origen_match: 'alias' | 'ia' | 'fuzzy' | null
}
interface ScanResult {
  proveedor: string | null
  numero_factura: string | null
  fecha_factura: string | null
  valor_total: number | null
  tipo_pago: string | null
  items: ScanItem[]
  advertencias: string[]
}

// Hora LOCAL: toISOString es UTC y despues de las 19:00 Colombia devuelve manana.
function hoy() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function fmt(n: number) { return '$' + n.toLocaleString('es-CO') }

function daysAgo(iso: string | null): string {
  if (!iso) return 'nunca'
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000)
  if (d === 0) return 'hoy'
  if (d === 1) return 'ayer'
  return `hace ${d} días`
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function Ingresos() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const embedded = useEmbedded()

  // Form
  const [proveedor, setProveedor]         = useState('')
  const [fechaRecibido, setFechaRecibido] = useState(hoy())
  const [tipoPago, setTipoPago]           = useState<'contado'|'credito'|'transferencia'>('contado')
  const [valorTotal, setValorTotal]       = useState('')
  const [numeroFactura, setNumeroFactura] = useState('')
  const [imagen, setImagen]               = useState<File | null>(null)
  const [preview, setPreview]             = useState<string | null>(null)
  const fileRef                           = useRef<HTMLInputElement>(null)
  const [items, setItems]                 = useState<ItemForm[]>([])

  // Escaneo de factura (foto → Claude → prefill del form)
  const scanRef                             = useRef<HTMLInputElement>(null)
  const [escaneando, setEscaneando]         = useState(false)
  const [scanWarnings, setScanWarnings]     = useState<string[]>([])

  // Proveedor picker
  const [showPickerProv, setShowPickerProv] = useState(false)
  const [queryProv, setQueryProv]           = useState('')
  const [historialProv, setHistorialProv]   = useState<ProveedorHistorial[]>([])

  // Quick-add
  const [showQuickAdd, setShowQuickAdd]   = useState(false)
  const [addQuery, setAddQuery]           = useState('')
  const [addProducto, setAddProducto]     = useState<Producto | null>(null)
  const [addCantidad, setAddCantidad]     = useState('')   // gr/ml o unidades directas
  const [addEmpaques, setAddEmpaques]     = useState('')   // nº de empaques (granel con cpe)
  const [addLote, setAddLote]             = useState('')
  const [addVence, setAddVence]           = useState('')

  // Al cambiar de producto dentro del quick-add, limpiar cantidad y empaques: sin
  // esto un valor grande auto-calculado quedaba pegado al siguiente producto.
  useEffect(() => { setAddCantidad(''); setAddEmpaques('') }, [addProducto?.id])

  // Data
  const [productos, setProductos] = useState<Producto[]>([])

  // Status
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')
  const [exito, setExito]   = useState(false)
  // Flujo del día en caja (venta efectivo + ingresos - salidas): si un pago de
  // contado lo supera, la plata va a salir del sobre separado — avisar ANTES.
  const [flujoCaja, setFlujoCaja] = useState<number | null>(null)

  useEffect(() => {
    api.get('/inventario/productos').then(r => setProductos(r.data))
    if (user?.tienda_id) {
      api.get(`/facturas/proveedores/${user.tienda_id}`)
        .then(r => setHistorialProv(r.data))
        .catch(() => {})
      api.get(`/caja/activo/${user.tienda_id}`)
        .then(r => {
          const t = r.data
          setFlujoCaja(t ? (t.efectivo_esperado_actual ?? 0) - (t.base_real ?? 0) : null)
        })
        .catch(() => setFlujoCaja(null))
    }
  }, [user?.tienda_id])

  // ── Foto factura ─────────────────────────────────────────────────────────
  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (preview) URL.revokeObjectURL(preview)
    setImagen(f)
    setPreview(URL.createObjectURL(f))
  }
  const quitarFoto = () => {
    if (preview) URL.revokeObjectURL(preview)
    setImagen(null); setPreview(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  // ── Escaneo: foto → extracción → prefill ──────────────────────────────────
  const aplicarExtraccion = (d: ScanResult) => {
    const warns: string[] = [...(d.advertencias || [])]
    if (d.proveedor) setProveedor(d.proveedor)
    if (d.numero_factura) setNumeroFactura(d.numero_factura)
    // La fecha impresa en la factura NO es la fecha de recibido (crédito, entregas
    // tardías): solo se usa si coincide con hoy; si no, se avisa y queda hoy.
    if (d.fecha_factura && d.fecha_factura !== hoy()) {
      warns.push(`La factura tiene fecha ${d.fecha_factura} — dejé "Fecha recibido" en hoy; cambiala solo si la mercancía llegó ese día.`)
    }
    if (d.valor_total != null && d.valor_total > 0) setValorTotal(String(Math.round(d.valor_total)))
    if (d.tipo_pago === 'contado' || d.tipo_pago === 'credito' || d.tipo_pago === 'transferencia') {
      setTipoPago(d.tipo_pago)
    }
    const nuevos: ItemForm[] = []
    for (const it of d.items || []) {
      // Renglón CON cantidad leída pero SIN producto: entra al form con el
      // selector de producto (en vez de desaparecer al banner). Al elegirlo y
      // guardar, la corrección entrena un alias proveedor→producto.
      if (!it.producto_id && it.cantidad_factura != null && it.cantidad_factura > 0) {
        nuevos.push({
          producto_id:       0,
          nombre:            it.descripcion,
          unidad_medida:     '',
          categoria:         '',
          // SIN precarga cruda: "2 KG" no son "2 gr" ni "2 empaques". La
          // cantidad queda vacía hasta asignar producto — ahí el server
          // convierte la unidad de la factura (regla de oro: nunca adivinar).
          cantidad:          '',
          en_empaques:       false,
          contenido_por_empaque: null,
          numero_lote:       it.numero_lote || '',
          fecha_vencimiento: it.fecha_vencimiento || '',
          precio_unitario:   null,
          descripcion_original: it.descripcion,
          origen_match:      null,
          cantidad_factura:  it.cantidad_factura,
          unidad_factura:    it.unidad_factura,
        })
        continue
      }
      if (it.advertencia) warns.push(`${it.producto_nombre || it.descripcion}: ${it.advertencia}`)
      // Solo entran al form los items con producto identificado Y cantidad
      // convertida sin dudas; el resto queda en advertencias para carga manual.
      if (!it.producto_id || it.cantidad == null || it.cantidad <= 0) continue
      nuevos.push({
        producto_id:       it.producto_id,
        nombre:            it.producto_nombre || it.descripcion,
        unidad_medida:     it.unidad_medida || '',
        categoria:         it.categoria || '',
        cantidad:          String(it.cantidad),
        en_empaques:       !!it.en_empaques,
        contenido_por_empaque: it.contenido_por_empaque ?? null,
        numero_lote:       it.numero_lote || '',
        fecha_vencimiento: it.fecha_vencimiento || '',
        precio_unitario:   it.precio_unitario ?? null,
        descripcion_original: it.descripcion,
        origen_match:      it.origen_match ?? null,
      })
    }
    setPickQuery({})
    setCambiandoIdx(null)
    if (nuevos.length > 0) setItems(nuevos)
    else warns.push('No pude armar ningún producto desde la foto — agregalos manual.')
    setScanWarnings(warns)
  }

  const escanearFactura = async (f: File) => {
    if (!user?.tienda_id) return
    if (items.length > 0 &&
        !window.confirm('El escaneo va a reemplazar los productos que ya agregaste. ¿Seguir?')) return
    setError(''); setScanWarnings([]); setEscaneando(true)
    // La misma foto queda adjunta a la factura que se va a registrar.
    if (preview) URL.revokeObjectURL(preview)
    setImagen(f)
    setPreview(URL.createObjectURL(f))
    const fd = new FormData()
    fd.append('tienda_id', String(user.tienda_id))
    fd.append('imagen', f)
    try {
      const r = await api.post<ScanResult>('/facturas/analizar-foto', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000,
      })
      aplicarExtraccion(r.data)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo leer la factura — llenala manual.')
    } finally {
      setEscaneando(false)
      if (scanRef.current) scanRef.current.value = ''
    }
  }

  const onScanFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (f) escanearFactura(f)
  }

  // ── Abrir quick-add ───────────────────────────────────────────────────────
  const openQuickAdd = () => {
    setAddQuery(''); setAddProducto(null); setAddCantidad(''); setAddEmpaques('')
    setAddLote(''); setAddVence('')
    setShowQuickAdd(true)
  }

  // ── Confirmar adición de ítem ──────────────────────────────────────────────
  const confirmarAdd = () => {
    if (!addProducto) return
    const cpe = addProducto.contenido_por_empaque || 0
    const granel = esGranel(addProducto.unidad_medida)
    // Camino EMPAQUES: la barista contó empaques (botellas, bolsas, tortas).
    // Se manda el nº de empaques + en_empaques=true; el backend convierte a la
    // unidad del inventario (× cpe, cualquier unidad) y NO aplica el guard.
    // No hay conversión en el cliente (evita valores fantasma).
    const usaEmpaques = cpe > 0 && Number(addEmpaques) > 0
    const cantidadStr = usaEmpaques ? addEmpaques : addCantidad
    if (!cantidadStr || Number(cantidadStr) <= 0) return

    // Guard anti-unidades SOLO en el camino de gramos directos: un granel con
    // valor diminuto = casi seguro contaron empaques (fuga #1 de la auditoría).
    if (!usaEmpaques && granel && Number(addCantidad) < MAX_EMPAQUES_PLAUSIBLE) {
      if (cpe > 0) {
        alert(`${addProducto.nombre} se registra en ${addProducto.unidad_medida}. ` +
          `Si recibiste empaques, usá el campo "Empaques" (1 = ${cpe} ${addProducto.unidad_medida}).`)
        return
      }
      if (!window.confirm(`¿Seguro que son ${addCantidad} ${addProducto.unidad_medida}? ` +
        'Este producto se registra en gramos totales, no en botellas/bolsas.')) return
    }
    setItems(prev => [...prev, {
      producto_id:       addProducto.id,
      nombre:            addProducto.nombre,
      unidad_medida:     addProducto.unidad_medida,
      categoria:         addProducto.categoria,
      cantidad:          cantidadStr,
      en_empaques:       usaEmpaques,
      contenido_por_empaque: cpe || null,
      numero_lote:       addLote,
      fecha_vencimiento: addVence,
    }])
    setShowQuickAdd(false)
  }

  const quitarItem = (idx: number) => {
    setItems(prev => prev.filter((_, i) => i !== idx))
    setPickQuery({})
    setCambiandoIdx(null)   // los índices corren: cerrar cualquier cambio abierto
  }

  // ── Asignar/cambiar producto de un renglón (entrena alias) ────────────────
  // Búsqueda por renglón (keyed por índice del item), y renglón matcheado con
  // el cambiador abierto (F1: un alias mal enseñado solo se corrige si el
  // producto asignado se puede CAMBIAR — si no, el error queda invisible y
  // permanente).
  const [pickQuery, setPickQuery] = useState<Record<number, string>>({})
  const [cambiandoIdx, setCambiandoIdx] = useState<number | null>(null)

  // Lo CRUDO de la factura, para advertencias legibles ("la factura dice: 2 KG").
  const crudoFactura = (it: ItemForm) =>
    `${it.cantidad_factura}${it.unidad_factura ? ' ' + it.unidad_factura : ''}`

  const asignarProducto = async (idx: number, p: Producto) => {
    const item = items[idx]

    // ── Renglón PENDIENTE del escaneo (producto_id=0): la cantidad viene en la
    // unidad de la FACTURA (kg/lt/caja). La conversión la decide el SERVER —
    // la misma _convertir_cantidad de los renglones matcheados. Si no hay
    // conversión segura (o la red falla), la cantidad queda VACÍA con
    // advertencia y la barista la digita: nunca se adivina.
    if (item && item.producto_id === 0 && item.cantidad_factura != null) {
      let cantidad = ''
      let enEmpaques = false
      let advertencia: string | null = null
      try {
        const r = await api.post('/facturas/convertir-cantidad', {
          producto_id: p.id,
          cantidad:    item.cantidad_factura,
          unidad:      item.unidad_factura ?? null,
        })
        if (r.data.cantidad != null && r.data.cantidad > 0) {
          cantidad = String(r.data.cantidad)
          enEmpaques = !!r.data.en_empaques
          advertencia = r.data.advertencia ?? null
        } else {
          advertencia = r.data.advertencia || `ingresá la cantidad en ${p.unidad_medida}`
        }
      } catch {
        // Red/servidor caído: mismo comportamiento conservador.
        advertencia = `no se pudo convertir — ingresá la cantidad en ${p.unidad_medida}`
      }
      setItems(prev => prev.map((it, i) => (i !== idx ? it : {
        ...it,
        producto_id:  p.id,
        nombre:       p.nombre,
        unidad_medida: p.unidad_medida,
        categoria:    p.categoria,
        contenido_por_empaque: p.contenido_por_empaque || null,
        cantidad,
        en_empaques:  enEmpaques,
        // Metadata local: un humano lo asignó acá (ver nota del camino de abajo).
        origen_match: 'correccion',
      })))
      setCambiandoIdx(null)
      setPickQuery(q => ({ ...q, [idx]: '' }))
      if (advertencia) {
        setScanWarnings(w => [...w,
          `${p.nombre}: la factura dice ${crudoFactura(item)} — ${advertencia}`])
      }
      return
    }

    // ── "Cambiar" de un renglón YA matcheado: la cantidad ya está en la unidad
    // del inventario (la convirtió el server al escanear) — solo cambia la
    // identidad del producto.
    const cpe = p.contenido_por_empaque || 0
    const granel = esGranel(p.unidad_medida)
    setItems(prev => prev.map((it, i) => {
      if (i !== idx) return it
      const cant = Number(it.cantidad) || 0
      // Espejo de la heurística del backend: pocas "unidades" de un producto
      // con empaque configurado casi seguro son empaques sellados (el backend
      // multiplica por contenido_por_empaque al registrar). Estricto (<),
      // igual que el guard del backend (ver MAX_EMPAQUES_PLAUSIBLE arriba).
      // Solo se AUTO-asume empaques en granel, donde "3" de un producto en gr es
      // inequívocamente 3 envases. En contables "3 und" es ambiguo (¿3 bolsas o 3
      // pulpas?) y acá hay un humano corrigiendo con la factura a la vista: dar
      // por hecho x10 en la acción de mayor confianza del flujo infla el stock en
      // silencio. Para contables queda apagado y la barista lo prende con el toggle.
      const enEmpaques = granel && cpe > 0 && cant > 0 && cant < MAX_EMPAQUES_PLAUSIBLE
      return {
        ...it,
        producto_id:  p.id,
        nombre:       p.nombre,
        unidad_medida: p.unidad_medida,
        categoria:    p.categoria,
        contenido_por_empaque: cpe || null,
        en_empaques:  enEmpaques,
        // Metadata local: un humano lo asignó/cambió acá. El backend NO le
        // cree a esta etiqueta para sobrescribir aliases (deriva server-side);
        // solo informa el origen cuando el alias es nuevo.
        origen_match: 'correccion',
      }
    }))
    setCambiandoIdx(null)
    setPickQuery(q => ({ ...q, [idx]: '' }))
    if (granel && !cpe) {
      setScanWarnings(w => [...w,
        `${p.nombre}: verificá la cantidad — este producto se registra en ${p.unidad_medida} totales, no en envases.`])
    }
  }

  const setCantidadItem = (idx: number, v: string) =>
    setItems(prev => prev.map((it, i) => (i === idx ? { ...it, cantidad: v } : it)))

  // precio_unitario SIEMPRE viaja por unidad de inventario: al escanear, el server
  // ya dividió el precio de la factura por el contenido del empaque. Si acá se
  // invierte la bandera hay que rebasarlo, o el costo unitario queda x cpe mal
  // (silencioso: el precio se muestra como chip read-only) y contamina el COGS.
  //   prender empaques  -> la cantidad pasa a ser empaques  -> precio /= cpe
  //   apagar empaques   -> la cantidad pasa a ser unidades  -> precio *= cpe
  const toggleEmpaquesItem = (idx: number) =>
    setItems(prev => prev.map((it, i) => {
      if (i !== idx) return it
      const cpe = it.contenido_por_empaque || 0
      const activando = !it.en_empaques
      const precio = it.precio_unitario
      return {
        ...it,
        en_empaques: activando,
        precio_unitario: precio != null && cpe > 0
          ? Math.round((activando ? precio / cpe : precio * cpe) * 10000) / 10000
          : precio,
      }
    }))

  const seleccionarProveedor = (p: string) => {
    setProveedor(p); setShowPickerProv(false); setQueryProv('')
  }

  // ── Guardar factura ────────────────────────────────────────────────────────
  const guardar = async () => {
    if (escaneando) return
    if (!proveedor.trim()) return setError('Selecciona o escribe el proveedor')
    if (!valorTotal || Number(valorTotal) <= 0) return setError('El valor total debe ser mayor a 0')
    if (items.length === 0) return setError('Agrega al menos un producto')
    for (const it of items) {
      if (it.producto_id === 0) {
        return setError(`Elegí el producto del inventario para "${it.nombre}" o quitá ese renglón`)
      }
      if (!it.cantidad || Number(it.cantidad) <= 0) return setError(`Cantidad inválida en ${it.nombre}`)
    }
    if (!user?.tienda_id) return
    setError(''); setSaving(true)

    const payload = {
      tienda_id:      user.tienda_id,
      proveedor:      proveedor.trim(),
      numero_factura: numeroFactura.trim() || null,
      numero_lote:    null,
      fecha_recibido: new Date(fechaRecibido + 'T00:00:00').toISOString(),
      valor_total:    Number(valorTotal),
      tipo_pago:      tipoPago,
      items: items.map(it => ({
        producto_id:      it.producto_id,
        cantidad:         Number(it.cantidad),
        en_empaques:      it.en_empaques,
        precio_unitario:  it.precio_unitario ?? null,
        numero_lote:      it.numero_lote || null,
        fecha_vencimiento: it.fecha_vencimiento
          ? new Date(it.fecha_vencimiento + 'T00:00:00').toISOString()
          : null,
        // Fase 2 (aliases): el texto original del renglón + cómo se resolvió.
        // Con esto el backend aprende el alias ("correccion" si lo asignó la
        // barista; confirmación sin cambios → "escaneo").
        descripcion_original: it.descripcion_original || null,
        origen_match:         it.origen_match || null,
      })),
    }

    const fd = new FormData()
    fd.append('data', JSON.stringify(payload))
    if (imagen) fd.append('imagen', imagen)

    try {
      await api.post('/facturas/', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      setExito(true)
      setProveedor(''); setFechaRecibido(hoy()); setTipoPago('contado')
      setValorTotal(''); setNumeroFactura('')
      if (preview) URL.revokeObjectURL(preview)
      setImagen(null); setPreview(null)
      if (fileRef.current) fileRef.current.value = ''
      setItems([])
      setScanWarnings([])
      setPickQuery({})
      setTimeout(() => setExito(false), 3000)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al guardar')
    } finally {
      setSaving(false)
    }
  }

  const filteredProv = historialProv.filter(p =>
    !queryProv || p.proveedor.toLowerCase().includes(queryProv.toLowerCase())
  )
  const suggestedProducts = productos.filter(p =>
    !items.some(i => i.producto_id === p.id) &&
    (!addQuery || p.nombre.toLowerCase().includes(addQuery.toLowerCase()))
  )

  // Para el contador del hero, los items en empaques aportan su magnitud convertida
  // (count × cpe), no el conteo crudo — así no mezcla "2 botellas" con gramos.
  const totalUnidades = items.reduce((s, i) =>
    s + (i.en_empaques ? Number(i.cantidad) * (i.contenido_por_empaque || 0) : Number(i.cantidad) || 0), 0)
  const canSave       = !!proveedor && !!valorTotal && Number(valorTotal) > 0 && items.length > 0

  return (
    <div className={embedded ? 'flex flex-col w-full' : 'min-h-screen bg-warm-50 flex flex-col'}>

      {/* ── Header con proveedor tappable ── */}
      <header className={`bg-white border-b border-warm-200 px-4 pb-3 sticky top-0 z-10 ${embedded ? 'pt-3' : 'header-safe'}`}>
        <div className="flex items-center gap-3 max-w-lg mx-auto">
          {!embedded && (
            <button
              onClick={() => navigate('/')}
              className="p-2 -ml-1 rounded-xl text-warm-400 hover:text-warm-700 hover:bg-warm-100 transition-colors"
            >
              <ArrowLeft size={18} />
            </button>
          )}
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-widest text-amber-600">
              Recibir mercancía
            </p>
            <button
              onClick={() => setShowPickerProv(true)}
              className="flex items-center gap-1.5 mt-0.5 max-w-full"
            >
              <span className={`text-sm font-bold leading-tight truncate ${proveedor ? 'text-warm-800' : 'text-warm-300'}`}>
                {proveedor || 'Seleccionar proveedor'}
              </span>
              <ChevronDown size={13} className="text-warm-400 shrink-0" />
            </button>
          </div>
          <span className="text-xs text-warm-400 font-mono shrink-0">
            {fechaRecibido.slice(5).replace('-', '/')}
          </span>
        </div>
      </header>

      {/* ── Proveedor picker overlay ──
          SIEMPRE fixed a pantalla completa (z alto): embebido en un panel angosto
          y bajo el notch no se podía seleccionar; full-screen garantiza el toque. */}
      {showPickerProv && (
        <div
          className="fixed inset-0 z-[70] flex flex-col"
          style={{ background: 'rgba(20,15,10,0.5)', backdropFilter: 'blur(2px)' }}
        >
          <div className="bg-white p-4 border-b border-warm-200" style={{ paddingTop: 'max(1rem, env(safe-area-inset-top))' }}>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-bold uppercase tracking-widest text-warm-400">Proveedor</p>
              <button onClick={() => { setShowPickerProv(false); setQueryProv('') }}
                className="p-1.5 rounded-lg text-warm-400 hover:bg-warm-100">
                <X size={16} />
              </button>
            </div>
            <div className="flex items-center gap-2 border-2 border-amber-500 rounded-xl px-3 py-2.5"
              style={{ boxShadow: '0 0 0 4px rgba(217,119,6,0.12)' }}>
              <Search size={14} className="text-amber-500 shrink-0" />
              <input
                value={queryProv}
                onChange={e => setQueryProv(e.target.value)}
                placeholder="Buscar o escribir proveedor…"
                className="flex-1 text-sm font-medium text-warm-800 bg-transparent outline-none placeholder:text-warm-300"
                autoFocus
              />
              {queryProv && (
                <button onClick={() => setQueryProv('')}><X size={12} className="text-warm-400" /></button>
              )}
            </div>
            {filteredProv.length > 0 && (
              <p className="text-[11px] text-warm-400 mt-2">
                {filteredProv.length} {filteredProv.length === 1 ? 'coincidencia' : 'coincidencias'}
              </p>
            )}
          </div>

          <div className="flex-1 bg-warm-50 overflow-auto">
            {filteredProv.map(p => (
              <button
                key={p.proveedor}
                onClick={() => seleccionarProveedor(p.proveedor)}
                className="w-full flex items-center gap-3 px-4 py-3 bg-white border-b border-warm-100 hover:bg-amber-50 text-left active:bg-amber-100 transition-colors"
              >
                <div className="w-8 h-8 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center text-sm font-bold font-mono shrink-0">
                  {p.proveedor[0].toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-warm-800 truncate">
                    <HighlightText text={p.proveedor} match={queryProv} />
                  </p>
                  <p className="text-[10px] text-warm-400 mt-0.5">
                    {p.frecuencia} {p.frecuencia === 1 ? 'factura' : 'facturas'} · última {daysAgo(p.ultima)}
                  </p>
                </div>
                <ChevronRight size={14} className="text-warm-300 shrink-0" />
              </button>
            ))}

            {queryProv && !filteredProv.some(p => p.proveedor.toLowerCase() === queryProv.toLowerCase()) && (
              <button
                onClick={() => seleccionarProveedor(queryProv.trim())}
                className="flex items-center justify-center gap-2 mx-4 my-3 px-4 py-3 border-2 border-dashed border-warm-200 rounded-2xl text-sm font-bold text-amber-600 w-[calc(100%-2rem)] hover:border-amber-400 hover:bg-amber-50 transition-colors"
              >
                <Plus size={14} /> Crear proveedor "{queryProv}"
              </button>
            )}

            {filteredProv.length === 0 && !queryProv && (
              <p className="text-sm text-warm-400 text-center py-10">
                Escribe el nombre del proveedor
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── Contenido scrollable ── */}
      <div className={`flex-1 ${embedded ? '' : 'overflow-auto pb-nav'}`}>
        <div className="max-w-lg mx-auto">

          {/* ── Hero: valor total ── */}
          <div className="bg-white border-b border-warm-100 px-4 py-3 flex items-center gap-4">
            <div className="flex-1">
              <p className="text-[9px] font-bold uppercase tracking-widest text-warm-400">Total factura</p>
              <div className="flex items-baseline gap-1 mt-1">
                <span className="text-lg font-bold text-warm-400">$</span>
                <input
                  type="text"
                  inputMode="numeric"
                  value={conMiles(valorTotal)}
                  onChange={e => setValorTotal(soloDigitos(e.target.value))}
                  placeholder="0"
                  className="text-2xl font-bold text-warm-800 bg-transparent outline-none w-full font-mono tracking-tight placeholder:text-warm-200"
                />
              </div>
              <p className="text-[10px] text-warm-400 mt-0.5">Solo el total · sin precio por producto</p>
            </div>
            {items.length > 0 && (
              <div className="text-right shrink-0">
                <p className="text-xl font-bold text-amber-600 font-mono">{totalUnidades}</p>
                <p className="text-[10px] text-warm-400">
                  {items.length} {items.length === 1 ? 'producto' : 'productos'}
                </p>
              </div>
            )}
          </div>

          {/* ── Header lista de productos ── */}
          <div className="flex items-center justify-between px-4 pt-4 pb-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-warm-400">
              Productos recibidos{items.length > 0 ? ` · ${items.length}` : ''}
            </p>
            {items.length > 0 && !showQuickAdd && (
              <button onClick={openQuickAdd} className="flex items-center gap-1 text-[11px] font-bold text-amber-600">
                <Plus size={12} /> Otro
              </button>
            )}
          </div>

          {/* ── Lista de ítems ── */}
          {items.length > 0 && (
            <div className="mx-4 bg-white border border-warm-100 rounded-2xl overflow-hidden">
              {items.map((it, idx) => it.producto_id === 0 ? (
                /* ── Renglón del escaneo SIN producto: elegirlo entrena un alias ── */
                <div key={`pendiente-${idx}`}
                  className={`px-3 py-2.5 bg-amber-50/60 ${idx < items.length - 1 ? 'border-b border-warm-100' : ''}`}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <AlertTriangle size={13} className="text-amber-500 shrink-0" />
                    <span className="flex-1 text-[13px] font-bold text-warm-800 truncate">{it.nombre}</span>
                    {/* Lo CRUDO de la factura (ej. "2 KG"): informativo — la
                        cantidad real se convierte al asignar el producto. */}
                    <span className="text-[13px] font-bold text-warm-600 font-mono shrink-0">{crudoFactura(it)}</span>
                    <button
                      onClick={() => quitarItem(idx)}
                      className="w-6 h-6 rounded-md flex items-center justify-center text-warm-300 hover:text-red-400 hover:bg-red-50 shrink-0 transition-colors"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  <p className="text-[11px] font-semibold text-amber-700 mb-1.5">
                    ¿Qué producto del inventario es? Elegilo y el sistema lo recuerda para la próxima.
                  </p>
                  <ProductoPicker
                    productos={productos}
                    query={pickQuery[idx] || ''}
                    onQuery={v => setPickQuery(q => ({ ...q, [idx]: v }))}
                    onPick={p => asignarProducto(idx, p)}
                  />
                </div>
              ) : (
                <div key={`${it.producto_id}-${idx}`}
                  className={`px-3 py-2.5 ${idx < items.length - 1 ? 'border-b border-warm-100' : ''}`}>
                  {/* Fila 1: nombre + cantidad + borrar */}
                  <div className="flex items-center gap-2 mb-2">
                    {it.numero_lote || it.fecha_vencimiento
                      ? <Croissant size={13} className="text-amber-500 shrink-0" />
                      : <Box size={13} className="text-warm-400 shrink-0" />
                    }
                    <span className="flex-1 text-[13px] font-bold text-warm-800 truncate">{it.nombre}</span>
                    {it.origen_match === 'correccion' || it.en_empaques ? (
                      /* Editable en dos casos:
                         - Recién asignado a mano: la cantidad vino cruda de la factura.
                         - en_empaques: la cantidad se va a MULTIPLICAR por el contenido
                           del empaque al registrar. En contables la unidad "und" es
                           ambigua (¿1 bolsa o 1 pulpa?), así que si el escáner asumió
                           empaques la barista tiene que poder desarmarlo con el toggle;
                           read-only entraría x10 sin manera de corregirlo. */
                      <span className="flex items-center gap-1 shrink-0">
                        <input
                          value={it.cantidad}
                          onChange={e => setCantidadItem(idx, e.target.value)}
                          inputMode="decimal"
                          className="w-16 px-1.5 py-1 border border-amber-300 rounded-md text-[13px] font-bold text-warm-700 font-mono text-right focus:outline-none focus:border-amber-500 bg-white"
                        />
                        {(it.contenido_por_empaque || 0) > 0 ? (
                          <button
                            onClick={() => toggleEmpaquesItem(idx)}
                            className={`px-1.5 py-1 rounded-md text-[10px] font-bold border transition-colors ${
                              it.en_empaques
                                ? 'bg-amber-100 border-amber-300 text-amber-700'
                                : 'bg-white border-warm-200 text-warm-400'}`}
                          >
                            {it.en_empaques ? 'emp.' : it.unidad_medida}
                          </button>
                        ) : (
                          <span className="text-[11px] font-semibold text-warm-500">{it.unidad_medida}</span>
                        )}
                      </span>
                    ) : (
                      <span className="text-[13px] font-bold text-warm-600 font-mono shrink-0 text-right">
                        {it.en_empaques
                          ? `${it.cantidad} emp. = ${Math.round(Number(it.cantidad) * (it.contenido_por_empaque || 0) * 100) / 100} ${it.unidad_medida}`
                          : `${it.cantidad} ${it.unidad_medida}`}
                      </span>
                    )}
                    {/* F1: TODO renglón permite CAMBIAR el producto asignado —
                        un match equivocado del escaneo que no se puede tocar
                        se convierte en alias malo permanente e invisible. */}
                    <button
                      onClick={() => {
                        setCambiandoIdx(cambiandoIdx === idx ? null : idx)
                        setPickQuery(q => ({ ...q, [idx]: '' }))
                      }}
                      className={`px-1.5 py-1 rounded-md text-[10px] font-bold shrink-0 transition-colors ${
                        cambiandoIdx === idx
                          ? 'bg-amber-100 text-amber-700'
                          : 'text-amber-600 hover:bg-amber-50'}`}
                    >
                      {cambiandoIdx === idx ? 'cancelar' : 'cambiar'}
                    </button>
                    <button
                      onClick={() => quitarItem(idx)}
                      className="w-6 h-6 rounded-md flex items-center justify-center text-warm-300 hover:text-red-400 hover:bg-red-50 shrink-0 transition-colors"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  {/* Cambiador de producto: mismo buscador que los renglones
                      pendientes. Elegir marca origen_match 'correccion'. */}
                  {cambiandoIdx === idx && (
                    <div className="mb-2">
                      <p className="text-[11px] font-semibold text-amber-700 mb-1.5">
                        ¿A qué producto va{it.descripcion_original ? ` "${it.descripcion_original}"` : ' este renglón'}?
                      </p>
                      <ProductoPicker
                        productos={productos}
                        query={pickQuery[idx] || ''}
                        onQuery={v => setPickQuery(q => ({ ...q, [idx]: v }))}
                        onPick={p => asignarProducto(idx, p)}
                      />
                    </div>
                  )}
                  {/* Equivalencia SIEMPRE que haya empaques: es el único lugar donde
                      se ve el total multiplicado que va a entrar al inventario. Antes
                      dependía de 'correccion' y las filas del escáner lo mostraban en
                      el span read-only; ahora esas filas son editables y sin esto el
                      x10 no se vería en ningún lado. */}
                  {it.en_empaques && (
                    <p className="text-[11px] font-semibold text-amber-700 mb-1.5">
                      {it.cantidad || 0} empaque{Number(it.cantidad) !== 1 ? 's' : ''} ={' '}
                      {Math.round(Number(it.cantidad) * (it.contenido_por_empaque || 0) * 100) / 100} {it.unidad_medida}
                    </p>
                  )}
                  {/* Fila 2: chips lote + vence + precio (escaneo) */}
                  {(it.numero_lote || it.fecha_vencimiento || it.precio_unitario != null) && (
                    <div className="grid grid-cols-2 gap-1.5">
                      {it.numero_lote && (
                        <FieldChip label="Lote" value={it.numero_lote} />
                      )}
                      {it.fecha_vencimiento && (
                        <FieldChip label="Vence" value={it.fecha_vencimiento.slice(5).replace('-', '/')} />
                      )}
                      {it.precio_unitario != null && (
                        <FieldChip label={`$/${it.unidad_medida}`} value={'$' + Number(it.precio_unitario).toLocaleString('es-CO')} />
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* ── Quick-add panel o botón dashed ── */}
          {showQuickAdd ? (
            <QuickAddPanel
              productos={suggestedProducts}
              addQuery={addQuery}     setAddQuery={setAddQuery}
              addProducto={addProducto} setAddProducto={setAddProducto}
              addCantidad={addCantidad} setAddCantidad={setAddCantidad}
              addEmpaques={addEmpaques} setAddEmpaques={setAddEmpaques}
              addLote={addLote}       setAddLote={setAddLote}
              addVence={addVence}     setAddVence={setAddVence}
              onCancel={() => setShowQuickAdd(false)}
              onConfirm={confirmarAdd}
            />
          ) : (
            <>
              {items.length === 0 && !escaneando && (
                <button
                  onClick={() => scanRef.current?.click()}
                  className="flex items-center justify-center gap-2 mx-4 mt-3 px-4 py-3.5 w-[calc(100%-2rem)] rounded-2xl text-[13px] font-bold text-white transition-colors active:scale-95"
                  style={{ background: 'oklch(55% 0.12 65)', boxShadow: '0 4px 12px oklch(55% 0.12 65 / 0.3)' }}
                >
                  <ScanLine size={15} />
                  Escanear factura con la cámara
                </button>
              )}
              {escaneando && (
                <div className="flex items-center justify-center gap-2.5 mx-4 mt-3 px-4 py-3.5 w-[calc(100%-2rem)] rounded-2xl bg-amber-50 border border-amber-200 text-[13px] font-semibold text-amber-700">
                  <Loader2 size={15} className="animate-spin" />
                  Leyendo la factura… esto tarda unos segundos
                </div>
              )}
              <button
                onClick={openQuickAdd}
                disabled={escaneando}
                className="flex items-center justify-center gap-2 mx-4 mt-3 px-4 py-3.5 w-[calc(100%-2rem)] border-2 border-dashed border-warm-200 rounded-2xl text-[13px] font-semibold text-warm-400 hover:border-amber-400 hover:bg-amber-50 hover:text-amber-600 transition-colors bg-white active:scale-95 disabled:opacity-40"
              >
                <Plus size={14} />
                Agregar {items.length === 0 ? 'producto manual' : 'otro producto'}
              </button>
            </>
          )}

          {/* ── Advertencias del escaneo ── */}
          {scanWarnings.length > 0 && (
            <div className="mx-4 mt-3 px-3 py-2.5 bg-amber-50 border border-amber-200 rounded-xl">
              <div className="flex items-center justify-between mb-1">
                <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-amber-700">
                  <AlertTriangle size={12} /> Revisá antes de registrar
                </p>
                <button onClick={() => setScanWarnings([])} className="p-1 text-amber-400 hover:text-amber-600">
                  <X size={13} />
                </button>
              </div>
              <ul className="space-y-1">
                {scanWarnings.map((w, i) => (
                  <li key={i} className="text-[12px] text-amber-800 leading-snug">• {w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* ── Foto de la factura ── */}
          <div className="mx-4 mt-4">
            <div className="bg-white rounded-2xl border border-warm-200 p-4 space-y-3">
              <p className="text-sm font-bold text-warm-700">
                Foto de la factura
                <span className="ml-1.5 text-xs font-normal text-warm-400">(opcional)</span>
              </p>
              <input ref={fileRef} type="file" accept="image/*" capture="environment" onChange={onFile} className="hidden" />
              <input ref={scanRef} type="file" accept="image/*" capture="environment" onChange={onScanFile} className="hidden" />
              {preview ? (
                <div className="space-y-2">
                  <div className="relative">
                    <img src={preview} alt="preview" className="w-full h-36 object-cover rounded-xl border-2 border-amber-300" />
                    <button
                      onClick={quitarFoto}
                      className="absolute top-2 right-2 bg-black/60 text-white rounded-full w-7 h-7 flex items-center justify-center"
                    >
                      <X size={13} />
                    </button>
                  </div>
                  {!escaneando && imagen && (
                    <button
                      onClick={() => escanearFactura(imagen)}
                      className="flex items-center justify-center gap-1.5 w-full py-2 rounded-xl border border-amber-300 text-[12px] font-bold text-amber-700 hover:bg-amber-50 transition-colors"
                    >
                      <ScanLine size={13} /> Escanear esta foto y llenar el form
                    </button>
                  )}
                </div>
              ) : (
                <button
                  onClick={() => fileRef.current?.click()}
                  className="w-full h-28 border-2 border-dashed border-warm-200 rounded-xl flex flex-col items-center justify-center gap-2 hover:border-amber-400 hover:bg-amber-50 transition-colors"
                >
                  <Upload size={22} className="text-warm-300" />
                  <span className="text-xs text-warm-400 font-medium">Toca para fotografiar la factura</span>
                </button>
              )}
            </div>
          </div>

          {/* ── Datos de la factura (a la vista, no ocultos) ── */}
          <div className="mx-4 mt-4">
            <div className="bg-white border border-warm-100 rounded-2xl overflow-hidden">
              <p className="px-4 py-3 text-[12px] font-semibold text-warm-500 border-b border-warm-100">
                Datos de la factura
              </p>
              <div className="px-4 pb-4 pt-3 space-y-3">
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wide text-warm-400">N° Factura</label>
                  <input value={numeroFactura} onChange={e => setNumeroFactura(e.target.value)}
                    placeholder="Ej: FV-001"
                    className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400" />
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wide text-warm-400">Tipo de pago</label>
                  <select value={tipoPago} onChange={e => setTipoPago(e.target.value as typeof tipoPago)}
                    className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400 bg-white">
                    <option value="contado">Contado (efectivo)</option>
                    <option value="credito">Crédito</option>
                    <option value="transferencia">Bancos</option>
                  </select>
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wide text-warm-400">Fecha recibido</label>
                  <input type="date" value={fechaRecibido} onChange={e => setFechaRecibido(e.target.value)}
                    className="w-full mt-1 border-2 border-warm-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-400" />
                </div>
              </div>
            </div>
          </div>

          {/* Pago contado que supera la venta del día: saldría del sobre separado */}
          {tipoPago === 'contado' && flujoCaja !== null && Number(valorTotal) > Math.max(0, flujoCaja) && (
            <div className="mx-4 mt-3 px-3 py-2.5 bg-amber-50 border border-amber-200 rounded-xl text-[13px] text-amber-800">
              <strong>Ojo:</strong> este pago de contado supera lo que hay de la venta de hoy en la
              registradora ({fmt(Math.max(0, Math.round(flujoCaja)))}) — lo que falte va a salir de la
              plata separada para consignar. Si se puede, mejor pagalo por Bancos (transferencia).
            </div>
          )}

          {/* Feedback */}
          {error && (
            <div className="mx-4 mt-3 px-3 py-2.5 bg-red-50 border border-red-100 rounded-xl text-sm text-red-600">
              {error}
            </div>
          )}
          {exito && (
            <div className="mx-4 mt-3 px-3 py-2.5 bg-green-50 border border-green-100 rounded-xl flex items-center gap-2 text-sm font-semibold text-green-700">
              <Check size={15} /> Mercancía recibida y registrada
            </div>
          )}

          <div className="h-6" />
        </div>
      </div>

      {/* ── CTA sticky encima del nav ──
          Embebido: `sticky` al pie del panel. Standalone: `fixed` sobre el bottom-nav. */}
      <div
        className={`${embedded ? 'sticky' : 'fixed'} left-0 right-0 px-4 pt-3 pb-2 z-20`}
        style={{
          bottom: embedded ? 0 : 'calc(4.5rem + env(safe-area-inset-bottom, 0px))',
          background: 'linear-gradient(to top, oklch(98% 0.006 75) 75%, transparent)',
        }}
      >
        <div className="max-w-lg mx-auto">
          <button
            onClick={guardar}
            disabled={saving || escaneando || !canSave}
            className="w-full py-4 rounded-2xl text-[15px] font-bold text-white disabled:opacity-40 transition-all flex items-center justify-center gap-2 active:scale-[0.98]"
            style={{
              background: 'oklch(35% 0.05 155)',
              boxShadow: canSave && !saving ? '0 6px 16px oklch(35% 0.05 155 / 0.25)' : 'none',
            }}
          >
            <Check size={16} strokeWidth={2.5} />
            {saving ? 'Guardando…' : valorTotal ? `Registrar · ${fmt(Number(valorTotal))}` : 'Registrar el recibo'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── FieldChip ───────────────────────────────────────────────────────────────

function FieldChip({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5 px-2 py-1.5 bg-warm-50 border border-warm-100 rounded-lg">
      <span className="text-[9px] font-bold uppercase tracking-wide text-warm-400">{label}</span>
      <span className="text-[12px] font-semibold text-warm-700 font-mono flex-1 text-right">{value}</span>
    </div>
  )
}

// ─── ProductoPicker ──────────────────────────────────────────────────────────
// Buscador compacto de producto: lo usan los renglones del escaneo SIN match y
// el "cambiar" de los renglones ya matcheados (ambos entrenan alias al elegir).

function ProductoPicker({ productos, query, onQuery, onPick }: {
  productos: Producto[]
  query: string
  onQuery: (v: string) => void
  onPick: (p: Producto) => void
}) {
  return (
    <>
      <div className="flex items-center gap-2 px-2.5 py-2 bg-white border border-amber-200 rounded-lg mb-1">
        <Search size={12} className="text-amber-500 shrink-0" />
        <input
          value={query}
          onChange={e => onQuery(e.target.value)}
          placeholder="Buscar producto…"
          className="flex-1 text-[13px] text-warm-700 bg-transparent outline-none placeholder:text-warm-300"
        />
      </div>
      <div className="max-h-32 overflow-y-auto rounded-lg border border-warm-100 divide-y divide-warm-50 bg-white">
        {productos
          .filter(p => !query || p.nombre.toLowerCase().includes(query.toLowerCase()))
          .slice(0, 5)
          .map(p => (
            <button key={p.id} onClick={() => onPick(p)}
              className="w-full text-left px-2.5 py-2 hover:bg-amber-50 transition-colors">
              <p className="text-[13px] font-semibold text-warm-700">{p.nombre}</p>
              <p className="text-[10px] text-warm-400">{p.categoria} · {p.unidad_medida}</p>
            </button>
          ))}
      </div>
    </>
  )
}

// ─── HighlightText ───────────────────────────────────────────────────────────

function HighlightText({ text, match }: { text: string; match: string }) {
  if (!match) return <>{text}</>
  const idx = text.toLowerCase().indexOf(match.toLowerCase())
  if (idx < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-amber-100 text-warm-800 rounded px-0.5 not-italic">
        {text.slice(idx, idx + match.length)}
      </mark>
      {text.slice(idx + match.length)}
    </>
  )
}

// ─── QuickAddPanel ───────────────────────────────────────────────────────────

interface QuickAddProps {
  productos: Producto[]
  addQuery: string;      setAddQuery: (v: string) => void
  addProducto: Producto | null; setAddProducto: (p: Producto | null) => void
  addCantidad: string;   setAddCantidad: (v: string) => void
  addEmpaques: string;   setAddEmpaques: (v: string) => void
  addLote: string;       setAddLote: (v: string) => void
  addVence: string;      setAddVence: (v: string) => void
  onCancel: () => void
  onConfirm: () => void
}

function QuickAddPanel({
  productos, addQuery, setAddQuery, addProducto, setAddProducto,
  addCantidad, setAddCantidad, addEmpaques, setAddEmpaques,
  addLote, setAddLote, addVence, setAddVence,
  onCancel, onConfirm,
}: QuickAddProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => { inputRef.current?.focus() }, [])
  // Empaques y cantidad son excluyentes: escribir en uno limpia el otro. NO se
  // convierte en el cliente — el backend recibe el nº de empaques + en_empaques.
  // Aplica a CUALQUIER unidad con empaque configurado (gr/ml y también und).
  const cpe = addProducto?.contenido_por_empaque || 0
  const conEmpaques = !!addProducto && cpe > 0
  const onEmpaques = (v: string) => { setAddEmpaques(v); if (v) setAddCantidad('') }
  const onCantidad = (v: string) => { setAddCantidad(v); if (v) setAddEmpaques('') }

  return (
    <div
      className="mx-4 mt-3 bg-white rounded-2xl p-3"
      style={{ border: '2px solid oklch(55% 0.12 155)', boxShadow: '0 8px 24px oklch(35% 0.05 155 / 0.15)' }}
    >
      <p className="text-[10px] font-bold uppercase tracking-widest mb-2.5" style={{ color: 'oklch(35% 0.05 155)' }}>
        Nuevo producto
      </p>

      {!addProducto ? (
        <>
          {/* Buscador */}
          <div className="flex items-center gap-2 px-3 py-2.5 bg-warm-50 border border-warm-200 rounded-xl mb-2">
            <Search size={13} className="text-warm-400 shrink-0" />
            <input
              ref={inputRef}
              value={addQuery}
              onChange={e => setAddQuery(e.target.value)}
              placeholder="Buscar producto…"
              className="flex-1 text-[13px] text-warm-700 bg-transparent outline-none placeholder:text-warm-300"
            />
          </div>
          {/* Lista */}
          <div className="max-h-40 overflow-y-auto rounded-xl border border-warm-100 divide-y divide-warm-50">
            {productos.slice(0, 8).map(p => (
              <button key={p.id} onClick={() => { setAddProducto(p); setAddQuery('') }}
                className="w-full text-left px-3 py-2.5 hover:bg-amber-50 transition-colors">
                <p className="text-[13px] font-semibold text-warm-700">{p.nombre}</p>
                <p className="text-[10px] text-warm-400">{p.categoria} · {p.unidad_medida}</p>
              </button>
            ))}
            {productos.length === 0 && (
              <p className="text-[12px] text-warm-400 text-center py-4">Sin resultados</p>
            )}
          </div>
        </>
      ) : (
        <>
          {/* Producto seleccionado */}
          <div className="flex items-center gap-2 mb-3 px-3 py-2 bg-amber-50 rounded-xl border border-amber-200">
            <Croissant size={14} className="text-amber-500 shrink-0" />
            <span className="text-[13px] font-bold text-warm-800 flex-1 truncate">{addProducto.nombre}</span>
            <button onClick={() => setAddProducto(null)} className="text-warm-300 hover:text-warm-500">
              <X size={13} />
            </button>
          </div>
          {/* Campos */}
          <div className="grid grid-cols-2 gap-2 mb-2">
            {conEmpaques && (
              <CompactInput
                label={`Empaques (1 = ${cpe} ${addProducto.unidad_medida})`}
                value={addEmpaques} onChange={onEmpaques}
                type="number" placeholder="0"
              />
            )}
            <CompactInput
              label={`Cantidad (${addProducto.unidad_medida})`}
              value={addCantidad} onChange={onCantidad}
              type="number" placeholder="0"
            />
            <CompactInput label="Lote" value={addLote} onChange={setAddLote} placeholder="—" />
            <CompactInput label="Vence" value={addVence} onChange={setAddVence} type="date" placeholder="" />
          </div>
          {conEmpaques && Number(addEmpaques) > 0 && (
            <p className="text-[11px] font-semibold mb-2" style={{ color: 'oklch(35% 0.05 155)' }}>
              {addEmpaques} empaque{Number(addEmpaques) !== 1 ? 's' : ''} = {Math.round(Number(addEmpaques) * cpe)} {addProducto.unidad_medida} ✓
            </p>
          )}
          {/* Granel de presentación variable (sin empaque fijo): recordar SIEMPRE
              que se registra el PESO en gr/ml, no la cantidad de frascos/bolsas. */}
          {esGranel(addProducto.unidad_medida) && !conEmpaques && (
            <div className="mb-2 px-2.5 py-2 rounded-lg flex items-start gap-1.5"
              style={{ background: 'oklch(95% 0.045 70)', border: '1px solid oklch(85% 0.08 70)' }}>
              <span className="text-[13px]">⚠️</span>
              <p className="text-[11px] font-semibold" style={{ color: 'oklch(45% 0.12 65)' }}>
                Registrá el PESO en {addProducto.unidad_medida} (pesá el frasco/bolsa), no la cantidad de envases.
              </p>
            </div>
          )}
        </>
      )}

      <div className="flex gap-2 mt-3">
        <button onClick={onCancel}
          className="flex-1 py-2.5 border border-warm-200 rounded-xl text-[12px] font-semibold text-warm-500 hover:bg-warm-50 transition-colors">
          Cancelar
        </button>
        <button onClick={onConfirm}
          disabled={!addProducto || (!addCantidad && !addEmpaques)}
          className="flex-[2] py-2.5 rounded-xl text-[12px] font-bold text-white disabled:opacity-40"
          style={{ background: 'oklch(35% 0.05 155)' }}>
          Agregar a la factura
        </button>
      </div>
    </div>
  )
}

// ─── CompactInput ────────────────────────────────────────────────────────────

function CompactInput({ label, value, onChange, type = 'text', placeholder, readOnly }: {
  label: string; value: string; onChange: (v: string) => void
  type?: string; placeholder?: string; readOnly?: boolean
}) {
  return (
    <div>
      <p className="text-[9px] font-bold uppercase tracking-wide text-warm-400 mb-1">{label}</p>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        readOnly={readOnly}
        className="w-full px-2.5 py-2 border border-warm-200 rounded-lg text-[13px] font-semibold text-warm-700 font-mono focus:outline-none focus:border-amber-400 bg-white"
      />
    </div>
  )
}
