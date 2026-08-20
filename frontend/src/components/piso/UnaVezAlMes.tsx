import { ReactNode, useMemo, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import api from '../../api/client'
import { soloDigitos } from '../../utils/plata'
import { Dato, mapDato } from '../../api/dato'
import type { Fuente } from '../../api/useDato'
import { SegunDato, NoSeSabe } from '../ui'
import { MESES, detalleDeError, plata } from '../plata/banco'
import { Agenda, Categoria, Flujo, Listado, Obligacion } from '../plata/tipos'
import { CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE, ErrorCampo, teclas } from '../plata/campos'
import type { Piso } from './tipos'

// ═════════════════════════════════════════════════════════════════════════════
// UNA VEZ AL MES — de acá salen el piso de hoy y el «¿llego a fin de mes?»
// ═════════════════════════════════════════════════════════════════════════════
// Todo lo de este bloque se toca una vez al mes o menos, así que vive plegado y
// al pie. Pero no es «configuración»: son los seis números que gobiernan la
// página entera. La reserva mínima decide el colchón, la comisión del datáfono
// decide el margen, la nómina agendada decide si el bloque 5 puede mostrar
// algún número.
//
// ── EL DÍA 1 SE DIBUJA ARRIBA DE TODO ────────────────────────────────────
// Es el único día del mes en que la página cambia de forma. `arriba` lo decide
// la página; acá solo cambia el título y el marco.
//
// ── SE ABRE EN EL MISMO SCROLL, NO NAVEGA ────────────────────────────────
// Cada una de estas cosas es un campo y un botón. Mandarlas a otra pantalla es
// lo que hizo que ninguna se cargara nunca.

interface Props {
  piso: Fuente<Piso>
  flujo: Fuente<Flujo>
  agenda: Fuente<Agenda>
  obligaciones: Fuente<Listado>
  categorias: Fuente<Categoria[]>
  anio: number
  mes: number
  anioSiguiente: number
  mesSiguiente: number
  /** true = hoy es día 1 (o quedan cosas del arranque): sube al tope. */
  arriba: boolean
  onCambio: () => void
  onVerElMesEnDetalle: () => void
  id?: string
}

const nombreMes = (m: number) => MESES[m - 1] ?? `mes ${m}`

/** Un renglón del bloque: rótulo, estado actual y el control que lo cambia. */
function Item({ titulo, estado, children }: {
  titulo: string; estado: ReactNode; children?: ReactNode
}) {
  return (
    <div className="px-4 py-2.5 border-t border-warm-100 first:border-t-0">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-semibold text-warm-700 flex-1 min-w-0">{titulo}</p>
        <div className="shrink-0 text-right">{estado}</div>
      </div>
      {children && <div className="mt-1.5">{children}</div>}
    </div>
  )
}

/** Un campo de plata con su botón, para los tres números que se declaran. */
function CampoPlata({ valor, onGuardar, sufijo, ayuda, etiqueta }: {
  valor: string
  onGuardar: (v: string) => Promise<void>
  sufijo?: string
  ayuda?: ReactNode
  etiqueta: string
}) {
  const [v, setV] = useState(valor)
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [ok, setOk] = useState(false)

  const guardar = async () => {
    if (guardando || !v) return
    setGuardando(true); setError(''); setOk(false)
    try { await onGuardar(v); setOk(true) }
    catch (e) { setError(detalleDeError(e, 'No se pudo guardar.')) }
    finally { setGuardando(false) }
  }

  return (
    <div className="space-y-1.5" onKeyDown={teclas({ listo: !!v, guardar })}>
      <div className="flex items-center gap-2">
        <input type="text" inputMode="decimal" value={v} aria-label={etiqueta}
          onChange={e => { setOk(false); setV(sufijo === '%' ? e.target.value : soloDigitos(e.target.value)) }}
          className={`${CLS_INPUT_PLATA} max-w-[180px]`} />
        {sufijo && <span className="text-sm font-bold text-warm-500">{sufijo}</span>}
        <button onClick={guardar} disabled={guardando || !v} className={CLS_BOTON_GUARDAR}>
          {guardando ? 'Guardando…' : 'Guardar'}
        </button>
      </div>
      {ayuda && <p className="text-[11px] text-warm-400 leading-snug">{ayuda}</p>}
      {ok && <p className="text-[11px] font-bold text-success-700">Guardado.</p>}
      <ErrorCampo msg={error} />
    </div>
  )
}

export default function UnaVezAlMes({
  piso, flujo, agenda, obligaciones, categorias,
  anio, mes, anioSiguiente, mesSiguiente, arriba, onCambio, onVerElMesEnDetalle, id,
}: Props) {
  const [abierto, setAbierto] = useState(arriba)
  const [error, setError] = useState('')
  const [aviso, setAviso] = useState('')
  const [armando, setArmando] = useState(false)
  const [agendando, setAgendando] = useState(false)

  /**
   * La reserva YA CARGADA, como texto para precargar el campo.
   *
   * `''` cuando el flujo no volvió o cuando la reserva es el default: el 0 del
   * default no es una decisión de nadie, así que precargarlo lo haría guardable
   * de un toque y un cero sin decidir pasaría por un cero decidido.
   */
  const reservaCargada = flujo.dato.estado === 'listo' && !flujo.dato.valor.reserva_es_default
    ? String(Math.round(flujo.dato.valor.reserva_minima_caja))
    : ''

  /** Las cuentas de la serie mensual que todavía no tienen copia el mes que viene. */
  const porArmar = useMemo<Dato<Obligacion[]>>(
    () => mapDato(obligaciones.dato, l => {
      const clave = `${anioSiguiente}-${String(mesSiguiente).padStart(2, '0')}`
      const vivas = l.obligaciones.filter(o => o.estado !== 'anulada')
      const ya = new Set(vivas
        .filter(o => o.fecha_devengo.slice(0, 7) === clave)
        .map(o => o.plantilla_id)
        .filter((x): x is number => x !== null))
      return vivas.filter(o =>
        o.fecha_devengo.slice(0, 7) !== clave
        && o.plantilla_id !== null
        && !ya.has(o.plantilla_id))
    }),
    [obligaciones.dato, anioSiguiente, mesSiguiente])

  /**
   * Arma el mes que viene copiando cada cuenta de la serie.
   *
   * `POST /obligaciones/{id}/repetir` es IDEMPOTENTE por serie y mes: tocar dos
   * veces devuelve la misma obligación con `ya_existia: true` en vez de cobrar
   * el arriendo dos veces. Por eso se puede reintentar sin miedo, y por eso el
   * conteo de abajo dice cuántas se crearon de verdad.
   */
  const armarElMes = async (os: Obligacion[]) => {
    if (armando) return
    setArmando(true); setError(''); setAviso('')
    let nuevas = 0
    let fallaron = 0
    for (const o of os) {
      try {
        const { data } = await api.post<Obligacion & { ya_existia: boolean }>(
          `/costos/obligaciones/${o.id}/repetir`)
        if (!data.ya_existia) nuevas++
      } catch { fallaron++ }
    }
    setArmando(false)
    onCambio()
    // Se dice CUÁNTAS fallaron. Un «listo» sobre 14 intentos con 3 caídos deja
    // al dueño creyendo que el mes que viene está armado, y el mes que viene ese
    // arriendo no está en ninguna proyección.
    setAviso(fallaron > 0
      ? `Se armaron ${nuevas} de ${os.length}. ${fallaron} no se pudieron copiar: tocá otra vez, `
        + 'no se duplica nada.'
      : `Se armaron ${nuevas} ${nuevas === 1 ? 'cuenta' : 'cuentas'} de ${nombreMes(mesSiguiente)}.`)
  }

  const agendarNomina = async () => {
    if (agendando) return
    setAgendando(true); setError(''); setAviso('')
    try {
      const { data } = await api.post<{ ya_existia?: boolean }>(
        '/costos/nomina/agendar', { anio: anioSiguiente, mes: mesSiguiente })
      setAviso(data.ya_existia
        ? `La nómina de ${nombreMes(mesSiguiente)} ya estaba agendada.`
        : `La nómina de ${nombreMes(mesSiguiente)} quedó en lo que hay que pagar.`)
      onCambio()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo agendar la nómina.'))
    } finally { setAgendando(false) }
  }

  const marco = arriba
    ? 'border-clay-200 bg-clay-50'
    : 'border-warm-200 bg-white'

  return (
    <section id={id} className={`rounded-2xl border overflow-hidden ${marco}`}>
      <button onClick={() => setAbierto(v => !v)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left min-h-[46px] hover:bg-black/[0.02]">
        <div className="flex-1 min-w-0">
          <h2 className={`text-sm font-bold ${arriba ? 'text-clay-600' : 'text-warm-700'}`}>
            {arriba
              ? `Arrancó ${nombreMes(mes)}: cosas para dejar listas`
              : 'Una vez al mes'}
          </h2>
          <p className={`text-[11px] leading-snug ${arriba ? 'text-clay-600/80' : 'text-warm-500'}`}>
            De acá salen el piso de hoy y el «¿llego a fin de mes?» de arriba.
          </p>
        </div>
        <span className="shrink-0 text-xs font-bold text-warm-500">{abierto ? '▾' : '▸'}</span>
      </button>

      {abierto && (
        <div className="border-t border-warm-100 bg-white">
          {aviso && (
            <p className="px-4 py-2 text-[11px] font-bold text-success-700 bg-success-50">{aviso}</p>
          )}
          <div className="px-4 py-1"><ErrorCampo msg={error} /></div>

          {/* ── Armar el mes que viene ────────────────────────────────────── */}
          <Item titulo={`Armar los costos de ${nombreMes(mesSiguiente)}`}
            estado={
              <SegunDato dato={porArmar}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={os => (
                  <span className="text-[11px] font-mono text-warm-500">
                    {os.length === 0 ? 'ya está' : `${os.length} sin copiar`}
                  </span>
                )} />
            }>
            <SegunDato dato={porArmar}
              cargando={null}
              falla={m => (
                <NoSeSabe onReintentar={obligaciones.recargar}
                  mensaje={`${m} — no se sabe qué cuentas de la serie mensual faltan copiar.`} />
              )}
              listo={os => os.length === 0 ? (
                <p className="text-[11px] text-warm-500">
                  Todas las cuentas de la serie mensual ya tienen su copia de {nombreMes(mesSiguiente)}.
                </p>
              ) : (<>
                <button onClick={() => armarElMes(os)} disabled={armando}
                  className={CLS_BOTON_GUARDAR}>
                  {armando ? 'Armando…' : `Armar las ${os.length} de ${nombreMes(mesSiguiente)}`}
                </button>
                <p className="text-[11px] text-warm-400 leading-snug mt-1">
                  Copia cada cuenta con su devengo y su vencimiento un mes adelante. Tocarlo dos
                  veces no duplica nada: cada serie se copia una sola vez por mes.
                </p>
              </>)} />
          </Item>

          {/* ── La nómina del mes que viene ───────────────────────────────── */}
          <Item titulo={`La nómina de ${nombreMes(mesSiguiente)}`}
            estado={
              <SegunDato dato={agenda.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={a => {
                  const clave = `${anioSiguiente}-${String(mesSiguiente).padStart(2, '0')}`
                  const hay = a.items.some(i => i.categoria === 'nomina' && i.fecha.startsWith(clave))
                  return (
                    <span className={`text-[11px] font-bold ${hay ? 'text-success-700' : 'text-gold-700'}`}>
                      {hay ? 'agendada' : 'sin agendar'}
                    </span>
                  )
                }} />
            }>
            <button onClick={agendarNomina} disabled={agendando} className={CLS_BOTON_SUAVE}>
              {agendando ? 'Agendando…' : `Agendar la nómina de ${nombreMes(mesSiguiente)}`}
            </button>
            <p className="text-[11px] text-warm-400 leading-snug mt-1">
              Un mes que todavía no ocurrió no tiene horas marcadas, así que el monto sale del{' '}
              <b>contrato</b> de cada persona. Sin esto, la nómina no está en la agenda, no baja la
              proyección y no tiene botón de pagar.
            </p>
          </Item>

          {/* ── La reserva mínima ─────────────────────────────────────────── */}
          <Item titulo="Cuánto no querés que la caja baje nunca"
            estado={
              <SegunDato dato={flujo.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={f => (
                  <span className={`text-[11px] font-mono ${
                    f.reserva_es_default ? 'text-gold-700 font-bold' : 'text-warm-500'}`}>
                    {plata(f.reserva_minima_caja)}{f.reserva_es_default && ' (sin decidir)'}
                  </span>
                )} />
            }>
            {/* EL AVISO ARRIBA, EL CAMPO SIEMPRE MONTADO (regla 5).
                La reserva es un número que el dueño tiene decidido en la cabeza:
                no depende de este fetch. Meter el campo adentro de la rama
                `listo` lo hacía desaparecer justo cuando la proyección no
                volvía — que es cuando más falta hace poder declararla. */}
            <SegunDato dato={flujo.dato}
              cargando={null}
              falla={() => (
                <NoSeSabe onReintentar={flujo.recargar}
                  mensaje="No se pudo leer la reserva que ya estaba cargada, así que el campo abre
                    en blanco. Lo que escribas se guarda igual." />
              )}
              listo={() => null} />
            <CampoPlata etiqueta="Reserva mínima de caja"
              /* `key` remonta el campo cuando llega el valor leído: `CampoPlata`
                 guarda su propio estado y sin esto el default nunca entraría. Y
                 remonta solo cuando el número CAMBIA, así que no le pisa lo que
                 el dueño esté tecleando. */
              key={reservaCargada}
              valor={reservaCargada}
              ayuda={<>Es lo que convierte «cuánto puedo gastar» en una decisión de negocio en
                vez de «cuánto puedo gastar hasta quedar en cero». El colchón del bloque de
                arriba se mide contra este número.</>}
              onGuardar={async v => {
                await api.post('/costos/reserva-minima', { reserva: Number(v) })
                onCambio()
              }} />
          </Item>

          {/* ── La comisión del datáfono ──────────────────────────────────── */}
          <Item titulo="Cuánto cobra el datáfono por cada venta con tarjeta"
            estado={
              <SegunDato dato={piso.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={p => p.razones === null ? (
                  <span className="text-[11px] text-warm-400">—</span>
                ) : (
                  <span className={`text-[11px] font-mono ${
                    p.razones.tasa_comision > 0 ? 'text-warm-500' : 'text-gold-700 font-bold'}`}>
                    {p.razones.tasa_comision > 0
                      ? `${(p.razones.tasa_comision * 100).toLocaleString('es-CO')}%`
                      : 'sin cargar'}
                  </span>
                )} />
            }>
            <CampoPlata etiqueta="Comisión del datáfono en porcentaje" valor="" sufijo="%"
              ayuda={<>Se escribe en porcentaje, como viene en el contrato del adquirente: <b>2.5</b>{' '}
                para 2,5%. Sin este número el piso de venta sale corto — la comisión se paga de
                cada venta y hoy no la descuenta nadie.</>}
              onGuardar={async v => {
                await api.post('/costos/comision-datafono', { porcentaje: Number(v.replace(',', '.')) })
                onCambio()
              }} />
          </Item>

          {/* ── Las categorías ────────────────────────────────────────────── */}
          <Item titulo="Mis categorías de costo"
            estado={
              <SegunDato dato={categorias.dato}
                cargando={<span className="text-[11px] text-warm-400">…</span>}
                falla={() => <span className="text-[11px] text-warm-400">—</span>}
                listo={cs => <span className="text-[11px] font-mono text-warm-500">{cs.length}</span>} />
            }>
            <MisCategorias categorias={categorias} onCambio={onCambio} />
          </Item>

          {/* ── El link al detalle ────────────────────────────────────────── */}
          <div className="px-4 py-3 border-t border-warm-100">
            <button onClick={onVerElMesEnDetalle}
              className="flex items-center gap-1 min-h-[46px] text-xs font-bold text-forest hover:underline">
              El mes en detalle: margen por producto, sede contra sede, la escalera del resultado
              <ChevronRight size={14} />
            </button>
            <p className="text-[11px] text-warm-400 leading-snug">
              Todo eso es para <b>interpretar</b>, no para decidir hoy. Por eso está acá y no
              arriba: el piso de arriba es el mismo hecho, ya convertido en una decisión.
            </p>
          </div>
        </div>
      )}
    </section>
  )
}

/**
 * El catálogo que el dueño decide.
 *
 * `grupo` es lo único que importa río abajo: el grupo `fijo` es el que arma el
 * numerador del piso. Por eso el alta lo pide explícitamente en vez de elegirlo
 * por él — una categoría nueva en el grupo equivocado le cambia el piso a todo
 * el negocio sin que nadie lo haya pedido.
 */
function MisCategorias({ categorias, onCambio }: {
  categorias: Fuente<Categoria[]>; onCambio: () => void
}) {
  const [abierto, setAbierto] = useState(false)
  const [nombre, setNombre] = useState('')
  const [grupo, setGrupo] = useState<'fijo' | 'variable'>('fijo')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)

  const guardar = async () => {
    if (guardando || !nombre.trim()) return
    setGuardando(true); setError('')
    try {
      await api.post('/costos/categorias', { nombre: nombre.trim(), grupo })
      setNombre('')
      onCambio()
    } catch (e) {
      setError(detalleDeError(e, 'No se pudo crear la categoría.'))
    } finally { setGuardando(false) }
  }

  return (<>
    <button onClick={() => setAbierto(v => !v)}
      className="text-[11px] font-bold text-forest underline decoration-dotted min-h-[44px]">
      {abierto ? 'cerrar' : 'ver y agregar categorías'}
    </button>

    {abierto && (
      <div className="mt-1.5 space-y-2" onKeyDown={teclas({ listo: !!nombre.trim(), guardar })}>
        <SegunDato
          dato={categorias.dato}
          cargando={<p className="text-[11px] text-warm-400">Leyendo el catálogo…</p>}
          falla={m => (
            <NoSeSabe onReintentar={categorias.recargar}
              mensaje={`${m} — no se pudo leer qué categorías hay. Podés crear una igual: el `
                + 'campo de abajo no depende de esta lectura.'} />
          )}
          listo={cs => cs.length === 0 ? (
            <p className="text-[11px] text-warm-500">Todavía no hay ninguna categoría cargada.</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {cs.map(c => (
                <span key={c.id}
                  className={`text-[10px] font-bold px-2 py-1 rounded-lg border ${
                    c.grupo === 'fijo'
                      ? 'bg-gold-50 text-gold-700 border-gold-200'
                      : 'bg-warm-50 text-warm-600 border-warm-200'}`}>
                  {c.nombre}
                </span>
              ))}
            </div>
          )} />

        <p className="text-[11px] text-warm-400 leading-snug">
          Las <b>fijas</b> (en dorado) son las que arman el piso: se pagan venda lo que venda. Las
          variables suben con la venta y no entran al numerador.
        </p>

        {/* El formulario NO se esconde cuando el catálogo no volvió (regla 5). */}
        <div className="flex flex-wrap items-center gap-2">
          <input type="text" value={nombre} onChange={e => setNombre(e.target.value)}
            placeholder="Nombre de la categoría" aria-label="Nombre de la categoría"
            className={`${CLS_INPUT} max-w-[220px]`} />
          <select value={grupo} onChange={e => setGrupo(e.target.value as 'fijo' | 'variable')}
            aria-label="Grupo" className={`${CLS_INPUT} max-w-[140px]`}>
            <option value="fijo">Fija (sube el piso)</option>
            <option value="variable">Variable</option>
          </select>
          <button onClick={guardar} disabled={guardando || !nombre.trim()} className={CLS_BOTON_GUARDAR}>
            {guardando ? 'Creando…' : 'Crear'}
          </button>
        </div>
        <ErrorCampo msg={error} />
      </div>
    )}
  </>)
}
