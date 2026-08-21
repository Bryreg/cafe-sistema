import { useEffect, useRef, useState } from 'react'
import { ArrowDownLeft, ArrowUpRight, Plus } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { CuentaBanco, MovimientoBanco, detalleDeError, fechaCorta, plata } from './banco'
import type { Agenda, AgendaItem, AgendaSinFecha, Categoria } from './tipos'
import { Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, ErrorCampo, teclas } from './campos'

/** El lugar de un select mientras su catálogo no está: gris y mudo, sin afirmar
 *  que no haya nada. Misma caja para los dos (cuentas y obligaciones) porque las
 *  dos ocupan una celda de la misma grilla y con alturas distintas se descuadra. */
const CajaMuda = ({ texto }: { texto: string }) => (
  <p className="text-[11px] text-warm-500 bg-warm-100 rounded-xl px-3 py-3 min-h-[44px] flex items-center">
    {texto}
  </p>
)

/**
 * Una obligación que la agenda todavía cuenta como plata por salir.
 *
 * Sale de la agenda y no de `/costos/obligaciones` por una razón concreta: la
 * agenda es la ÚNICA lista que ya descuenta lo que salió del banco enlazado
 * (`cubierto_de` en services/costos.py), así que es exactamente «lo que la
 * proyección sigue esperando». Enlazar acá hace desaparecer la opción de la
 * próxima lectura, y esa es la señal de que el enlace sirvió. El listado de
 * obligaciones no aplica esa cuenta: seguiría ofreciendo lo ya cubierto y dejaría
 * enlazar la misma plata dos veces. Además la página ya la tiene pedida y la
 * repide sola después de guardar, así que esto no agrega un fetch a las 7am.
 */
type Pendiente = AgendaItem | AgendaSinFecha

/**
 * «Arriendo · Vida · $2.400.000 · vence 3 sep».
 *
 * El monto NO es opcional: dos sedes tienen dos arriendos con el mismo concepto
 * y sin la cifra no hay con qué elegir. Y es el SALDO que falta, no el total.
 *
 * LA FECHA TAMPOCO ES OPCIONAL, y es la que más caro sale omitir. «Repetir»
 * copia una obligación al mes siguiente con el mismo concepto Y el mismo monto,
 * así que el arriendo de agosto y el de septiembre están vivos a la vez y se
 * escriben IDÉNTICOS. Enlazar el débito de agosto a la fila de septiembre hace
 * desaparecer de la agenda una deuda que todavía no vence y deja proyectada la
 * que ya está vencida: la plata cuadra en el total y las dos filas mienten.
 */
const etiqueta = (o: Pendiente) => {
  // `!== null` y no un chequeo de verdad: `AgendaItem.fecha` es `string`, así que
  // para el compilador podría ser '' y la rama de abajo seguiría incluyendo a los
  // dos tipos. `null` es el discriminante real de la unión.
  const cuando = o.fecha !== null
    ? `vence ${fechaCorta(o.fecha)}`
    // Las sin fecha se rotulan por su devengo, que es lo único que las ubica en
    // el tiempo — si no, dos «sin fecha» iguales vuelven al mismo empate.
    : `sin fecha · de ${fechaCorta(o.fecha_devengo)}`
  return `${o.concepto}${o.tienda_nombre ? ` · ${o.tienda_nombre}` : ''}`
    + ` · ${plata(o.monto)} · ${cuando}`
}

// Las dos grillas anchas, escritas ENTERAS y no armadas por concatenación: el
// JIT de Tailwind lee clases literales del código fuente y una plantilla
// interpolada no genera ninguna regla.
//
// LA COLUMNA DEL ENLACE ES `1fr` Y NO UN ANCHO FIJO, y esto no es cosmético: los
// cuatro primeros campos suman 36.5rem inamovibles y el botón otros ~90px, así
// que en la tablet —con la barra lateral de 15rem comiéndose el ancho a partir de
// `lg`— al concepto le quedan un par de cientos de píxeles y nada más. Una
// séptima columna de ancho fijo se los comía enteros y dejaba el concepto en un
// hilo, o directamente empujaba la fila fuera de la pantalla. Compartiendo el
// sobrante con el concepto, el ancho MÍNIMO de la fila no cambia (solo se suma un
// gap) y aparecer el select no puede romper el renglón.
const GRILLA_SM = 'sm:grid-cols-[7.5rem_11rem_9rem_9rem_1fr_auto]'
const GRILLA_SM_CON_ENLACE = 'sm:grid-cols-[7.5rem_11rem_9rem_9rem_1fr_1fr_auto]'

