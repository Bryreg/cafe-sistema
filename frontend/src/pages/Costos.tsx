import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import PagosProveedores from './PagosProveedores'
import ModalRegistrarPago from '../components/plata/ModalRegistrarPago'
import { conMiles, soloDigitos } from '../utils/plata'
import {
  Wallet, Plus, X, Building2, CheckCircle, Clock, AlertCircle,
  Trash2, Receipt, CalendarClock, CalendarDays, Truck, Inbox, Tag,
  TrendingDown, Landmark, Pencil,
} from 'lucide-react'

// ─── Tipos ────────────────────────────────────────────────────────────────────
export interface Categoria { id: number; clave: string; nombre: string; grupo: string }
export interface Tienda { id: number; nombre: string }
export interface Pago {
  id: number; monto: number; fecha_pago: string; metodo: string
  nota: string | null; anulado: boolean
}
export interface Obligacion {
  id: number
  tienda_id: number | null; tienda_nombre: string | null
  categoria_id: number; categoria_clave: string; categoria_nombre: string; categoria_grupo: string
  concepto: string; beneficiario: string | null
  monto: number; pagado: number; saldo: number
  estado: 'pendiente' | 'parcial' | 'pagada' | 'anulada'
  fecha_devengo: string; fecha_vencimiento: string | null
  // Llave de la serie mensual: la escribe «Repetir» y une agosto→septiembre→…
  plantilla_id: number | null
  nota: string | null
  pagos: Pago[]
}
export interface Listado {
  obligaciones: Obligacion[]
  totales: { monto: number; pagado: number; saldo: number; n: number }
}
// Agenda: la unión de facturas de proveedor y costos fijos. El backend nunca copia
// la deuda del proveedor acá — la factura sigue siendo su única verdad.
export interface AgendaItem {
  tipo: 'factura' | 'obligacion'
  id: number
  concepto: string; beneficiario: string | null; referencia: string | null
  tienda_id: number | null; tienda_nombre: string | null
  monto: number                    // el SALDO, no el total
  fecha: string                    // YYYY-MM-DD ya proyectada por el backend
  origen_fecha: string             // programada | vencimiento | plazo
  vencida: boolean
  categoria: string | null         // clave estable ('nomina', 'arriendo'…)
  categoria_nombre: string | null   // lo que se pinta: «Nómina», «Arriendo»
}
// Obligación con saldo y SIN fecha de vencimiento. No se agenda (no hay para
// cuándo) pero tampoco puede ser invisible: «Vence» es opcional en el formulario,
// así que el caso normal terminaba en una pantalla vacía y en la conclusión de
// que el módulo no guarda nada.
export interface AgendaSinFecha extends Omit<AgendaItem, 'fecha'> {
  fecha: null
  fecha_devengo: string
}
export interface GrupoCategoria { clave: string; nombre: string; monto: number; n: number }
export interface Agenda {
  items: AgendaItem[]
  sin_fecha: AgendaSinFecha[]
  por_categoria: GrupoCategoria[]
  totales: { monto: number; vencido: number; n: number; sin_fecha: number; n_sin_fecha: number }
}
// Egresos de caja que el P&L todavía muestra como texto libre. Adoptarlos NO cambia
// ningún total: el movimiento de caja queda intacto y el gasto pasa de "concepto
// suelto" a "categoría". Es puro ordenamiento, no plata nueva.
export interface EgresoSuelto {
  id: number
  concepto: string
  valor: number
  fecha: string | null             // día Colombia en que se TECLEÓ el egreso
  tienda_id: number | null; tienda_nombre: string | null
  barista_nombre: string | null
}
export interface Bandeja {
  egresos: EgresoSuelto[]
  totales: { monto: number; n: number }
}
// Flujo proyectado: el día en que se acaba la plata, ANTES de que pase.
// saldo(D) = caja de hoy + venta esperada acumulada − lo que hay que pagar.
export interface PuntoFlujo {
  fecha: string
  entradas: number                 // venta esperada = MEDIANA del mismo día de semana
  salidas: number                  // saldo de facturas + obligaciones que vencen ese día
  saldo: number                    // acumulado desde la caja de hoy
}
export interface CajaHoy {
  efectivo_registradora: number
  por_tienda: { tienda_id: number; tienda_nombre: string; efectivo: number; origen: string }[]
  // Dato del DUEÑO, no del sistema: acá se registran consignaciones, nunca un saldo bancario.
  saldo_banco: number
  saldo_banco_fecha: string | null
  saldo_banco_desactualizado: boolean
  // false filtrando por sede: la cuenta es de la empresa, no de la sede.
  saldo_banco_incluido: boolean
  total: number
}
// Lo que la proyección NO sabe. Las entradas se derivan solas de cada ticket, pero
// las salidas existen solo si alguien las tecleó: la PRESENCIA de un punto de
// quiebre significa algo, su AUSENCIA sola no significa nada.
export interface AdvertenciasFlujo {
  saldo_banco_desactualizado: boolean
  sin_salidas_cargadas: boolean
  sin_historia_ventas: boolean
  excluye_corporativas: boolean
  corporativas_fuera: number
}
export interface Flujo {
  hoy: string
  dias: number
  caja_hoy: CajaHoy
  serie: PuntoFlujo[]
  punto_de_quiebre: string | null  // null = la proyección nunca cruza cero
  dias_hasta_quiebre: number | null
  advertencias: AdvertenciasFlujo
  totales: { entradas: number; salidas: number; saldo_final: number }
}

const ORIGEN_CAJA: Record<string, string> = {
  turno_abierto: 'turno abierto',
  ultimo_cierre: 'conteo del cierre',   // el dato bueno con la sede cerrada
  ultimo_cuadre: 'último cuadre',       // respaldo: turno cerrado sin conteo
  sin_datos: 'sin datos',
}

const fmt = (v: number) => '$' + Math.round(v || 0).toLocaleString('es-CO')
const fecha = (s: string | null) => (s ? new Date(s + 'T00:00:00').toLocaleDateString('es-CO') : '—')
const hoyISO = () => new Date().toLocaleDateString('en-CA')   // YYYY-MM-DD local

const ESTADO: Record<string, { label: string; cls: string; Icon: typeof CheckCircle }> = {
  pagada:    { label: 'Pagada',    cls: 'bg-green-100 text-green-700', Icon: CheckCircle },
  parcial:   { label: 'Parcial',   cls: 'bg-amber-100 text-amber-700', Icon: Clock },
  pendiente: { label: 'Pendiente', cls: 'bg-red-100 text-red-700',     Icon: AlertCircle },
}

