import { Fragment, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useTurno } from '../contexts/TurnoContext'
import api from '../api/client'
import { CheckCircle2, Circle, ArrowLeft, ArrowRight, AlertTriangle, ClipboardCheck, Save, X } from 'lucide-react'
import { dark } from '../constants/darkTheme'
import NivelEnvase from './NivelEnvase'
import { evaluarExpresion, limpiarExpresion } from '../utils/calculo'
import { abreBloque, ordenarPorRecorrido } from '../utils/ordenConteo'

/** Valor numérico de una casilla que puede contener una expresión (+2500+1000). */
const valorDe = (raw: string | undefined): number | null => {
  if (raw === undefined || raw === '') return null
  return evaluarExpresion(raw) ?? (Number(raw) || 0)
}

/** Al dar Enter (o salir de la casilla) la expresión se convierte en su resultado. */
const resolver = (raw: string): string => {
  const v = evaluarExpresion(raw)
  return v === null ? raw : String(v)
}

interface InvItem {
  producto_id: number
  producto_nombre: string
  unidad_medida: string
  stock_actual: number
  categoria?: string
  fraccionable?: boolean
  envase?: 'bolsa' | 'botella' | null
  /** Gramos por unidad sellada (bolsa de café 2500). Activa el conteo en gramos. */
  contenido_por_unidad?: number | null
  /** Posición en el recorrido físico del local (ver utils/ordenConteo). */
  orden_conteo?: number | null
}

/** Conteo en GRAMOS para fraccionables con contenido conocido: bolsas cerradas ×
 *  contenido + gramos pesados de la abierta (gramera). El total viaja en gramos.
 *  CONTROLADO por el padre (para poder guardar/restaurar el borrador) y las
 *  casillas aceptan sumas/restas: "+2500+1000" se calcula al dar Enter. */
function ConteoGramos({ contenido, cerradas, abierta, onChange }: {
  contenido: number; cerradas: string; abierta: string
  onChange: (c: string, a: string, total: number) => void
}) {
  const tocado = cerradas !== '' || abierta !== ''
  const num = (s: string) => valorDe(s) ?? 0
  const total = num(cerradas) * contenido + num(abierta)

  const set = (c: string, a: string) =>
    onChange(c, a, num(c) * contenido + num(a))

  const inp: CSSProperties = {
    background: dark.surfaceAlt, border: `2px solid ${dark.border}`, color: dark.ink,
    fontFamily: '"JetBrains Mono", monospace',
  }
  return (
    <div className="flex items-end gap-3 flex-wrap">
      <div>
        <p className="text-[10px] mb-1" style={{ color: dark.inkSubtle }}>Bolsas cerradas (×{Math.round(contenido)} gr)</p>
        <input type="text" value={cerradas} placeholder="0"
          onChange={e => set(limpiarExpresion(e.target.value), abierta)}
          onKeyDown={e => { if (e.key === 'Enter') set(resolver(cerradas), abierta) }}
          onBlur={() => set(resolver(cerradas), abierta)}
          className="w-20 text-right rounded-lg px-2 py-1.5 text-sm font-bold outline-none" style={inp} />
      </div>
      <div>
        <p className="text-[10px] mb-1" style={{ color: dark.inkSubtle }}>Abierta — pesala (gr)</p>
        <input type="text" value={abierta} placeholder="0"
          onChange={e => set(cerradas, limpiarExpresion(e.target.value))}
          onKeyDown={e => { if (e.key === 'Enter') set(cerradas, resolver(abierta)) }}
          onBlur={() => set(cerradas, resolver(abierta))}
          className="w-28 text-right rounded-lg px-2 py-1.5 text-sm font-bold outline-none" style={inp} />
      </div>
      {tocado && (
        <p className="text-[13px] font-bold pb-1.5 font-mono tabular-nums" style={{ color: dark.green }}>
          = {Math.round(total).toLocaleString('es-CO')} gr
        </p>
      )}
    </div>
  )
}

interface Props {
  tipo: 'apertura' | 'cierre'
}

interface ReferenciaConteo {
  tipo_referencia: 'apertura' | 'cierre'
  fecha: string | null
  barista: string | null
  por_producto: Record<number, number>
}

