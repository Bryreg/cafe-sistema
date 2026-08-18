import { useCallback, useEffect, useMemo, useState } from 'react'
import { Landmark, Wallet } from 'lucide-react'
import api from '../api/client'
import { Dato, ambos, datoListo } from '../api/dato'
import { useDato } from '../api/useDato'
import { FranjaDeConfianza } from '../components/ui'
import {
  RentabilidadData, PorProductoData, PulsoData,
  computeOutliers, computeInsumosSinCosto,
} from '../components/rentabilidad/helpers'
import ResultadoView from '../components/rentabilidad/ResultadoView'
import LaPlataView from '../components/plata/LaPlataView'
import { Agenda, Categoria, Flujo, Tienda } from '../components/plata/tipos'
import { CuentaBanco } from '../components/plata/banco'
import { hoyBogota } from '../utils/fechaLocal'

// ─── Plata: el módulo único de la plata del negocio ──────────────────────────
//
// ═════════════════════════════════════════════════════════════════════════════
// DOS PESTAÑAS, DOS PREGUNTAS
// ═════════════════════════════════════════════════════════════════════════════
//   La plata  → ¿ME ALCANZA?  cuánta hay, qué entró, qué hay que pagar y cuándo
//                             se acaba. Abre en HOY, porque hoy es una fila del
//                             libro.
//   Resultado → ¿GANO?        el margen del mes, en qué se fue lo que no quedó,
//                             qué sede y qué producto dejan plata.
//
// ── POR QUÉ MURIÓ «HOY» ────────────────────────────────────────────────────
// Se verificó leyendo el código: la vista de «Hoy» no traía UN SOLO dato propio.
// Consumía `pulso` (la venta), `plMes` (el margen del mes, que es Resultado),
// `prodData` (los productos, que es Resultado) y la tarjeta de compromisos (el
// punto de quiebre, que es La plata). No era una pregunta: era un resumen de las
// otras dos, y por eso el dueño tenía tres pestañas para dos decisiones.
//
// Cada pieza que vivía ahí se mudó a la pestaña que contesta SU pregunta: la
// venta del día y el punto de quiebre a La plata; el margen con su semáforo, el
// duelo de sedes y los insumos que subieron a Resultado.
//
// ── POR QUÉ MURIERON LOS CAJONES ───────────────────────────────────────────
// Pedido textual del dueño: «no quiero desplegar pestañas para hacer un
// movimiento o agregar una obligación, tampoco quiero que los pagos a
// proveedores queden escondidos». Los cuatro cajones y los ocho modales dejaron
// de existir COMO MECANISMO; su contenido está entero, repartido en banners de
// las dos páginas. La carga de un movimiento y la de una obligación —lo que se
// hace todos los días— quedaron como filas siempre visibles.

type Tab = 'plata' | 'resultado'
const TABS: { id: Tab; label: string; sub: string; Icon: typeof Wallet }[] = [
  { id: 'plata', label: 'La plata', sub: '¿me alcanza?', Icon: Landmark },
  { id: 'resultado', label: 'Resultado', sub: '¿gano?', Icon: Wallet },
]
const IDS = TABS.map(t => t.id)

/**
 * Los links viejos siguen entrando donde corresponde.
 *
 * `hoy` TIENE que estar acá: esa pestaña ya no existe, y el dueño tiene la URL
 * `/plata#hoy` guardada en el navegador de la tablet. Sin el alias caería en el
 * default sin ninguna explicación. `calendario` es el nombre todavía más viejo
 * de «La plata», y /costos y /pagos-proveedores redirigen a `/plata#plata`
 * (App.tsx).
 */
const ALIAS: Record<string, Tab> = { calendario: 'plata', hoy: 'plata' }
const tabFromHash = (): Tab => {
  const h = window.location.hash.replace('#', '')
  if (IDS.includes(h as Tab)) return h as Tab
  // El default es «La plata»: es la pantalla de todos los días.
  return ALIAS[h] ?? 'plata'
}

/** «Hoy» e inicio de mes según el reloj de COLOMBIA, nunca el del navegador. */
function mesActualBogota(): { desde: string; hasta: string } {
  const s = hoyBogota()
  const [y, m] = s.split('-')
  return { desde: `${y}-${m}-01`, hasta: s }
}

