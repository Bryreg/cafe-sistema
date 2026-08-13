import { useEffect, useState, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import api from '../api/client'
import {
  ShoppingCart, AlertTriangle, Clock, CheckCircle2, CheckCircle,
  Copy, ChevronDown, ChevronUp, Phone, ClipboardList, Settings2, Check, Search,
  ChefHat, Plus, X, HelpCircle, Package,
} from 'lucide-react'

// Timestamps en UTC naive → parsear como UTC para mostrar hora local Colombia
// (UTC-5). Sin esto `new Date` los toma como local y quedan 5 horas adelantados.
const parseUTC = (s: string) => {
  const t = s.replace(' ', 'T').replace('+00:00', 'Z')
  return new Date(t.endsWith('Z') ? t : t + 'Z')
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Sede { id: number; nombre: string }

/** Un producto DENTRO del catálogo de un proveedor. Lo arma
 *  `services/pedidos.catalogo_proveedores` fusionando dos fuentes: lo que el
 *  dueño asignó a mano (`fuente: manual`) y lo que las facturas enseñaron
 *  (`fuente: compras`). */
interface ItemCatalogo {
  producto_id: number
  nombre: string
  categoria: string
  unidad: string
  contenido_por_empaque: number | null
  /** ¿Se cuenta en esta sede? Si no, su stock es null — no cero. */
  gestionado: boolean
  /** Este proveedor es al que se le pide por defecto (asignación manual, o la
   *  factura más reciente cuando no hay asignación). */
  titular: boolean
  fuente: 'manual' | 'compras' | null
  proveedor_manual: string | null
  ultimo_precio: number | null
  ultima_compra: string | null
  veces_comprado: number
  stock_actual: number | null
  stock_minimo: number | null
  consumo_diario: number
  dias_restantes: number | null
  estado: 'agotado' | 'urgente' | 'pronto' | 'bajo' | 'ok' | null
  cantidad_sugerida: number
  lead_time_dias: number
  barista_alerto: boolean
  /** El motor dice que hay que reponerlo: va precargado en el pedido. */
  necesita: boolean
  /** Está agotado o urgente pero la fórmula dio 0 (nadie cargó `stock_minimo`
   *  y no hay consumo registrado). Se MUESTRA con el input en cero: no se
   *  inventa una cantidad, pero tampoco se esconde un producto en rojo. */
  en_alerta_sin_sugerencia: boolean
}

interface ItemHuerfano extends ItemCatalogo {
  /** Acá nadie se lo entregó nunca, pero en la otra sede sí: pista para
   *  asignarlo de un toque. */
  visto_en_otra_sede: string | null
}

interface GrupoProveedor {
  proveedor: string
  clave: string
  origen: 'manual' | 'compras' | 'ambos'
  productos: ItemCatalogo[]
  n_necesita: number
  n_en_alerta: number
  estado_resumen: string
  lead_time_dias: number
  lead_time_observado: number | null
  ultima_compra: string | null
  dias_desde_ultima: number | null
  cada_dias: number | null
  total_productos: number
}

interface Preparable {
  producto_id: number
  nombre: string
  unidad: string
  estado: string
  cantidad_sugerida: number
  accion: string
  tandas_sugeridas: number | null
  rendimiento_tanda: number | null
  barista_alerto: boolean
}

interface SinAsignar {
  producto_id: number; nombre: string; categoria: string
  unidad: string; estado: string
}

interface Catalogo {
  proveedores: GrupoProveedor[]
  sin_proveedor: ItemHuerfano[]
  sin_asignar: SinAsignar[]
  preparables: Preparable[]
  proveedores_conocidos: string[]
  total_urgentes: number
  total_pronto: number
  total_bajo: number
  total_ok: number
}

// ─── Config ───────────────────────────────────────────────────────────────────

const ESTADO_CFG = {
  agotado: { label: 'AGOTADO',  bg: 'bg-red-100',    text: 'text-red-700',    border: 'border-red-300',    dot: 'bg-red-500'    },
  urgente: { label: 'URGENTE',  bg: 'bg-red-50',     text: 'text-red-600',    border: 'border-red-200',    dot: 'bg-red-400'    },
  pronto:  { label: 'PEDIR',    bg: 'bg-amber-50',   text: 'text-amber-700',  border: 'border-amber-200',  dot: 'bg-amber-400'  },
  bajo:    { label: 'BAJO',     bg: 'bg-yellow-50',  text: 'text-yellow-700', border: 'border-yellow-200', dot: 'bg-yellow-400' },
  ok:      { label: 'OK',       bg: 'bg-green-50',   text: 'text-green-700',  border: 'border-green-200',  dot: 'bg-green-400'  },
}

const CAT_LABEL: Record<string, string> = {
  pasteleria: 'Pastelería',
  bebida: 'Bebidas e insumos',
  insumo: 'Desechables y limpieza',
  porciones: 'Porciones',
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function BadgeEstado({ estado }: { estado: string }) {
  const cfg = ESTADO_CFG[estado as keyof typeof ESTADO_CFG] ?? ESTADO_CFG.ok
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold ${cfg.bg} ${cfg.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

function diasLabel(d: number | null): string {
  if (d === null) return '—'
  if (d < 1) return `${Math.round(d * 24)}h`
  return `${d.toFixed(1)}d`
}

const money = (n: number) =>
  '$' + Math.round(n).toLocaleString('es-CO')

const numero = (n: number) =>
  Number.isInteger(n) ? n.toLocaleString('es-CO') : n.toLocaleString('es-CO', { maximumFractionDigits: 1 })

/** «2 empaques de 2.500 gr» — SOLO cuando `contenido_por_empaque` está cargado.
 *  Sin ese número no hay factor de conversión y no se inventa: la cantidad se
 *  lee en unidades y ya. El ≈ aparece cuando la división no da entera: decir
 *  «2 bolsas» de 2,4 bolsas sería mentir por redondeo. */
function enEmpaques(cantidad: number, contenido: number | null, unidad: string): string | null {
  if (!contenido || contenido <= 0 || cantidad <= 0) return null
  const n = cantidad / contenido
  const exacto = Math.abs(n - Math.round(n)) < 0.001
  return `${exacto ? '' : '≈ '}${numero(exacto ? Math.round(n) : Math.round(n * 10) / 10)} empaque${
    Math.round(n) === 1 && exacto ? '' : 's'} de ${numero(contenido)} ${unidad}`
}

/** La clave de una cantidad es (proveedor, producto) y NO solo el producto: el
 *  mismo vaso puede estar en el catálogo de dos proveedores y se le pide a UNO.
 *  Con una clave por producto, escribir 100 en un card los llenaba a los dos. */
const claveCantidad = (clavePr: string, productoId: number) => `${clavePr}::${productoId}`

/** LA regla de qué entra al pedido, en UN solo lugar. El botón la usa para
 *  contar y el texto de WhatsApp para escribir, así que el número del botón y
 *  las líneas del mensaje NO PUEDEN divergir: antes el botón contaba productos
 *  del grupo y el texto filtraba cantidad > 0, y eran dos números distintos. */
function lineasPedido(grupo: GrupoProveedor, cantidades: Record<string, number>): ItemCatalogo[] {
  return grupo.productos.filter(p => (cantidades[claveCantidad(grupo.clave, p.producto_id)] ?? 0) > 0)
}

function textoWhatsApp(
  grupo: GrupoProveedor, cantidades: Record<string, number>, sede: string,
): string | null {
  const lineas = lineasPedido(grupo, cantidades)
  if (!lineas.length) return null
  const fecha = new Date().toLocaleDateString('es-CO', { day: 'numeric', month: 'long' })
  const cuerpo = lineas.map(p => {
    const cant = cantidades[claveCantidad(grupo.clave, p.producto_id)]
    const emp = enEmpaques(cant, p.contenido_por_empaque, p.unidad)
    return `- ${p.nombre}: ${numero(cant)} ${p.unidad}${emp ? ` (${emp})` : ''}`
  })
  return `*Pedido ${grupo.proveedor} — ${fecha}*\n${sede ? `${sede}\n` : ''}${cuerpo.join('\n')}`
}

function copiar(texto: string, ok: string) {
  navigator.clipboard?.writeText(texto)
    .then(() => alert(ok))
    .catch(() => alert(texto))
}

// ─── Fila de producto dentro de un card de proveedor ──────────────────────────

function FilaPedido({
  p, cantidad, onCantidad, onQuitar,
}: {
  p: ItemCatalogo
  cantidad: number
  onCantidad: (v: number) => void
  onQuitar: () => void
}) {
  const cfg = ESTADO_CFG[(p.estado ?? 'ok') as keyof typeof ESTADO_CFG] ?? ESTADO_CFG.ok
  const emp = enEmpaques(cantidad, p.contenido_por_empaque, p.unidad)

  return (
    <div className="flex items-start gap-2 py-2 border-b border-gray-100 last:border-0">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${p.gestionado ? cfg.dot : 'bg-gray-200'}`} />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-sm text-gray-800 font-medium">{p.nombre}</span>
          {p.barista_alerto && (
            <span className="text-[10px] bg-purple-100 text-purple-700 px-1.5 rounded-full font-medium">barista</span>
          )}
          {!p.titular && (
            <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 rounded-full font-medium"
                  title={p.proveedor_manual
                    ? `Se le pide a ${p.proveedor_manual}, pero este proveedor también lo ha traído`
                    : 'Otro proveedor lo trajo más recientemente'}>
              también acá
            </span>
          )}
        </div>
        <p className="text-[11px] text-gray-400 mt-0.5">
          {p.gestionado
            ? <>Hay {numero(p.stock_actual ?? 0)} {p.unidad} · dura {diasLabel(p.dias_restantes)}</>
            : <>No se cuenta en esta sede</>}
          {p.ultimo_precio !== null && (
            <> · {money(p.ultimo_precio)}/{p.unidad}</>
          )}
          {p.veces_comprado > 0 && p.ultima_compra && (
            <> · comprado {p.veces_comprado}×</>
          )}
        </p>
      </div>

      <div className="flex flex-col items-end gap-0.5">
        <div className="flex items-center gap-1">
          <input
            type="number" min={0} step={1} value={cantidad}
            onChange={e => onCantidad(Math.max(0, Number(e.target.value)))}
            className="w-20 text-center border border-gray-300 rounded-lg py-1 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
          <span className="text-xs text-gray-400 w-8">{p.unidad}</span>
          {/* Solo se puede sacar lo que está adentro: con la cantidad en cero
              el producto ya no es parte del pedido. */}
          {cantidad > 0 ? (
            <button onClick={onQuitar} title="Sacar del pedido"
                    className="text-gray-300 hover:text-red-500 transition-colors">
              <X size={14} />
            </button>
          ) : <span className="w-[14px]" />}
        </div>
        {emp && <span className="text-[10px] text-gray-400">{emp}</span>}
      </div>
    </div>
  )
}

// ─── Card de proveedor ────────────────────────────────────────────────────────

function CardProveedor({
  grupo, cantidades, setCantidad, sede,
}: {
  grupo: GrupoProveedor
  cantidades: Record<string, number>
  setCantidad: (clave: string, productoId: number, v: number) => void
  sede: string
}) {
  const [abierto, setAbierto] = useState(grupo.n_necesita + grupo.n_en_alerta > 0)
  const [verCatalogo, setVerCatalogo] = useState(false)
  const cfg = ESTADO_CFG[grupo.estado_resumen as keyof typeof ESTADO_CFG] ?? ESTADO_CFG.ok

  // El pedido = lo que tiene cantidad > 0. Mismo cálculo para el número del
  // botón y para el texto: no hay dos verdades.
  const enPedido = lineasPedido(grupo, cantidades)
  const enPedidoIds = new Set(enPedido.map(p => p.producto_id))
  // VISIBLE = lo que está en rojo del titular, más TODO lo que el usuario tocó
  // (aunque el input haya vuelto a vacío), en EL ORDEN ORIGINAL del catálogo.
  //
  // La primera versión armaba [...enPedido, ...enAlerta]: la fila SALTABA al
  // tope con la primera tecla (mis-click servido en un celular), y borrar el
  // input la hacía DESAPARECER adentro del acordeón — Number('') es 0 y la
  // sacaba de enPedido. Una lista de trabajo no se reordena ni se traga filas
  // mientras la estás escribiendo: se filtra sobre el orden estable y toda
  // clave tocada queda anclada.
  //
  // Solo del TITULAR: un producto que dos proveedores trajeron aparecería en
  // rojo en los dos cards y se podría pedir dos veces. En el card del otro
  // proveedor sigue estando, en «agregar del catálogo».
  const visibles = grupo.productos.filter(p =>
    enPedidoIds.has(p.producto_id)
    || cantidades[claveCantidad(grupo.clave, p.producto_id)] !== undefined
    || (p.en_alerta_sin_sugerencia && p.titular))
  const nEnAlerta = grupo.productos.filter(
    p => p.en_alerta_sin_sugerencia && p.titular && !enPedidoIds.has(p.producto_id)).length
  const visiblesIds = new Set(visibles.map(p => p.producto_id))
  const resto = grupo.productos.filter(p => !visiblesIds.has(p.producto_id))

  const copiarPedido = () => {
    const texto = textoWhatsApp(grupo, cantidades, sede)
    if (!texto) { alert('Este pedido está vacío: poné una cantidad mayor a cero.'); return }
    copiar(texto, `Pedido de ${grupo.proveedor} copiado ✓`)
  }

  return (
    <div className={`rounded-2xl border-2 ${enPedido.length ? cfg.border : 'border-gray-200'} overflow-hidden mb-3 bg-white`}>
      <button
        onClick={() => setAbierto(v => !v)}
        className={`w-full flex items-center justify-between gap-2 px-4 py-3 text-left ${enPedido.length ? cfg.bg : 'bg-gray-50'}`}
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Phone size={14} className={enPedido.length ? cfg.text : 'text-gray-400'} />
            <span className={`font-bold text-sm ${enPedido.length ? cfg.text : 'text-gray-600'}`}>
              {grupo.proveedor}
            </span>
            {grupo.n_necesita + grupo.n_en_alerta > 0 && <BadgeEstado estado={grupo.estado_resumen} />}
            {grupo.lead_time_dias <= 1 && (
              <span className="flex items-center gap-1 text-[11px] text-amber-700 font-medium bg-amber-100 px-2 py-0.5 rounded-full">
                <Clock size={10} /> Entrega al día siguiente
              </span>
            )}
          </div>
          <p className="text-[11px] text-gray-500 mt-0.5">
            {grupo.total_productos} producto{grupo.total_productos !== 1 ? 's' : ''} en su catálogo
            {grupo.cada_dias !== null && <> · viene cada {numero(grupo.cada_dias)} días</>}
            {grupo.dias_desde_ultima !== null && (
              <> · última compra hace {grupo.dias_desde_ultima} día{grupo.dias_desde_ultima !== 1 ? 's' : ''}</>
            )}
            {grupo.origen === 'compras' && <> · aprendido de las facturas</>}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {enPedido.length > 0 && (
            <span className="text-xs font-bold text-white bg-amber-500 rounded-full px-2 py-0.5">
              {enPedido.length}
            </span>
          )}
          {abierto ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
        </div>
      </button>

      {abierto && (
        <div className="px-4 pb-3 pt-1">
          {visibles.length > 0 ? (
            visibles.map(p => (
              <FilaPedido
                key={p.producto_id}
                p={p}
                cantidad={cantidades[claveCantidad(grupo.clave, p.producto_id)] ?? 0}
                onCantidad={v => setCantidad(grupo.clave, p.producto_id, v)}
                onQuitar={() => setCantidad(grupo.clave, p.producto_id, 0)}
              />
            ))
          ) : (
            <p className="text-xs text-gray-400 py-3">
              Nada de este proveedor está en alerta. Agregá lo que quieras pedirle igual.
            </p>
          )}

          {nEnAlerta > 0 && (
            <p className="text-[11px] text-gray-500 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-1.5 mt-2">
              {nEnAlerta === 1 ? 'Un producto está' : `${nEnAlerta} productos están`} en
              rojo pero sin stock mínimo cargado, así que el sistema no calcula cuánto pedir.
              Escribí vos la cantidad y {nEnAlerta === 1 ? 'entra' : 'entran'} al pedido.
            </p>
          )}

          {resto.length > 0 && (
            <div className="mt-2">
              <button
                onClick={() => setVerCatalogo(v => !v)}
                className="flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-700"
              >
                <Plus size={12} />
                Agregar del catálogo de {grupo.proveedor} ({resto.length})
                {verCatalogo ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              </button>

              {verCatalogo && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {resto.map(p => (
                    <button
                      key={p.producto_id}
                      onClick={() => setCantidad(
                        grupo.clave, p.producto_id,
                        p.cantidad_sugerida > 0 ? p.cantidad_sugerida : 1)}
                      className="flex items-center gap-1 text-xs border border-gray-200 hover:border-amber-400 hover:bg-amber-50 rounded-lg px-2 py-1 text-gray-600 transition-colors"
                      title={p.gestionado
                        ? `Hay ${numero(p.stock_actual ?? 0)} ${p.unidad}`
                        : 'No se cuenta en esta sede'}
                    >
                      <Plus size={11} className="text-amber-500" /> {p.nombre}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <button
            onClick={copiarPedido}
            disabled={enPedido.length === 0}
            className={`mt-3 flex items-center gap-1.5 text-xs font-semibold rounded-lg px-3 py-2 transition-colors ${
              enPedido.length
                ? 'bg-green-600 text-white hover:bg-green-700'
                : 'bg-gray-100 text-gray-300 cursor-not-allowed'
            }`}
          >
            <Copy size={12} />
            {enPedido.length
              ? `Copiar pedido para WhatsApp (${enPedido.length} producto${enPedido.length !== 1 ? 's' : ''})`
              : 'Sin nada que pedir'}
          </button>
        </div>
      )}
    </div>
  )
}

// ─── Bucket «Sin proveedor», con asignación EN EL LUGAR ───────────────────────

function BucketSinProveedor({
  items, conocidos, onAsignado,
}: {
  items: ItemHuerfano[]
  conocidos: string[]
  onAsignado: () => void
}) {
  const [valores, setValores] = useState<Record<number, string>>({})
  const [guardando, setGuardando] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busqueda, setBusqueda] = useState('')
  // Con el inventario recién cargado esta lista puede tener decenas de
  // productos: abierta de entrada enterraría los cards de proveedor, que son lo
  // que se viene a hacer. Chica se abre sola; grande espera a que la pidan.
  const [abierto, setAbierto] = useState(items.length <= 8)
  const listId = 'proveedores-conocidos'

  if (!items.length) return null

  const conPista = items.filter(p => p.visto_en_otra_sede).length
  const filtrados = busqueda.trim()
    ? items.filter(p => p.nombre.toLowerCase().includes(busqueda.toLowerCase()))
    : items

  const asignar = async (productoId: number, nombre: string) => {
    const valor = (nombre ?? '').trim()
    if (!valor) return
    setGuardando(productoId); setError('')
    try {
      await api.patch(`/inventario/productos/${productoId}`, { proveedor: valor })
      onAsignado()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo guardar el proveedor')
    } finally { setGuardando(null) }
  }

  return (
    <div className="rounded-2xl border-2 border-dashed border-gray-300 bg-white overflow-hidden mb-3">
      <button onClick={() => setAbierto(v => !v)}
              className="w-full text-left px-4 py-3 bg-gray-50 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <HelpCircle size={14} className="text-gray-400" />
          <span className="font-bold text-sm text-gray-600">Sin proveedor</span>
          <span className="text-xs font-bold text-white bg-gray-400 rounded-full px-2 py-0.5">{items.length}</span>
          <span className="ml-auto">
            {abierto ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
          </span>
        </div>
        <p className="text-[11px] text-gray-500 mt-0.5">
          Hay que pedirlos y el sistema todavía no sabe quién los trae. Asignalos acá
          y quedan guardados en su proveedor para siempre.
          {conPista > 0 && (
            <span className="text-amber-700 font-medium"> {conPista} ya se sabe{conPista !== 1 ? 'n' : ''} de la otra sede.</span>
          )}
        </p>
      </button>

      {error && (
        <p className="px-4 py-2 text-xs text-red-600 bg-red-50 border-b border-red-100">{error}</p>
      )}

      <datalist id={listId}>
        {conocidos.map(p => <option key={p} value={p} />)}
      </datalist>

      {abierto && items.length > 8 && (
        <div className="px-4 pt-2.5">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text" value={busqueda} onChange={e => setBusqueda(e.target.value)}
              placeholder="Buscar entre los que no tienen proveedor…"
              className="w-full pl-7 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-300"
            />
          </div>
        </div>
      )}

      <div className={`divide-y divide-gray-50 ${abierto ? '' : 'hidden'}`}>
        {filtrados.map(p => {
          const val = valores[p.producto_id] ?? ''
          return (
            <div key={p.producto_id} className="px-4 py-2.5">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800">{p.nombre}</p>
                  <p className="text-[11px] text-gray-400">
                    {p.necesita
                      ? <>Pedir {numero(p.cantidad_sugerida)} {p.unidad}</>
                      : <span className="text-red-500 font-medium">
                          {(ESTADO_CFG[(p.estado ?? 'ok') as keyof typeof ESTADO_CFG] ?? ESTADO_CFG.ok).label}
                        </span>}
                    {' · '}hay {numero(p.stock_actual ?? 0)} {p.unidad}
                  </p>
                </div>
                <input
                  type="text" list={listId} value={val}
                  onChange={e => setValores(v => ({ ...v, [p.producto_id]: e.target.value }))}
                  onKeyDown={e => { if (e.key === 'Enter') asignar(p.producto_id, val) }}
                  placeholder="¿Quién lo trae?"
                  className="w-44 border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300 text-gray-700 placeholder:text-gray-300"
                />
                <button
                  onClick={() => asignar(p.producto_id, val)}
                  disabled={!val.trim() || guardando === p.producto_id}
                  className={`shrink-0 h-8 px-3 flex items-center gap-1 rounded-lg text-xs font-semibold transition-all ${
                    val.trim() ? 'bg-amber-500 text-white hover:bg-amber-600' : 'bg-gray-100 text-gray-300'
                  }`}
                >
                  {guardando === p.producto_id ? '…' : <><Check size={13} /> Asignar</>}
                </button>
              </div>
              {p.visto_en_otra_sede && (
                <button
                  onClick={() => asignar(p.producto_id, p.visto_en_otra_sede!)}
                  className="mt-1 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5 hover:bg-amber-100 transition-colors"
                >
                  En la otra sede lo trae <strong>{p.visto_en_otra_sede}</strong> — asignar
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── TabPedidos: armar el pedido del día ──────────────────────────────────────

function TabPedidos({ tiendaId, sedeNombre }: { tiendaId: number | null; sedeNombre: string }) {
  const [data, setData]           = useState<Catalogo | null>(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')
  // Clave (proveedor, producto): el mismo producto puede estar en dos catálogos
  // y se le pide a UNO.
  const [cantidades, setCantidades] = useState<Record<string, number>>({})

  // `preservar`: el refetch por ASIGNAR un proveedor conserva lo tipeado. La
  // versión sin esto hacía setCantidades(init) incondicional, e init está vacío
  // cuando nada tiene mínimo: asignar un proveedor desde el cajón —el flujo que
  // la propia pantalla publicita— borraba en silencio todas las cantidades del
  // pedido a medio armar. Cambiar de SEDE sí resetea (preservar=false vía el
  // useEffect): las cantidades de Vida no son un pedido de Palmetto.
  const cargar = useCallback((preservar = false) => {
    if (tiendaId === null) return
    setLoading(true); setError('')
    api.get<Catalogo>('/pedidos/proveedores', { params: { tienda_id: tiendaId } })
      .then(r => {
        setData(r.data)
        // Precarga: SOLO lo que el motor dice que hay que reponer, y en el
        // catálogo de su TITULAR. Precargar el mismo producto en los dos
        // proveedores que lo trajeron sería pedirlo dos veces.
        const init: Record<string, number> = {}
        for (const g of r.data.proveedores)
          for (const p of g.productos)
            if (p.necesita && p.titular)
              init[claveCantidad(g.clave, p.producto_id)] = p.cantidad_sugerida
        setCantidades(prev => preservar ? { ...init, ...prev } : init)
      })
      .catch(e => setError(e.response?.data?.detail || 'No se pudo cargar el catálogo de proveedores'))
      .finally(() => setLoading(false))
  }, [tiendaId])

  useEffect(() => { cargar() }, [cargar])

  const setCantidad = (clavePr: string, productoId: number, v: number) =>
    setCantidades(prev => ({ ...prev, [claveCantidad(clavePr, productoId)]: v }))

  // Total de líneas del pedido: la MISMA regla que cada card y que cada texto.
  const totalLineas = useMemo(
    () => (data?.proveedores ?? []).reduce((n, g) => n + lineasPedido(g, cantidades).length, 0),
    [data, cantidades],
  )
  // Lo que está en rojo y todavía no tiene cantidad. Se cuenta aparte porque NO
  // va en ningún WhatsApp hasta que alguien escriba el número.
  // Se recalcula CON las cantidades: el payload congelado dejaba el contador
  // clavado mientras escribias — dos numeros peleados en la misma pantalla, el
  // pecado exacto que este rework vino a matar. «Esperando cantidad» = en rojo
  // del titular y todavia sin numero.
  const totalAlertas = useMemo(
    () => (data?.proveedores ?? []).reduce((n, g) =>
      n + g.productos.filter(p =>
        p.titular && (p.en_alerta_sin_sugerencia || p.necesita)
        && !((cantidades[claveCantidad(g.clave, p.producto_id)] ?? 0) > 0)).length, 0),
    [data, cantidades],
  )

  if (loading) return (
    <p className="text-sm text-gray-400 animate-pulse py-8 text-center">Leyendo el catálogo de proveedores…</p>
  )
  if (error) return (
    <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
      <AlertTriangle size={14} /> {error}
    </div>
  )
  if (!data) return null

  const conPedido = data.proveedores.filter(g => lineasPedido(g, cantidades).length > 0)

  return (
    <div className="space-y-3">
      {/* Resumen de trabajo: cuántas líneas y a cuántos teléfonos. */}
      <div className="flex items-center gap-3 flex-wrap bg-white border border-gray-200 rounded-xl px-4 py-2.5">
        <p className="text-sm text-gray-700">
          <strong className="text-amber-600">{totalLineas}</strong> producto{totalLineas !== 1 ? 's' : ''} en el pedido
          {conPedido.length > 0 && <> · <strong>{conPedido.length}</strong> proveedor{conPedido.length !== 1 ? 'es' : ''} a quien llamar</>}
          {totalAlertas > 0 && (
            <span className="text-gray-400"> · {totalAlertas} en rojo esperando cantidad</span>
          )}
        </p>
        <span className="ml-auto text-xs text-gray-400">
          {data.total_urgentes > 0 && <span className="text-red-500 font-semibold">{data.total_urgentes} urgente{data.total_urgentes !== 1 ? 's' : ''}</span>}
          {data.total_urgentes > 0 && (data.total_pronto > 0 || data.total_bajo > 0) && ' · '}
          {data.total_pronto > 0 && `${data.total_pronto} para pedir`}
          {data.total_pronto > 0 && data.total_bajo > 0 && ' · '}
          {data.total_bajo > 0 && `${data.total_bajo} bajo`}
        </span>
      </div>

      {data.proveedores.length === 0 && data.sin_proveedor.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl px-4 py-8 text-center">
          <Package size={28} className="text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">
            Todavía no hay proveedores para esta sede.
          </p>
          <p className="text-xs text-gray-400 mt-1">
            Se aprenden solos al registrar facturas, o los asignás en la pestaña «Proveedores».
          </p>
        </div>
      )}

      <BucketSinProveedor
        items={data.sin_proveedor}
        conocidos={data.proveedores_conocidos}
        onAsignado={() => cargar(true)}   // preserva lo tipeado: ver cargar()
      />

      {data.proveedores.map(g => (
        <CardProveedor
          key={g.clave}
          grupo={g}
          cantidades={cantidades}
          setCantidad={setCantidad}
          sede={sedeNombre}
        />
      ))}

      {/* Lo que se ARMA en la barra: no es de ningún proveedor y no entra a
          ningún WhatsApp, pero su necesidad es igual de real. */}
      {data.preparables.length > 0 && (
        <div className="rounded-2xl border-2 border-emerald-200 bg-white overflow-hidden">
          <div className="px-4 py-3 bg-emerald-50 flex items-center gap-2">
            <ChefHat size={14} className="text-emerald-600" />
            <span className="font-bold text-sm text-emerald-700">Se prepara en la barra</span>
            <span className="text-[11px] text-emerald-600">no se le pide a nadie</span>
          </div>
          <div className="px-4 py-2 divide-y divide-gray-50">
            {data.preparables.map(p => (
              <div key={p.producto_id} className="flex items-center justify-between gap-2 py-2">
                <span className="text-sm text-gray-800">{p.nombre}</span>
                <span className="text-xs font-semibold text-emerald-700 whitespace-nowrap">
                  preparar {numero(p.cantidad_sugerida)} {p.unidad}
                  {p.tandas_sugeridas ? ` ≈ ${p.tandas_sugeridas} tanda${p.tandas_sugeridas === 1 ? '' : 's'}` : ''}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {totalLineas === 0 && totalAlertas === 0 && data.proveedores.length > 0 && (
        <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
          <CheckCircle2 size={16} />
          Nada está en alerta hoy. Abrí cualquier proveedor para agregarle lo que quieras pedirle igual.
        </div>
      )}
    </div>
  )
}

// ─── TabSolicitudes: pedidos de las baristas, con decisión ────────────────────

interface SolItem {
  id: number; producto_id: number; cantidad_solicitada: number
  nombre: string; unidad_medida: string; proveedor: string | null
  accion?: 'comprar' | 'preparar'
}

// La solicitud de la barista se agrupa por proveedor y de ahí sale el texto de
// WhatsApp. Lo que se prepara en la barra no tiene proveedor a quien mandárselo:
// va en su propio grupo, con un rótulo que no es un teléfono.
const GRUPO_PREPARAR = 'Preparar en barra'
const grupoDe = (it: SolItem) =>
  it.accion === 'preparar' ? GRUPO_PREPARAR : (it.proveedor || 'Sin proveedor')
interface Solicitud {
  id: number; tienda_id: number; tienda_nombre: string | null
  fecha_solicitud: string; estado: string; nota: string | null
  items: SolItem[]
}

function TabSolicitudes({ onCount }: { onCount: (n: number) => void }) {
  const [solicitudes, setSolicitudes] = useState<Solicitud[]>([])
  const [accionando, setAccionando]   = useState<number | null>(null)
  const [verResueltas, setVerResueltas] = useState(false)
  const [error, setError]             = useState('')

  const cargar = useCallback(async () => {
    try {
      const { data } = await api.get<Solicitud[]>('/solicitudes/pedido/todas')
      setSolicitudes(data)
      onCount(data.filter(s => s.estado === 'pendiente').length)
      setError('')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudieron cargar las solicitudes')
    }
  }, [onCount])

  useEffect(() => { cargar() }, [cargar])

  const decidir = async (id: number, accion: 'aprobar' | 'rechazar') => {
    setAccionando(id); setError('')
    try {
      await api.patch(`/solicitudes/pedido/${id}/${accion}`)
      await cargar()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo actualizar')
    } finally { setAccionando(null) }
  }

  const copiarPorProveedor = (s: Solicitud) => {
    const fecha = parseUTC(s.fecha_solicitud).toLocaleDateString('es-CO', { day: 'numeric', month: 'long' })
    const porProv: Record<string, SolItem[]> = {}
    for (const it of s.items) {
      // Lo que se prepara NO entra en el texto: es un pedido a un proveedor.
      if (it.accion === 'preparar') continue
      const k = grupoDe(it)
      if (!porProv[k]) porProv[k] = []
      porProv[k].push(it)
    }
    if (!Object.keys(porProv).length) {
      alert('Esta solicitud es solo de cosas que se preparan en la barra: no hay nada que pedirle a un proveedor.')
      return
    }
    const bloques = Object.entries(porProv).map(([prov, items]) =>
      `*${prov}*\n${items.map(i => `- ${i.nombre}: ${i.cantidad_solicitada} ${i.unidad_medida}`).join('\n')}`)
    const texto = `*Pedido ${s.tienda_nombre ?? ''} — ${fecha}*\n\n${bloques.join('\n\n')}`
    copiar(texto, 'Pedido copiado por proveedor ✓')
  }

  const pendientes = solicitudes.filter(s => s.estado === 'pendiente')
  const resueltas  = solicitudes.filter(s => s.estado !== 'pendiente')
  const visibles   = verResueltas ? solicitudes : pendientes

  return (
    <div className="space-y-3">
      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-600 rounded-xl px-4 py-3 text-sm">
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">
          Lo que las baristas pidieron desde el kiosko, con el proveedor de sus compras.
        </p>
        {resueltas.length > 0 && (
          <button onClick={() => setVerResueltas(v => !v)} className="text-xs text-gray-400 hover:text-gray-600 underline">
            {verResueltas ? 'Solo pendientes' : `Ver ${resueltas.length} resueltas`}
          </button>
        )}
      </div>

      {visibles.length === 0 && (
        <div className="bg-white border border-gray-200 rounded-2xl px-4 py-8 text-center">
          <CheckCircle size={28} className="text-green-400 mx-auto mb-2" />
          <p className="text-sm text-gray-500">No hay solicitudes pendientes</p>
        </div>
      )}

      {visibles.map(s => {
        // Items agrupados por proveedor (el de las compras de las baristas)
        const porProv: Record<string, SolItem[]> = {}
        for (const it of s.items) {
          const k = grupoDe(it)
          if (!porProv[k]) porProv[k] = []
          porProv[k].push(it)
        }
        const pendiente = s.estado === 'pendiente'
        return (
          <div key={s.id} className={`bg-white border rounded-2xl overflow-hidden ${pendiente ? 'border-amber-300' : 'border-gray-200 opacity-70'}`}>
            <div className="px-4 py-3 flex items-center justify-between gap-2 flex-wrap border-b border-gray-100">
              <div>
                <p className="text-sm font-semibold text-gray-800">
                  {s.tienda_nombre ?? `Tienda ${s.tienda_id}`} · {s.items.length} producto{s.items.length !== 1 ? 's' : ''}
                </p>
                <p className="text-xs text-gray-400">
                  {parseUTC(s.fecha_solicitud).toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'short' })}
                  {' · '}
                  {parseUTC(s.fecha_solicitud).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' })}
                </p>
                {s.nota && <p className="text-xs text-amber-700 mt-0.5 font-medium">Nota: {s.nota}</p>}
              </div>
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                s.estado === 'pendiente' ? 'bg-amber-100 text-amber-700'
                : s.estado === 'aprobada' ? 'bg-green-100 text-green-700'
                : 'bg-gray-100 text-gray-500'
              }`}>{s.estado}</span>
            </div>

            <div className="px-4 py-2 space-y-2">
              {Object.entries(porProv).map(([prov, items]) => (
                <div key={prov}>
                  <p className={`text-[11px] font-bold uppercase tracking-wide flex items-center gap-1 ${
                    prov === GRUPO_PREPARAR ? 'text-emerald-600' : 'text-gray-400'}`}>
                    {prov === GRUPO_PREPARAR ? <ChefHat size={10} /> : <Phone size={10} />} {prov}
                  </p>
                  {items.map(it => (
                    <div key={it.id} className="flex items-center justify-between text-sm py-0.5 pl-4">
                      <span className="text-gray-700">{it.nombre}</span>
                      <span className="font-mono font-bold text-gray-800">
                        {it.cantidad_solicitada} {it.unidad_medida}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>

            <div className="px-4 py-3 border-t border-gray-100 flex items-center gap-2 flex-wrap">
              <button onClick={() => copiarPorProveedor(s)}
                className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-700 border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50">
                <Copy size={12} /> Copiar por proveedor
              </button>
              {pendiente && (
                <>
                  <button onClick={() => decidir(s.id, 'aprobar')} disabled={accionando === s.id}
                    className="ml-auto flex items-center gap-1.5 text-xs font-bold text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 px-3 py-1.5 rounded-lg">
                    <Check size={13} /> Aprobar
                  </button>
                  <button onClick={() => decidir(s.id, 'rechazar')} disabled={accionando === s.id}
                    className="text-xs font-semibold text-red-500 hover:text-red-700 border border-red-100 hover:border-red-300 px-3 py-1.5 rounded-lg">
                    Rechazar
                  </button>
                </>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── TabProveedores: asignar a mano lo que las facturas no enseñaron ──────────

interface ProdAsignable {
  id: number
  nombre: string
  categoria: string
  /** El valor REAL de `Producto.proveedor`. Es contra ESTO que se compara si el
   *  input está sucio. La versión vieja de esta pantalla mandaba `''` para todo
   *  lo que no estuviera en un grupo fijo: lo tipeado se guardaba pero volvía a
   *  blanco al recargar, y el botón de guardar quedaba apagado sin reintento. */
  proveedorManual: string
  /** Quién lo trae según el catálogo (manual o aprendido). Vacío = nadie. */
  titular: string
}

function TabProveedores({ tiendaId }: { tiendaId: number | null }) {
  const [productos, setProductos]   = useState<ProdAsignable[]>([])
  const [conocidos, setConocidos]   = useState<string[]>([])
  const [editores, setEditores]     = useState<Record<number, string>>({})
  const [saving, setSaving]         = useState<Record<number, boolean>>({})
  const [saved, setSaved]           = useState<Record<number, boolean>>({})
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState('')
  const [busqueda, setBusqueda]     = useState('')
  const listId = 'proveedores-list'

  const cargar = useCallback(() => {
    if (!tiendaId) return
    setLoading(true); setError('')
    api.get<Catalogo>('/pedidos/proveedores', { params: { tienda_id: tiendaId } })
      .then(r => {
        // Un producto puede estar en dos catálogos; acá se lista UNA vez, con su
        // titular y con el valor manual verdadero (que puede estar vacío aunque
        // el catálogo lo haya aprendido de una factura).
        const vistos = new Map<number, ProdAsignable>()
        for (const g of r.data.proveedores) {
          for (const p of g.productos) {
            if (!p.titular) continue
            vistos.set(p.producto_id, {
              id: p.producto_id, nombre: p.nombre, categoria: p.categoria,
              proveedorManual: p.proveedor_manual ?? '',
              titular: g.proveedor,
            })
          }
        }
        for (const p of r.data.sin_asignar) {
          if (vistos.has(p.producto_id)) continue
          vistos.set(p.producto_id, {
            id: p.producto_id, nombre: p.nombre, categoria: p.categoria,
            proveedorManual: '', titular: '',
          })
        }
        const all = [...vistos.values()].sort(
          (a, b) => a.titular.localeCompare(b.titular) || a.nombre.localeCompare(b.nombre))
        setProductos(all)
        setConocidos(r.data.proveedores_conocidos)
        const init: Record<number, string> = {}
        for (const p of all) init[p.id] = p.proveedorManual
        setEditores(init)
      })
      .catch(e => setError(e.response?.data?.detail || 'No se pudo cargar'))
      .finally(() => setLoading(false))
  }, [tiendaId])

  useEffect(() => { cargar() }, [cargar])

  const guardar = async (id: number) => {
    setSaving(prev => ({ ...prev, [id]: true })); setError('')
    try {
      await api.patch(`/inventario/productos/${id}`, { proveedor: editores[id]?.trim() ?? '' })
      setSaved(prev => ({ ...prev, [id]: true }))
      setTimeout(() => { setSaved(prev => ({ ...prev, [id]: false })); cargar() }, 900)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'No se pudo guardar')
    } finally { setSaving(prev => ({ ...prev, [id]: false })) }
  }

  // Agrupar por quién lo trae hoy (titular), no por el campo manual: así se ve
  // el catálogo real, incluido lo que el sistema aprendió solo.
  const grupos: Record<string, ProdAsignable[]> = {}
  for (const p of productos) {
    const key = p.titular || '__sin__'
    if (!grupos[key]) grupos[key] = []
    grupos[key].push(p)
  }
  const gruposOrdenados: [string, ProdAsignable[]][] = [
    ...Object.entries(grupos).filter(([k]) => k !== '__sin__').sort(([a], [b]) => a.localeCompare(b)),
    ...(grupos['__sin__'] ? [['__sin__', grupos['__sin__']] as [string, ProdAsignable[]]] : []),
  ]

  const gruposFiltrados: [string, ProdAsignable[]][] = busqueda.trim()
    ? gruposOrdenados
        .map(([key, items]) => [
          key,
          items.filter(p => p.nombre.toLowerCase().includes(busqueda.toLowerCase())),
        ] as [string, ProdAsignable[]])
        .filter(([, items]) => items.length > 0)
    : gruposOrdenados

  if (loading) return <p className="text-sm text-gray-400 text-center py-8 animate-pulse">Cargando…</p>

  return (
    <div className="space-y-4">
      <datalist id={listId}>
        {conocidos.map(p => <option key={p} value={p} />)}
      </datalist>

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-600 rounded-xl px-4 py-3 text-sm">
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          placeholder="Buscar producto…"
          value={busqueda}
          onChange={e => setBusqueda(e.target.value)}
          className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-amber-300"
        />
      </div>

      <p className="text-xs text-gray-400">
        Los proveedores se aprenden solos de las facturas que se escanean. Acá se corrige
        o se asigna a mano lo que todavía no aprendieron — y la asignación a mano manda.
      </p>

      {gruposFiltrados.map(([key, items]) => (
        <div key={key} className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-4 py-2.5 bg-gray-50 border-b border-gray-100 flex items-center gap-2">
            <Phone size={13} className="text-gray-400" />
            <p className="text-xs font-bold text-gray-600 uppercase tracking-wide">
              {key === '__sin__' ? 'Sin proveedor' : key}
            </p>
            <span className="ml-auto text-xs text-gray-400">{items.length} productos</span>
          </div>
          <div className="divide-y divide-gray-50">
            {items.map(p => {
              const val = editores[p.id] ?? p.proveedorManual
              const dirty = val.trim() !== p.proveedorManual
              return (
                <div key={p.id} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800">{p.nombre}</p>
                    <p className="text-xs text-gray-400">
                      {CAT_LABEL[p.categoria] ?? p.categoria}
                      {!p.proveedorManual && p.titular && (
                        <span className="text-gray-400"> · aprendido de facturas: {p.titular}</span>
                      )}
                    </p>
                  </div>
                  <input
                    type="text"
                    list={listId}
                    value={val}
                    onChange={e => setEditores(prev => ({ ...prev, [p.id]: e.target.value }))}
                    placeholder={p.titular || 'Nombre del proveedor…'}
                    className="w-44 border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-amber-300 text-gray-700 placeholder:text-gray-300"
                  />
                  <button
                    onClick={() => guardar(p.id)}
                    disabled={!dirty || saving[p.id] || saved[p.id]}
                    className={`shrink-0 w-8 h-8 flex items-center justify-center rounded-lg transition-all ${
                      saved[p.id]  ? 'bg-green-100 text-green-600' :
                      dirty        ? 'bg-amber-500 text-white hover:bg-amber-600' :
                      'bg-gray-100 text-gray-300'
                    }`}
                    title="Guardar"
                  >
                    {saved[p.id] ? <Check size={14} /> : saving[p.id] ? '…' : <Check size={14} />}
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PedidosAdmin() {
  const { user } = useAuth()
  const [sedes, setSedes] = useState<Sede[]>([])
  // Sede y pestaña viven en la URL, no en un useState que solo se evalúa al
  // montar. Dos bugs se caen juntos: `?tienda_id=` hace que el link «Armar
  // pedido» de Inventario aterrice en la sede que se estaba mirando, y
  // useSearchParams (en vez de leer window.location una sola vez) hace que un
  // navigate a la MISMA ruta con otro ?tab= sí cambie de pestaña.
  const [sp, setSp] = useSearchParams()
  const [nPendientes, setNPendientes] = useState(0)

  const tabURL = sp.get('tab')
  const tab: 'pedidos' | 'solicitudes' | 'proveedores' =
    tabURL === 'pedidos' || tabURL === 'proveedores' ? tabURL : 'solicitudes'

  const tiendaURL = Number(sp.get('tienda_id'))
  const tiendaId: number | null =
    Number.isFinite(tiendaURL) && tiendaURL > 0 ? tiendaURL : (user?.tienda_id ?? null)

  const irA = (cambios: { tab?: string; tienda_id?: number }) => {
    const next = new URLSearchParams(sp)
    if (cambios.tab) next.set('tab', cambios.tab)
    if (cambios.tienda_id) next.set('tienda_id', String(cambios.tienda_id))
    setSp(next, { replace: true })
  }

  useEffect(() => {
    api.get<Sede[]>('/auth/tiendas').then(r => {
      setSedes(r.data)
    }).catch(() => {})
    // Badge de solicitudes pendientes (lo que las baristas pidieron y espera decisión)
    api.get<Solicitud[]>('/solicitudes/pedido/todas')
      .then(r => setNPendientes(r.data.filter(s => s.estado === 'pendiente').length))
      .catch(() => {})
  }, [])

  const sedeNombre = sedes.find(s => s.id === tiendaId)?.nombre ?? ''

  return (
    <div className="space-y-4 pb-10">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <ShoppingCart size={18} className="text-amber-600" />
          <h1 className="text-lg font-bold text-gray-800">Pedidos</h1>
          {sedeNombre && <span className="text-sm text-gray-400">· {sedeNombre}</span>}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {sedes.length > 1 && (
            <div className="flex gap-1">
              {sedes.map(s => (
                <button key={s.id} onClick={() => irA({ tienda_id: s.id })}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    tiendaId === s.id
                      ? 'bg-amber-500 text-white'
                      : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
                  }`}>
                  {s.nombre}
                </button>
              ))}
            </div>
          )}

          <div className="flex bg-gray-100 rounded-xl p-0.5">
            <button
              onClick={() => irA({ tab: 'pedidos' })}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === 'pedidos' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <ShoppingCart size={13} /> Armar pedido
            </button>
            <button
              onClick={() => irA({ tab: 'solicitudes' })}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === 'solicitudes' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <ClipboardList size={13} /> Solicitudes
              {nPendientes > 0 && (
                <span className="bg-red-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center">
                  {nPendientes}
                </span>
              )}
            </button>
            <button
              onClick={() => irA({ tab: 'proveedores' })}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                tab === 'proveedores' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Settings2 size={13} /> Proveedores
            </button>
          </div>
        </div>
      </div>

      {tab === 'pedidos'     && <TabPedidos     tiendaId={tiendaId} sedeNombre={sedeNombre} />}
      {tab === 'solicitudes' && <TabSolicitudes onCount={setNPendientes} />}
      {tab === 'proveedores' && <TabProveedores tiendaId={tiendaId} />}
    </div>
  )
}