// Sede "Corporativo": el arriendo y la nómina no pertenecen a ninguna sede, así que
// el filtro necesita una opción explícita para ellos (no es lo mismo que "todas").
const CORPORATIVO = 'corp'

// 'proveedores' reusa la pantalla completa de PagosProveedores: la plata que sale
// por proveedor y la que sale por costo fijo son el mismo tema y ahora viven juntas.
// Esa vista trae sus PROPIOS filtros (rango, sede) y datos, así que los del header
// de Costos se apagan mientras esté activa — dos juegos de filtros compitiendo por
// la misma pantalla es peor que ninguno.
//
// 'agenda' ya NO existe: la lista por semanas que vivía acá la reemplazó la grilla
// de mes de Plata·Calendario (components/plata/CalendarioView), que es la pantalla
// que el dueño pidió. Con Costos convertido en panel, Plata lo monta siempre con
// `vistas={[cajon]}` y ningún cajón vale 'agenda', así que esa vista quedó
// inalcanzable: se borró en vez de dejarla como segunda verdad de los mismos datos.
export type Vista = 'obligaciones' | 'sinCategorizar' | 'flujo' | 'proveedores'

const VISTAS: { v: Vista; l: string; Icon: typeof CalendarDays }[] = [
  { v: 'flujo', l: 'Flujo proyectado', Icon: TrendingDown },
  { v: 'obligaciones', l: 'Obligaciones', Icon: Receipt },
  { v: 'proveedores', l: 'Pagos proveedores', Icon: Truck },
  { v: 'sinCategorizar', l: 'Egresos sin categorizar', Icon: Inbox },
]

/**
 * Desde la fusión en «Plata» este componente ya no es una ruta: es el PANEL que
 * Plata monta como drill-down (`vistas` recorta qué pestañas ofrece, `embebido`
 * apaga el título propio para no repetir el header de la página que lo contiene).
 *
 * Se reusa entero a propósito. Las pestañas que Plata no promueve a primer nivel
 * —Obligaciones, Pagos proveedores, Egresos sin categorizar, el detalle del
 * flujo— siguen siendo ESTA pantalla, ya probada: reescribirlas para meterlas en
 * el módulo nuevo sería tirar comportamiento que hoy funciona.
 */