/**
 * Cargar un movimiento del banco — LA FILA, no un modal.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * POR QUÉ DEJÓ DE SER UN MODAL
 * ═════════════════════════════════════════════════════════════════════════════
 * Pedido textual del dueño: «no quiero desplegar pestañas para hacer un
 * movimiento». Era el formulario MÁS usado del módulo y costaba abrir un modal,
 * llenarlo, guardarlo y verlo cerrarse — y para el siguiente, todo de nuevo.
 * Acá la fila queda montada: guardar limpia los campos y devuelve el foco al
 * primero, así que veinte movimientos seguidos son veinte tabuladas, no veinte
 * aperturas.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * LO QUE NO SE PUEDE PERDER AL SACARLO DEL MODAL
 * ═════════════════════════════════════════════════════════════════════════════
 *  - EL TIPO ARRANCA SIN ELEGIR. Un default («salida», por ser lo más común) se
 *    guarda sin que nadie lo mire, y el signo equivocado no se nota hasta que el
 *    mes no cuadra contra el extracto. Que el botón no se habilite hasta elegirlo
 *    cuesta un toque y evita el único error caro de este formulario.
 *  - EL MONTO VA SIEMPRE POSITIVO: el signo lo pone «Entró»/«Salió», que es la
 *    regla de `services/banco.py`. Un campo con signo dejaría que una salida de
 *    −$100.000 sumara plata.
 *  - EL TIPO NO SE CONSERVA ENTRE CARGAS. Es la única cosa que NO se limpia por
 *    comodidad sino que se limpia por seguridad: encadenar una entrada después
 *    de otra sin volver a mirar el botón es exactamente cómo se cuela el signo
 *    equivocado en la carga número 14.
 *  - GUARDAR SALTA AL MES DEL MOVIMIENTO GUARDADO, no al que se estaba mirando
 *    (lo hace quien monta esta fila, con la fecha que devuelve el backend): la
 *    fecha es editable, y guardar algo de otro mes sin ver ningún cambio en
 *    pantalla se lee como que no se guardó.
 *  - «CARGANDO» Y «NO HAY NINGUNA» NO SON LA MISMA CAJA. Antes las dos decían
 *    «Cargando las cuentas…» porque el catálogo llegaba como `CuentaBanco[]` y
 *    una lista vacía no se distinguía de una que no volvió. Con el catálogo
 *    caído esa caja se quedaba puesta para siempre y el dueño esperaba un fetch
 *    que ya había fallado.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * EL ENLACE A UNA OBLIGACIÓN — la mitad de pantalla del arreglo del doble conteo
 * ═════════════════════════════════════════════════════════════════════════════
 * El dueño teclea acá la salida del arriendo contra el extracto y el saldo del
 * banco baja. Pero la obligación del arriendo sigue viva en la agenda, así que la
 * proyección la sigue contando como salida FUTURA: la misma plata dos veces, y el
 * día en que se queda sin plata sale ANTES de lo real.
 *
 * El backend ya sabe cerrar eso —`_salidas_banco_por_obligacion` + `cubierto_de`
 * en services/costos.py descuentan de la agenda lo que salió del banco enlazado—
 * pero hasta acá NADIE podía escribir ese enlace desde el libro: el único lugar
 * que llenaba `obligacion_id` era `FormPagoObligacion`, y por ese camino el pago
 * ya existía. Sin este select, la guarda del backend no la puede usar nadie.
 *
 * Tres decisiones, y las tres son sobre no estorbar el trabajo de las 7am:
 *  - SOLO EN LAS SALIDAS. Una entrada enlazada a una obligación no significa
 *    nada, y `_salidas_banco_por_obligacion` solo suma salidas: quedaría escrita
 *    en la base sin efecto, que es peor que no escribirla.
 *  - OPCIONAL Y SIN GATE. Con la agenda caída el formulario sigue entero: se
 *    teclea el movimiento igual, sin enlace, con el aviso arriba. Veinte
 *    movimientos seguidos del extracto no pueden depender de un segundo fetch.
 *  - NO PRELLENA EL MONTO (sí el concepto, y solo si está vacío). Ver `elegir`.
 */
