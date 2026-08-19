import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  Banknote, User, ImageIcon, Check, X, ZoomIn,
  ChevronDown, ChevronUp, AlertTriangle, CheckCircle2,
  Download, FileText, TrendingUp, Trash2, Pencil, CornerDownRight,
} from 'lucide-react'
import {
  cascadaDelDia, faltaConsignar, diferenciaEfectiva, diaCuadrado,
} from '../components/consignaciones/cascada'
import type {
  Cascada, CamposCascada, CruceCascada, RotularCruce,
} from '../components/consignaciones/cascada'

// ─── Tipos ────────────────────────────────────────────────────────────────────
interface Sede { id: number; nombre: string }

interface MovDetalle { concepto: string; valor: number; fecha: string }
interface ConsignacionItem {
  id: number; valor: number; estado: string; fecha: string
  imagen_url: string | null; usuario_nombre: string | null
}
// Hereda `CamposCascada`: los campos de la cascada llegan en el mismo turno del
// resumen. Ver `components/consignaciones/cascada.ts` — la cuenta de qué día le
// tapó el hueco a cuál la hace el backend y acá NO se recalcula.
interface ResumenDia extends CamposCascada {
  turno_id: number
  tienda_id: number
  tienda_nombre: string
  fecha_apertura: string
  fecha_cierre: string | null
  total_efectivo: number
  efectivo_final_real: number
  base_real: number
  total_egresos: number
  total_ingresos_mov: number
  diferencia_cierre?: number
  esperado_consignar: number
  total_consignado: number
  /**
   * `total_consignado − esperado_consignar` tal cual lo manda el backend, o sea
   * ANTES de la cascada. No la uses para pintar: en un día que le tapó el hueco
   * a otro te va a dar un rojo que no corresponde. La buena es
   * `diferenciaEfectiva(cascada, …)`.
   */
  diferencia: number
  egresos_detalle: MovDetalle[]
  ingresos_detalle: MovDetalle[]
  consignaciones: ConsignacionItem[]
}

// Un DÍA de calendario = uno o más turnos cerrados ese día, agregados. Cada consignación
// sigue atada a su turno (backend); esto es SOLO presentación: sumamos los turnos del día
// para mostrar una tarjeta por día. El detalle expande los movimientos y consignaciones de
// todos los turnos del día juntos.
interface DiaAgrupado {
  key: string
  turno_ids: number[]
  /** La cascada del día, ya sumada y rotulada. Es lo que decide el número grande. */
  cascada: Cascada
  tienda_nombre: string
  fecha_apertura: string
  fecha_cierre: string | null
  n_turnos: number
  total_efectivo: number
  total_ingresos_mov: number
  total_egresos: number
  diferencia_cierre: number
  /** Los sumandos que NO son venta del día, a la vista. `sobrante_apertura` era
   *  el único de los cinco términos de la fórmula que no se exponía en ninguna
   *  parte, así que un día que pedía más de lo vendido no tenía cómo explicarse.
   *  Opcionales por si el backend todavía no los manda (deploy a medias). */
  sobrante_apertura?: number
  en_cajon_no_es_venta?: number
  esperado_consignar: number
  total_consignado: number
  // NO hay `diferencia` acá a propósito. La había —`consignado − esperado`— y
  // era la cuenta PRE-CASCADA: dejarla sumada y guardada es dejar servida la
  // cifra equivocada para el próximo que agregue una fila a esta tarjeta. La
  // diferencia del día se saca con `diferenciaEfectiva(cascada, …)`, que sin
  // cascada da exactamente la misma.
  egresos_detalle: MovDetalle[]
  ingresos_detalle: MovDetalle[]
  consignaciones: ConsignacionItem[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (v: number) => `$${Math.round(v).toLocaleString('es-CO')}`
const fmtNum = (v: number) => Math.round(v).toLocaleString('es-CO')

const parseUTC = (f: string) => {
  const s = f.replace(' ', 'T').replace('+00:00', 'Z')
  return new Date(s.endsWith('Z') ? s : s + 'Z')
}

// Día calendario LOCAL (YYYY-MM-DD) de APERTURA — el día en que el turno vendió.
// Se agrupa por apertura (no por cierre) porque un turno puede abrir a la mañana y
// cerrarse recién a la mañana siguiente (cierre demorado / turno huérfano): su plata
// es del día que abrió. Por cierre, ese día "desaparecía" dentro del día siguiente.
const dayKeyOf = (d: ResumenDia) => {
  const dt = parseUTC(d.fecha_apertura)
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
}

// Tolerantes a null/'' — un turno cerrado puede no tener fecha_cierre cargada.
const fmtFecha = (f: string | null | undefined) =>
  f ? parseUTC(f).toLocaleDateString('es-CO', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }) : '—'

const fmtHora = (f: string | null | undefined) =>
  f ? parseUTC(f).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }) : '—'

// ─── Exportar Excel ───────────────────────────────────────────────────────────

async function exportarExcelConsig(dias: ResumenDia[]) {
  const XLSX = await import('xlsx')
  const filas = dias.flatMap((d, di) =>
    d.consignaciones.map((c, ci) => [
      di * 100 + ci + 1,                               // Nº
      fmtFecha(d.fecha_cierre),                         // Fecha
      fmtHora(c.fecha),                                 // Hora
      d.tienda_nombre,                                  // Sede
      c.usuario_nombre ?? '—',                          // Barista
      Math.round(c.valor),                              // Valor (número)
      c.estado,                                         // Estado
      c.imagen_url ?? '',                               // URL foto
    ])
  )
  const ws = XLSX.utils.aoa_to_sheet([
    ['Nº', 'Fecha', 'Hora', 'Sede', 'Barista', 'Valor', 'Estado', 'URL foto'],
    ...filas,
  ])
  ws['!cols'] = [
    { wch: 4 }, { wch: 22 }, { wch: 8 }, { wch: 12 },
    { wch: 20 }, { wch: 14 }, { wch: 12 }, { wch: 60 },
  ]
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, 'Consignaciones')
  XLSX.writeFile(wb, `consignaciones_${new Date().toISOString().slice(0, 10)}.xlsx`)
}

