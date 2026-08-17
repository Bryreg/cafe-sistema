import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertCircle, Building2, CalendarClock, ChevronLeft, ChevronRight, Landmark,
  Pencil, Plus, Receipt, Tag, Trash2, TrendingDown, Truck, Wallet, Inbox, X,
} from 'lucide-react'
import api from '../../api/client'
import { hoyBogota } from '../../utils/fechaLocal'
import { conMiles, soloDigitos } from '../../utils/plata'
import { Agenda, AgendaItem, AgendaSinFecha } from '../../pages/Costos'
import ModalRegistrarPago from './ModalRegistrarPago'
import ModalMovimiento from './ModalMovimiento'
import {
  CuentaBanco, DiaLibro, LibroMes, SerieAnual,
  MESES, MESES_CORTOS, compacto, detalleDeError, diaSemana, diasEntre,
  esFinde, fechaCorta, fechaLarga, plata,
} from './banco'

/**
 * Plata · «La plata» — el LIBRO del banco y la agenda de pagos, en una sola vista.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * QUÉ REEMPLAZA Y POR QUÉ
 * ═════════════════════════════════════════════════════════════════════════════
 * Reemplaza a `CalendarioView` (la grilla de mes), que junto con la lista de días
 * del cajón del flujo eran la misma vista dibujada dos veces sin que ninguna
 * estuviera completa: la grilla tenía el detalle del vencimiento y el botón de
 * pagar pero no tenía saldo inicial ni entradas; la lista del flujo tenía el
 * saldo y las entradas pero no tenía ni conceptos ni acciones. Peor: la grilla
 * pintaba encima el saldo PROYECTADO, que se pedía con un horizonte de 30 días
 * quemado mientras la grilla navegaba doce meses — pasado ese horizonte la celda
 * pintaba el vencimiento y dejaba de pintar saldo, sin decir por qué.
 *
 * Acá el eje es el LIBRO: plata REAL, la que el dueño concilia contra el
 * extracto. La proyección NO se mezcla en la fila del día a propósito: sigue
 * entera en «Hoy» y en su cajón (que esta pantalla enlaza), que es donde una
 * estimación se puede leer como estimación. Pintar las dos en la misma columna es
 * lo que hacía que dos números que no significan lo mismo se leyeran como si sí.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * LO QUE LA PANTALLA NO PUEDE CONTRADECIR (services/banco.py)
 * ═════════════════════════════════════════════════════════════════════════════
 *  - LA CADENA SE DECIDE POR DÍA, NO POR MES. Cada fila trae su `cadena`: los
 *    días anteriores al ancla vienen con `inicial`/`final` en null y son los
 *    únicos que se pintan «—». Del ancla en adelante el saldo es EXACTO y se
 *    muestra, aunque el mes haya arrancado antes.
 *  - `cadena_completa` significa «TODOS los días del rango tienen saldo», y con
 *    el ancla a mitad de mes —el caso normal— es false casi siempre. Decidir
 *    con ella apagaba el mes entero y le pedía al dueño cargar el extracto que
 *    acababa de cargar: ese era el bug, y por eso acá no se usa para decidir.
 *  - El ancla es un saldo de APERTURA: «con cuánta plata arranco ese día».
 *  - Los días sin movimiento también van: son los que dejan ver que el saldo se
 *    quedó abajo cuatro días seguidos.
 *  - El monto va siempre positivo; el signo lo pone el tipo.
 */