export default function Plata() {
  const [tab, setTab] = useState<Tab>(tabFromHash)

  // ═══════════════════════════════════════════════════════════════════════════
  // LOS NUEVE DATOS DE LA PÁGINA
  // ═══════════════════════════════════════════════════════════════════════════
  // Viven acá porque una mutación en un banner cambia lo que muestran otros:
  // pagar una obligación mueve la agenda, el punto de quiebre Y el margen del mes.
  //
  // Cada uno es una `Fuente<T>`, no un `T | null`. El molde viejo era
  // `.then(r => setX(r.data)).catch(() => setX(null))` ocho veces, y ese `null`
  // significaba a la vez «no llegó», «llegó vacío» y «no volvió» — que es como
  // «no se pudo preguntar» terminaba dibujándose de $0 y de verde. El detalle
  // completo está en `src/api/dato.ts`.
  //
  // El segundo argumento de `useDato` es el nombre EN CASTELLANO que ve el dueño
  // en la franja de arriba cuando ese fetch falla; el tercero, el mensaje para
  // cuando no hubo respuesta (si el backend contestó con `detail`, gana el detail).

  /** Sube con cada mutación: es la señal para las vistas con fetch propio. */
  const [refresco, setRefresco] = useState(0)

  const pulso = useDato<PulsoData>(
    () => api.get('/rentabilidad/pulso'), 'el pulso del mes',
    'No se pudo leer el pulso del mes.')

  const prodData = useDato<PorProductoData>(
    () => api.get('/rentabilidad/por-producto'), 'los productos',
    'No se pudieron leer los productos.', [refresco])

  const plMes = useDato<RentabilidadData>(
    () => { const { desde, hasta } = mesActualBogota(); return api.get('/rentabilidad/', { params: { desde, hasta } }) },
    'el resultado del mes', 'No se pudo leer el resultado del mes.', [refresco])

  /**
   * LA VENTA DEL DÍA, pedida aparte y con el rango de HOY.
   *
   * No se deriva de `/rentabilidad/pulso`: ese endpoint es del MES a la fecha
   * (get_pulso arranca el día 1), y rotular sus KPIs como «hoy» sería decidir
   * con un dato que está CERCA del correcto — la familia de error que costó
   * nueve rondas. Acá el backend devuelve `ventas` y `n_tickets` del día
   * Colombia, resueltos, y son los que se muestran.
   */
  const ventasHoy = useDato<RentabilidadData>(
    () => { const hoy = hoyBogota(); return api.get('/rentabilidad/', { params: { desde: hoy, hasta: hoy } }) },
    'la venta de hoy', 'No se pudo leer la venta de hoy.')

  /**
   * La agenda va SIN rango: «La plata» navega meses hacia adelante y hacia atrás
   * y pedirla por rango obligaría a un fetch por cada flechita. El flujo va con
   * horizonte fijo de 30 días, que es lo único que se muestra de él.
   *
   * Ninguno de los dos lleva `tienda_id`: filtrar el flujo por sede saca el saldo
   * del banco de la cuenta (la cuenta es de la empresa) y deja afuera el arriendo
   * y la nómina, que son corporativos. El resultado sería una proyección que no
   * contesta «¿me alcanza?» sino una versión mutilada de la pregunta.
   */
  const agenda = useDato<Agenda>(
    () => api.get('/costos/agenda'), 'la agenda de pagos',
    'No se pudo leer la agenda de pagos.', [refresco])

  const flujo = useDato<Flujo>(
    () => api.get('/costos/flujo', { params: { dias: 30 } }), 'la proyección a 30 días',
    'No se pudo leer la proyección.', [refresco])

  // Los tres catálogos. Antes caían a `[]`, que en un `<select>` se dibuja igual
  // que «no hay ninguna cuenta cargada» — y ahí el dueño concluía que tenía que
  // ir a crear una cuenta que ya existe.
  const categorias = useDato<Categoria[]>(
    () => api.get('/costos/categorias'), 'las categorías de gasto',
    'No se pudieron leer las categorías.')

  const tiendas = useDato<Tienda[]>(
    () => api.get('/auth/tiendas'), 'las sedes', 'No se pudieron leer las sedes.')

  const cuentas = useDato<CuentaBanco[]>(
    () => api.get('/banco/cuentas'), 'las cuentas del banco',
    'No se pudieron leer las cuentas del banco.')

  /** Lo que mira la franja de confianza: si algo de esto falló, el dueño lo sabe. */
  const fuentes = useMemo(
    () => [pulso, prodData, plMes, ventasHoy, agenda, flujo, categorias, tiendas, cuentas],
    [pulso, prodData, plMes, ventasHoy, agenda, flujo, categorias, tiendas, cuentas])

  /**
   * Se tocó plata en algún banner. Sin esto quedaban dos números para la misma
   * pregunta: el dueño adoptaba un egreso o pagaba el arriendo y la proyección
   * seguía mostrando el mundo de antes, con el optimista adelante.
   *
   * Sube `refresco`, que además de avisarle a las vistas con fetch propio es la
   * dependencia de los seis recursos que dependen de la plata. Los tres
   * catálogos NO se repiden: no cambian al pagar una obligación.
   */
  const refrescarTodo = useCallback(() => setRefresco(n => n + 1), [])
  //
  // `pulso` y `ventasHoy` NO llevan `[refresco]`, y es deliberado: los dos son
  // VENTA, y en esta página no se vende. Pagar el arriendo no cambia lo que se
  // facturó hoy. Repedirlos sería un ida y vuelta de más por cada guardado —en
  // una tablet con la señal del local, eso se siente— y además haría parpadear
  // dos banners que nadie tocó. El set que se repide es exactamente el mismo
  // que antes del refactor: agenda, flujo, resultado del mes y productos.

  // Tab ↔ hash de URL (deep-links y botón atrás del navegador).
  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const goTab = useCallback((t: Tab) => {
    window.location.hash = t
    setTab(t)
    window.scrollTo({ top: 0 })
  }, [])
  const irALaPlata = useCallback(() => goTab('plata'), [goTab])

  /**
   * Lo que le falta a los datos para que el margen sea real.
   *
   * Se calcula acá una sola vez y baja al banner de salud: sumar outliers,
   * insumos sin costo, facturas sin leer y —por MONTO, no por contador— la falta
   * de costos fijos del mes. Sin el último, «Datos sanos» podía afirmarse con el
   * arriendo entero faltando.
   */
  const pendientesDatos: Dato<number> = useMemo(() => {
    // Los DOS tienen que estar. El viejo `plMes && !plMes.resumen...` cortaba en
    // el `&&` y sumaba 0 cuando el P&L no volvía: un resultado del mes muerto
    // aportaba cero pendientes, exactamente igual que un mes con todo cargado.
    // «Datos sanos» podía afirmarse con el arriendo entero faltando.
    const base = ambos(prodData.dato, plMes.dato)
    if (base.estado !== 'listo') return base
    const [prod, pl] = base.valor
    // Y si una derivación no tuvo con qué comparar, el total tampoco la tiene:
    // contarla como cero pendientes es el veredicto tranquilizador otra vez.
    const out = computeOutliers(prod.productos)
    if (out.estado !== 'listo') return out
    const ins = computeInsumosSinCosto(prod.productos)
    if (ins.estado !== 'listo') return ins
    return datoListo(
      out.valor.length + ins.valor.length
      + (prod.facturas_pendientes_de_costos || 0)
      + (pl.resumen.tiene_costos_fijos ? 0 : 1))
  }, [prodData.dato, plMes.dato])

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Wallet size={20} className="text-forest" />
        <h1 className="text-lg font-bold text-warm-700">Plata</h1>
      </div>

      {/* «¿Le puedo creer a esta pantalla?». Solo aparece si algo se rompió:
          en el día normal no ocupa un píxel. Va arriba de las pestañas porque
          la respuesta vale para las dos. */}
      <FranjaDeConfianza fuentes={fuentes} />

      {/* Dos pestañas, con la pregunta que contesta cada una debajo del nombre:
          es lo que evita tener que abrirlas para acordarse cuál era cuál. */}
      <div className="sticky top-0 z-20 -mx-1 px-1 py-1.5 bg-warm-50/90 backdrop-blur-sm">
        <div className="grid grid-cols-2 gap-1 bg-warm-100 rounded-xl p-1">
          {TABS.map(({ id, label, sub, Icon }) => (
            <button key={id} onClick={() => goTab(id)}
              className={`flex items-center justify-center gap-1.5 min-h-[46px] rounded-lg transition-colors ${
                tab === id ? 'bg-white text-forest shadow-sm' : 'text-warm-500'}`}>
              <Icon size={15} className="shrink-0" />
              <span className="text-left leading-tight">
                <span className="block text-xs font-bold">{label}</span>
                <span className={`block text-[10px] ${tab === id ? 'text-forest/70' : 'text-warm-400'}`}>
                  {sub}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Las vistas reciben la `Fuente` ENTERA, no solo el dato: así cada banner
          tiene su propio «Reintentar» sin cablear un callback por recurso desde
          acá, y el dueño no tiene que recargar la página —ni perder lo que
          estaba tecleando— para volver a pedir lo único que falló. */}
      {tab === 'plata' && (
        <LaPlataView
          agenda={agenda} flujo={flujo} pulso={pulso} ventasHoy={ventasHoy}
          categorias={categorias} tiendas={tiendas} cuentas={cuentas}
          onCambio={refrescarTodo} />
      )}

      {tab === 'resultado' && (
        <ResultadoView
          pulso={pulso} prodData={prodData} plMes={plMes}
          categorias={categorias} tiendas={tiendas}
          pendientesDatos={pendientesDatos}
          refreshKey={refresco}
          onRefrescarProductos={prodData.recargar}
          onIrALaPlata={irALaPlata}
          onCambio={refrescarTodo} />
      )}
    </div>
  )
}