export default function Costos({ vistas, embebido = false }: {
  vistas?: Vista[]
  embebido?: boolean
} = {}) {
  const disponibles = vistas?.length ? VISTAS.filter(o => vistas.includes(o.v)) : VISTAS
  const [vista, setVista] = useState<Vista>(disponibles[0]?.v ?? 'obligaciones')
  const [categorias, setCategorias] = useState<Categoria[]>([])
  const [tiendas, setTiendas] = useState<Tienda[]>([])
  const [data, setData] = useState<Listado | null>(null)
  const [bandeja, setBandeja] = useState<Bandeja | null>(null)
  const [flujo, setFlujo] = useState<Flujo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // editor del saldo del banco (input del dueño: el sistema no puede derivarlo)
  const [bancoAbierto, setBancoAbierto] = useState(false)
  const [bSaldo, setBSaldo] = useState('')
  const [bFecha, setBFecha] = useState(hoyISO())
  const [bError, setBError] = useState('')

  // filtros
  const [sede, setSede] = useState<string>('')          // '' = todas · 'corp' · id de tienda
  const [fCategoria, setFCategoria] = useState('')
  const [fEstado, setFEstado] = useState('')
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')

  // alta de obligación
  const [nuevaAbierta, setNuevaAbierta] = useState(false)
  const [nConcepto, setNConcepto] = useState('')
  const [nCategoria, setNCategoria] = useState('')
  const [nBeneficiario, setNBeneficiario] = useState('')
  const [nMonto, setNMonto] = useState('')
  const [nDevengo, setNDevengo] = useState(hoyISO())
  const [nVencimiento, setNVencimiento] = useState('')
  const [nSede, setNSede] = useState<string>(CORPORATIVO)
  const [nNota, setNNota] = useState('')
  const [nError, setNError] = useState('')

  // registrar pago (el formulario vive en components/plata/ModalRegistrarPago)
  const [pagoDe, setPagoDe] = useState<Obligacion | null>(null)

  // adoptar un egreso suelto
  const [adoptando, setAdoptando] = useState<EgresoSuelto | null>(null)
  const [aCategoria, setACategoria] = useState('')
  const [aDevengo, setADevengo] = useState('')
  const [aError, setAError] = useState('')

  const [guardando, setGuardando] = useState(false)
  const [detalle, setDetalle] = useState<number | null>(null)

  useEffect(() => {
    api.get<Categoria[]>('/costos/categorias')
      .then(r => { setCategorias(r.data); if (r.data.length) setNCategoria(String(r.data[0].id)) })
      .catch(() => {})
    api.get<Tienda[]>('/auth/tiendas').then(r => setTiendas(r.data)).catch(() => {})
  }, [])

  const cargar = () => {
    setLoading(true); setError('')
    const params: Record<string, string | number | boolean> = {}
    if (sede === CORPORATIVO) params.solo_corporativas = true
    else if (sede) params.tienda_id = Number(sede)
    if (fCategoria) params.categoria = fCategoria
    if (fEstado) params.estado = fEstado
    if (desde) params.desde = desde
    if (hasta) params.hasta = hasta
    api.get<Listado>('/costos/obligaciones', { params })
      .then(r => setData(r.data))
      .catch(e => { setData(null); setError(e.response?.data?.detail || 'No se pudieron cargar los costos') })
      .finally(() => setLoading(false))
  }

  const cargarBandeja = () => {
    setLoading(true); setError('')
    const params: Record<string, string | number> = {}
    if (sede && sede !== CORPORATIVO) params.tienda_id = Number(sede)
    if (desde) params.desde = desde
    if (hasta) params.hasta = hasta
    api.get<Bandeja>('/costos/egresos-sin-adoptar', { params })
      .then(r => setBandeja(r.data))
      .catch(e => { setBandeja(null); setError(e.response?.data?.detail || 'No se pudieron cargar los egresos') })
      .finally(() => setLoading(false))
  }

  // El flujo NO usa el rango de fechas del header: su eje es siempre "de hoy en
  // adelante". Un rango que empiece ayer no significaría nada para una proyección.
  const cargarFlujo = () => {
    setLoading(true); setError('')
    const params: Record<string, string | number> = { dias: 30 }
    if (sede && sede !== CORPORATIVO) params.tienda_id = Number(sede)
    api.get<Flujo>('/costos/flujo', { params })
      .then(r => setFlujo(r.data))
      .catch(e => { setFlujo(null); setError(e.response?.data?.detail || 'No se pudo cargar el flujo') })
      .finally(() => setLoading(false))
  }

  // Recarga la vista ACTIVA, sea cual sea. Es lo que va después de cada mutación.
  //
  // El bug que arregla: cada pestaña vive en su propio estado (`data`, `flujo`,
  // `bandeja`) y todos los mutadores llamaban a `cargar()`, que solo llena `data`
  // (Obligaciones). El dueño tecleaba «Arriendo agosto», guardaba, y la pantalla
  // que estuviera abierta seguía igual — para él, el módulo no guardaba nada.
  //
  // Las pestañas inactivas no se refrescan acá porque no hace falta: cambiar de
  // pestaña dispara el efecto de abajo (`vista` es dependencia) y la que se abre
  // se vuelve a pedir siempre.
  const refrescar = () => {
    if (vista === 'proveedores') return   // trae su propio fetch
    if (vista === 'sinCategorizar') cargarBandeja()
    else if (vista === 'flujo') cargarFlujo()
    else cargar()
  }

  useEffect(() => {
    // 'proveedores' se carga sola (trae su propio fetch y sus propios filtros): si
    // cayera en el `else`, pediría obligaciones que nadie va a mostrar y dejaría el
    // spinner de Costos tapando la vista.
    if (vista === 'proveedores') { setLoading(false); setError(''); return }
    refrescar()
  }, [vista, sede, fCategoria, fEstado, desde, hasta])

  const obligaciones = data?.obligaciones ?? []
  const porCategoria = useMemo(() => {
    const acc: Record<string, { nombre: string; monto: number; saldo: number }> = {}
    obligaciones.forEach(o => {
      const g = acc[o.categoria_clave] ?? { nombre: o.categoria_nombre, monto: 0, saldo: 0 }
      g.monto += o.monto; g.saldo += o.saldo
      acc[o.categoria_clave] = g
    })
    return Object.values(acc).sort((a, b) => b.monto - a.monto)
  }, [obligaciones])

  // Escala del gráfico: el mayor valor absoluto de la serie. Con una escala solo
  // sobre los positivos, un saldo muy negativo se saldría del cajón y el día del
  // quiebre —lo único que importa acá— se vería como una barrita cualquiera.
  const escalaFlujo = useMemo(() => {
    const vals = (flujo?.serie ?? []).map(p => Math.abs(p.saldo))
    return Math.max(1, ...vals)
  }, [flujo])
  // Solo los días con movimiento: 30 filas de ceros esconden las 4 que importan.
  const diasConMovimiento = useMemo(
    () => (flujo?.serie ?? []).filter(p => p.entradas > 0 || p.salidas > 0),
    [flujo])

  // Lo que le falta a la proyección para significar algo. Se arma en UN solo lugar
  // porque el mismo listado gobierna el color del banner y su texto: sin salidas
  // cargadas, un verde estaría afirmando una seguridad que nadie verificó.
  type Faltante = { titulo: string; detalle: string; banco?: boolean }
  const faltantes = useMemo<Faltante[]>(() => {
    const a = flujo?.advertencias
    if (!flujo || !a) return []
    const items: Faltante[] = []
    if (a.sin_salidas_cargadas) items.push({
      titulo: `No hay pagos cargados en los próximos ${flujo.dias} días`,
      detalle: 'Si tenés cuentas por pagar —arriendo, nómina, proveedores—, cargalas para que '
        + 'esta proyección signifique algo. Como está, solo sabe de la plata que entra.',
    })
    if (a.sin_historia_ventas) items.push({
      titulo: 'No hay ventas de las últimas 8 semanas para estimar lo que entra',
      detalle: 'La proyección está asumiendo que no entra un peso. Con ventas registradas, cada '
        + 'día toma la mediana de su mismo día de la semana.',
    })
    if (a.excluye_corporativas) items.push({
      titulo: `Esta sede no incluye ${fmt(a.corporativas_fuera)} de gastos corporativos`,
      detalle: 'El arriendo y la nómina no pertenecen a ninguna sede, así que quedan afuera — y '
        + 'el saldo del banco tampoco suma acá, porque la cuenta es de la empresa. Sacá el filtro '
        + 'de sede para ver el negocio completo.',
    })
    if (a.saldo_banco_desactualizado) items.push({
      titulo: flujo.caja_hoy.saldo_banco_fecha
        ? `El saldo del banco es del ${fecha(flujo.caja_hoy.saldo_banco_fecha)}`
        : 'Todavía no cargaste el saldo del banco',
      detalle: 'El sistema registra las consignaciones pero nunca el saldo de la cuenta: ese '
        + 'número lo tenés que mirar vos. Mientras esté viejo, la proyección arranca de una plata '
        + 'que puede no ser la que hay.',
      banco: true,
    })
    return items
  }, [flujo])

  const limpiarNueva = () => {
    setNConcepto(''); setNBeneficiario(''); setNMonto('')
    setNDevengo(hoyISO()); setNVencimiento(''); setNNota(''); setNError('')
  }

  const crearObligacion = async () => {
    if (!nConcepto.trim()) { setNError('Poné un concepto'); return }
    if (!(Number(nMonto) > 0)) { setNError('El monto tiene que ser mayor a 0'); return }
    if (!nDevengo) { setNError('Elegí la fecha de devengo'); return }
    setGuardando(true); setNError('')
    try {
      await api.post('/costos/obligaciones', {
        categoria_id: Number(nCategoria),
        concepto: nConcepto.trim(),
        beneficiario: nBeneficiario.trim() || null,
        monto: Number(nMonto),
        fecha_devengo: nDevengo,
        fecha_vencimiento: nVencimiento || null,
        // Corporativo = sin sede: es el caso del arriendo y la nómina.
        tienda_id: nSede === CORPORATIVO ? null : Number(nSede),
        nota: nNota.trim() || null,
      })
      setNuevaAbierta(false); limpiarNueva(); refrescar()
    } catch (e: any) {
      setNError(e.response?.data?.detail || 'No se pudo guardar. Reintentá.')
    } finally { setGuardando(false) }
  }

  // A5: la copia del mes que viene en un tap, en vez de retipear 12-18 costos por
  // mes entre las dos sedes. El backend es idempotente por serie y mes, así que
  // un doble clic no cobra el arriendo dos veces — lo dice con `ya_existia`.
  const repetirObligacion = async (o: Obligacion) => {
    if (!window.confirm(
      `¿Crear «${o.concepto}» para el mes que viene por ${fmt(o.monto)}?\n\n`
      + 'Se copia con el devengo y el vencimiento un mes más adelante. Después la '
      + 'podés editar si el monto cambió.')) return
    setGuardando(true)
    try {
      const { data: copia } = await api.post<Obligacion & { ya_existia: boolean }>(
        `/costos/obligaciones/${o.id}/repetir`)
      if (copia.ya_existia) alert(`Ya existía: «${copia.concepto}» del ${fecha(copia.fecha_devengo)}. No se duplicó.`)
      refrescar()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'No se pudo repetir')
    } finally { setGuardando(false) }
  }

  const anularObligacion = async (o: Obligacion) => {
    if (!window.confirm(`¿Anular «${o.concepto}» por ${fmt(o.monto)}?\n\nSale de la lista y de los totales. Los pagos ya registrados quedan como traza.`)) return
    try { await api.delete(`/costos/obligaciones/${o.id}`); refrescar() }
    catch (e: any) { alert(e.response?.data?.detail || 'No se pudo anular') }
  }

  const anularPago = async (p: Pago) => {
    if (!window.confirm(`¿Anular el pago de ${fmt(p.monto)} del ${fecha(p.fecha_pago)}?`)) return
    try { await api.delete(`/costos/pagos/${p.id}`); refrescar() }
    catch (e: any) { alert(e.response?.data?.detail || 'No se pudo anular el pago') }
  }

  const abrirEditorBanco = () => {
    setBSaldo(String(Math.round(flujo?.caja_hoy.saldo_banco ?? 0)))
    setBFecha(hoyISO())
    setBError('')
    setBancoAbierto(true)
  }

  const guardarSaldoBanco = async () => {
    const saldo = Number(bSaldo)
    if (!Number.isFinite(saldo) || saldo < 0) { setBError('Poné un saldo válido (0 o más)'); return }
    setGuardando(true); setBError('')
    try {
      await api.post('/costos/saldo-banco', { saldo, fecha: bFecha })
      setBancoAbierto(false); cargarFlujo()
    } catch (e: any) {
      setBError(e.response?.data?.detail || 'No se pudo guardar. Reintentá.')
    } finally { setGuardando(false) }
  }

  const abrirAdopcion = (e: EgresoSuelto) => {
    setAdoptando(e)
    setACategoria(categorias.length ? String(categorias[0].id) : '')
    // Arranca en el día en que se tecleó el egreso; el admin lo corrige si el costo
    // era de otro mes (y eso mueve el mes en el P&L, así que se avisa en el modal).
    setADevengo(e.fecha || hoyISO())
    setAError('')
  }

  const adoptarEgreso = async () => {
    if (!adoptando) return
    if (!aCategoria) { setAError('Elegí la categoría del gasto'); return }
    if (!aDevengo) { setAError('Poné a qué día pertenece el costo'); return }
    setGuardando(true); setAError('')
    try {
      await api.post(`/costos/egresos/${adoptando.id}/adoptar`, {
        categoria_id: Number(aCategoria),
        fecha_devengo: aDevengo,
      })
      // Adoptar CREA una obligación devengada + su pago espejo: no alcanza con
      // vaciar la bandeja, la agenda y el P&L también cambiaron.
      setAdoptando(null); refrescar()
    } catch (e: any) {
      setAError(e.response?.data?.detail || 'No se pudo adoptar. Reintentá.')
    } finally { setGuardando(false) }
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        {!embebido && (
          <div className="flex items-center gap-2">
            <Wallet size={20} className="text-forest" />
            <h1 className="text-lg font-bold text-gray-800">Costos</h1>
          </div>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {/* El flujo no lleva rango (su eje es "de hoy en adelante") y proveedores
              trae el suyo propio. */}
          {vista !== 'flujo' && vista !== 'proveedores' && (<>
            <input type="date" value={desde} onChange={e => setDesde(e.target.value)}
              title="Devengo desde"
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm bg-white" />
            <span className="text-gray-400 text-sm">→</span>
            <input type="date" value={hasta} onChange={e => setHasta(e.target.value)}
              title="Devengo hasta"
              className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm bg-white" />
          </>)}
          {/* Fuera de la bandeja de egresos: ahí la acción es ADOPTAR el gasto que
              ya existe, y ofrecer "crear uno nuevo" al lado invita a cargarlo dos veces. */}
          {vista !== 'proveedores' && vista !== 'sinCategorizar' && (
            <button onClick={() => { limpiarNueva(); setNuevaAbierta(true) }}
              className="flex items-center gap-1.5 text-sm font-bold text-white bg-forest hover:bg-forest-700 px-3 py-1.5 rounded-lg">
              <Plus size={15} /> Nueva obligación
            </button>
          )}
        </div>
      </div>

      {/* Vistas. Con UNA sola disponible el selector no se dibuja: como drill-down
          de Plata sería una pestaña de un solo botón, o sea ruido puro. */}
      {disponibles.length > 1 && (
      <div className="flex items-center gap-1 bg-gray-100 rounded-xl p-1 w-fit">
        {disponibles.map(op => (
          <button key={op.v}
            onClick={() => {
              // "Corporativo" no es un filtro válido acá: caen a todas las sedes.
              if (op.v !== 'obligaciones' && sede === CORPORATIVO) setSede('')
              setVista(op.v)
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-semibold transition-colors ${
              vista === op.v ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}>
            <op.Icon size={14} /> {op.l}
          </button>
        ))}
      </div>
      )}

      {/* Sede (con la opción explícita Corporativo, que solo aplica a la lista).
          Proveedores trae su propio selector de sede: mostrar dos sería mentir
          sobre cuál manda. */}
      <div className={`flex items-center gap-2 flex-wrap ${vista === 'proveedores' ? 'hidden' : ''}`}>
        {[{ v: '', l: 'Todas las sedes' },
          ...(vista === 'obligaciones' ? [{ v: CORPORATIVO, l: 'Corporativo' }] : []),
          ...tiendas.map(t => ({ v: String(t.id), l: t.nombre }))].map(op => (
          <button key={op.v || 'todas'} onClick={() => setSede(op.v)}
            className={`px-3 py-1.5 rounded-xl text-sm font-semibold transition-colors ${
              sede === op.v ? 'bg-forest text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'
            }`}>{op.l}</button>
        ))}
      </div>

      {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">{error}</p>}
      {loading && <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando…</p>}

      {/* ─── PAGOS A PROVEEDORES (la pantalla completa, reusada) ────────────── */}
      {vista === 'proveedores' && <PagosProveedores embebido />}

      {/* ─── FLUJO PROYECTADO ───────────────────────────────────────────────── */}
      {vista === 'flujo' && !loading && flujo && (
        <>
          {/* Punto de quiebre: es EL número de esta pantalla, así que va primero
              y ocupa el ancho — no una tarjetita más en una grilla de cuatro.

              Tres estados, no dos: rojo (hay quiebre), ÁMBAR (no hay quiebre pero
              faltan datos para afirmar nada) y verde (no hay quiebre y los datos
              están). El verde solo aparece cuando de verdad se puede sostener. */}
          <div className={`rounded-2xl border p-4 ${
            flujo.punto_de_quiebre ? 'border-red-200 bg-red-50'
              : faltantes.length > 0 ? 'border-amber-200 bg-amber-50'
              : 'border-green-200 bg-green-50'
          }`}>
            <div className="flex items-start gap-3">
              {flujo.punto_de_quiebre
                ? <TrendingDown size={22} className="text-red-600 mt-0.5 shrink-0" />
                : faltantes.length > 0
                ? <AlertCircle size={22} className="text-amber-600 mt-0.5 shrink-0" />
                : <CheckCircle size={22} className="text-green-600 mt-0.5 shrink-0" />}
              <div className="min-w-0">
                {flujo.punto_de_quiebre ? (<>
                  <p className="text-sm font-bold text-red-700">
                    Te quedás sin plata el {fecha(flujo.punto_de_quiebre)}
                    {flujo.dias_hasta_quiebre != null && (
                      <span className="font-semibold"> — en {flujo.dias_hasta_quiebre} día{flujo.dias_hasta_quiebre !== 1 ? 's' : ''}</span>
                    )}
                  </p>
                  <p className="text-xs text-red-600/90 mt-0.5 leading-relaxed">
                    Con lo que hay en caja hoy, lo que se espera vender y lo que hay que pagar,
                    ese día el saldo se va a negativo. Movés la fecha pagando algo más tarde
                    o consiguiendo plata antes.
                  </p>
                </>) : faltantes.length > 0 ? (<>
                  <p className="text-sm font-bold text-amber-800">
                    Falta información para saber si estás bien
                  </p>
                  <p className="text-xs text-amber-700/90 mt-0.5 leading-relaxed">
                    La proyección no encontró ningún día en rojo, pero eso no alcanza para
                    afirmar nada: lo que entra lo calcula sola con tus ventas, lo que sale
                    solo existe si alguien lo cargó. Esto es lo que falta:
                  </p>
                </>) : (<>
                  <p className="text-sm font-bold text-green-700">
                    No te quedás sin plata en los próximos {flujo.dias} días
                  </p>
                  <p className="text-xs text-green-700/80 mt-0.5">
                    El saldo proyectado nunca cruza cero. Terminás el período con {fmt(flujo.totales.saldo_final)}.
                  </p>
                </>)}
              </div>
            </div>
          </div>

          {/* Lo que falta va acá arriba y no al pie: enterrarlo es exactamente lo
              que convierte un "no sé" en un "estás bien". */}
          {faltantes.map((f, i) => (
            <div key={i}
              className="flex items-start gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
              <AlertCircle size={16} className="text-amber-700 mt-0.5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-bold text-amber-800">{f.titulo}</p>
                <p className="text-xs text-amber-700/90 mt-0.5 leading-relaxed">{f.detalle}</p>
              </div>
              {f.banco && (
                <button onClick={abrirEditorBanco}
                  className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 px-3 py-1.5 rounded-lg">
                  <Pencil size={12} /> Actualizar
                </button>
              )}
            </div>
          ))}

          {/* Con cuánta plata arranca la proyección */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Plata hoy</p>
              <p className="text-xl font-bold text-gray-800 font-mono">{fmt(flujo.caja_hoy.total)}</p>
              <p className="text-xs text-gray-400">
                {flujo.caja_hoy.saldo_banco_incluido ? 'Caja + banco' : 'Solo la caja de esta sede'}
              </p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">En la registradora</p>
              <p className="text-xl font-bold text-gray-800 font-mono">{fmt(flujo.caja_hoy.efectivo_registradora)}</p>
              <div className="space-y-0.5 mt-1">
                {flujo.caja_hoy.por_tienda.map(t => (
                  <div key={t.tienda_id} className="flex items-center justify-between text-[11px]">
                    <span className="text-gray-500 truncate">{t.tienda_nombre}</span>
                    <span className="font-mono text-gray-600 shrink-0 ml-2">
                      {fmt(t.efectivo)} <span className="text-gray-400">· {ORIGEN_CAJA[t.origen] ?? t.origen}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <button onClick={abrirEditorBanco}
              className="bg-white rounded-2xl border border-gray-200 p-4 text-left hover:border-forest transition-colors">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1 flex items-center gap-1">
                <Landmark size={12} /> En el banco
              </p>
              <p className={`text-xl font-bold font-mono ${
                flujo.caja_hoy.saldo_banco_desactualizado && flujo.caja_hoy.saldo_banco_incluido
                  ? 'text-amber-600'
                  : !flujo.caja_hoy.saldo_banco_incluido ? 'text-gray-400' : 'text-gray-800'}`}>
                {fmt(flujo.caja_hoy.saldo_banco)}
              </p>
              <p className="text-xs text-gray-400 flex items-center gap-1">
                {flujo.caja_hoy.saldo_banco_fecha
                  ? `Declarado el ${fecha(flujo.caja_hoy.saldo_banco_fecha)}`
                  : 'Sin declarar'}
                <Pencil size={10} />
              </p>
              {/* La cuenta es de la empresa: en la vista de una sede se muestra
                  pero NO suma, y decirlo acá evita leer un total que no existe. */}
              {!flujo.caja_hoy.saldo_banco_incluido && (
                <p className="text-[11px] text-gray-400 mt-0.5 leading-snug">
                  No entra en esta vista: la cuenta es de la empresa, no de la sede
                </p>
              )}
            </button>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Próximos {flujo.dias} días</p>
              <p className="text-sm font-mono font-bold text-green-700">+ {fmt(flujo.totales.entradas)}</p>
              <p className="text-sm font-mono font-bold text-red-600">− {fmt(flujo.totales.salidas)}</p>
              <p className="text-xs text-gray-400 mt-0.5">Entra / sale</p>
            </div>
          </div>

          {/* Serie diaria. Barras hacia abajo = saldo negativo. */}
          <div className="bg-white rounded-2xl border border-gray-200 p-4">
            <p className="text-sm font-bold text-gray-700 mb-3">Saldo proyectado día a día</p>
            <div className="flex items-stretch gap-[3px] overflow-x-auto pb-1" style={{ minHeight: 132 }}>
              {flujo.serie.map(p => {
                const alto = Math.round((Math.abs(p.saldo) / escalaFlujo) * 56)
                const neg = p.saldo < 0
                const esQuiebre = p.fecha === flujo.punto_de_quiebre
                return (
                  <div key={p.fecha} className="flex flex-col items-center justify-center flex-1 min-w-[13px]"
                    title={`${fecha(p.fecha)}\nSaldo: ${fmt(p.saldo)}\nEntra: ${fmt(p.entradas)}\nSale: ${fmt(p.salidas)}`}>
                    <div className="flex flex-col justify-end" style={{ height: 60 }}>
                      {!neg && <div className="w-full rounded-t"
                        style={{ height: alto, minHeight: 2, background: esQuiebre ? '#dc2626' : '#5c7a4e' }} />}
                    </div>
                    <div className="w-full border-t border-gray-200" />
                    <div className="flex flex-col justify-start" style={{ height: 60 }}>
                      {neg && <div className="w-full rounded-b"
                        style={{ height: alto, minHeight: 2, background: esQuiebre ? '#dc2626' : '#f87171' }} />}
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="flex items-center justify-between text-[11px] text-gray-400 mt-1">
              <span>{fecha(flujo.serie[0]?.fecha ?? null)}</span>
              <span>{fecha(flujo.serie[flujo.serie.length - 1]?.fecha ?? null)}</span>
            </div>
            <p className="text-[11px] text-gray-400 mt-2 leading-relaxed">
              La venta esperada de cada día es la <b>mediana</b> del mismo día de la semana en las
              últimas 8 semanas — no el promedio, para que un solo día raro no infle la proyección.
              Todo lo que ya está vencido se carga entero a mañana: se debe ahora.
            </p>
          </div>

          {/* Detalle de los días que mueven la aguja */}
          <div className="bg-white rounded-2xl border border-gray-200">
            <p className="text-sm font-bold text-gray-700 px-4 py-2.5 border-b border-gray-100">
              Días con movimiento
            </p>
            <div className="divide-y divide-gray-50">
              {diasConMovimiento.map(p => (
                <div key={p.fecha}
                  className={`flex items-center gap-3 px-4 py-2.5 ${p.fecha === flujo.punto_de_quiebre ? 'bg-red-50/60' : ''}`}>
                  <span className="text-xs text-gray-500 w-24 shrink-0">{fecha(p.fecha)}</span>
                  <span className="font-mono text-xs text-green-700 w-24 shrink-0 text-right">
                    {p.entradas > 0 ? `+ ${fmt(p.entradas)}` : ''}
                  </span>
                  <span className="font-mono text-xs text-red-600 w-24 shrink-0 text-right">
                    {p.salidas > 0 ? `− ${fmt(p.salidas)}` : ''}
                  </span>
                  <span className={`font-mono text-sm font-bold ml-auto ${p.saldo < 0 ? 'text-red-600' : 'text-gray-800'}`}>
                    {fmt(p.saldo)}
                  </span>
                </div>
              ))}
              {diasConMovimiento.length === 0 && (
                <p className="px-4 py-8 text-center text-sm text-gray-500">
                  No hay ni ventas esperadas ni pagos agendados en el período
                </p>
              )}
            </div>
          </div>
        </>
      )}

      {/* ─── EGRESOS SIN CATEGORIZAR ────────────────────────────────────────── */}
      {vista === 'sinCategorizar' && !loading && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Sin categorizar</p>
              <p className="text-xl font-bold text-gray-800 font-mono">{fmt(bandeja?.totales.monto ?? 0)}</p>
              <p className="text-xs text-gray-400">{bandeja?.totales.n ?? 0} egresos de caja</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4 col-span-2 lg:col-span-2">
              <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Qué hace adoptar</p>
              <p className="text-xs text-gray-500 leading-relaxed">
                Estos son egresos que se registraron en caja con texto libre. Al adoptarlos les
                ponés una categoría y una fecha de devengo: el gasto deja de aparecer suelto en
                el P&amp;L y pasa a contar como categoría. <b>El movimiento de caja no se toca</b> —
                el cuadre del turno y el total de gastos del período quedan exactamente iguales.
              </p>
            </div>
          </div>

          <div className="space-y-2">
            {(bandeja?.egresos ?? []).map(e => (
              <div key={e.id} className="bg-white border border-gray-200 rounded-2xl p-4 flex items-center gap-3 flex-wrap">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-bold text-gray-800 truncate">{e.concepto}</p>
                  <p className="text-[11px] text-gray-400 truncate">
                    {e.tienda_nombre || 'Sin sede'} · registrado {fecha(e.fecha)}
                    {e.barista_nombre ? ` · ${e.barista_nombre}` : ''}
                  </p>
                </div>
                <span className="font-mono font-bold text-sm text-gray-800 shrink-0">{fmt(e.valor)}</span>
                <button onClick={() => abrirAdopcion(e)}
                  className="flex items-center gap-1.5 text-xs font-bold text-white bg-forest hover:bg-forest-700 px-3 py-1.5 rounded-lg shrink-0">
                  <Tag size={13} /> Adoptar
                </button>
              </div>
            ))}
            {(bandeja?.egresos.length ?? 0) === 0 && !error && (
              <div className="bg-white border border-gray-200 rounded-2xl px-4 py-10 text-center">
                <Inbox size={26} className="text-gray-300 mx-auto mb-2" />
                <p className="text-sm text-gray-500">No hay egresos sueltos para categorizar</p>
                <p className="text-xs text-gray-400 mt-1">
                  Los pagos a proveedor no aparecen acá: ya están contados dentro de Compras.
                </p>
              </div>
            )}
          </div>
        </>
      )}

      {/* ─── OBLIGACIONES ───────────────────────────────────────────────────── */}
      {vista === 'obligaciones' && !loading && (<>
      {/* Totales */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Total causado</p>
          <p className="text-xl font-bold text-gray-800 font-mono">{fmt(data?.totales.monto ?? 0)}</p>
          <p className="text-xs text-gray-400">{data?.totales.n ?? 0} obligaciones</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Ya pagado</p>
          <p className="text-xl font-bold text-green-700 font-mono">{fmt(data?.totales.pagado ?? 0)}</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Saldo pendiente</p>
          <p className="text-xl font-bold text-red-600 font-mono">{fmt(data?.totales.saldo ?? 0)}</p>
        </div>
        <div className="bg-white rounded-2xl border border-gray-200 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400 mb-1">Por categoría</p>
          {/* Todas, no las 3 primeras: si el arriendo queda cuarto, la pantalla que
              tenía que responder «cuánto de arriendo» lo esconde. */}
          <div className="space-y-0.5 mt-1 max-h-28 overflow-y-auto">
            {porCategoria.map(c => (
              <div key={c.nombre} className="flex items-center justify-between text-xs">
                <span className="text-gray-600 truncate">{c.nombre}</span>
                <span className="font-mono text-gray-700 shrink-0 ml-2">{fmt(c.monto)}</span>
              </div>
            ))}
            {porCategoria.length === 0 && <p className="text-xs text-gray-400">Sin datos</p>}
          </div>
        </div>
      </div>

      {/* Filtros de lista */}
      <div className="flex flex-wrap items-center gap-2">
        <select value={fCategoria} onChange={e => setFCategoria(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">Todas las categorías</option>
          {categorias.map(c => <option key={c.id} value={c.clave}>{c.nombre}</option>)}
        </select>
        <select value={fEstado} onChange={e => setFEstado(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          <option value="">Todo estado</option>
          <option value="pendiente">Pendiente</option>
          <option value="parcial">Parcial</option>
          <option value="pagada">Pagada</option>
          <option value="anulada">Anuladas</option>
        </select>
      </div>

      {/* Lista */}
      {!error && (
        <div className="space-y-2">
          {obligaciones.map(o => {
            const e = ESTADO[o.estado] ?? ESTADO.pendiente
            const pagosVivos = o.pagos.filter(p => !p.anulado)
            return (
              <div key={o.id} className="bg-white border border-gray-200 rounded-2xl p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-sm font-bold text-gray-800 truncate">{o.concepto}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {o.categoria_nombre} · {o.tienda_nombre || 'Corporativo'}
                      {o.beneficiario ? ` · ${o.beneficiario}` : ''}
                    </p>
                  </div>
                  <span className={`text-[11px] px-2 py-0.5 rounded-full font-bold flex items-center gap-1 shrink-0 ${e.cls}`}>
                    <e.Icon size={11} /> {e.label}
                  </span>
                </div>

                <div className="flex items-center gap-3 mt-1.5 text-sm flex-wrap">
                  <span className="text-gray-500">Monto: <span className="font-mono font-bold text-gray-800">{fmt(o.monto)}</span></span>
                  <span className="text-gray-500">Pagado: <span className="font-mono font-bold text-green-700">{fmt(o.pagado)}</span></span>
                  {o.saldo > 0 && <span className="text-gray-500">Saldo: <span className="font-mono font-bold text-red-600">{fmt(o.saldo)}</span></span>}
                </div>
                <p className="text-xs text-gray-400 mt-1 flex items-center gap-1">
                  <CalendarClock size={12} /> Devengo {fecha(o.fecha_devengo)}
                  {o.fecha_vencimiento ? ` · vence ${fecha(o.fecha_vencimiento)}` : ''}
                </p>

                {pagosVivos.length > 0 && (
                  <div className="mt-2">
                    <button onClick={() => setDetalle(d => (d === o.id ? null : o.id))}
                      className="text-xs font-semibold text-gray-500 hover:text-gray-700">
                      {detalle === o.id ? '▾' : '▸'} Pagos ({pagosVivos.length})
                    </button>
                    {detalle === o.id && (
                      <div className="mt-1.5 ml-3 pl-3 border-l-2 border-gray-100 space-y-1">
                        {pagosVivos.map(p => (
                          <div key={p.id} className="flex items-center justify-between gap-2 text-xs">
                            <span className="text-gray-600 truncate">
                              {fecha(p.fecha_pago)} · {p.metodo}{p.nota ? ` · ${p.nota}` : ''}
                            </span>
                            <span className="flex items-center gap-2 shrink-0">
                              <span className="font-mono font-semibold text-gray-800">{fmt(p.monto)}</span>
                              <button onClick={() => anularPago(p)} title="Anular pago"
                                className="text-red-400 hover:text-red-600"><X size={12} /></button>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {o.estado !== 'anulada' && (
                  <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-50 flex-wrap">
                    {o.saldo > 0 && (
                      <button onClick={() => setPagoDe(o)}
                        className="flex items-center gap-1.5 text-xs font-bold text-white bg-forest hover:bg-forest-700 px-3 py-1.5 rounded-lg">
                        <Wallet size={13} /> Registrar pago
                      </button>
                    )}
                    {/* A5: la copia del mes que viene en un tap. Sin esto, con dos
                        sedes son 12-18 cargas manuales por mes retecleando lo mismo. */}
                    <button onClick={() => repetirObligacion(o)} disabled={guardando}
                      title="Crear la copia del mes siguiente (idempotente: no duplica)"
                      className="flex items-center gap-1.5 text-xs font-bold text-forest bg-forest/10 hover:bg-forest/20 disabled:opacity-40 px-3 py-1.5 rounded-lg">
                      <CalendarDays size={13} /> Repetir mes que viene
                    </button>
                    {!o.fecha_vencimiento && (
                      <span className="flex items-center gap-1 text-[11px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-1 rounded-lg">
                        <AlertCircle size={11} /> Sin fecha de pago
                      </span>
                    )}
                    <button onClick={() => anularObligacion(o)}
                      title="Anular (baja lógica: no borra los pagos)"
                      className="ml-auto flex items-center gap-1 text-xs font-semibold text-red-500 hover:text-red-700 px-2 py-1 rounded-lg border border-red-100 hover:border-red-300">
                      <Trash2 size={12} /> Anular
                    </button>
                  </div>
                )}
              </div>
            )
          })}
          {obligaciones.length === 0 && (
            <div className="bg-white border border-gray-200 rounded-2xl px-4 py-10 text-center">
              <Receipt size={26} className="text-gray-300 mx-auto mb-2" />
              <p className="text-sm text-gray-500">No hay obligaciones con esos filtros</p>
              <p className="text-xs text-gray-400 mt-1">Registrá acá el arriendo, la nómina y los servicios — aunque se paguen fuera del turno.</p>
            </div>
          )}
        </div>
      )}
      </>)}

      {/* Modal nueva obligación */}
      {nuevaAbierta && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4" onClick={() => setNuevaAbierta(false)}>
          <div className="bg-white rounded-2xl w-full max-w-lg p-5 space-y-4 max-h-[90vh] overflow-y-auto" onClick={ev => ev.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-gray-800">Nueva obligación</h3>
              <button onClick={() => setNuevaAbierta(false)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Concepto</label>
              <input value={nConcepto} onChange={ev => setNConcepto(ev.target.value)}
                placeholder="Arriendo agosto, energía, nómina quincena…"
                className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-forest" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Categoría</label>
                <select value={nCategoria} onChange={ev => setNCategoria(ev.target.value)}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:border-forest">
                  {categorias.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Monto</label>
                <input type="text" inputMode="numeric" value={conMiles(nMonto)}
                  onChange={ev => setNMonto(soloDigitos(ev.target.value))}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-base font-bold font-mono focus:outline-none focus:border-forest" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Fecha de devengo</label>
                <input type="date" value={nDevengo} onChange={ev => setNDevengo(ev.target.value)}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-forest" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Vence (opcional)</label>
                <input type="date" value={nVencimiento} onChange={ev => setNVencimiento(ev.target.value)}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-forest" />
                {/* Se avisa EN EL MOMENTO, no después: sin fecha el costo se guarda
                    igual y cuenta en el P&L, pero queda fuera de la agenda y de la
                    proyección. Enterarse recién al ver la agenda vacía es lo que
                    hace pensar que el módulo no guardó nada. */}
                {!nVencimiento && (
                  <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1.5 mt-1 flex items-start gap-1.5">
                    <AlertCircle size={12} className="mt-0.5 shrink-0" />
                    <span>Sin fecha se guarda igual, pero no va a aparecer en la agenda ni en la
                      proyección: queda en «Sin fecha de pago» hasta que le pongas una.</span>
                  </p>
                )}
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Beneficiario (opcional)</label>
                <input value={nBeneficiario} onChange={ev => setNBeneficiario(ev.target.value)}
                  placeholder="A quién se le paga"
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-forest" />
              </div>
              <div>
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Sede</label>
                <select value={nSede} onChange={ev => setNSede(ev.target.value)}
                  className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:border-forest">
                  <option value={CORPORATIVO}>Corporativo / todas las sedes</option>
                  {tiendas.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
                </select>
              </div>
            </div>
            <p className="text-[11px] text-gray-400 -mt-1 flex items-start gap-1">
              <Building2 size={12} className="mt-0.5 shrink-0" />
              La fecha de devengo es el mes al que pertenece el costo. Si el gasto no es de una sede
              puntual (arriendo, nómina), dejalo en Corporativo.
            </p>

            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Nota (opcional)</label>
              <input value={nNota} onChange={ev => setNNota(ev.target.value)}
                className="w-full border-2 border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-forest" />
            </div>

            {nError && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">{nError}</p>}
            <button onClick={crearObligacion} disabled={guardando}
              className="w-full bg-forest hover:bg-forest-700 disabled:opacity-50 text-white font-bold py-2.5 rounded-xl">
              {guardando ? 'Guardando…' : 'Guardar obligación'}
            </button>
          </div>
        </div>
      )}

      {/* Modal adoptar egreso */}
      {adoptando && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setAdoptando(null)}>
          <div className="bg-white rounded-2xl w-full max-w-sm p-5 space-y-4" onClick={ev => ev.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-gray-800">Adoptar egreso</h2>
              <button onClick={() => setAdoptando(null)} className="text-gray-400"><X size={18} /></button>
            </div>
            <div className="text-sm text-gray-500">
              <p className="font-semibold text-gray-700">{adoptando.concepto}</p>
              <p>Monto: <span className="font-mono font-bold text-gray-800">{fmt(adoptando.valor)}</span>
                {adoptando.tienda_nombre ? ` · ${adoptando.tienda_nombre}` : ''}</p>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Categoría</label>
              <select value={aCategoria} onChange={ev => setACategoria(ev.target.value)}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-2.5 text-sm bg-white focus:outline-none focus:border-forest">
                {categorias.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
              </select>
            </div>

            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">A qué día pertenece el costo</label>
              <input type="date" value={aDevengo} onChange={ev => setADevengo(ev.target.value)}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-forest" />
              <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-2 mt-1.5 flex items-start gap-1.5">
                <AlertCircle size={13} className="mt-0.5 shrink-0" />
                <span>
                  Viene del día en que se <b>tecleó</b> el egreso en caja, que no siempre es el mes
                  al que pertenece el gasto. Si lo corregís, el costo <b>se mueve de mes</b> en el P&amp;L.
                </span>
              </p>
            </div>

            <p className="text-[11px] text-gray-400 leading-relaxed">
              El movimiento de caja queda intacto: el cuadre del turno y el total de gastos del
              período no cambian. El gasto solo deja de verse como texto libre.
            </p>

            {aError && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">{aError}</p>}
            <button onClick={adoptarEgreso} disabled={guardando || !aCategoria || !aDevengo}
              className="w-full bg-forest hover:bg-forest-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm">
              {guardando ? 'Guardando...' : 'Adoptar como obligación'}
            </button>
          </div>
        </div>
      )}

      {/* Modal saldo del banco */}
      {bancoAbierto && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setBancoAbierto(false)}>
          <div className="bg-white rounded-2xl w-full max-w-sm p-5 space-y-4" onClick={ev => ev.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-gray-800 flex items-center gap-2"><Landmark size={17} /> Saldo del banco</h2>
              <button onClick={() => setBancoAbierto(false)} className="text-gray-400"><X size={18} /></button>
            </div>
            <p className="text-xs text-gray-500 leading-relaxed">
              Abrí la app del banco y copiá el saldo de la cuenta. El sistema registra las
              consignaciones que hacen las baristas, pero no tiene forma de saber cuánta plata
              hay en la cuenta: sin este dato la proyección arranca incompleta.
            </p>
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">Saldo</label>
              <input type="text" inputMode="numeric" value={conMiles(bSaldo)}
                onChange={ev => setBSaldo(soloDigitos(ev.target.value))}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-2.5 text-lg font-bold font-mono focus:outline-none focus:border-forest" />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide block mb-1">¿De qué día es?</label>
              <input type="date" value={bFecha} max={hoyISO()} onChange={ev => setBFecha(ev.target.value)}
                className="w-full border-2 border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-forest" />
              <p className="text-[11px] text-gray-400 mt-1">
                Si el saldo es del extracto del viernes, poné el viernes. Pasada una semana
                la proyección te avisa que el dato está viejo.
              </p>
            </div>
            {bError && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">{bError}</p>}
            <button onClick={guardarSaldoBanco} disabled={guardando || !bFecha}
              className="w-full bg-forest hover:bg-forest-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm">
              {guardando ? 'Guardando...' : 'Guardar saldo'}
            </button>
          </div>
        </div>
      )}

      {/* Registrar pago: MISMO componente que usa Plata·Calendario. `key` fuerza el
          montaje limpio que su estado inicial-desde-props necesita. */}
      {pagoDe && (
        <ModalRegistrarPago key={pagoDe.id}
          obligacion={{
            id: pagoDe.id,
            concepto: pagoDe.concepto,
            saldo: pagoDe.saldo,
            detalle: [pagoDe.categoria_nombre, pagoDe.tienda_nombre || 'Corporativo',
              pagoDe.beneficiario || ''].filter(Boolean).join(' · '),
          }}
          onCerrar={() => setPagoDe(null)}
          onPagado={() => { setPagoDe(null); refrescar() }} />
      )}
    </div>
  )
}