export default function LibroView({
  agenda, cargandoAgenda, refreshKey, onRefrescar,
  onAbrirObligaciones, onAbrirProveedores, onAbrirFlujo,
}: {
  agenda: Agenda | null
  cargandoAgenda: boolean
  /**
   * Sube cada vez que se cierra un cajón. Sin esto, el editor del saldo del banco
   * que vive adentro del cajón del flujo escribe las MISMAS dos claves que el
   * ancla de acá (`saldo_banco`, `saldo_banco_fecha`) y esta pantalla se queda
   * mostrando la cadena vieja: el cajón se abre encima, así que el componente no
   * se desmonta y sus efectos no vuelven a correr solos.
   */
  refreshKey: number
  /** Recarga la agenda y el flujo de Plata (los dos leen lo que se toca acá). */
  onRefrescar: () => void
  onAbrirObligaciones: () => void
  onAbrirProveedores: () => void
  onAbrirFlujo: () => void
}) {
  const hoy = hoyBogota()
  const anioDeHoy = Number(hoy.slice(0, 4))
  const mesDeHoy = Number(hoy.slice(5, 7))

  const [anio, setAnio] = useState(anioDeHoy)
  const [mes, setMes] = useState(mesDeHoy)
  const [libro, setLibro] = useState<LibroMes | null>(null)
  const [serie, setSerie] = useState<SerieAnual | null>(null)
  const [cuentas, setCuentas] = useState<CuentaBanco[]>([])
  // El libro del mes de HOY, solo cuando se está mirando otro mes: el saldo de
  // hoy es la cabecera de la pantalla y no puede depender de dónde navegó el ojo.
  const [libroDeHoy, setLibroDeHoy] = useState<LibroMes | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState('')
  const [refresco, setRefresco] = useState(0)
  const recargar = useCallback(() => setRefresco(n => n + 1), [])

  const [diaAbierto, setDiaAbierto] = useState<string | null>(hoy)
  const [borrandoId, setBorrandoId] = useState<number | null>(null)
  const [nuevoEn, setNuevoEn] = useState<string | null>(null)   // fecha del alta

  // Editor del saldo del extracto, arriba y a un click (antes vivía a cuatro,
  // adentro de un cajón: por eso el dato llegaba viejo o no llegaba).
  const [anclaAbierta, setAnclaAbierta] = useState(false)
  const [aSaldo, setASaldo] = useState('')
  const [aFecha, setAFecha] = useState(hoy)
  const [aError, setAError] = useState('')
  const [guardandoAncla, setGuardandoAncla] = useState(false)

  // Pagar un vencimiento y ponerle fecha a una obligación sin «Vence»: las dos
  // acciones que ya vivían en el calendario y se mudan enteras acá.
  const [pagoDe, setPagoDe] = useState<AgendaItem | null>(null)
  const [fechando, setFechando] = useState<AgendaSinFecha | null>(null)
  const [fVence, setFVence] = useState('')
  const [fError, setFError] = useState('')
  const [guardandoFecha, setGuardandoFecha] = useState(false)

  const viendoElMesDeHoy = anio === anioDeHoy && mes === mesDeHoy

  useEffect(() => {
    let vivo = true
    setCargando(true); setError('')
    Promise.all([
      api.get<LibroMes>('/banco/libro', { params: { anio, mes } }),
      api.get<SerieAnual>('/banco/serie', { params: { anio } }),
    ])
      .then(([l, s]) => { if (!vivo) return; setLibro(l.data); setSerie(s.data) })
      .catch(e => {
        if (!vivo) return
        setLibro(null); setSerie(null)
        setError(detalleDeError(e, 'No se pudo cargar el libro del banco.'))
      })
      .finally(() => { if (vivo) setCargando(false) })
    return () => { vivo = false }
  }, [anio, mes, refresco, refreshKey])

  // El mes de hoy solo se pide aparte cuando NO es el que se está mirando: en el
  // caso normal se lee del mismo libro y no se gasta una segunda consulta.
  useEffect(() => {
    if (viendoElMesDeHoy) { setLibroDeHoy(null); return }
    let vivo = true
    api.get<LibroMes>('/banco/libro', { params: { anio: anioDeHoy, mes: mesDeHoy } })
      .then(r => { if (vivo) setLibroDeHoy(r.data) })
      .catch(() => { if (vivo) setLibroDeHoy(null) })
    return () => { vivo = false }
  }, [viendoElMesDeHoy, anioDeHoy, mesDeHoy, refresco, refreshKey])

  useEffect(() => {
    api.get<CuentaBanco[]>('/banco/cuentas').then(r => setCuentas(r.data)).catch(() => setCuentas([]))
  }, [])

  // ─── El saldo de hoy ────────────────────────────────────────────────────────
  const libroConHoy = viendoElMesDeHoy ? libro : libroDeHoy
  const filaHoy = libroConHoy?.dias.find(d => d.fecha === hoy) ?? null
  // Lo decide LA FILA DE HOY, no el mes. Con el ancla a mitad de mes el mes no
  // está completo pero el saldo de hoy SÍ es exacto: condicionarlo por
  // `cadena_completa` era decirle «falta el saldo del extracto» justo después
  // de que lo cargara. La unión discriminada de `DiaLibro` hace el resto: en la
  // rama con cadena, `inicial` y `final` son números, no `number | null`.
  const saldoDeHoy = filaHoy?.cadena ? filaHoy : null

  const ancla = libro?.ancla ?? libroConHoy?.ancla ?? null
  // Las dos columnas de saldo existen si hay AL MENOS UN día que mostrar. Con
  // cero se apagan porque no habría nada que poner ahí, no porque el mes esté
  // «incompleto»: un mes a medias muestra sus días buenos y pinta «—» en los
  // otros, que es la verdad parcial.
  const hayColumnasDeSaldo = (libro?.dias_con_saldo ?? 0) > 0

  /**
   * Qué le falta a la cadena EN ESTE MES, dicho con los datos del backend.
   *
   * Tres estados, y ninguno se infiere de la forma del rango:
   *  - completa (`cadena_completa`) → no hay nada que avisar;
   *  - parcial (`primer_dia_con_saldo` con algún día sin saldo) → se dice DESDE
   *    CUÁNDO hay saldo, en vez de apagar el mes entero;
   *  - vacía (`dias_con_saldo === 0`) → recién ahí «este mes no tiene saldos», y
   *    el motivo sale de si el ancla existe o no. Con ancla cargada NUNCA se
   *    dice «falta el saldo del extracto»: está cargado, lo que pasa es que su
   *    fecha es posterior a este mes y la cadena no corre para atrás.
   */
  const avisoDeCadena = useMemo(() => {
    if (!libro || libro.cadena_completa) return null
    const anclaFecha = libro.ancla.fecha
    const desde = libro.primer_dia_con_saldo

    if (desde) {
      // Que el primer día con saldo SEA el del extracto se COMPARA, no se
      // deduce del caso: es el motivo que se le está por afirmar al dueño.
      const arrancaEnElExtracto = anclaFecha != null && anclaFecha === desde
      return {
        titulo: `Los saldos arrancan el ${fechaCorta(desde)}`,
        texto: `Antes de esa fecha no se sabe cuánta plata había, así que esos días van con «—» `
          + `en «arranca» y «queda»; lo que entró y lo que salió sí es real. Del `
          + `${fechaCorta(desde)} en adelante el saldo es exacto.`
          + (arrancaEnElExtracto
            ? ' Arranca ahí porque esa es la fecha del saldo del extracto: si tenés uno más '
              + 'viejo, tocá acá y cambiale la fecha.'
            : ''),
      }
    }
    return {
      titulo: 'Este mes no tiene saldos',
      texto: anclaFecha
        ? `El saldo del extracto es del ${fechaCorta(anclaFecha)} y este mes termina el `
          + `${fechaCorta(libro.hasta)}: la cadena arranca en esa fecha y no corre para atrás. `
          + `Lo que entró y lo que salió sí es real; con cuánto arrancaste y con cuánto `
          + `quedaste, no. Si tenés el extracto de esos días, tocá acá y cambiale la fecha.`
        : 'Nunca cargaste el saldo del extracto, así que la cadena no tiene de dónde arrancar. '
          + 'Lo que entró y lo que salió sí es real; con cuánto arrancaste y con cuánto '
          + 'quedaste, no. Cargá el saldo del extracto y aparecen.',
    }
  }, [libro])

  // ─── La agenda, indexada por día ────────────────────────────────────────────
  // Los vencimientos NO están en el libro (son compromisos, no plata que ya se
  // movió): vienen de /costos/agenda y se fusionan acá, en el cliente.
  const items = agenda?.items ?? []
  const vencidos = useMemo(
    () => items.filter(i => i.vencida).sort((a, b) => a.fecha.localeCompare(b.fecha)),
    [items])
  const vencePorDia = useMemo(() => {
    const m = new Map<string, AgendaItem[]>()
    for (const i of items) {
      const arr = m.get(i.fecha)
      if (arr) arr.push(i); else m.set(i.fecha, [i])
    }
    return m
  }, [items])

  // Cuántos meses del año no tienen cierre. Se cuenta para no escribir la
  // explicación del «—» cuando no hay ningún «—» que explicar.
  const mesesSinCierre = useMemo(
    () => (serie?.meses ?? []).filter(m => m.cierre == null).length, [serie])

  // ─── Navegación ─────────────────────────────────────────────────────────────
  const moverMes = (n: number) => {
    const d = new Date(anio, mes - 1 + n, 1)
    setDiaAbierto(null)
    setAnio(d.getFullYear()); setMes(d.getMonth() + 1)
  }
  const irAHoy = () => {
    setAnio(anioDeHoy); setMes(mesDeHoy); setDiaAbierto(hoy)
  }
  const verMes = (m: number) => { setMes(m); setDiaAbierto(null) }

  // ─── Acciones ───────────────────────────────────────────────────────────────
  const abrirAncla = () => {
    // Sin fecha no hay saldo cargado: el 0 que devuelve el backend en ese caso es
    // el default de la fila vacía, no una plata que alguien haya declarado. Se
    // abre en blanco para que no se guarde ese cero sin querer.
    setASaldo(ancla?.fecha ? String(Math.round(ancla.saldo)) : '')
    setAFecha(ancla?.fecha ?? hoy)
    setAError('')
    setAnclaAbierta(true)
  }

  const guardarAncla = async () => {
    setGuardandoAncla(true); setAError('')
    try {
      await api.put('/banco/ancla', { saldo: Number(aSaldo || 0), fecha: aFecha })
      setAnclaAbierta(false)
      recargar()
      // El mismo dato alimenta la proyección de «Hoy» (`saldo_banco` en
      // configuracion): si no se avisa, esa pestaña sigue arrancando del viejo.
      onRefrescar()
    } catch (e) {
      setAError(detalleDeError(e, 'No se pudo guardar el saldo. Reintentá.'))
    } finally { setGuardandoAncla(false) }
  }

  const borrarMovimiento = async (id: number) => {
    setError('')
    try {
      await api.delete(`/banco/movimientos/${id}`)
      setBorrandoId(null)
      recargar()
      // TAMBIÉN hacia afuera. Desde que el flujo proyectado arranca del libro y
      // no del ancla cruda, borrar un movimiento mueve el punto de quiebre — y
      // «Hoy» solo repide /costos/flujo cuando alguien se lo avisa. Sin esto, la
      // pestaña que el dueño mira primero seguía proyectando con la plata vieja
      // y el número correcto aparecía a un toque, en el cajón: dos números para
      // la misma pregunta, con el optimista adelante.
      onRefrescar()
    } catch (e) {
      setBorrandoId(null)
      setError(detalleDeError(e, 'No se pudo borrar el movimiento.'))
    }
  }

  const fecharObligacion = async () => {
    if (!fechando) return
    if (!fVence) { setFError('Elegí para cuándo hay que pagarlo'); return }
    setGuardandoFecha(true); setFError('')
    try {
      await api.patch(`/costos/obligaciones/${fechando.id}`, { fecha_vencimiento: fVence })
      setFechando(null); onRefrescar()
    } catch (e) {
      setFError(detalleDeError(e, 'No se pudo guardar la fecha. Reintentá.'))
    } finally { setGuardandoFecha(false) }
  }

  const diasDesdeAncla = ancla?.fecha ? diasEntre(ancla.fecha, hoy) : null

  return (
    <div className="space-y-3">
      {/* ─── Los dos saldos, arriba y editables ──────────────────────────────
          El de hoy (lo que el libro dice que hay) y el del extracto (lo que el
          banco dijo que había). Que se vean juntos es el punto: la distancia
          entre los dos es lo que hay que teclear. */}
      <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
        <div className="grid grid-cols-2 divide-x divide-warm-100">
          <div className="px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500">Hoy quedás con</p>
            {saldoDeHoy ? (<>
              <p className={`text-xl font-bold font-mono tabular-nums leading-tight mt-0.5 ${
                saldoDeHoy.final < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                {plata(saldoDeHoy.final)}
              </p>
              {/* El número grande explicado en una línea, sin abrir nada. */}
              <p className="text-[11px] text-warm-500 leading-snug">
                Arrancó en {compacto(saldoDeHoy.inicial)}
                {saldoDeHoy.total_entradas > 0 && <> · entró {compacto(saldoDeHoy.total_entradas)}</>}
                {saldoDeHoy.total_salidas > 0 && <> · salió {compacto(saldoDeHoy.total_salidas)}</>}
              </p>
            </>) : (<>
              <p className="text-xl font-bold font-mono text-warm-400 leading-tight mt-0.5">—</p>
              {/* El motivo se elige por el DATO que falta, no por una bandera del
                  mes. Con el ancla cargada esto no puede decir «falta el saldo
                  del extracto»: el backend solo deja hoy sin cadena si el ancla
                  no existe (su fecha nunca puede ser futura, la rechaza el
                  router) o si el libro directamente no cargó. */}
              <p className="text-[11px] text-warm-500 leading-snug">
                {!libroConHoy
                  ? 'Todavía no se pudo leer el libro de este mes.'
                  : !libroConHoy.ancla.fecha
                    ? 'Falta el saldo del extracto para saberlo.'
                    : `El saldo del extracto es del ${fechaCorta(libroConHoy.ancla.fecha)}: `
                      + 'la cadena todavía no llega hasta hoy.'}
              </p>
            </>)}
          </div>

          <button onClick={abrirAncla} className="px-4 py-3 text-left hover:bg-warm-50 transition-colors">
            <p className="text-[10px] font-bold uppercase tracking-wide text-warm-500 flex items-center gap-1">
              <Landmark size={11} /> Saldo del extracto
            </p>
            <p className="text-xl font-bold font-mono tabular-nums text-warm-700 leading-tight mt-0.5">
              {ancla?.fecha ? plata(ancla.saldo) : '—'}
            </p>
            <p className="text-[11px] text-warm-500 leading-snug flex items-center gap-1">
              {ancla?.fecha
                ? <>Del {fechaCorta(ancla.fecha)}
                    {diasDesdeAncla != null && diasDesdeAncla > 0 && ` · hace ${diasDesdeAncla} día${diasDesdeAncla === 1 ? '' : 's'}`}</>
                : 'Sin cargar — cargalo acá'}
              <Pencil size={10} className="shrink-0" />
            </p>
          </button>
        </div>

        {/* El editor se abre EN LA MISMA tarjeta: es un dato que solo el dueño
            tiene (el sistema registra consignaciones, nunca un saldo bancario) y
            cada click de distancia es un día más de saldo viejo. */}
        {anclaAbierta && (
          <div className="border-t border-warm-200 bg-warm-50 px-4 py-3 space-y-3">
            <p className="text-[11px] text-warm-600 leading-relaxed">
              Abrí la app del banco y copiá el saldo. Es el saldo con el que <b>arranca</b> ese
              día: de ahí para adelante el libro suma lo que entra y resta lo que sale.
            </p>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wide text-warm-500 block mb-1">Saldo</label>
                <input type="text" inputMode="numeric" value={conMiles(aSaldo)}
                  onChange={e => setASaldo(soloDigitos(e.target.value))}
                  className="w-full border-2 border-warm-200 rounded-xl px-3 py-2 text-base font-bold font-mono tabular-nums bg-white focus:outline-none focus:border-forest" />
              </div>
              <div>
                <label className="text-[10px] font-bold uppercase tracking-wide text-warm-500 block mb-1">¿De qué día es?</label>
                <input type="date" value={aFecha} max={hoy} onChange={e => setAFecha(e.target.value)}
                  className="w-full border-2 border-warm-200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:border-forest" />
              </div>
            </div>
            <p className="text-[11px] text-warm-500 leading-relaxed">
              La cadena arranca en esa fecha: los días anteriores quedan sin saldo. Si tenés el
              extracto del primero del mes, poné el primero y el mes entero queda con saldo.
            </p>
            {aError && (
              <p className="text-sm text-danger-700 bg-danger-50 border border-danger-200 rounded-xl px-3 py-2">{aError}</p>
            )}
            <div className="flex gap-2">
              <button onClick={() => setAnclaAbierta(false)}
                className="min-h-[42px] px-4 rounded-xl border border-warm-200 bg-white text-sm font-bold text-warm-500">
                Cancelar
              </button>
              <button onClick={guardarAncla} disabled={guardandoAncla || !aFecha || !aSaldo}
                className="flex-1 min-h-[42px] bg-forest hover:bg-forest-700 disabled:opacity-40 text-white font-bold rounded-xl text-sm">
                {guardandoAncla ? 'Guardando...' : 'Guardar saldo'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Lo vencido: arriba, aparte y primero. No es «el pasado», es lo que se
          debe hoy — y no depende del mes que se esté mirando. */}
      {vencidos.length > 0 && (
        <div className="rounded-2xl border border-danger-200 bg-danger-50 overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-danger-200/60">
            <p className="text-sm font-bold text-danger-700">Vencido — pagalo ya</p>
            <span className="font-mono font-bold text-sm text-danger-700 tabular-nums">
              {plata(agenda?.totales.vencido ?? 0)}
            </span>
          </div>
          <div className="divide-y divide-danger-200/40">
            {vencidos.map(i => (
              <FilaVencimiento key={`v-${i.tipo}-${i.id}`} item={i}
                onPagar={() => setPagoDe(i)} onProveedores={onAbrirProveedores} />
            ))}
          </div>
        </div>
      )}

      {error && (
        <p className="text-sm text-danger-700 bg-danger-50 border border-danger-200 rounded-xl px-3 py-2">{error}</p>
      )}

      {/* ─── EL MES: una fila por día ───────────────────────────────────────── */}
      <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
        <div className="flex items-center gap-1 px-2 py-2 border-b border-warm-100">
          <button onClick={() => moverMes(-1)} aria-label="Mes anterior"
            className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronLeft size={17} /></button>
          <div className="min-w-0 flex-1 text-center">
            <p className="text-sm font-bold text-warm-700 first-letter:uppercase">{MESES[mes - 1]} {anio}</p>
            {!viendoElMesDeHoy && (
              <button onClick={irAHoy} className="text-[11px] font-bold text-forest">Volver a hoy</button>
            )}
          </div>
          <button onClick={() => moverMes(1)} aria-label="Mes siguiente"
            className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronRight size={17} /></button>
          <button onClick={() => setNuevoEn(viendoElMesDeHoy ? hoy : (libro?.desde ?? hoy))}
            className="ml-1 flex items-center gap-1 min-h-[38px] px-3 rounded-xl bg-forest hover:bg-forest-700 text-white text-xs font-bold">
            <Plus size={14} /> Movimiento
          </button>
        </div>

        {/* La verdad PARCIAL: desde cuándo hay saldo. Solo cuando no hay ningún
            día con saldo esto dice «este mes no tiene saldos». */}
        {avisoDeCadena && (
          <button onClick={abrirAncla}
            className="w-full flex items-start gap-2 px-4 py-3 border-b border-gold-200 bg-gold-50 text-left">
            <AlertCircle size={15} className="text-gold-700 mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-bold text-gold-700">{avisoDeCadena.titulo}</span>
              <span className="block text-[11px] text-gold-700/90 leading-relaxed mt-0.5">
                {avisoDeCadena.texto}
              </span>
            </span>
          </button>
        )}

        {/* Encabezado de columnas: es la fórmula de la hoja del dueño, y se deja
            leer a ojo — arranca + entra − sale = queda. */}
        <div className={`grid gap-1 px-2 py-1.5 bg-warm-50 border-b border-warm-100 text-[9px] font-bold uppercase tracking-wide text-warm-500 ${
          hayColumnasDeSaldo ? 'grid-cols-[2.9rem_1fr_1fr_1fr_1fr]' : 'grid-cols-[2.9rem_1fr_1fr]'}`}>
          <span>Día</span>
          {hayColumnasDeSaldo && <span className="text-right">Arranca</span>}
          <span className="text-right">Entra</span>
          <span className="text-right">Sale</span>
          {hayColumnasDeSaldo && <span className="text-right">Queda</span>}
        </div>

        {cargando && <p className="px-4 py-8 text-center text-sm text-warm-400 animate-pulse">Cargando…</p>}

        {!cargando && libro && libro.dias.map(d => (
          <FilaDia key={d.fecha} dia={d} hoy={hoy} columnasDeSaldo={hayColumnasDeSaldo}
            abierto={diaAbierto === d.fecha}
            vencimientos={vencePorDia.get(d.fecha) ?? []}
            onAbrir={() => setDiaAbierto(x => (x === d.fecha ? null : d.fecha))}
            onPagar={setPagoDe}
            onProveedores={onAbrirProveedores}
            onCargarMovimiento={() => setNuevoEn(d.fecha)}
            borrandoId={borrandoId}
            onPedirBorrar={setBorrandoId}
            onBorrar={borrarMovimiento} />
        ))}

        {/* Pie del mes: los dos números que el dueño busca cuando ya vio las filas. */}
        {!cargando && libro && (
          <div className="px-4 py-3 border-t border-warm-200 bg-warm-50 space-y-1">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="text-warm-500">Entró en el mes</span>
              <span className="font-mono font-bold tabular-nums text-success-600">+ {plata(libro.totales.entradas)}</span>
            </div>
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="text-warm-500">Salió en el mes</span>
              <span className="font-mono font-bold tabular-nums text-danger-600">− {plata(libro.totales.salidas)}</span>
            </div>
            {/* `totales.final` viene en null cuando el ÚLTIMO día del mes no
                tiene saldo: ahí no hay con cuánto termina y no se escribe la
                línea. No es lo mismo que terminar en cero. */}
            {libro.totales.final != null && (
              <div className="flex items-center justify-between gap-2 text-xs pt-1 border-t border-warm-200">
                <span className="font-bold text-warm-600">Con lo cargado, el mes termina en</span>
                <span className={`font-mono font-bold tabular-nums ${
                  libro.totales.final < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                  {plata(libro.totales.final)}
                </span>
              </div>
            )}
            {/* El conteo de rojos y el día más bajo se calculan SOLO sobre los
                días con saldo (services/banco.py), así que la frase se acota
                cuando el mes no está entero: decir «ningún día cerró en rojo»
                de un mes al que le faltan quince días sin saldo sería afirmar
                de más justo en el renglón que tranquiliza. */}
            {libro.dias_con_saldo > 0 && (
              <p className={`text-[11px] leading-relaxed pt-0.5 ${
                libro.totales.dias_en_rojo > 0 ? 'text-danger-700 font-semibold' : 'text-warm-500'}`}>
                {libro.totales.dias_en_rojo > 0
                  ? `${libro.totales.dias_en_rojo} ${libro.totales.dias_en_rojo === 1 ? 'día cerró' : 'días cerraron'} en rojo.`
                  : libro.cadena_completa
                    ? 'Ningún día cerró en rojo.'
                    : 'Ninguno de los días con saldo cerró en rojo.'}
                {libro.totales.fecha_dia_mas_bajo && libro.totales.dia_mas_bajo != null && (
                  <> El más bajo fue el <b>{fechaCorta(libro.totales.fecha_dia_mas_bajo)}</b>,
                    {' '}con {plata(libro.totales.dia_mas_bajo)}.</>
                )}
              </p>
            )}
          </div>
        )}
      </div>

      {/* ─── LOS DOCE MESES ─────────────────────────────────────────────────── */}
      {serie && (
        <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
          <div className="flex items-center gap-1 px-2 py-2 border-b border-warm-100">
            <button onClick={() => setAnio(a => a - 1)} aria-label="Año anterior"
              className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronLeft size={16} /></button>
            <div className="min-w-0 flex-1 text-center">
              <p className="text-sm font-bold text-warm-700">El año {serie.anio}</p>
              <p className="text-[11px] text-warm-500">Cuánto entró, cuánto salió y con cuánto cerró cada mes</p>
            </div>
            <button onClick={() => setAnio(a => a + 1)} aria-label="Año siguiente"
              className="p-2 rounded-xl text-warm-500 hover:bg-warm-100"><ChevronRight size={16} /></button>
          </div>

          <div className="grid grid-cols-[2.6rem_1fr_1fr_1fr] gap-1 px-3 py-1.5 bg-warm-50 border-b border-warm-100 text-[9px] font-bold uppercase tracking-wide text-warm-500">
            <span>Mes</span>
            <span className="text-right">Entra</span>
            <span className="text-right">Sale</span>
            <span className="text-right">Cierra</span>
          </div>

          {serie.meses.map(m => {
            // Condicionado por MONTO, no por la forma del dato: un mes sin plata
            // movida se apaga; uno con plata se lee aunque el cierre no exista.
            const conMovimiento = m.entradas > 0 || m.salidas > 0
            return (
              <button key={m.mes} onClick={() => verMes(m.mes)}
                className={`w-full grid grid-cols-[2.6rem_1fr_1fr_1fr] gap-1 items-center px-3 py-2 border-b border-warm-100 text-right transition-colors ${
                  m.mes === mes ? 'bg-forest-50' : 'hover:bg-warm-50'
                } ${conMovimiento ? '' : 'opacity-45'}`}>
                <span className="text-left text-[11px] font-bold text-warm-600 capitalize">{MESES_CORTOS[m.mes - 1]}</span>
                <span className="text-[11px] font-mono tabular-nums text-success-600">
                  {m.entradas > 0 ? compacto(m.entradas) : '—'}
                </span>
                <span className="text-[11px] font-mono tabular-nums text-danger-600">
                  {m.salidas > 0 ? compacto(m.salidas) : '—'}
                </span>
                <span className={`text-[11px] font-mono font-bold tabular-nums ${
                  m.cierre == null ? 'text-warm-300' : m.cierre < 0 ? 'text-danger-700' : 'text-warm-700'}`}>
                  {m.cierre == null ? '—' : compacto(m.cierre)}
                </span>
              </button>
            )
          })}

          <p className="px-3 py-2 text-[11px] text-warm-500 leading-relaxed">
            Tocá un mes para abrirlo arriba.
            {/* La explicación del «—» solo se escribe si hay alguno, y dice el
                motivo REAL de este año: no es lo mismo «el extracto es posterior»
                que «nunca se cargó un extracto».

                EL CRITERIO ES QUE EL MES TERMINA ANTES, NO QUE ARRANCA ANTES:
                `serie_mensual` pide `saldo_al_cierre(db, fin)` con el ÚLTIMO día
                del mes (services/banco.py), así que el cierre falta solo cuando
                ese último día queda antes del ancla. La diferencia se ve en esta
                misma pantalla: el mes que CONTIENE al ancla también arranca antes
                y sí trae cierre. */}
            {mesesSinCierre > 0 && (<>
              {' '}{mesesSinCierre === 1
                ? <>El mes con <b>cierre en «—»</b> es uno al que la cadena no llega</>
                : <>Los meses con <b>cierre en «—»</b> son los que la cadena no alcanza</>}
              {ancla?.fecha
                ? `: el cierre se mide el último día del mes, y ${mesesSinCierre === 1
                    ? 'ese mes termina' : 'esos meses terminan'} antes del `
                  + `${fechaCorta(ancla.fecha)}, que es la fecha del saldo del extracto.`
                : ': todavía no cargaste ningún saldo del extracto.'}
              {mesesSinCierre === 1
                ? ' No cerró en cero: no se sabe con cuánto cerró.'
                : ' No cerraron en cero: no se sabe con cuánto cerraron.'}
            </>)}
          </p>
        </div>
      )}

      {/* La proyección NO se dibuja adentro del libro y esta tarjeta dice por qué.
          Es la distinción que el módulo perdía cuando el saldo proyectado se
          pintaba encima del calendario: una cosa es la plata que ya se movió y
          otra es una estimación de la venta que viene. Las dos sirven; leerlas
          como si fueran el mismo número es lo que hacía tomar decisiones malas. */}
      <button onClick={onAbrirFlujo}
        className="w-full flex items-start gap-2 bg-white rounded-2xl border border-warm-200 px-4 py-3 text-left">
        <TrendingDown size={16} className="text-forest mt-0.5 shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-bold text-warm-700">¿Y lo que todavía no pasó?</span>
          <span className="block text-[11px] text-warm-500 leading-relaxed mt-0.5">
            Este libro es plata que <b>ya se movió</b>. El flujo proyectado estima lo que va a
            entrar con las ventas de las próximas semanas y marca el día en que te quedarías sin
            plata. Es una estimación, y por eso vive aparte. <b className="text-forest">Verlo</b>
          </span>
        </span>
      </button>

      {/* Obligaciones cargadas SIN fecha de pago: no se agendan (no hay para
          cuándo) pero tampoco pueden ser invisibles — sí cuentan en el resultado. */}
      {(agenda?.sin_fecha.length ?? 0) > 0 && (
        <div className="rounded-2xl border border-gold-200 bg-gold-50 overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-gold-200/60">
            <div className="min-w-0">
              <p className="text-sm font-bold text-gold-700">Sin fecha de pago</p>
              <p className="text-[11px] text-gold-700/90 leading-snug">
                Cuentan en el resultado del mes, pero no se pueden agendar hasta que tengan una
                fecha. Ponésela y aparecen en el día que les toca.
              </p>
            </div>
            <span className="font-mono font-bold text-sm text-gold-700 shrink-0 tabular-nums">
              {plata(agenda?.totales.sin_fecha ?? 0)}
            </span>
          </div>
          <div className="divide-y divide-gold-200/40">
            {(agenda?.sin_fecha ?? []).map(i => (
              <div key={`sf-${i.id}`} className="flex items-center gap-3 px-4 py-2.5">
                <span className="shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-lg bg-white text-gold-700 border border-gold-200">
                  <Tag size={11} /> {i.categoria_nombre || 'Sin categoría'}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-warm-700 truncate">{i.concepto}</p>
                  <p className="text-[11px] text-warm-500 truncate">
                    {i.tienda_nombre || 'Corporativo'} · devengo {fechaCorta(i.fecha_devengo)}
                  </p>
                </div>
                <span className="font-mono font-bold text-sm text-warm-700 shrink-0 tabular-nums">{plata(i.monto)}</span>
                <button onClick={() => { setFechando(i); setFVence(i.fecha_devengo || hoy); setFError('') }}
                  className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-white bg-gold-600 hover:bg-gold-500 px-3 py-1.5 rounded-lg">
                  <CalendarClock size={13} /> Poner fecha
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {!cargandoAgenda && items.length === 0 && (agenda?.sin_fecha.length ?? 0) === 0 && (
        <p className="text-[11px] text-warm-500 px-1 leading-relaxed">
          No hay nada agendado todavía. El arriendo, la nómina y los servicios se cargan en
          Obligaciones; las facturas de proveedor traen su plazo desde Pagos a proveedores.
        </p>
      )}

      {/* Las herramientas que no son una pantalla para mirar un martes. */}
      <div className="grid grid-cols-2 gap-2">
        <button onClick={onAbrirObligaciones}
          className="flex items-center gap-2 bg-white rounded-2xl border border-warm-200 px-3 py-3 text-left">
          <Receipt size={16} className="text-forest shrink-0" />
          <span className="min-w-0">
            <span className="block text-sm font-bold text-warm-700">Obligaciones</span>
            <span className="block text-[11px] text-warm-500 leading-snug">Cargar, repetir y anular costos fijos</span>
          </span>
        </button>
        <button onClick={onAbrirProveedores}
          className="flex items-center gap-2 bg-white rounded-2xl border border-warm-200 px-3 py-3 text-left">
          <Truck size={16} className="text-forest shrink-0" />
          <span className="min-w-0">
            <span className="block text-sm font-bold text-warm-700">Pagos a proveedores</span>
            <span className="block text-[11px] text-warm-500 leading-snug">Registrar el pago de una factura</span>
          </span>
        </button>
      </div>

      {/* El modal de pago es el MISMO que usa Costos: `key` fuerza el montaje
          limpio que su estado inicial-desde-props necesita. */}
      {pagoDe && (
        <ModalRegistrarPago key={pagoDe.id}
          obligacion={{
            id: pagoDe.id,
            concepto: pagoDe.concepto,
            saldo: pagoDe.monto,
            detalle: [pagoDe.categoria_nombre || 'Costo fijo',
              pagoDe.tienda_nombre || 'Corporativo',
              pagoDe.beneficiario || ''].filter(Boolean).join(' · '),
          }}
          onCerrar={() => setPagoDe(null)}
          onPagado={() => { setPagoDe(null); onRefrescar() }} />
      )}

      {nuevoEn && (
        <ModalMovimiento key={nuevoEn} fechaInicial={nuevoEn} cuentas={cuentas}
          onCerrar={() => setNuevoEn(null)}
          onGuardado={m => {
            // Se salta al mes del movimiento GUARDADO, no al que se estaba
            // mirando: la fecha es editable adentro del modal, y guardar algo del
            // mes que viene para después no ver ningún cambio en pantalla se lee
            // como que no se guardó.
            setAnio(Number(m.fecha.slice(0, 4)))
            setMes(Number(m.fecha.slice(5, 7)))
            setDiaAbierto(m.fecha)
            setNuevoEn(null)
            recargar()
            // Mismo motivo que en `borrarMovimiento`: un movimiento nuevo mueve
            // el saldo del que vive la proyección de «Hoy», y esa pestaña solo
            // repide /costos/flujo cuando alguien se lo avisa.
            onRefrescar()
          }} />
      )}

      {/* Ponerle fecha a una obligación cargada sin «Vence». */}
      {fechando && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setFechando(null)}>
          <div className="bg-white rounded-2xl w-full max-w-sm p-5 space-y-4" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h2 className="font-bold text-warm-700">¿Para cuándo hay que pagarlo?</h2>
              <button onClick={() => setFechando(null)} aria-label="Cerrar" className="text-warm-400"><X size={18} /></button>
            </div>
            <div className="text-sm text-warm-500">
              <p className="font-semibold text-warm-700">{fechando.concepto}</p>
              <p>{fechando.categoria_nombre || 'Sin categoría'} · {fechando.tienda_nombre || 'Corporativo'}
                {' · '}<span className="font-mono font-bold text-warm-700">{plata(fechando.monto)}</span></p>
            </div>
            <div>
              <label className="text-xs font-semibold text-warm-500 uppercase tracking-wide block mb-1">Fecha de pago</label>
              <input type="date" value={fVence} onChange={e => setFVence(e.target.value)}
                className="w-full border-2 border-warm-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:border-forest" />
              <p className="text-[11px] text-warm-400 mt-1">
                Con esta fecha el costo entra al día que le toca. El mes al que pertenece (el
                devengo) no cambia.
              </p>
            </div>
            {fError && <p className="text-sm text-danger-700 bg-danger-50 border border-danger-200 rounded-xl px-3 py-2">{fError}</p>}
            <button onClick={fecharObligacion} disabled={guardandoFecha || !fVence}
              className="w-full bg-forest hover:bg-forest-700 disabled:opacity-40 text-white font-bold py-3 rounded-xl text-sm">
              {guardandoFecha ? 'Guardando...' : 'Guardar fecha'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Una fila del libro = un día, y se despliega.
 *
 * INVARIANTE: ninguna fila es inerte. Un día sin movimientos y sin vencimientos
 * abre igual, porque tiene algo que decir (con cuánto arrancó, con cuánto quedó y
 * que no se movió nada) y una acción que ofrecer (cargar el movimiento que falta).
 *
 * `columnasDeSaldo` decide si la GRILLA tiene las dos columnas de saldo (es del
 * mes: o están para todas las filas o el ancho se descuadra). Lo que va DENTRO
 * de esas columnas lo decide `dia.cadena`, que es de esta fila: un día anterior
 * al ancla pinta «—» y los demás su número.
 */
function FilaDia({
  dia, hoy, columnasDeSaldo, abierto, vencimientos, onAbrir, onPagar, onProveedores,
  onCargarMovimiento, borrandoId, onPedirBorrar, onBorrar,
}: {
  dia: DiaLibro
  hoy: string
  columnasDeSaldo: boolean
  abierto: boolean
  vencimientos: AgendaItem[]
  onAbrir: () => void
  onPagar: (i: AgendaItem) => void
  onProveedores: () => void
  onCargarMovimiento: () => void
  borrandoId: number | null
  onPedirBorrar: (id: number | null) => void
  onBorrar: (id: number) => void
}) {
  const esHoy = dia.fecha === hoy
  // `en_rojo` lo calcula el backend y ya viene en false cuando la fila no tiene
  // cadena (un saldo que no se conoce no puede estar en negativo), así que no
  // hay nada que volver a condicionar acá.
  const rojo = dia.en_rojo
  const totalVence = vencimientos.reduce((s, i) => s + i.monto, 0)
  const numero = Number(dia.fecha.slice(8, 10))

  return (
    <div className={rojo ? 'bg-danger-50/70' : esFinde(dia.fecha) ? 'bg-warm-50/60' : ''}>
      <button onClick={onAbrir}
        aria-expanded={abierto}
        aria-label={`${fechaLarga(dia.fecha)}${
          dia.total_entradas > 0 ? `, entró ${plata(dia.total_entradas)}` : ''}${
          dia.total_salidas > 0 ? `, salió ${plata(dia.total_salidas)}` : ''}${
          dia.cadena ? `, queda ${plata(dia.final)}` : ''}${
          totalVence > 0 ? `, vence ${plata(totalVence)}` : ''}`}
        className={`w-full px-2 py-2 border-b text-left transition-colors ${
          abierto ? 'border-forest bg-forest-50' : 'border-warm-100 hover:bg-warm-50'}`}>
        <div className={`grid gap-1 items-center ${
          columnasDeSaldo ? 'grid-cols-[2.9rem_1fr_1fr_1fr_1fr]' : 'grid-cols-[2.9rem_1fr_1fr]'}`}>
          <span className="flex items-baseline gap-1">
            <span className={`text-xs font-bold ${
              esHoy ? 'text-forest bg-forest-100 rounded-full px-1.5' : 'text-warm-600'}`}>{numero}</span>
            <span className="text-[9px] text-warm-400">{diaSemana(dia.fecha)}</span>
          </span>
          {columnasDeSaldo && (
            <span className={`text-[11px] font-mono tabular-nums text-right ${
              dia.cadena ? 'text-warm-400' : 'text-warm-300'}`}>
              {dia.cadena ? compacto(dia.inicial) : '—'}
            </span>
          )}
          <span className={`text-[11px] font-mono tabular-nums text-right ${
            dia.total_entradas > 0 ? 'text-success-600 font-bold' : 'text-warm-300'}`}>
            {dia.total_entradas > 0 ? compacto(dia.total_entradas) : '—'}
          </span>
          <span className={`text-[11px] font-mono tabular-nums text-right ${
            dia.total_salidas > 0 ? 'text-danger-600 font-bold' : 'text-warm-300'}`}>
            {dia.total_salidas > 0 ? compacto(dia.total_salidas) : '—'}
          </span>
          {columnasDeSaldo && (
            <span className={`text-[11px] font-mono font-bold tabular-nums text-right ${
              !dia.cadena ? 'text-warm-300' : rojo ? 'text-danger-700' : 'text-warm-700'}`}>
              {dia.cadena ? compacto(dia.final) : '—'}
            </span>
          )}
        </div>

        {/* Lo que VENCE ese día no es plata que ya se movió: es un compromiso, y
            por eso va en su propia línea y no adentro de la columna «Sale». Meterlo
            ahí sumaría al saldo una plata que todavía está en la cuenta. */}
        {totalVence > 0 && (
          <div className="flex items-center gap-1.5 mt-1 pl-1">
            <CalendarClock size={11} className="text-gold-700 shrink-0" />
            <span className="text-[10px] text-gold-700 font-semibold">
              Vence {plata(totalVence)}
            </span>
            <span className="text-[10px] text-warm-400">
              · {vencimientos.length} {vencimientos.length === 1 ? 'pago' : 'pagos'}
            </span>
          </div>
        )}
      </button>

      {abierto && (
        <div className="border-b border-warm-200 bg-white px-3 py-3 space-y-3">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-xs font-bold text-warm-700 first-letter:uppercase">{fechaLarga(dia.fecha)}</p>
            {dia.cadena ? (
              <p className="text-[11px] text-warm-500 shrink-0 font-mono tabular-nums">
                {plata(dia.inicial)} → <b className={rojo ? 'text-danger-700' : 'text-warm-700'}>{plata(dia.final)}</b>
              </p>
            ) : (
              <p className="text-[11px] text-warm-400 shrink-0">Sin saldo: es anterior al extracto</p>
            )}
          </div>

          {/* Los movimientos del libro: lo que YA se movió en la cuenta. */}
          {dia.movimientos.length > 0 ? (
            <div className="divide-y divide-warm-100 border border-warm-200 rounded-xl overflow-hidden">
              {dia.movimientos.map(m => (
                <div key={m.id} className="flex items-center gap-2 px-3 py-2">
                  <span className="shrink-0 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-lg bg-warm-100 text-warm-600">
                    {m.cuenta}
                  </span>
                  <p className="min-w-0 flex-1 text-sm text-warm-700 truncate">{m.concepto}</p>
                  <span className={`shrink-0 font-mono font-bold text-sm tabular-nums ${
                    m.tipo === 'entrada' ? 'text-success-600' : 'text-danger-600'}`}>
                    {m.tipo === 'entrada' ? '+' : '−'} {plata(m.monto)}
                  </span>
                  {borrandoId === m.id ? (
                    <span className="shrink-0 flex items-center gap-1">
                      <button onClick={() => onBorrar(m.id)}
                        className="text-[11px] font-bold text-white bg-danger-500 px-2 py-1 rounded-lg">Borrar</button>
                      <button onClick={() => onPedirBorrar(null)}
                        className="text-[11px] font-bold text-warm-500 px-1.5 py-1">No</button>
                    </span>
                  ) : (
                    <button onClick={() => onPedirBorrar(m.id)} aria-label={`Borrar ${m.concepto}`}
                      className="shrink-0 p-1.5 rounded-lg text-warm-400 hover:text-danger-600 hover:bg-danger-50">
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-warm-500 leading-relaxed">
              No se movió plata en el banco este día
              {dia.cadena && <>: quedó igual que como arrancó</>}.
            </p>
          )}

          <button onClick={onCargarMovimiento}
            className="w-full flex items-center justify-center gap-1.5 min-h-[40px] rounded-xl border border-forest text-forest text-xs font-bold hover:bg-forest-50">
            <Plus size={14} /> Cargar un movimiento de este día
          </button>

          {/* La agenda de ese día, con su acción. Es la mitad que al libro le
              falta: el libro dice qué se movió, la agenda qué hay que mover. */}
          {vencimientos.length > 0 && (
            <div>
              <p className="text-xs font-bold text-warm-600 mb-1">Vence este día</p>
              <div className="divide-y divide-warm-100 border border-warm-200 rounded-xl overflow-hidden">
                {vencimientos.map(i => (
                  <FilaVencimiento key={`d-${i.tipo}-${i.id}`} item={i}
                    onPagar={() => onPagar(i)} onProveedores={onProveedores} />
                ))}
              </div>
              {/* Sin esta línea el dueño paga, ve el vencimiento tachado y espera
                  que el saldo baje solo. No baja: el libro solo tiene lo tecleado. */}
              <p className="text-[11px] text-warm-500 leading-relaxed mt-1.5">
                Registrar el pago tacha el vencimiento, pero <b>no mueve el libro del banco</b>:
                acá solo entra lo que se teclea. Cuando la plata salga de la cuenta, cargala como
                salida de este día.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Un vencimiento de la agenda, con la CATEGORÍA adelante — que es como el dueño
 * los nombra («la nómina», «el arriendo»), no «costo fijo».
 *
 * La acción depende del tipo, y no por estética: `POST /costos/pagos` con
 * `factura_id` guarda el pago pero NO mueve `FacturaCompra.valor_pagado`, o sea
 * que el saldo de la factura quedaría igual y el pago se vería como si no hubiera
 * pasado. El camino real de una factura es `PATCH /facturas/{id}/pago`, que vive
 * en Pagos a proveedores: se manda ahí en vez de fingir que se pagó.
 */
function FilaVencimiento({ item, onPagar, onProveedores }: {
  item: AgendaItem
  onPagar: () => void
  onProveedores: () => void
}) {
  const esFactura = item.tipo === 'factura'
  return (
    <div className="flex items-center gap-2 px-3 py-2.5">
      <span className={`shrink-0 flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-lg ${
        esFactura ? 'bg-white text-forest border border-warm-200' : 'bg-gold-50 text-gold-700 border border-gold-200'
      }`}>
        {esFactura ? <Truck size={11} /> : <Building2 size={11} />}
        {esFactura ? 'Proveedor' : (item.categoria_nombre || 'Costo fijo')}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-warm-700 truncate">{item.concepto}</p>
        <p className="text-[11px] text-warm-500 truncate">
          {item.beneficiario && item.beneficiario !== item.concepto ? `${item.beneficiario} · ` : ''}
          {item.tienda_nombre || 'Corporativo'}
          {item.referencia ? ` · Fact. ${item.referencia}` : ''}
          {` · ${fechaCorta(item.fecha)}`}
          {item.vencida ? ' · vencido' : ''}
          {item.origen_fecha === 'programada' ? ' (programado)' : ''}
          {item.origen_fecha === 'plazo' ? ' (por plazo del proveedor)' : ''}
        </p>
      </div>
      <span className={`font-mono font-bold text-sm shrink-0 tabular-nums ${
        item.vencida ? 'text-danger-600' : 'text-warm-700'}`}>
        {plata(item.monto)}
      </span>
      {esFactura ? (
        <button onClick={onProveedores} title="El pago de una factura se registra en Pagos a proveedores"
          className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-forest bg-forest-50 hover:bg-forest-100 px-3 py-1.5 rounded-lg">
          <Inbox size={13} /> Pagar
        </button>
      ) : (
        <button onClick={onPagar}
          className="shrink-0 flex items-center gap-1.5 text-xs font-bold text-white bg-forest hover:bg-forest-700 px-3 py-1.5 rounded-lg">
          <Wallet size={13} /> Pagar
        </button>
      )}
    </div>
  )
}