// ─── Reporte HTML con fotos ────────────────────────────────────────────────────

// `rotular` entra por parámetro porque nombrar el otro lado de un cruce necesita
// los turnos cargados, y eso solo lo sabe la pantalla. El reporte impreso corre
// la MISMA cuenta que la lista a propósito: un PDF que diga «Diff: $177.700» de
// un día que la pantalla da por cuadrado reabre las dos cuentas en papel.
function descargarReporteHTML(dias: ResumenDia[], rotular: RotularCruce) {
  const totalConsignado = dias.reduce((s, d) => s + d.total_consignado, 0)
  const conFoto = dias.flatMap(d => d.consignaciones).filter(c => c.imagen_url).length
  const totalConsig = dias.flatMap(d => d.consignaciones).length

  const html = `<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reporte Consignaciones</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f3f4f6; color: #111827; padding: 24px; }
    .page { max-width: 860px; margin: 0 auto; }
    h1 { font-size: 1.6rem; font-weight: 800; margin-bottom: 4px; }
    .resumen-header { color: #6b7280; font-size: 0.9rem; margin-bottom: 20px; }
    .resumen-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 28px; }
    .card { background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px 18px; }
    .card-label { font-size: 0.75rem; color: #9ca3af; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
    .card-value { font-size: 1.4rem; font-weight: 800; margin-top: 4px; }
    .dia-title { font-size: 1rem; font-weight: 700; color: #374151; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; margin: 28px 0 14px; display: flex; justify-content: space-between; align-items: baseline; }
    .dia-meta { font-size: 0.8rem; font-weight: 500; color: #6b7280; }
    .consig { background: white; border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px 16px; margin-bottom: 10px; display: flex; gap: 16px; align-items: flex-start; }
    .foto-wrap { flex-shrink: 0; }
    .foto { width: 110px; height: 110px; object-fit: cover; border-radius: 8px; border: 1px solid #e5e7eb; display: block; }
    .sin-foto { width: 110px; height: 110px; border-radius: 8px; border: 1.5px dashed #d1d5db; background: #f9fafb; display: flex; align-items: center; justify-content: center; font-size: 0.75rem; color: #9ca3af; flex-direction: column; gap: 4px; }
    .datos { flex: 1; min-width: 0; }
    .valor { font-size: 1.5rem; font-weight: 800; color: #111827; font-variant-numeric: tabular-nums; }
    .info { font-size: 0.85rem; color: #6b7280; margin-top: 5px; }
    .badge { display: inline-block; font-size: 0.75rem; font-weight: 600; padding: 2px 10px; border-radius: 999px; margin-top: 8px; }
    .realizada { background: #dcfce7; color: #166534; }
    .pendiente  { background: #fef9c3; color: #854d0e; }
    .foto-link  { display: inline-block; margin-top: 8px; font-size: 0.8rem; color: #2563eb; text-decoration: none; }
    .foto-link:hover { text-decoration: underline; }
    .seq { font-size: 0.8rem; color: #d1d5db; font-weight: 700; width: 28px; flex-shrink: 0; padding-top: 2px; }
    .cascada { font-size: 0.8rem; color: #b45309; margin: -6px 0 12px; }
    .cascada-rojo { font-size: 0.8rem; color: #dc2626; font-weight: 600; margin: -6px 0 12px; }
    @media print {
      body { background: white; padding: 0; }
      .resumen-cards { break-inside: avoid; }
      .consig { break-inside: avoid; border: 1px solid #ccc; }
    }
  </style>
</head>
<body>
<div class="page">
  <h1>Consignaciones</h1>
  <p class="resumen-header">
    Reporte generado: ${new Date().toLocaleString('es-CO', { dateStyle: 'long', timeStyle: 'short' })}
  </p>
  <div class="resumen-cards">
    <div class="card">
      <div class="card-label">Total consignado</div>
      <div class="card-value" style="color:#166534">$${fmtNum(totalConsignado)}</div>
    </div>
    <div class="card">
      <div class="card-label">Consignaciones</div>
      <div class="card-value">${totalConsig}</div>
    </div>
    <div class="card">
      <div class="card-label">Con foto</div>
      <div class="card-value" style="color:#1d4ed8">${conFoto} / ${totalConsig}</div>
    </div>
  </div>

  ${dias.map(d => {
    const c = cascadaDelDia([d], rotular)
    const ok = diaCuadrado(c, d.esperado_consignar, d.total_consignado)
    const dif = diferenciaEfectiva(c, d.esperado_consignar, d.total_consignado)
    const cruces = !c.legible || !c.hubo ? '' : [
      ...c.cubrio.map(l => `<p class="cascada">Cubrió el faltante del ${l.dia}: −$${fmtNum(l.monto)}</p>`),
      ...c.cubiertoPor.map(l => `<p class="cascada">Le faltaron $${fmtNum(l.monto)}; los cubrió la venta del ${l.dia}</p>`),
      c.faltanteSinCubrir > 0.5
        ? `<p class="cascada-rojo">Faltaron $${fmtNum(c.faltanteSinCubrir)} que ningún día anterior alcanzó a cubrir</p>`
        : '',
    ].join('')
    return `
  <div class="dia-title">
    <span>${fmtFecha(d.fecha_cierre)} — ${d.tienda_nombre}</span>
    <span class="dia-meta" style="color:${ok ? '#16a34a' : '#dc2626'}">
      ${ok ? '✓ Cuadrado' : `Diff: $${fmtNum(dif)}`}
      &nbsp;·&nbsp; $${fmtNum(d.total_consignado)} consignado
    </span>
  </div>
  ${cruces}
  ${d.consignaciones.length === 0
    ? '<p style="color:#f59e0b;font-size:0.85rem;margin-bottom:12px">⚠ Sin consignaciones registradas</p>'
    : d.consignaciones.map((c, i) => `
  <div class="consig">
    <div class="seq">#${i + 1}</div>
    <div class="foto-wrap">
      ${c.imagen_url
        ? `<a href="${c.imagen_url}" target="_blank"><img src="${c.imagen_url}" class="foto" loading="lazy" /></a>`
        : `<div class="sin-foto"><span>📷</span><span>Sin foto</span></div>`
      }
    </div>
    <div class="datos">
      <div class="valor">$${fmtNum(c.valor)}</div>
      <div class="info">
        ${c.usuario_nombre ?? '—'} &nbsp;·&nbsp; ${fmtHora(c.fecha)}
      </div>
      <span class="badge ${c.estado}">${c.estado}</span>
      ${c.imagen_url ? `<br><a href="${c.imagen_url}" target="_blank" class="foto-link">🔗 Ver foto completa</a>` : ''}
    </div>
  </div>`).join('')
  }`
  }).join('')}
</div>
</body>
</html>`

  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `consignaciones_${new Date().toISOString().slice(0, 10)}.html`
  a.click()
  URL.revokeObjectURL(url)
}