export default function FormMovimiento({
  fechaInicial, cuentas, agenda, maxFecha, onGuardado,
  categorias, tasaGmf, onCategoriaCreada,
}: {
  /** Con qué día arranca. El libro precarga hoy, o el día de la fila que lo abrió. */
  fechaInicial: string
  cuentas: Fuente<CuentaBanco[]>
  /** De dónde salen las obligaciones enlazables. Es la MISMA fuente que ya usa el
   *  libro para las líneas «Vence $X», no un fetch nuevo: la página la pide una
   *  vez y la repide sola después de cada guardado. */
  agenda: Fuente<Agenda>
  /** Hoy en Colombia: el backend RECHAZA fechas futuras (el libro es plata que ya
   *  se movió), así que el campo no las ofrece en vez de ofrecerlas y fallar. */
  maxFecha: string
  onGuardado: (movimiento: MovimientoBanco) => void
  /**
   * El catálogo COMPLETO (`/costos/categorias?ambito=todas`): café, personales
   * y las del banco. Opcional en dos sentidos: el campo es opcional para el
   * dueño (un movimiento sin clasificar es válido), y la prop tolera el
   * servidor viejo que solo devuelve las del café — el select ofrece lo que
   * haya, sin inventar.
   */
  categorias?: Fuente<Categoria[]>
  /** La tasa del GMF (4×1000) que viaja en el libro. null/undefined = no se
   *  conoce y la sugerencia no aparece: proponer un monto con tasa inventada
   *  es la familia de error de la casa. */
  tasaGmf?: number | null
  /** Se creó una categoría desde acá: el catálogo de la página tiene que
   *  repedirse para que el resto de los selects la vean. */
  onCategoriaCreada?: () => void
}) {
  /** El catálogo LEÍDO, o `null` mientras no esté en la mano. `null` no es «no
   *  hay cuentas»: es «no se sabe». Solo alimenta el default del efecto. */
  const cs = cuentas.dato.estado === 'listo' ? cuentas.dato.valor : null

  const [fecha, setFecha] = useState(fechaInicial)
  const [cuentaId, setCuentaId] = useState(cs?.[0] ? String(cs[0].id) : '')
  const [tipo, setTipo] = useState<'entrada' | 'salida' | null>(null)
  const [monto, setMonto] = useState('')
  const [concepto, setConcepto] = useState('')
  /** '' = sin enlazar, y es un valor legítimo: el enlace es opcional. */
  const [obligacionId, setObligacionId] = useState('')
  /** '' = sin clasificar, también legítimo: la categoría es un rótulo, no un gate. */
  const [categoriaId, setCategoriaId] = useState('')
  /** Esta entrada es un depósito de lo recogido: efectivo que ya estaba en la
   *  mano y que pasa al banco. Sube el banco y baja la mano — neutro al total.
   *  Solo aplica a las entradas; se olvida al pasar a «Salió» y al guardar. */
  const [desdeMano, setDesdeMano] = useState(false)
  // La creación sobre la marcha: cuando cargue «Reteica» o «Cuota del carro»
  // por primera vez, la categoría nace ACÁ, sin ir a otra pantalla.
  const [creandoCat, setCreandoCat] = useState(false)
  const [nuevoNombre, setNuevoNombre] = useState('')
  const [nuevoAmbito, setNuevoAmbito] = useState<'cafe' | 'personal'>('cafe')
  const [creandoCatOcupado, setCreandoCatOcupado] = useState(false)
  /** La salida recién guardada, para ofrecerle su GMF con un toque. */
  const [gmfPendiente, setGmfPendiente] = useState<
    { fecha: string; cuentaId: number; monto: number } | null>(null)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [ultimo, setUltimo] = useState('')
  /** Un aviso del backend sobre lo recién guardado (p.ej. «esa entrada de
   *  Occidente puede estar contada dos veces»). No es un error: quedó guardado. */
  const [aviso, setAviso] = useState('')

  const cats = categorias?.dato.estado === 'listo' ? categorias.dato.valor : null
  const catGmf = cats?.find(c => c.clave === 'gmf')
  const catElegida = cats?.find(c => String(c.id) === categoriaId)

  // El foco vuelve acá después de guardar: es el primer campo que se toca para
  // cargar el siguiente movimiento.
  const refMonto = useRef<HTMLInputElement>(null)

  // EL DEFAULT SE SINCRONIZA CUANDO LLEGA EL CATÁLOGO. El useState corre en el
  // PRIMER render, cuando la lista todavía no llegó porque el fetch va en un
  // hook del padre. Sin esto el estado quedaba en '' para siempre —el componente
  // no remonta— y el resultado era el peor posible: el select se ve CON una
  // opción elegida (React marca la primera cuando el value controlado no matchea
  // ninguna) y el botón «Guardar» gris, sin explicación. El dueño tecleaba todo
  // y no podía guardar. No pisa lo que ya eligió: solo llena el hueco.
  useEffect(() => {
    if (!cuentaId && cs && cs.length > 0) setCuentaId(String(cs[0].id))
  }, [cs, cuentaId])

  const cuenta = cs?.find(c => String(c.id) === cuentaId)
  // El enlace NO entra acá a propósito: es opcional, y meterlo en `listo`
  // convertiría un campo de ayuda en un requisito para guardar el movimiento.
  const listo = !!fecha && !!cuentaId && !!tipo && Number(monto) > 0 && !!concepto.trim()

  /**
   * Lo enlazable: las obligaciones con saldo, agendadas y sin fecha.
   *
   * Las dos listas van juntas porque `get_agenda` las parte por si tienen o no
   * fecha de vencimiento —que es un campo OPCIONAL del alta— y no por si se
   * deben: las de `sin_fecha` también quedan cubiertas por `cubierto_de`. Dejar
   * afuera las que no tienen fecha sería esconder justo las que nadie fechó.
   *
   * El filtro por `tipo` no es defensivo: `items` trae también las facturas de
   * proveedor, y `obligacion_id` no las acepta (son otra tabla). El orden que
   * viene del backend se respeta: primero lo agendado de más viejo a más nuevo
   * —lo más probable que esté pagando—, después lo que no tiene fecha.
   */
  const pendientes = mapDato(agenda.dato, a =>
    [...a.items, ...a.sin_fecha].filter(i => i.tipo === 'obligacion'))

  /** La obligación elegida, o `undefined`. Se resuelve SOLO con la lista en la
   *  mano (la rama `listo` del Dato, no el `listo` de este formulario): sin ella
   *  no hay de dónde sacar el concepto que se confirma después de guardar. */
  const enlazada = pendientes.estado === 'listo'
    ? pendientes.valor.find(o => String(o.id) === obligacionId)
    : undefined

  /**
   * Eligió una obligación: se guarda el id y se PRELLENA EL CONCEPTO SI ESTÁ VACÍO.
   *
   * Y el monto NO, aunque la etiqueta lo muestre. Este libro se teclea contra el
   * extracto —decisión del dueño, fidelidad al banco por encima de la comodidad—
   * y el monto es el único campo donde eso se juega. Copiar la cifra de la
   * obligación adentro del movimiento la vuelve circular: `cubierto_de` toma el
   * máximo entre lo pagado y lo que salió del banco, así que una salida heredada
   * de la obligación SIEMPRE la cubre exacto. El enlace dejaría de ser evidencia
   * del banco para ser la obligación confirmándose sola, y un débito que en el
   * extracto decía $2.395.000 se guardaría en $2.400.000 sin que nadie lo mire.
   *
   * El costo de no prellenarlo es cero: el monto es el campo que arranca con el
   * foco, así que en el orden normal ya está tecleado cuando se toca este select.
   * El concepto sí se prellena porque es un rótulo para conciliar a ojo contra el
   * extracto —cualquiera sirve mientras diga qué fue— y es lo que ahorra tipeo.
   */
  const elegir = (id: string) => {
    setObligacionId(id)
    const o = pendientes.estado === 'listo'
      ? pendientes.valor.find(x => String(x.id) === id)
      : undefined
    if (o && !concepto.trim()) setConcepto(o.concepto)
  }

  const guardar = async () => {
    // GUARDA DE REENTRADA. Enter y el botón llaman a lo mismo, y entre el
    // toque y la respuesta hay una ida y vuelta: dos toques ahí adentro
    // escribían DOS veces. En una tablet con conexión lenta eso duplica un
    // movimiento, un pago o una obligación, y `registrar_pago` del backend
    // ni siquiera valida contra el saldo.
    if (guardando) return
    if (!listo || !tipo) return
    setGuardando(true); setError('')
    try {
      const r = await api.post<MovimientoBanco>('/banco/movimientos', {
        fecha,
        cuenta_id: Number(cuentaId),
        tipo,
        monto: Number(monto),
        concepto: concepto.trim(),
        // Blindado por tipo además de por el select: el estado del enlace vive
        // acá arriba y sobrevive a que la celda se desmonte. Sin esta guarda, un
        // «Salió» enlazado y después cambiado a «Entró» mandaría el enlace igual,
        // y quedaría escrito en la base sin efecto — `_salidas_banco_por_obligacion`
        // solo suma salidas. Una fila que dice pagar algo que no paga nada.
        obligacion_id: tipo === 'salida' && obligacionId ? Number(obligacionId) : null,
        categoria_id: categoriaId ? Number(categoriaId) : null,
        // Blindado por tipo, igual que el enlace: el estado vive acá arriba y
        // sobrevive a que la celda se desmonte. Un «Entró» marcado como depósito
        // y después cambiado a «Salió» no debe mandar la marca — el backend la
        // rechaza en una salida, pero no dependemos de eso para no mandarla.
        desde_mano: tipo === 'entrada' && desdeMano,
      })
      // El GMF se OFRECE, nunca se escribe solo: el banco lo cobra por débito y
      // la fila sale con un toque — pero es el dueño el que confirma que este
      // débito lo paga. Solo con la tasa conocida y la categoría sembrada, y
      // nunca sobre un GMF (el impuesto no paga impuesto).
      setGmfPendiente(
        tipo === 'salida' && tasaGmf && catGmf && catElegida?.clave !== 'gmf'
          ? { fecha, cuentaId: Number(cuentaId), monto: Number(monto) }
          : null)
      // Confirmación EN LA FILA. Sin el modal que se cerraba, guardar no tenía
      // ningún gesto propio: la grilla de abajo cambia, pero el ojo está acá.
      // Lo del enlace se lee de la RESPUESTA y no de lo que se mandó: el enlace
      // es lo único de esta fila que no se ve en el libro, así que confirmarlo
      // con lo que el backend guardó es la única forma de saber que quedó.
      // El nombre de la obligación es un lujo; DECIR QUE QUEDÓ ENLAZADO no lo es.
      // Si el enlace volvió y por lo que sea no se puede nombrar, se dice igual:
      // callarlo se lee como que el enlace no se hizo, y el dueño lo vuelve a
      // cargar o va a registrar el pago aparte — el doble conteo que vinimos a
      // cerrar, entrando por la otra puerta.
      setUltimo(`${tipo === 'entrada' ? 'Entró' : 'Salió'} ${conMiles(monto)} · ${concepto.trim()}`
        + (r.data.obligacion_id
          ? ` · enlazado a ${enlazada ? enlazada.concepto : 'una obligación'}`
          : ''))
      // El enlace se limpia por la misma razón que el tipo, y con más urgencia:
      // arrastrarlo al movimiento siguiente cubriría dos veces la misma obligación
      // y la sacaría de la agenda debiendo plata. La categoría también: el GMF
      // del arriendo no es el arriendo siguiente.
      setMonto(''); setConcepto(''); setTipo(null); setObligacionId(''); setCategoriaId('')
      setDesdeMano(false)
      setAviso(r.data.advertencia ?? '')
      refMonto.current?.focus()
      onGuardado(r.data)
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo guardar el movimiento. Reintentá.'))
    } finally { setGuardando(false) }
  }

  /** El GMF de la salida recién guardada, con un toque. */
  const cargarGmf = async () => {
    if (!gmfPendiente || !tasaGmf || !catGmf || guardando) return
    const montoGmf = Math.round(gmfPendiente.monto * tasaGmf * 100) / 100
    if (montoGmf <= 0) { setGmfPendiente(null); return }
    setGuardando(true); setError('')
    try {
      const r = await api.post<MovimientoBanco>('/banco/movimientos', {
        fecha: gmfPendiente.fecha,
        cuenta_id: gmfPendiente.cuentaId,
        tipo: 'salida',
        monto: montoGmf,
        concepto: 'GMF (4×1000)',
        obligacion_id: null,
        categoria_id: catGmf.id,
      })
      setGmfPendiente(null)
      setUltimo(`Salió ${conMiles(String(Math.round(montoGmf)))} · GMF (4×1000)`)
      onGuardado(r.data)
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo cargar el GMF. Reintentá.'))
    } finally { setGuardando(false) }
  }

  /**
   * La categoría nueva nace desde el propio formulario — «cuando cargue
   * RETEICA por primera vez, que pueda crearla ahí mismo». El ámbito es la
   * única pregunta que importa: ¿es del café o es plata personal? La personal
   * jamás toca el resultado ni el punto de equilibrio, y eso está dicho en el
   * propio botón.
   */
  const crearCategoria = async () => {
    const nombre = nuevoNombre.trim()
    if (!nombre || creandoCatOcupado) return
    setCreandoCatOcupado(true); setError('')
    try {
      const r = await api.post<Categoria>('/costos/categorias', {
        nombre, ambito: nuevoAmbito,
      })
      setCategoriaId(String(r.data.id))
      setCreandoCat(false); setNuevoNombre(''); setNuevoAmbito('cafe')
      onCategoriaCreada?.()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo crear la categoría.'))
    } finally { setCreandoCatOcupado(false) }
  }

  return (
    <div className="px-3 py-3 bg-warm-50 border-b border-warm-100 space-y-2"
      onKeyDown={teclas({ listo, guardar })}>
      <div className="flex items-center gap-1.5">
        <Plus size={13} className="text-forest shrink-0" />
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
          Cargar un movimiento del banco
        </p>
      </div>

      {/* EL AVISO VA ARRIBA DEL SELECT y el formulario se queda montado: sin
          cuenta el backend no acepta el movimiento, así que decirlo acá —con el
          botón de reintentar— es lo único que evita que el dueño teclee todo
          contra un «Guardar» gris que no explica nada. */}
      <SegunDato
        dato={cuentas.dato}
        cargando={null}
        falla={m => (
          <NoSeSabe onReintentar={cuentas.recargar}
            mensaje={`${m} — sin la cuenta no se puede guardar el movimiento. Podés ir tecleando `
              + 'el resto: el día, el monto y el concepto no dependen del catálogo.'} />
        )}
        listo={lista => lista.length === 0 ? (
          <NoSeSabe mensaje="No hay ninguna cuenta de banco cargada, así que todavía no se puede cargar un movimiento." />
        ) : null}
      />

      {/* La agenda no volvió y esto ES una salida: el enlace no se puede hacer.
          El aviso va acá arriba —y no dentro de la celda— porque es el único
          lugar donde entra el «Reintentar», y sale SOLO en las salidas para no
          alarmar en un camino donde el enlace ni existe. El libro tiene otro
          aviso propio para la agenda unas líneas más abajo (BannerLibro): no es
          un duplicado por descuido, dicen dos cosas distintas —aquel habla de
          las líneas «Vence» de la grilla, este de que este movimiento se va a
          guardar sin enlazar. */}
      {tipo === 'salida' && (
        <SegunDato
          dato={agenda.dato}
          cargando={null}
          falla={m => (
            <NoSeSabe onReintentar={agenda.recargar}
              mensaje={`${m} — no se puede enlazar esta salida a una obligación. Guardala igual: `
                + 'el movimiento queda bien cargado, pero la proyección va a seguir esperando ese pago.'} />
          )}
          listo={() => null}
        />
      )}

      {/* Mobile-first: una columna en celular, la fila entera en tablet. El
          monto va PRIMERO en la grilla ancha porque es el campo que se toca
          siempre; la fecha casi nunca se cambia (viene precargada).

          La columna del enlace se agrega al FINAL, entre el concepto y el botón:
          así los cuatro campos de ancho fijo no se mueven cuando aparece —lo
          único que cede lugar es el concepto, que reparte su sobrante— y el
          «Guardar» se queda pegado al borde derecho, donde el dedo lo dejó. En
          celular cae como una fila entera ARRIBA del botón, que es donde tiene
          que estar un campo. */}
      <div className={`grid grid-cols-2 gap-2 items-end ${
        tipo === 'salida' ? GRILLA_SM_CON_ENLACE : GRILLA_SM}`}>
        <Campo label="Día">
          <input type="date" value={fecha} max={maxFecha}
            onChange={e => setFecha(e.target.value)} className={CLS_INPUT} />
        </Campo>

        {/* Dos botones grandes y no un select: es lo que decide el SIGNO de la
            plata, y un desplegable de dos opciones esconde justo el dato que más
            caro sale equivocar. */}
        <Campo label="¿Entró o salió?">
          <div className="grid grid-cols-2 gap-1.5">
            {/* Pasar a «Entró» OLVIDA el enlace, no solo lo esconde: el estado
                vive en el componente y la celda que lo muestra se desmonta, así
                que un enlace elegido y después arrepentido seguiría ahí, mudo. */}
            <button type="button" onClick={() => { setTipo('entrada'); setObligacionId('') }}
              aria-pressed={tipo === 'entrada'}
              className={`flex items-center justify-center gap-1 min-h-[44px] rounded-xl border-2 text-xs font-bold transition-colors ${
                tipo === 'entrada'
                  ? 'border-success-500 bg-success-50 text-success-700'
                  : 'border-warm-200 bg-white text-warm-500'}`}>
              <ArrowDownLeft size={14} /> Entró
            </button>
            <button type="button" onClick={() => { setTipo('salida'); setDesdeMano(false) }}
              aria-pressed={tipo === 'salida'}
              className={`flex items-center justify-center gap-1 min-h-[44px] rounded-xl border-2 text-xs font-bold transition-colors ${
                tipo === 'salida'
                  ? 'border-danger-500 bg-danger-50 text-danger-700'
                  : 'border-warm-200 bg-white text-warm-500'}`}>
              <ArrowUpRight size={14} /> Salió
            </button>
          </div>
        </Campo>

        <Campo label="Monto">
          <input ref={refMonto} type="text" inputMode="numeric" value={conMiles(monto)}
            onChange={e => setMonto(soloDigitos(e.target.value))} placeholder="0"
            aria-label="Monto del movimiento"
            className={CLS_INPUT_PLATA} />
        </Campo>

        <Campo label="Cuenta">
          {/* «Vacío», «todavía no llegó» y «no volvió» son TRES cosas distintas y
              cada una se dibuja distinta: antes las tres decían «Cargando las
              cuentas…», y con el catálogo caído esa caja no se iba nunca. */}
          <SegunDato
            dato={cuentas.dato}
            cargando={<CajaMuda texto="Cargando las cuentas…" />}
            falla={() => <CajaMuda texto="Sin cuentas para elegir" />}
            listo={lista => lista.length === 0
              ? <CajaMuda texto="No hay cuentas cargadas" />
              : (
                <select value={cuentaId} onChange={e => setCuentaId(e.target.value)} className={CLS_INPUT}>
                  {lista.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
              )}
          />
        </Campo>

        <Campo label="Concepto" ancho="col-span-2 sm:col-span-1">
          <input value={concepto} onChange={e => setConcepto(e.target.value)}
            placeholder={tipo === 'entrada' ? 'Consignación del viernes'
              : tipo === 'salida' ? 'Arriendo agosto' : 'Qué fue ese movimiento'}
            className={CLS_INPUT} />
        </Campo>

        {tipo === 'salida' && (
          <Campo label="¿Paga una obligación?" ancho="col-span-2 sm:col-span-1">
            {/* «SIN ENLAZAR» ES UNA OPCIÓN DE VERDAD, con su propio `value=""`, y
                por eso este select NO necesita el efecto de preselección que sí
                necesita el de cuentas. Es el mismo bug visto del otro lado: cuando
                el `value` controlado no matchea ninguna opción, el navegador
                dibuja la PRIMERA como si estuviera elegida. Con el estado en ''
                y sin esta opción, el select mostraría el arriendo y guardaría un
                movimiento sin enlace — el error más caro posible acá, porque se
                ve exactamente igual que el enlace hecho. */}
            <SegunDato
              dato={pendientes}
              cargando={<CajaMuda texto="Cargando la agenda…" />}
              // «No se pudo leer» y no «no hay ninguna»: la caída de la agenda no
              // es una afirmación sobre lo que se debe. El «Reintentar» va en el
              // aviso de arriba, que es donde hay ancho para ponerlo.
              falla={() => <CajaMuda texto="No se pudo leer la agenda" />}
              listo={lista => lista.length === 0
                // Esto SÍ es una afirmación, y por eso vive en `listo`. Dice
                // «obligaciones» y no «pagos»: las facturas de proveedor pueden
                // estar pendientes igual y no se pueden enlazar desde acá.
                ? <CajaMuda texto="No hay obligaciones pendientes" />
                : (
                  <select value={obligacionId} onChange={e => elegir(e.target.value)}
                    className={CLS_INPUT}>
                    <option value="">Sin enlazar</option>
                    {lista.map(o => <option key={o.id} value={o.id}>{etiqueta(o)}</option>)}
                  </select>
                )}
            />
          </Campo>
        )}

        <button type="button" onClick={guardar} disabled={guardando || !listo}
          className={`${CLS_BOTON_GUARDAR} col-span-2 sm:col-span-1`}>
          {guardando ? 'Guardando…' : 'Guardar'}
        </button>
      </div>

      {/* ── ¿ES UN DEPÓSITO DE LO RECOGIDO? — solo en las entradas ───────────
          Cuando el dueño deposita en el banco efectivo que ya había recogido, esa
          plata YA se contó (al recogerla entró a la mano). Marcarlo hace el
          depósito NEUTRO al total: sube el banco, baja la mano. Sin la marca, lo
          recogido quedaría contado dos veces. Va afuera de la grilla y sin gate:
          es opcional, y la enorme mayoría de las entradas son plata nueva. */}
      {tipo === 'entrada' && (
        <label className="flex items-start gap-2.5 rounded-xl border border-success-200 bg-success-50/60 px-3 py-2.5 cursor-pointer">
          <input type="checkbox" checked={desdeMano}
            onChange={e => setDesdeMano(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-success-600" />
          <span className="text-[12px] text-warm-600 leading-snug">
            <b className="text-success-800">Es plata que ya recogí</b> y ahora deposité en el banco.
            <span className="block text-[11px] text-warm-500 mt-0.5">
              Ya la contamos cuando la recogiste, así que acá <b>no vuelve a sumar</b> al total: solo
              pasa de tu mano al banco.
            </span>
          </span>
        </label>
      )}

      {/* ── LA CATEGORÍA: un rótulo, no un gate ─────────────────────────────
          Va en su propia fila y no en la grilla de arriba: es opcional, y la
          fila de carga de las 7am no puede crecer una columna por un campo que
          no hace falta para guardar. Con ella el mes contesta «cuánto nos
          estamos gastando en cada cosa»; sin ella el movimiento queda «sin
          clasificar», que es un estado válido, no un error. Y la categoría
          nueva se crea ACÁ (el pedido textual: cargar «Reteica» por primera
          vez sin ir a otra pantalla). */}
      {categorias && (
        <div className="flex flex-wrap items-end gap-2">
          <Campo label="Categoría (opcional)" ancho="w-56 max-w-full">
            <SegunDato
              dato={categorias.dato}
              cargando={<CajaMuda texto="Cargando categorías…" />}
              falla={() => <CajaMuda texto="No se pudo leer el catálogo" />}
              listo={lista => (
                <select value={categoriaId} onChange={e => setCategoriaId(e.target.value)}
                  className={CLS_INPUT}>
                  <option value="">Sin clasificar</option>
                  {lista.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.nombre}{c.ambito === 'personal' ? ' · personal' : ''}
                    </option>
                  ))}
                </select>
              )}
            />
          </Campo>
          {!creandoCat ? (
            <button type="button" onClick={() => setCreandoCat(true)}
              className="min-h-[44px] px-3 rounded-xl border border-warm-300 text-warm-600 text-xs font-bold hover:bg-warm-100">
              + Nueva categoría
            </button>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <Campo label="Nombre">
                <input value={nuevoNombre} onChange={e => setNuevoNombre(e.target.value)}
                  placeholder="Reteica, Cuota del carro…" className={CLS_INPUT} autoFocus />
              </Campo>
              <Campo label="¿De quién es esta plata?">
                <div className="grid grid-cols-2 gap-1.5">
                  <button type="button" onClick={() => setNuevoAmbito('cafe')}
                    aria-pressed={nuevoAmbito === 'cafe'}
                    className={`min-h-[44px] px-2 rounded-xl border-2 text-xs font-bold ${
                      nuevoAmbito === 'cafe'
                        ? 'border-forest bg-forest-50 text-forest'
                        : 'border-warm-200 bg-white text-warm-500'}`}>
                    Del café
                  </button>
                  <button type="button" onClick={() => setNuevoAmbito('personal')}
                    aria-pressed={nuevoAmbito === 'personal'}
                    className={`min-h-[44px] px-2 rounded-xl border-2 text-xs font-bold ${
                      nuevoAmbito === 'personal'
                        ? 'border-gold-500 bg-gold-50 text-gold-700'
                        : 'border-warm-200 bg-white text-warm-500'}`}>
                    Personal
                  </button>
                </div>
              </Campo>
              <button type="button" onClick={crearCategoria}
                disabled={creandoCatOcupado || !nuevoNombre.trim()}
                className={CLS_BOTON_GUARDAR}>
                {creandoCatOcupado ? 'Creando…' : 'Crear'}
              </button>
              <button type="button" onClick={() => setCreandoCat(false)}
                className="min-h-[44px] px-2 text-xs font-bold text-warm-500">
                Cancelar
              </button>
            </div>
          )}
          {nuevoAmbito === 'personal' && creandoCat && (
            <p className="w-full text-[11px] text-warm-500 leading-snug -mt-1">
              Una categoría <b>personal</b> (la casa, la cuota del carro) solo rotula filas de este
              libro: esa plata sale de la cuenta pero <b>nunca</b> entra al resultado ni al punto de
              equilibrio del café.
            </p>
          )}
          {catElegida?.fuera_del_gasto && (
            <p className="w-full text-[11px] text-gold-700 leading-snug -mt-1">
              «{catElegida.nombre}» sale de la caja pero <b>no cuenta como costo del mes</b> (la
              clasificación vigente, pendiente de confirmar con el contador).
            </p>
          )}
        </div>
      )}

      {/* QUÉ HACE ENLAZAR, en el idioma del dueño y sin pedirle que abra nada.
          Va acá y no como `hint` del campo porque en una columna de 12rem el
          párrafo sale hecho un gusano de una palabra por renglón. Sin esta línea
          el select no se usa —nadie enlaza algo que no sabe para qué sirve— y el
          arreglo del doble conteo queda escrito y muerto. */}
      {tipo === 'salida' && (
        <p className="text-[11px] text-warm-500 leading-snug">
          Si esta salida paga una obligación de la agenda, enlazala: la proyección deja de contarla
          como pago pendiente. Sin enlazar, el saldo del banco baja igual y la obligación se sigue
          esperando — <b>la misma plata contada dos veces</b>, y el día en que se acaba la plata
          aparece antes de lo real.
        </p>
      )}

      {/* La nota del monto y la de la cuenta van juntas y chiquitas: son las dos
          cosas que hay que saber una sola vez, no en cada carga. */}
      <p className="text-[11px] text-warm-400 leading-snug">
        El monto va siempre en positivo: el signo lo pone «Entró» o «Salió». El concepto es lo
        que después te deja conciliar la fila contra el extracto del banco.
        {cuenta?.nota && <> · {cuenta.nota}</>}
      </p>

      <ErrorCampo msg={error} />
      {!error && ultimo && (
        <p className="text-[11px] font-semibold text-success-600">Guardado: {ultimo}</p>
      )}
      {!error && aviso && (
        <p className="text-[11px] font-semibold text-gold-700 leading-snug">{aviso}</p>
      )}

      {/* La sugerencia del GMF, pegada a la confirmación de la salida que lo
          genera. El 4×1000 salía del banco en cada débito y ningún reporte lo
          veía ($3,4 millones en siete meses); ahora la fila sale con un toque
          — pero la confirma el dueño: no todos los débitos lo pagan. */}
      {!error && gmfPendiente && tasaGmf && catGmf && (
        <button type="button" onClick={cargarGmf} disabled={guardando}
          className="flex items-center gap-1.5 min-h-[40px] px-3 rounded-xl border border-gold-500 bg-gold-50 text-gold-700 text-xs font-bold hover:bg-gold-100">
          <Plus size={13} />
          ¿Ese débito pagó GMF? Cargar {plata(Math.round(gmfPendiente.monto * tasaGmf))} (4×1000)
        </button>
      )}
    </div>
  )
}