export default function ConteoInventario({ tipo }: Props) {
  const { user } = useAuth()
  const { refresh } = useTurno()
  const navigate = useNavigate()
  const [items, setItems] = useState<InvItem[]>([])
  const [conteos, setConteos] = useState<Record<number, string>>({})
  const [gramos, setGramos] = useState<Record<number, { c: string; a: string }>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [isDirty, setIsDirty] = useState(false)
  const [error, setError] = useState('')
  const [borradorInfo, setBorradorInfo] = useState<string | null>(null)
  const [guardadoOk, setGuardadoOk] = useState(false)
  const draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Borrador persistente: sobrevive si salen a revisar otra pantalla ────────
  const draftKey = `conteo_borrador_${user?.tienda_id ?? 0}_${tipo}`

  const guardarBorrador = (feedback = false) => {
    try {
      localStorage.setItem(draftKey, JSON.stringify({ conteos, gramos, ts: Date.now() }))
      if (feedback) { setGuardadoOk(true); setTimeout(() => setGuardadoOk(false), 2500) }
    } catch { /* almacenamiento lleno: no bloquear el conteo */ }
  }

  const descartarBorrador = () => {
    localStorage.removeItem(draftKey)
    setConteos({}); setGramos({}); setIsDirty(false); setBorradorInfo(null)
  }

  // Restaurar al entrar (borradores de menos de 20h; uno viejo es de otro día)
  useEffect(() => {
    if (!user?.tienda_id) return
    try {
      const raw = localStorage.getItem(draftKey)
      if (!raw) return
      const d = JSON.parse(raw)
      if (!d.ts || Date.now() - d.ts > 20 * 3600 * 1000) { localStorage.removeItem(draftKey); return }
      if (d.conteos && Object.keys(d.conteos).length) {
        setConteos(d.conteos); setGramos(d.gramos ?? {}); setIsDirty(true)
        setBorradorInfo(new Date(d.ts).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }))
      }
    } catch { /* borrador corrupto: ignorar */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.tienda_id, tipo])

  // Autoguardado silencioso (respaldo del boton "Guardar cambios")
  useEffect(() => {
    if (!isDirty) return
    if (draftTimer.current) clearTimeout(draftTimer.current)
    draftTimer.current = setTimeout(() => guardarBorrador(false), 800)
    return () => { if (draftTimer.current) clearTimeout(draftTimer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conteos, gramos, isDirty])

  const [searchParams] = useSearchParams()
  const isKioskClose = searchParams.get('kiosk') === '1'
  const isApertura = tipo === 'apertura'
  const paso = isApertura ? 'Paso 2 de 3' : 'Conteo de cierre'
  const titulo = isApertura ? 'Conteo de apertura' : 'Conteo de cierre'
  const subtitulo = isApertura
    ? 'La referencia es el cierre de anoche: si nada pasó de noche, debería coincidir. Tocá "Coincide" o registrá lo que pesaste.'
    : 'La referencia es la apertura de hoy. "Coincide" solo para lo que no se movió — lo demás pesalo o contalo.'
  const ctaLabel = isApertura ? 'Confirmar conteo — seguir al cuadre de caja' : 'Confirmar conteo de cierre'
  const backPath = isApertura ? '/gestion-turno' : '/gestion-turno'
  // Apertura: baristas → conteo → cuadre inicial (efectivo del día anterior, sin foto).
  // Cierre: el conteo es INDEPENDIENTE del cuadre — se hace en PC y vuelve a gestión;
  // el cuadre con foto y el cierre del turno se hacen desde el celular (Salida).
  const nextPath = isApertura ? '/cuadre-inicial' : (isKioskClose ? '/salida-efectivo' : '/gestion-turno')

  // Referencia = el conteo inmediatamente anterior (apertura ← último cierre;
  // cierre ← apertura de hoy). El stock del SISTEMA no se muestra: conteo a
  // ciegas — la comparación contra el sistema la hace el backend al registrar.
  const [referencia, setReferencia] = useState<ReferenciaConteo | null>(null)

  useEffect(() => {
    if (!user?.tienda_id) return
    Promise.all([
      api.get(`/inventario/tienda/${user.tienda_id}`),
      api.get(`/conteos/referencia/${user.tienda_id}`, { params: { tipo } }).catch(() => null),
    ])
      .then(([inv, ref]) => { setItems(inv.data); if (ref) setReferencia(ref.data) })
      .finally(() => setLoading(false))
  }, [user?.tienda_id, tipo])

  // La pantalla sigue el RECORRIDO físico con que se cuenta el local, no el
  // orden en que la base devuelve las filas. El backend ya manda este mismo
  // orden en el ORDER BY, pero ordenar acá lo deja explícito y sobrevive a que
  // otro consumidor del endpoint pida otro orden mañana.
  const ordenados = useMemo(
    () => ordenarPorRecorrido(items, i => i.producto_nombre),
    [items],
  )

  const refDe = (pid: number): number | null => {
    const v = referencia?.por_producto?.[pid]
    return v === undefined ? null : v
  }
  const refLabel = tipo === 'apertura' ? 'Cierre anterior' : 'Apertura de hoy'

  const coincidir = (item: InvItem) => {
    const v = refDe(item.producto_id)
    if (v === null) return
    setConteos(prev => ({ ...prev, [item.producto_id]: String(v) }))
    if (item.fraccionable && (item.contenido_por_unidad ?? 0) > 0) {
      // El subcomponente de gramos es controlado: reflejar la referencia como "abierta"
      setGramos(prev => ({ ...prev, [item.producto_id]: { c: '', a: String(v) } }))
    }
    setIsDirty(true)
  }

  const getVal  = (id: number, ref: number) => {
    const v = valorDe(conteos[id])
    return v === null ? ref : v
  }
  const getDiff = (id: number, ref: number) => getVal(id, ref) - ref


  const confirmar = async () => {
    // Guard de magnitud (fuga #1 de la auditoría): producto en gramos con la
    // referencia en miles y un valor diminuto = casi seguro contaron unidades
    // (tarros/botellas) en vez de pesar. Confirmar antes de registrar.
    const sospechosos = items.filter(i => {
      const v = valorDe(conteos[i.producto_id]); const r = refDe(i.producto_id)
      return ['gr', 'g', 'gramos', 'ml'].includes((i.unidad_medida || '').toLowerCase())
        && v !== null && v > 0 && v < 20 && r !== null && r >= 500
    })
    if (sospechosos.length > 0) {
      const lista = sospechosos.map(i =>
        `· ${i.producto_nombre}: pusiste ${valorDe(conteos[i.producto_id])} y la referencia es ${refDe(i.producto_id)} ${i.unidad_medida}`
      ).join('\n')
      if (!window.confirm(`Estos productos se cuentan en GRAMOS y el valor parece de unidades:\n\n${lista}\n\n¿Registrar así de todas formas?`)) return
    }
    setSaving(true); setError('')
    try {
      // cantidad_real NUNCA cae al stock del sistema: canConfirm garantiza que todo
      // está registrado; si algo faltara, cae a la referencia física (0 como último caso).
      const itemsList = items.map(i => ({
        producto_id: i.producto_id,
        cantidad_real: valorDe(conteos[i.producto_id]) ?? refDe(i.producto_id) ?? 0,
      }))
      await api.post('/conteos/', { tienda_id: user?.tienda_id, tipo, items: itemsList })
      localStorage.removeItem(draftKey)   // conteo confirmado: el borrador ya cumplió
      await refresh()
      navigate(nextPath)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Error al registrar conteo')
    } finally {
      setSaving(false)
    }
  }

  const registrados = items.filter(i => valorDe(conteos[i.producto_id]) !== null).length
  // Novedad nocturna (solo apertura): lo contado difiere del cierre anterior
  const novedades = tipo === 'apertura'
    ? items.filter(i => {
        const v = valorDe(conteos[i.producto_id]); const r = refDe(i.producto_id)
        return v !== null && r !== null && Math.abs(v - r) > 0.001
      }).length
    : 0
  const progreso = items.length > 0 ? Math.round((registrados / items.length) * 100) : 0

  // TODOS los productos deben registrarse (pesados, contados o con "Coincide") —
  // sin valor del sistema a la vista no hay relleno implícito posible.
  const canConfirm = !saving && items.length > 0 && registrados === items.length

  return (
    <div className="min-h-screen flex flex-col" style={{ background: dark.bg }}>

      {/* Header */}
      <header className="flex items-center gap-3 px-4 pb-3 header-safe sticky top-0 z-10"
        style={{ background: dark.surface, borderBottom: `1px solid ${dark.border}` }}>
        <button
          onClick={() => navigate(backPath)}
          className="p-2 rounded-xl transition-colors"
          style={{ color: dark.inkMuted }}
          onMouseEnter={e => (e.currentTarget.style.background = dark.surfaceAlt)}
          onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
          aria-label="Volver"
        >
          <ArrowLeft size={18} />
        </button>
        <span className="flex-1 text-sm font-bold" style={{ color: dark.ink }}>
          {titulo}
        </span>
        <span className="text-xs" style={{ color: dark.inkSubtle }}>
          {user?.nombre?.split(' ')[0]}
        </span>
      </header>

      {/* Progress bar */}
      <div className="h-1 w-full" style={{ background: dark.border }}>
        <div className="h-1 transition-all duration-500" style={{
          width: `${progreso}%`,
          background: `linear-gradient(90deg, ${dark.amberDim}, ${dark.amber})`,
        }} />
      </div>

      <div className="flex-1 px-4 max-w-4xl mx-auto w-full space-y-4 pt-5"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom, 16px) + 6rem)' }}>

        {/* Título */}
        <div>
          <p className="text-xs font-bold uppercase tracking-widest mb-1" style={{ color: dark.amberDim }}>
            {paso}
          </p>
          <h1 className="text-xl font-bold" style={{ color: dark.ink }}>{titulo}</h1>
          <p className="text-sm mt-0.5" style={{ color: dark.inkMuted }}>{subtitulo}</p>
          <p className="text-xs mt-1" style={{ color: dark.inkSubtle }}>
            Tip: en las casillas podés sumar y restar — escribí <span className="font-mono">+2500+1000</span> y dale Enter para calcular.
          </p>
        </div>

        {/* Borrador restaurado */}
        {borradorInfo && (
          <div className="flex items-center gap-2 text-sm px-4 py-2.5 rounded-xl"
            style={{ background: dark.amberTint, border: `1px solid ${dark.amberDim}`, color: dark.amber }}>
            <Save size={14} className="shrink-0" />
            <span className="flex-1">Se restauró tu conteo guardado a las {borradorInfo} — seguí donde ibas.</span>
            <button onClick={descartarBorrador} className="p-1 rounded-lg" aria-label="Descartar borrador"
              style={{ color: dark.amber }}>
              <X size={14} />
            </button>
          </div>
        )}

        {/* Progreso: todos los productos deben quedar registrados */}
        <div className="flex gap-2 flex-wrap items-center">
          <span className="px-3 py-1 rounded-full text-xs font-bold" style={{
            background: registrados === items.length && items.length > 0 ? dark.greenTint : dark.surfaceAlt,
            color: registrados === items.length && items.length > 0 ? dark.green : dark.inkMuted,
          }}>
            {registrados} de {items.length} registrados
          </span>
          {novedades > 0 && (
            <span className="px-3 py-1 rounded-full text-xs font-bold" style={{
              background: dark.amberTint, color: dark.amber,
            }}>
              ⚠ {novedades} distinto{novedades > 1 ? 's' : ''} al cierre anterior
            </span>
          )}
          {referencia?.fecha && (
            <span className="text-xs" style={{ color: dark.inkSubtle }}>
              Referencia: {refLabel.toLowerCase()}
              {referencia.barista ? ` (${referencia.barista})` : ''}
            </span>
          )}
        </div>

        {error && (
          <div className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl"
            style={{ background: dark.dangerTint, color: dark.danger, border: `1px solid ${dark.dangerDim}` }}>
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* Lista de productos */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <p className="text-sm animate-pulse" style={{ color: dark.inkSubtle }}>Cargando productos...</p>
          </div>
        ) : (
          <div className="rounded-2xl overflow-hidden grid grid-cols-1 lg:grid-cols-2" style={{
            background: dark.surface,
            border: `1px solid ${dark.border}`,
          }}>
            {ordenados.map((item, idx) => {
              // Corte entre zonas del local. Es una línea, no un encabezado: la
              // barista ya sabe dónde está parada — lo único que necesita es ver
              // que ahí termina un tramo del recorrido. En dos columnas, además,
              // hace que la zona siguiente arranque en fila nueva.
              const corte = idx > 0 && abreBloque(item.orden_conteo, ordenados[idx - 1].orden_conteo)
              const val    = conteos[item.producto_id]
              const nval   = valorDe(val)
              const filled = nval !== null
              const ref    = refDe(item.producto_id)
              // Solo en APERTURA una diferencia con la referencia es novedad (de noche
              // no debió moverse nada). En cierre, moverse durante el día es lo normal.
              const novedad = isApertura && filled && ref !== null && Math.abs(nval - ref) > 0.001
              const coincide = filled && ref !== null && Math.abs(nval - ref) <= 0.001

              let rowBg = 'transparent'
              if (filled && !novedad) rowBg = 'oklch(94% 0.04 155 / 0.35)'
              if (novedad) rowBg = 'oklch(96% 0.05 70 / 0.5)'

              return (
                <Fragment key={item.producto_id}>
                {corte && (
                  <div className="col-span-full" aria-hidden="true" style={{
                    height: '0.75rem',
                    background: dark.bg,
                    borderBottom: `1px solid ${dark.border}`,
                  }} />
                )}
                <div className="px-4 py-3.5 transition-colors"
                  style={{
                    background: rowBg,
                    borderBottom: `1px solid ${dark.border}`,
                  }}>
                  <div className="flex items-center gap-3">
                    <div className="shrink-0">
                      {novedad
                        ? <AlertTriangle size={18} style={{ color: dark.amber }} />
                        : filled
                        ? <CheckCircle2 size={18} style={{ color: dark.green }} />
                        : <Circle size={18} style={{ color: dark.inkSubtle }} />
                      }
                    </div>
                    <div className="flex-1 min-w-0">
                      <label
                        htmlFor={`conteo-${item.producto_id}`}
                        className="text-sm font-semibold leading-tight block"
                        style={{ color: dark.ink }}
                      >
                        {item.producto_nombre}
                      </label>
                      <p className="text-xs mt-0.5" style={{ color: dark.inkSubtle }}>
                        {ref !== null
                          ? `${refLabel}: ${Math.round(ref * 100) / 100} ${item.unidad_medida}`
                          : 'Sin conteo anterior — pesalo o contalo'}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {ref !== null && (
                        <button
                          onClick={() => coincidir(item)}
                          className="text-xs font-bold px-2.5 py-1.5 rounded-lg transition-colors"
                          style={{
                            background: coincide ? dark.greenTint : dark.surfaceAlt,
                            color: coincide ? dark.green : dark.inkMuted,
                            border: `1px solid ${coincide ? dark.greenDim : dark.border}`,
                          }}>
                          {coincide ? '✓ Coincide' : 'Coincide'}
                        </button>
                      )}
                      {!item.fraccionable && (
                        <>
                          <input
                            id={`conteo-${item.producto_id}`}
                            type="text"
                            value={val ?? ''}
                            onChange={e => {
                              setConteos(prev => ({ ...prev, [item.producto_id]: limpiarExpresion(e.target.value) }))
                              setIsDirty(true)
                            }}
                            onKeyDown={e => {
                              if (e.key === 'Enter' && val)
                                setConteos(prev => ({ ...prev, [item.producto_id]: resolver(val) }))
                            }}
                            onBlur={() => {
                              if (val) setConteos(prev => ({ ...prev, [item.producto_id]: resolver(val) }))
                            }}
                            placeholder="0"
                            className="w-24 text-right rounded-lg px-2 py-1.5 text-sm font-bold outline-none transition-colors"
                            style={{
                              background: dark.surfaceAlt,
                              border: `2px solid ${novedad ? dark.amberDim : filled ? dark.greenDim : dark.border}`,
                              color: novedad ? dark.amber : filled ? dark.green : dark.ink,
                              fontFamily: '"JetBrains Mono", monospace',
                            }}
                          />
                          <span className="text-xs w-7 text-left" style={{ color: dark.inkSubtle }}>
                            {item.unidad_medida}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  {item.fraccionable && (item.contenido_por_unidad ?? 0) > 0 ? (
                    <div className="mt-2.5 ml-7">
                      <ConteoGramos
                        contenido={item.contenido_por_unidad as number}
                        cerradas={gramos[item.producto_id]?.c ?? ''}
                        abierta={gramos[item.producto_id]?.a ?? ''}
                        onChange={(c, a, t) => {
                          setGramos(prev => ({ ...prev, [item.producto_id]: { c, a } }))
                          setConteos(prev => ({ ...prev, [item.producto_id]: String(t) }))
                          setIsDirty(true)
                        }}
                      />
                    </div>
                  ) : item.fraccionable ? (
                    <div className="mt-2.5 ml-7">
                      <NivelEnvase
                        envase={item.envase === 'botella' ? 'botella' : 'bolsa'}
                        unidad={item.unidad_medida}
                        selladas={Math.floor(Number(val ?? 0))}
                        nivel={Number(val ?? 0) - Math.floor(Number(val ?? 0))}
                        onChange={(s, n) => {
                          setConteos(prev => ({ ...prev, [item.producto_id]: String(s + n) }))
                          setIsDirty(true)
                        }}
                      />
                    </div>
                  ) : null}
                  {novedad && ref !== null && (
                    <p className="text-xs font-medium mt-1 ml-7" style={{ color: dark.amber }}>
                      Distinto al {refLabel.toLowerCase()} ({Math.round(ref * 100) / 100}): revisá si hubo novedad nocturna
                    </p>
                  )}
                </div>
                </Fragment>
              )
            })}
          </div>
        )}

        {novedades > 0 && (
          <div className="px-4 py-3 rounded-xl text-sm" style={{
            background: dark.amberTint,
            border: `1px solid ${dark.amberDim}`,
            color: dark.amber,
          }}>
            <strong>{novedades} producto{novedades > 1 ? 's' : ''}</strong> distinto{novedades > 1 ? 's' : ''} al cierre anterior — quedará registrado para revisión.
          </div>
        )}
      </div>

      {/* CTA sticky */}
      <div className="fixed bottom-0 left-0 right-0 p-4 max-w-4xl mx-auto" style={{
        background: `linear-gradient(to top, ${dark.bg} 70%, transparent)`,
        paddingBottom: 'env(safe-area-inset-bottom, 16px)',
      }}>
        {!canConfirm && !saving && (
          <p className="text-center text-xs mb-2" style={{ color: dark.inkSubtle }}>
            {items.length - registrados > 0
              ? `Faltan ${items.length - registrados} producto${items.length - registrados > 1 ? 's' : ''} por registrar — pesalos o tocá "Coincide"`
              : 'Cargando…'}
          </p>
        )}
        {isDirty && !saving && (
          <button
            onClick={() => guardarBorrador(true)}
            className="w-full font-semibold py-2.5 rounded-xl text-sm flex items-center justify-center gap-2 mb-2 transition-colors"
            style={{
              background: guardadoOk ? dark.greenTint : dark.surfaceAlt,
              color: guardadoOk ? dark.green : dark.inkMuted,
              border: `1px solid ${guardadoOk ? dark.greenDim : dark.border}`,
            }}
          >
            {guardadoOk ? <CheckCircle2 size={15} /> : <Save size={15} />}
            {guardadoOk ? 'Guardado — podés salir y volver sin perderlo' : 'Guardar cambios'}
          </button>
        )}
        <button
          onClick={confirmar}
          disabled={!canConfirm}
          className="w-full font-bold py-4 rounded-2xl text-base flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
          style={{
            background: canConfirm
              ? `linear-gradient(135deg, ${dark.amberDim}, ${dark.amber})`
              : dark.surfaceAlt,
            color: canConfirm ? dark.bg : dark.inkSubtle,
            opacity: canConfirm ? 1 : 0.6,
            cursor: canConfirm ? 'pointer' : 'not-allowed',
          }}
        >
          <ClipboardCheck size={18} />
          {saving ? 'Guardando...' : ctaLabel}
          {!saving && canConfirm && <ArrowRight size={18} />}
        </button>
      </div>
    </div>
  )
}