// ─── Tipos Flujo ──────────────────────────────────────────────────────────────

interface TurnoHistorial {
  id: number
  fecha_apertura: string
  fecha_cierre: string | null
  estado: string
}

interface MovimientoFlujo {
  tipo: string
  concepto: string
  valor: number
}

interface ConsignacionFlujo {
  id: number
  valor: number
  fecha: string
}

interface FlujoCaja {
  turno_id: number
  barista: string
  fecha_apertura: string
  base_real: number
  ventas_total: number
  ventas_efectivo: number
  ventas_tarjeta: number
  movimientos: MovimientoFlujo[]
  consignaciones: ConsignacionFlujo[]
  efectivo_esperado: number
  efectivo_final_real: number | null
  diferencia_cierre: number | null
}

// ─── Tab: Flujo por turno ─────────────────────────────────────────────────────

function FlujoPorTurno({ tiendaId }: { tiendaId: number | null }) {
  const [turnos, setTurnos]         = useState<TurnoHistorial[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [flujo, setFlujo]           = useState<FlujoCaja | null>(null)
  const [loadingTurnos, setLoadingTurnos] = useState(false)
  const [loadingFlujo, setLoadingFlujo]   = useState(false)
  const [errorFlujo, setErrorFlujo] = useState('')

  useEffect(() => {
    if (tiendaId === null) return
    setLoadingTurnos(true)
    api.get(`/caja/historial/${tiendaId}`)
      .then(({ data }) => {
        const cerrados = (data as TurnoHistorial[]).filter(t => t.estado === 'cerrado')
        setTurnos(cerrados)
        setSelectedId(null)
        setFlujo(null)
      })
      .catch(() => {})
      .finally(() => setLoadingTurnos(false))
  }, [tiendaId])

  const cargarFlujo = async (turnoId: number) => {
    setSelectedId(turnoId)
    setFlujo(null)
    setErrorFlujo('')
    setLoadingFlujo(true)
    try {
      const { data } = await api.get(`/caja/${turnoId}/flujo`)
      setFlujo(data)
    } catch {
      setErrorFlujo('No se pudo cargar el flujo de este turno')
    } finally {
      setLoadingFlujo(false)
    }
  }

  const ingresos = flujo?.movimientos.filter(m => m.tipo === 'ingreso') ?? []
  const egresos  = flujo?.movimientos.filter(m => m.tipo === 'egreso')  ?? []
  const difColor = flujo?.diferencia_cierre == null
    ? '#6b7280'
    : Math.abs(flujo.diferencia_cierre) <= 0.5
      ? '#16a34a'
      : '#dc2626'

  if (loadingTurnos) return <p className="text-sm text-gray-400 py-8 text-center">Cargando turnos...</p>

  if (turnos.length === 0) return (
    <div className="bg-white rounded-2xl border border-gray-200 p-10 text-center">
      <TrendingUp size={32} className="text-gray-300 mx-auto mb-3" />
      <p className="text-sm text-gray-400">No hay turnos cerrados para esta sede</p>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Selector de turno */}
      <div>
        <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1.5">
          Seleccionar turno
        </label>
        <select
          value={selectedId ?? ''}
          onChange={e => cargarFlujo(Number(e.target.value))}
          className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-white text-gray-800 outline-none focus:border-amber-400"
        >
          <option value="" disabled>— Elegir turno —</option>
          {turnos.map(t => (
            <option key={t.id} value={t.id}>
              {t.fecha_cierre
                ? fmtFecha(t.fecha_cierre) + ' — ' + fmtHora(t.fecha_cierre)
                : fmtFecha(t.fecha_apertura)} (#{t.id})
            </option>
          ))}
        </select>
      </div>

      {loadingFlujo && <p className="text-sm text-gray-400 text-center py-6">Cargando flujo...</p>}

      {errorFlujo && (
        <div className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl bg-red-50 border border-red-200 text-red-600">
          <AlertTriangle size={14} /> {errorFlujo}
        </div>
      )}

      {flujo && !loadingFlujo && (
        <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          {/* Encabezado del turno */}
          <div className="px-5 py-4 border-b border-gray-100 bg-gray-50">
            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide">Barista</p>
            <p className="text-sm font-semibold text-gray-800 mt-0.5">{flujo.barista}</p>
            <p className="text-xs text-gray-400 mt-0.5">{fmtFecha(flujo.fecha_apertura)} · {fmtHora(flujo.fecha_apertura)}</p>
          </div>

          {/* Cascada de efectivo */}
          <div className="px-5 py-4 space-y-2 text-sm">
            <p className="text-xs font-bold text-gray-500 uppercase tracking-wide mb-3">Flujo de efectivo</p>

            {/* Base */}
            <div className="flex justify-between">
              <span className="text-gray-600">Base apertura</span>
              <span className="font-semibold text-gray-800">{fmt(flujo.base_real)}</span>
            </div>

            {/* Ventas */}
            <div className="flex justify-between font-medium">
              <span className="text-gray-700">Ventas total</span>
              <span className="text-gray-800">{fmt(flujo.ventas_total)}</span>
            </div>
            <div className="flex justify-between pl-4 text-xs text-gray-500">
              <span>Efectivo</span>
              <span>{fmt(flujo.ventas_efectivo)}</span>
            </div>
            <div className="flex justify-between pl-4 text-xs text-gray-500">
              <span>Tarjeta</span>
              <span>{fmt(flujo.ventas_tarjeta)}</span>
            </div>

            {/* Movimientos ingresos */}
            {ingresos.map((m, i) => (
              <div key={i} className="flex justify-between text-green-700">
                <span className="text-xs pl-2">+ {m.concepto}</span>
                <span className="text-xs font-semibold">{fmt(m.valor)}</span>
              </div>
            ))}

            {/* Movimientos egresos */}
            {egresos.map((m, i) => (
              <div key={i} className="flex justify-between text-red-600">
                <span className="text-xs pl-2">− {m.concepto}</span>
                <span className="text-xs font-semibold">{fmt(m.valor)}</span>
              </div>
            ))}

            {/* Consignaciones */}
            {flujo.consignaciones.length > 0 && (
              <>
                <p className="text-xs font-bold text-gray-400 uppercase tracking-wide pt-1">Consignaciones</p>
                {flujo.consignaciones.map(c => (
                  <div key={c.id} className="flex justify-between text-blue-600">
                    <span className="text-xs pl-2">− Consignación · {fmtHora(c.fecha)}</span>
                    <span className="text-xs font-semibold">{fmt(c.valor)}</span>
                  </div>
                ))}
              </>
            )}

            {/* Efectivo esperado */}
            <div className="border-t border-gray-200 pt-2 flex justify-between font-bold">
              <span className="text-gray-700">Efectivo esperado</span>
              <span className="text-blue-700">{fmt(flujo.efectivo_esperado)}</span>
            </div>

            {/* Efectivo final real */}
            {flujo.efectivo_final_real != null && (
              <div className="flex justify-between">
                <span className="text-gray-600">Efectivo final real</span>
                <span className="font-semibold text-gray-800">{fmt(flujo.efectivo_final_real)}</span>
              </div>
            )}

            {/* Diferencia */}
            {flujo.diferencia_cierre != null && (
              <div className="flex justify-between font-bold pt-1 border-t border-gray-200"
                style={{ color: difColor }}>
                <span className="flex items-center gap-1">
                  {Math.abs(flujo.diferencia_cierre) <= 0.5
                    ? <CheckCircle2 size={14} />
                    : <AlertTriangle size={14} />}
                  Diferencia cierre
                </span>
                <span>
                  {Math.abs(flujo.diferencia_cierre) <= 0.5
                    ? 'Sin diferencia'
                    : fmt(flujo.diferencia_cierre)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Componente principal ─────────────────────────────────────────────────────

type Tab = 'consignaciones' | 'flujo'

export default function ConsignacionesAdmin() {
  const { user } = useAuth()
  const [tab, setTab] = useState<Tab>('consignaciones')
  const [sedes, setSedes] = useState<Sede[]>([])
  const [tiendaId, setTiendaId] = useState<number | null>(user?.tienda_id ?? null)
  const [dias, setDias] = useState<ResumenDia[]>([])
  const [loading, setLoading] = useState(false)
  const [fotoModal, setFotoModal] = useState<string | null>(null)
  const [confirmando, setConfirmando] = useState<number | null>(null)
  const [recogiendo, setRecogiendo] = useState<string | null>(null)
  // expandido = clave de DÍA (YYYY-MM-DD), no turno_id: la lista ahora es por día.
  const [expandido, setExpandido] = useState<string | null>(null)
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')

  // Cargar sedes disponibles
  useEffect(() => {
    api.get('/auth/tiendas').then(({ data }) => {
      setSedes(data)
      if (!tiendaId && data.length > 0) setTiendaId(data[0].id)
    }).catch(() => {})
  }, [])

  const load = async (tid: number) => {
    setLoading(true)
    try {
      const params: Record<string, string | number> = { tienda_id: tid }
      if (desde) params.desde = desde
      if (hasta) params.hasta = hasta
      const { data } = await api.get('/consignaciones/resumen-admin', { params })
      setDias(data)
      setExpandido(null)
      const primero = data.find((d: ResumenDia) =>
        d.consignaciones.some((c: ConsignacionItem) => c.estado === 'pendiente')
      )
      if (primero) setExpandido(dayKeyOf(primero))
    } finally { setLoading(false) }
  }

  useEffect(() => { if (tiendaId !== null) load(tiendaId) }, [tiendaId, desde, hasta])

  // Atajos de rango: setea desde/hasta en formato YYYY-MM-DD (local).
  const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const aplicarRango = (preset: 'hoy' | '7d' | 'mes' | 'todo') => {
    const hoy = new Date()
    if (preset === 'todo') { setDesde(''); setHasta(''); return }
    if (preset === 'hoy') { const s = ymd(hoy); setDesde(s); setHasta(s); return }
    if (preset === '7d') { const d = new Date(hoy); d.setDate(d.getDate() - 6); setDesde(ymd(d)); setHasta(ymd(hoy)); return }
    if (preset === 'mes') { setDesde(ymd(new Date(hoy.getFullYear(), hoy.getMonth(), 1))); setHasta(ymd(hoy)) }
  }
  const rangoActivo = !!(desde || hasta)

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

  const eliminar = async (c: ConsignacionItem) => {
    if (!window.confirm(`¿Revertir la consignación de $${Math.round(c.valor).toLocaleString('es-CO')}? El saldo por consignar del turno se recalcula.`)) return
    setConfirmando(c.id)
    try {
      await api.delete(`/consignaciones/${c.id}`)
      if (tiendaId !== null) await load(tiendaId)
    } finally { setConfirmando(null) }
  }

  const editar = async (c: ConsignacionItem) => {
    const actual = Math.round(c.valor).toLocaleString('es-CO')
    const entrada = window.prompt(`Valor correcto de la consignación (actual: $${actual}):`)
    if (entrada === null) return
    const nuevo = Number(entrada.replace(/[^\d]/g, ''))
    if (!(nuevo > 0)) { alert('Valor inválido'); return }
    setConfirmando(c.id)
    try {
      const fd = new FormData()
      fd.append('valor', String(nuevo))
      await api.patch(`/consignaciones/${c.id}`, fd)
      if (tiendaId !== null) await load(tiendaId)
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo editar')
    } finally { setConfirmando(null) }
  }

  // El admin pasó por la tienda y se llevó el efectivo del día: salda esos turnos
  // sin comprobante (ya no hay foto que aprobar, la plata la recogió él en persona).
  // El monto lo recalcula el backend desde el saldo real; acá sólo mandamos los turnos.
  const recoger = async (dia: DiaAgrupado, monto: number) => {
    if (tiendaId === null) return
    if (!window.confirm(
      `¿Confirmás que recogiste ${fmt(monto)} de ${fmtFecha(dia.fecha_apertura)}?\n\n` +
      `El día queda saldado sin comprobante. Se puede revertir borrando la consignación.`
    )) return
    setRecogiendo(dia.key)
    try {
      const fd = new FormData()
      fd.append('tienda_id', String(tiendaId))
      fd.append('turno_ids', JSON.stringify(dia.turno_ids))
      await api.post('/consignaciones/recoger', fd)
      await load(tiendaId)
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo registrar la recogida')
    } finally { setRecogiendo(null) }
  }

  // Cómo se nombra el día del OTRO lado de un cruce de la cascada.
  //
  // Se rotula por la APERTURA del turno cuando lo tenemos cargado —igual que las
  // tarjetas de abajo, que agrupan por apertura a propósito— y no por el
  // `fecha_cierre` que viaja en el cruce: un turno que abre el domingo y cierra
  // pasada la medianoche se llamaría «lunes» adentro de la explicación y
  // «domingo» en la lista, y el dueño saldría a buscar un día que no existe.
  //
  // La cascada corre sobre la HISTORIA COMPLETA de la sede y esta pantalla
  // muestra un rango filtrado, así que el otro lado puede no estar cargado.
  // `fuera: true` es exactamente eso, y se dice en voz alta: una fecha que no
  // aparece en la lista de abajo, sin aclarar por qué, se lee como un error.
  const rotularCruce = useMemo<RotularCruce>(() => {
    const porTurno = new Map(dias.map(d => [d.turno_id, d]))
    return (ref: CruceCascada) => {
      const t = porTurno.get(ref.turno_id)
      return t
        ? { dia: fmtFecha(t.fecha_apertura), fuera: false }
        : { dia: fmtFecha(ref.fecha_cierre), fuera: true }
    }
  }, [dias])

  // Agrupar los turnos por DÍA de calendario (una tarjeta por día). Suma esperado y
  // consignado del día; concatena movimientos y consignaciones de sus turnos. El backend
  // devuelve los turnos en orden de cierre desc, así que el Map conserva ese orden por día.
  const diasAgrupados = useMemo<DiaAgrupado[]>(() => {
    // `turnos` no llega a la tarjeta: es el insumo para armar la cascada al
    // final, cuando ya se sabe cuáles turnos son de este mismo día.
    type Acum = Omit<DiaAgrupado, 'cascada'> & { turnos: ResumenDia[] }
    const map = new Map<string, Acum>()
    for (const d of dias) {
      const key = dayKeyOf(d)
      let g = map.get(key)
      if (!g) {
        g = {
          key, turno_ids: [], turnos: [], tienda_nombre: d.tienda_nombre,
          fecha_apertura: d.fecha_apertura, fecha_cierre: d.fecha_cierre,
          n_turnos: 0, total_efectivo: 0, total_ingresos_mov: 0, total_egresos: 0,
          diferencia_cierre: 0, esperado_consignar: 0, total_consignado: 0,
          egresos_detalle: [], ingresos_detalle: [], consignaciones: [],
        }
        map.set(key, g)
      }
      g.n_turnos += 1
      g.turno_ids.push(d.turno_id)
      g.turnos.push(d)
      g.total_efectivo += d.total_efectivo
      g.total_ingresos_mov += d.total_ingresos_mov
      g.total_egresos += d.total_egresos
      g.diferencia_cierre += d.diferencia_cierre ?? 0
      g.esperado_consignar += d.esperado_consignar
      g.total_consignado += d.total_consignado
      g.egresos_detalle.push(...d.egresos_detalle)
      g.ingresos_detalle.push(...d.ingresos_detalle)
      g.consignaciones.push(...d.consignaciones)
      // Rango del día: apertura más temprana, cierre más tardío.
      if (d.fecha_apertura < g.fecha_apertura) g.fecha_apertura = d.fecha_apertura
      if (d.fecha_cierre && (!g.fecha_cierre || d.fecha_cierre > g.fecha_cierre)) g.fecha_cierre = d.fecha_cierre
    }
    const arr = [...map.values()]
    for (const g of arr) {
      g.egresos_detalle.sort((a, b) => (a.fecha || '').localeCompare(b.fecha || ''))
      g.ingresos_detalle.sort((a, b) => (a.fecha || '').localeCompare(b.fecha || ''))
      g.consignaciones.sort((a, b) => (a.fecha || '').localeCompare(b.fecha || ''))
    }
    // La cascada se arma recién acá, con TODOS los turnos del día en la mano:
    // los cruces entre turnos del mismo día se descartan, y para saber cuáles
    // son hay que haber terminado de agrupar.
    return arr.map(({ turnos, ...g }) => ({
      ...g, cascada: cascadaDelDia(turnos, rotularCruce),
    }))
  }, [dias, rotularCruce])

  // Totales globales — sobre los días agregados (coincide con lo que muestran las tarjetas).
  const totalEsperado   = diasAgrupados.reduce((s, g) => s + g.esperado_consignar, 0)
  const totalConsignado = diasAgrupados.reduce((s, g) => s + g.total_consignado, 0)
  // Por consignar sale del saldo POST-CASCADA, no de `esperado − consignado`: si
  // el titular siguiera con la resta cruda volvería a discrepar con las tarjetas
  // —y con lo que el backend efectivamente cobra— que es el bug que se cierra acá.
  const totalPendiente  = diasAgrupados.reduce(
    (s, g) => s + faltaConsignar(g.cascada, g.esperado_consignar, g.total_consignado), 0)
  // Lo que se fue a tapar huecos de otros días, y lo que faltó y nadie pudo tapar.
  // Ambos se suman sobre lo que el periodo filtrado muestra, no sobre la historia.
  const totalCubierto = diasAgrupados.reduce(
    (s, g) => s + (g.cascada.legible ? g.cascada.cubrioTotal : 0), 0)
  const totalSinCubrir = diasAgrupados.reduce(
    (s, g) => s + (g.cascada.legible ? g.cascada.faltanteSinCubrir : 0), 0)
  // Un backend que todavía no manda la cascada deja el número viejo en pantalla.
  // Es el mismo que mostraba ayer, pero decirlo es la diferencia entre una cifra
  // que se puede auditar y una que baja sin que nadie sepa por qué.
  const cascadaIlegible = diasAgrupados.some(g => !g.cascada.legible)

  return (
    <div className="space-y-6">
      {/* Encabezado + tabs */}
      <div>
        <div className="flex items-start justify-between gap-3 flex-wrap mb-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Consignaciones</h1>
            <p className="text-sm text-gray-500 mt-1">
              Reconciliación de efectivo por día — ventas en cash ± movimientos = debe consignarse
            </p>
          </div>
          {tab === 'consignaciones' && dias.length > 0 && (
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => exportarExcelConsig(dias)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white transition-colors"
                style={{ background: 'oklch(48% 0.15 155)' }}
                title="Descargar Excel con fecha, valor y link de foto"
              >
                <Download size={14} /> Excel
              </button>
              <button
                onClick={() => descargarReporteHTML(dias, rotularCruce)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 transition-colors"
                title="Reporte HTML con fotos — abre en el navegador, imprimible a PDF"
              >
                <FileText size={14} /> Reporte con fotos
              </button>
            </div>
          )}
        </div>

        {/* Tab bar */}
        <div className="flex gap-1 border-b border-gray-200">
          <button
            onClick={() => setTab('consignaciones')}
            className={`px-4 py-2 text-sm font-semibold border-b-2 transition-colors -mb-px ${
              tab === 'consignaciones'
                ? 'border-amber-500 text-amber-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            Consignaciones
          </button>
          <button
            onClick={() => setTab('flujo')}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-semibold border-b-2 transition-colors -mb-px ${
              tab === 'flujo'
                ? 'border-amber-500 text-amber-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <TrendingUp size={14} /> Flujo por turno
          </button>
        </div>
      </div>

      {/* Selector de sede — compartido entre tabs */}
      {sedes.length > 1 && (
        <div className="flex gap-1.5 flex-wrap">
          {sedes.map(s => (
            <button key={s.id} onClick={() => setTiendaId(s.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                tiendaId === s.id
                  ? 'bg-amber-600 text-white border-amber-600'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-amber-400'
              }`}>
              {s.nombre}
            </button>
          ))}
        </div>
      )}

      {/* ─── Tab: Consignaciones ─────────────────────────────────────────────── */}
      {tab === 'consignaciones' && (
        <>
          {/* Filtro de fecha */}
          <div className="flex items-center gap-2 flex-wrap bg-white border border-gray-200 rounded-xl px-3 py-2.5">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Periodo</span>
            <div className="flex gap-1">
              {([['hoy', 'Hoy'], ['7d', '7 días'], ['mes', 'Este mes'], ['todo', 'Todo']] as const).map(([k, label]) => {
                const activo = (k === 'todo' && !rangoActivo)
                return (
                  <button key={k} onClick={() => aplicarRango(k)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold border transition-colors ${
                      activo ? 'bg-amber-600 text-white border-amber-600' : 'bg-white text-gray-600 border-gray-200 hover:border-amber-400'
                    }`}>
                    {label}
                  </button>
                )
              })}
            </div>
            <div className="flex items-center gap-1.5 ml-auto">
              <input type="date" value={desde} max={hasta || undefined}
                onChange={e => setDesde(e.target.value)}
                className="border border-gray-200 rounded-lg px-2 py-1 text-xs text-gray-700 outline-none focus:border-amber-400" />
              <span className="text-gray-300 text-xs">→</span>
              <input type="date" value={hasta} min={desde || undefined}
                onChange={e => setHasta(e.target.value)}
                className="border border-gray-200 rounded-lg px-2 py-1 text-xs text-gray-700 outline-none focus:border-amber-400" />
              {rangoActivo && (
                <button onClick={() => aplicarRango('todo')} title="Limpiar filtro"
                  className="text-gray-400 hover:text-gray-600 p-1"><X size={14} /></button>
              )}
            </div>
          </div>

          {loading
            ? <p className="text-sm text-gray-400 text-center py-12">Cargando...</p>
            : (
              <>
                {/* Resumen global */}
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3">
                  {/* Por consignar — fila completa en móvil.
                      El verde tiene DOS condiciones, no una: sin nada pendiente y
                      sin plata faltante. Un «al día ✓» arriba de un faltante que
                      nadie tapó es la mentira más cara que puede decir esta pantalla. */}
                  <div className={`col-span-2 sm:col-span-1 border-2 rounded-2xl p-4 ${
                    totalSinCubrir > 0.5 ? 'bg-red-50 border-red-300'
                      : totalPendiente > 0 ? 'bg-amber-50 border-amber-300'
                      : 'bg-green-50 border-green-200'
                  }`}>
                    <p className={`text-xs font-semibold uppercase tracking-wide ${
                      totalSinCubrir > 0.5 ? 'text-red-700'
                        : totalPendiente > 0 ? 'text-amber-700' : 'text-green-600'
                    }`}>
                      Por consignar
                    </p>
                    <p className={`text-2xl font-bold mt-1 ${
                      totalSinCubrir > 0.5 ? 'text-red-800'
                        : totalPendiente > 0 ? 'text-amber-800' : 'text-green-700'
                    }`}>
                      {fmt(totalPendiente)}
                    </p>
                    {totalPendiente === 0 && totalSinCubrir <= 0.5 && (
                      <p className="text-xs text-green-600 mt-0.5">Al día ✓</p>
                    )}
                    {totalCubierto > 0.5 && (
                      <p className="text-xs text-amber-700 mt-1 leading-snug">
                        Ya se descontaron {fmt(totalCubierto)} que taparon faltantes de otros días.
                      </p>
                    )}
                    {totalSinCubrir > 0.5 && (
                      <p className="text-xs text-red-700 font-semibold mt-1 leading-snug">
                        Faltan {fmt(totalSinCubrir)} que ningún día anterior alcanzó a cubrir.
                      </p>
                    )}
                    {cascadaIlegible && (
                      <p className="text-xs text-gray-500 mt-1 leading-snug">
                        Hay días de los que el servidor no informó la cascada: ahí este total
                        usa la cuenta vieja, sin descontar lo que tapó faltantes.
                      </p>
                    )}
                  </div>
                  <div className="bg-gray-50 border border-gray-200 rounded-2xl p-3 sm:p-4">
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Ya consignado</p>
                    <p className="text-base sm:text-xl font-bold text-gray-700 mt-1">{fmt(totalConsignado)}</p>
                  </div>
                  <div className="bg-blue-50 border border-blue-200 rounded-2xl p-3 sm:p-4">
                    <p className="text-xs font-semibold text-blue-600 uppercase tracking-wide">Total esperado</p>
                    <p className="text-base sm:text-xl font-bold text-blue-800 mt-1">{fmt(totalEsperado)}</p>
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
                {diasAgrupados.map(dia => {
          const abierto = expandido === dia.key
          const pendientes = dia.consignaciones.filter(c => c.estado === 'pendiente')
          const hayEgresos = dia.egresos_detalle.length > 0
          const hayIngresos = dia.ingresos_detalle.length > 0
          // Las tres cifras del día salen de la MISMA cuenta con la que el backend
          // cobra. Cuando la cascada no tocó el día dan idénticas a las de siempre,
          // así que el día normal —que son casi todos— se dibuja como se dibujaba.
          const cascada = dia.cascada
          const porConsignar = faltaConsignar(cascada, dia.esperado_consignar, dia.total_consignado)
          const dif = diferenciaEfectiva(cascada, dia.esperado_consignar, dia.total_consignado)
          const ok = diaCuadrado(cascada, dia.esperado_consignar, dia.total_consignado)

          return (
            <div key={dia.key}
              className={`bg-white rounded-2xl border-2 overflow-hidden transition-all ${
                !ok ? 'border-red-200' : pendientes.length > 0 ? 'border-amber-200' : 'border-gray-200'
              }`}>

              {/* Cabecera del día — siempre visible */}
              <button
                className="w-full px-5 py-4 flex items-center gap-4 hover:bg-gray-50 transition-colors text-left"
                onClick={() => setExpandido(abierto ? null : dia.key)}
              >
                {/* Indicador estado */}
                <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                  !ok ? 'bg-red-500' : pendientes.length > 0 ? 'bg-amber-400' : 'bg-green-400'
                }`} />

                {/* Fecha + sede */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-bold text-gray-800 capitalize">{fmtFecha(dia.fecha_apertura)}</p>
                    {sedes.length > 1 && (
                      <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full font-medium">
                        {dia.tienda_nombre}
                      </span>
                    )}
                    {pendientes.length > 0 && (
                      <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-semibold">
                        {pendientes.length} pendiente{pendientes.length !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {dia.n_turnos > 1 && `${dia.n_turnos} turnos · `}Efectivo ventas {fmt(dia.total_efectivo)}
                  </p>

                  {/* La procedencia va en la fila CERRADA, no escondida en el
                      detalle: el dueño baja la lista de un vistazo, y un número
                      que bajó sin decir por qué no se distingue de un bug. */}
                  {cascada.legible && cascada.hubo && (
                    <div className="mt-1 space-y-0.5">
                      {cascada.cubrio.map(l => (
                        <p key={`dio-${l.dia}`} className="text-xs text-amber-700 leading-snug">
                          Cubrió el faltante del {l.dia}{l.fuera ? ' (fuera del periodo)' : ''} · −{fmt(l.monto)}
                        </p>
                      ))}
                      {cascada.cubiertoPor.map(l => (
                        <p key={`rec-${l.dia}`} className="text-xs text-amber-700 leading-snug">
                          Le faltaron {fmt(l.monto)}; los cubrió la venta del {l.dia}{l.fuera ? ' (fuera del periodo)' : ''}
                        </p>
                      ))}
                      {cascada.faltanteSinCubrir > 0.5 && (
                        <p className="text-xs text-red-600 font-semibold leading-snug">
                          Faltaron {fmt(cascada.faltanteSinCubrir)} que ningún día anterior alcanzó a cubrir
                        </p>
                      )}
                    </div>
                  )}
                </div>

                {/* Pendiente / cuadrado */}
                <div className="text-right shrink-0">
                  {porConsignar > 0.5 ? (
                    <>
                      <p className="text-base font-bold text-amber-600">{fmt(porConsignar)}</p>
                      <p className="text-xs text-amber-500">por consignar</p>
                    </>
                  ) : (
                    <p className={`text-base font-bold ${ok ? 'text-green-600' : 'text-red-600'}`}>
                      {ok ? '✓ Al día' : fmt(dif)}
                    </p>
                  )}
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

                    {Math.round(dia.diferencia_cierre ?? 0) !== 0 && (
                      <div className={`flex justify-between ${(dia.diferencia_cierre ?? 0) > 0 ? 'text-green-700' : 'text-red-600'}`}>
                        <span className="text-xs pl-3">{(dia.diferencia_cierre ?? 0) > 0 ? '+' : '−'} Diferencia del cierre</span>
                        <span className="text-xs font-semibold">{fmt(Math.abs(dia.diferencia_cierre ?? 0))}</span>
                      </div>
                    )}

                    {/* EL SOBRANTE DE APERTURA, que hasta acá no se veía en
                        ninguna parte. La fórmula suma cinco términos y este era
                        el único invisible: un martes que pedía $416.800 con
                        $260.115 de venta no tenía cómo explicarse. */}
                    {(dia.sobrante_apertura ?? 0) !== 0 && (
                      <div className="flex justify-between text-amber-700">
                        <span className="text-xs pl-3">+ Sobrante de la apertura</span>
                        <span className="text-xs font-semibold">{fmt(dia.sobrante_apertura ?? 0)}</span>
                      </div>
                    )}

                    <div className="border-t border-gray-200 pt-2 flex justify-between font-bold">
                      <span className="text-gray-700">Debe consignarse</span>
                      <span className="text-blue-700">{fmt(dia.esperado_consignar)}</span>
                    </div>

                    {/* La respuesta a la pregunta que aparece al leer el total:
                        «¿y por qué pide más de lo que vendí?». Si es cero, no
                        ocupa lugar. */}
                    {(dia.en_cajon_no_es_venta ?? 0) !== 0 && (
                      <div className="text-[11px] text-gray-500 pl-3">
                        De eso, {fmt(dia.en_cajon_no_es_venta ?? 0)} no son venta de este día
                      </div>
                    )}

                    {/* La cascada, renglón por renglón. Va DEBAJO del esperado
                        crudo y no en lugar de él: el dueño tiene que poder seguir
                        la cuenta desde la cifra que ya conocía hasta la que le
                        cobra el sistema, sin saltos. */}
                    {cascada.legible && cascada.hubo && (<>
                      {cascada.cubrio.map(l => (
                        <div key={`dio-${l.dia}`} className="flex justify-between gap-2 text-amber-700">
                          <span className="text-xs pl-3 flex items-start gap-1">
                            <CornerDownRight size={12} className="mt-0.5 shrink-0" />
                            Cubrió el faltante del {l.dia}{l.fuera ? ' (fuera del periodo mostrado)' : ''}
                          </span>
                          <span className="text-xs font-semibold whitespace-nowrap">−{fmt(l.monto)}</span>
                        </div>
                      ))}
                      {cascada.cubiertoPor.map(l => (
                        <div key={`rec-${l.dia}`} className="flex justify-between gap-2 text-amber-700">
                          <span className="text-xs pl-3 flex items-start gap-1">
                            <CornerDownRight size={12} className="mt-0.5 shrink-0" />
                            Lo cubrió la venta del {l.dia}{l.fuera ? ' (fuera del periodo mostrado)' : ''}
                          </span>
                          <span className="text-xs font-semibold whitespace-nowrap">+{fmt(l.monto)}</span>
                        </div>
                      ))}
                      {cascada.faltanteSinCubrir > 0.5 && (<>
                        <div className="flex justify-between gap-2 text-red-600">
                          <span className="text-xs pl-3 flex items-start gap-1">
                            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                            Faltó plata y ningún día anterior tenía saldo para cubrirla
                          </span>
                          <span className="text-xs font-semibold whitespace-nowrap">{fmt(cascada.faltanteSinCubrir)}</span>
                        </div>
                        <p className="text-[11px] text-red-600/90 leading-snug pl-6">
                          El sistema deja este monto fuera del saldo por consignar, así que no
                          lo va a volver a pedir. Conviene revisar los egresos en efectivo de
                          ese día contra los soportes.
                        </p>
                      </>)}
                    </>)}

                    <div className="flex justify-between">
                      <span className="text-gray-600">Total consignado</span>
                      <span className="font-semibold text-gray-800">{fmt(dia.total_consignado)}</span>
                    </div>

                    {/* Con cascada el renglón de cierre es «falta consignar» —el
                        número accionable— y no «diferencia», que ahí abajo ya no
                        contesta nada. Sin cascada queda tal cual estaba: los tres
                        términos nuevos valen cero y `dif` da la diferencia vieja. */}
                    {cascada.legible && cascada.hubo ? (
                      <div className="flex justify-between font-bold pt-1 border-t border-gray-200">
                        <span className="text-gray-700">Falta consignar</span>
                        {porConsignar > 0.5 ? (
                          <span className="text-amber-700">{fmt(porConsignar)}</span>
                        ) : ok ? (
                          <span className="text-green-600 flex items-center gap-1">
                            <CheckCircle2 size={14} /> Nada pendiente
                          </span>
                        ) : (
                          <span className="text-red-600 flex items-center gap-1 text-right">
                            <AlertTriangle size={14} className="shrink-0" /> Nada por consignar, pero falta plata
                          </span>
                        )}
                      </div>
                    ) : (
                      <div className={`flex justify-between font-bold pt-1 border-t border-gray-200 ${ok ? 'text-green-600' : 'text-red-600'}`}>
                        <span>Diferencia</span>
                        <span className="flex items-center gap-1">
                          {ok
                            ? <><CheckCircle2 size={14} /> Sin diferencia</>
                            : <><AlertTriangle size={14} /> {fmt(dif)}</>
                          }
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Recogida por el admin — reemplaza la foto del comprobante */}
                  {porConsignar > 0.5 && (
                    <button
                      onClick={() => recoger(dia, porConsignar)}
                      disabled={recogiendo === dia.key}
                      className="w-full flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm font-bold px-4 py-3 rounded-xl transition-colors"
                    >
                      <Banknote size={16} />
                      {recogiendo === dia.key
                        ? 'Registrando...'
                        : `Recogí ${fmt(porConsignar)} — marcar saldado`}
                    </button>
                  )}

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
                          <button onClick={() => editar(c)} disabled={confirmando === c.id}
                            title="Corregir el valor de la consignación"
                            className="flex items-center gap-1 text-blue-500 hover:text-blue-700 hover:bg-blue-50 disabled:opacity-50 text-xs font-semibold px-2 py-1.5 rounded-lg transition-colors shrink-0">
                            <Pencil size={13} />
                          </button>
                          <button onClick={() => eliminar(c)} disabled={confirmando === c.id}
                            title="Revertir consignación (registrada por error)"
                            className="flex items-center gap-1 text-red-500 hover:text-red-700 hover:bg-red-50 disabled:opacity-50 text-xs font-semibold px-2 py-1.5 rounded-lg transition-colors shrink-0">
                            <Trash2 size={13} />
                          </button>
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
              </>
            )
          }
        </>
      )}

      {/* ─── Tab: Flujo por turno ────────────────────────────────────────────── */}
      {tab === 'flujo' && <FlujoPorTurno tiendaId={tiendaId} />}

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
