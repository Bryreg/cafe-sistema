import { useEffect, useState } from 'react'
import api from '../../api/client'
import {
  AlertTriangle, Building2, ChevronDown, ChevronRight, Download, Info, Wallet,
} from 'lucide-react'
import { Aviso } from './SemanaGrid'
import {
  fmtHoras, fmtPesos, MESES, type BaristaResumen, type EstadoDia, type Liquidacion,
  type Resumen,
} from './tipos'

/**
 * Resumen del mes: horas, novedades, PLANEADO vs REAL y la liquidación.
 *
 * Los dos números de plata que importan son DISTINTOS y esta pantalla existe
 * para que no se confundan nunca más:
 *
 *   NETO ..... devengado + auxilio − deducciones. Es lo que la barista recibe
 *              y lo que ella va a preguntar.
 *   COSTO .... devengado + auxilio + aportes + prestaciones. Es lo que sale
 *              del negocio y lo único con lo que se puede decidir contratar.
 *
 * El costo es entre 1,5 y 1,7 veces el sueldo. Mostrar uno solo, o mostrarlos
 * con el mismo tamaño y sin etiqueta, es exactamente el malentendido que costó
 * plata: por eso acá el neto se presenta como una CUENTA (con sus signos) y el
 * costo vive en su propio bloque, con otro color y otro peso visual.
 */

interface Props { tiendaId: number; anio: number; mes: number }

const ESTADO_LABEL: Record<EstadoDia, string> = {
  ok: 'Trabajó',
  no_programado: 'Trabajó sin estar programada',
  sin_marcacion: 'Sin marcación y sin novedad',
  cubrio_otra_sede: 'Marcó en la otra sede',
  novedad_remunerada: 'Novedad que se paga',
  novedad_no_remunerada: 'Novedad que no se paga',
  libre: 'Libre',
}

const ESTADO_COLOR: Record<EstadoDia, string> = {
  ok: 'text-forest-700 bg-forest-50',
  no_programado: 'text-clay-600 bg-clay-50',
  // Ámbar, no rojo: el sistema sabe que falta un REGISTRO, no que faltó la
  // persona. El rojo de peligro es una acusación que el dato no sostiene.
  // (600 y no 700: la paleta `clay` de tailwind.config.js llega hasta 600, y
  // un tono inexistente no genera clase — el texto se quedaba sin color.)
  sin_marcacion: 'text-clay-600 bg-clay-50',
  cubrio_otra_sede: 'text-forest-700 bg-forest-50',
  novedad_remunerada: 'text-warm-600 bg-warm-100',
  novedad_no_remunerada: 'text-warm-600 bg-warm-100',
  libre: 'text-warm-400 bg-warm-50',
}

/** «1,55» — el factor se lee mejor con coma, que es como se escribe acá. */
const fmtFactor = (v: number) => `×${v.toFixed(2).replace('.', ',')}`

export default function ResumenMensual({ tiendaId, anio, mes }: Props) {
  const [data, setData] = useState<Resumen | null>(null)
  const [loading, setLoading] = useState(true)
  const [abierta, setAbierta] = useState<number | null>(null)

  useEffect(() => {
    setLoading(true)
    api.get<Resumen>('/horarios/resumen', { params: { tienda_id: tiendaId, anio, mes } })
      .then(r => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [tiendaId, anio, mes])

  const descargar = async () => {
    const r = await api.get('/horarios/resumen.csv', {
      params: { tienda_id: tiendaId, anio, mes }, responseType: 'blob',
    })
    const url = URL.createObjectURL(new Blob([r.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = `horas-${anio}-${String(mes).padStart(2, '0')}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (loading) {
    return <p className="text-sm text-warm-400 py-10 text-center animate-pulse">Calculando el mes…</p>
  }
  if (!data) return <Aviso tono="error">No se pudo cargar el resumen del mes.</Aviso>

  const t = data.totales

  // Factor de costo del mes entero: la misma división que hace el backend por
  // persona (`factor_costo`), aplicada a los totales. Es el número que dice de
  // un vistazo cuánto más que el sueldo cuesta la nómina.
  const factorMes = t.total_devengado > 0 ? t.total_costo_empleador / t.total_devengado : 0

  // Plata que HOY se está pagando en salud patronal + SENA + ICBF y que la
  // exoneración del art. 114-1 apagaría. Solo suma a las que no están marcadas
  // como exoneradas: si ya lo están, no hay nada que ahorrar.
  const noExoneradas = data.baristas.filter(b => !b.liquidacion.aportes_empleador.exonerado)
  const ahorroExoneracion = noExoneradas.reduce(
    (s, b) => s + b.liquidacion.aportes_empleador.ahorro_por_exoneracion, 0)

  // DOS ESTADOS DISTINTOS QUE EL PAYLOAD DEVUELVE CON LA MISMA BANDERA.
  //
  // Cuando no hay ninguna vigencia de parámetros cargada, el backend contesta
  // la liquidación vacía: todo en cero, `vigencia_parametros` en null y
  // `confirmar_contador` en TRUE. O sea que la bandera se prende igual que
  // cuando los parámetros existen y todavía no los validó el contador, que es
  // el caso opuesto: allá hay un cálculo real esperando visto bueno, acá no hay
  // cálculo. Mirar solo `confirmar_contador` hacía que la pantalla dijera
  // «vigentes desde ,» sobre una liquidación que no se calculó con nada.
  // Quien manda para distinguirlos es `vigencia_parametros`.
  const sinParametros = data.baristas.some(b => b.liquidacion.vigencia_parametros === null)
  const sinConfirmar = data.baristas.some(
    b => b.liquidacion.confirmar_contador && b.liquidacion.vigencia_parametros !== null)
  const vigencia = data.baristas[0]?.liquidacion.vigencia_parametros ?? null

  return (
    <div className="space-y-3">
      {/* ── Encabezado + export ── */}
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-bold text-warm-700">
          {MESES[data.mes - 1]} {data.anio}
        </h2>
        <div className="flex-1" />
        <button
          onClick={descargar}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-white border border-warm-200 text-warm-600 hover:bg-warm-100"
        >
          <Download size={14} /> Bajar CSV para el contador
        </button>
      </div>

      {/* ── Horas ── */}
      <div className="grid grid-cols-3 gap-2">
        <Tarjeta titulo="Horas planeadas" valor={fmtHoras(t.total_planeado)} />
        <Tarjeta titulo="Horas reales" valor={fmtHoras(t.total_real)} />
        <Tarjeta
          titulo="Horas a pagar"
          valor={fmtHoras(t.total_acreditado)}
          pie="reales + novedades que se pagan"
        />
      </div>

      {/* ── La cuenta del mes: neto de ellas vs costo del negocio ── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-2">
        {/* Lado de ellas: se lee como una cuenta, con los signos a la vista. */}
        <div className="lg:col-span-3 bg-white rounded-2xl border border-warm-200 p-4">
          <div className="flex items-center gap-1.5 mb-2">
            <Wallet size={14} className="text-warm-500" />
            <p className="text-xs font-bold text-warm-600 uppercase tracking-wide">
              Lo que reciben las baristas
            </p>
          </div>
          <div className="space-y-1">
            <Renglon signo="" etiqueta="Devengado" pie="horas a pagar con recargos"
              valor={t.total_devengado} />
            <Renglon signo="+" etiqueta="Auxilio de transporte" pie="no es salario, pero se paga"
              valor={t.total_auxilio} />
            <Renglon signo="−" etiqueta="Deducciones" pie="salud y pensión de ella"
              valor={t.total_deducciones} />
            <div className="border-t border-warm-200 pt-1.5 mt-1.5">
              <Renglon signo="=" etiqueta="Neto a pagar" pie="es lo que ella recibe"
                valor={t.total_neto} fuerte />
            </div>
          </div>
        </div>

        {/* Lado del negocio: otro bloque, otro color, otro peso. No es el neto. */}
        <div className="lg:col-span-2 bg-clay-50 rounded-2xl border border-clay-200 p-4 flex flex-col">
          <div className="flex items-center gap-1.5 mb-2">
            <Building2 size={14} className="text-clay-600" />
            <p className="text-xs font-bold text-clay-600 uppercase tracking-wide">
              Costo para el negocio
            </p>
          </div>
          <p className="text-3xl font-bold text-clay-600 font-mono leading-none">
            {fmtPesos(t.total_costo_empleador)}
          </p>
          <p className="text-[11px] text-clay-600 mt-2 leading-relaxed">
            Devengado + auxilio + aportes del empleador + prestaciones.
            {factorMes > 0 && (
              <> Es <b className="font-mono">{fmtFactor(factorMes)}</b> el devengado.</>
            )}
          </p>
          <div className="flex-1" />
          <p className="text-[11px] text-clay-600 mt-2 pt-2 border-t border-clay-200">
            Son <b className="font-mono">
              {fmtPesos(t.total_costo_empleador - t.total_neto)}
            </b> más de lo que reciben ellas. Este es el número para decidir
            contrataciones; el neto es el que ellas van a preguntar.
          </p>
        </div>
      </div>

      {/* ── Exoneración 114-1: no es un pie de página, son cientos de miles ── */}
      {ahorroExoneracion > 0 && (
        <div className="bg-white rounded-2xl border-2 border-clay-200 p-4">
          <div className="flex items-start gap-2">
            <AlertTriangle size={16} className="text-clay-600 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="text-sm font-bold text-warm-700">
                Se están pagando {fmtPesos(ahorroExoneracion)} este mes que podrían no pagarse
              </p>
              <p className="text-xs text-warm-600 leading-relaxed">
                Los parámetros de nómina cargados dicen que el negocio NO está exonerado del
                art. 114-1, así que se liquidan salud patronal, SENA e ICBF por
                {' '}{noExoneradas.length} barista(s): {fmtPesos(ahorroExoneracion)} en el mes.
                Si el negocio califica para esa exoneración, ese es exactamente el monto que
                dejaría de pagar. <b>Confirmalo con tu contador antes de tocarlo</b> — el
                sistema no sabe si califica, solo sabe lo que está marcado.
              </p>
              <p className="text-[11px] text-warm-400">
                La caja de compensación se paga igual: la exoneración nunca la apaga.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Cómo se liquida y con qué parámetros ── */}
      <div className="bg-white rounded-2xl border border-warm-200 p-4 space-y-2">
        <div className="flex items-start gap-2">
          <Info size={14} className="text-warm-500 shrink-0 mt-0.5" />
          <p className="text-xs text-warm-600">{data.base_liquidacion_detalle}</p>
        </div>
        {data.advertencias.map((a, i) => (
          <p key={i} className="text-[11px] text-warm-400 pl-6">{a}</p>
        ))}
        <p className="text-[11px] text-warm-400 pl-6">
          La liquidación es un estimado: no incluye retención en la fuente, embargos,
          libranzas ni el redondeo de aportes de PILA.
          {vigencia && <> Parámetros de nómina vigentes desde <b className="font-mono">{vigencia}</b>.</>}
        </p>
        <div className="pl-6 flex flex-wrap gap-x-4 gap-y-1 pt-1">
          {data.semanas.map(s => (
            <span key={s.lunes} className="text-[11px] text-warm-400 font-mono">
              semana {s.lunes}: máx {s.jornada_max_semanal} h
              {s.confirmar_contador && ' *'}
            </span>
          ))}
        </div>
        {data.semanas.some(s => s.confirmar_contador) && (
          <p className="text-[11px] text-warm-400 pl-6">
            * tasa cargada pero todavía sin confirmar con el contador.
          </p>
        )}
        {sinConfirmar && (
          <p className="text-[11px] text-clay-600 font-semibold pl-6 flex items-start gap-1.5">
            <AlertTriangle size={12} className="shrink-0 mt-0.5" />
            Los parámetros de nómina (mínimo, auxilio, aportes, prestaciones) están cargados
            pero todavía sin confirmar con tu contador.
          </p>
        )}
        {/* El otro estado, que hasta acá se leía como el de arriba y decía justo
            lo contrario de lo que pasó: sin parámetros no hay nada cargado y no
            hubo liquidación. Se dice con los números a la vista porque el mes
            igual muestra horas reales: el $0 es del cálculo, no del trabajo. */}
        {sinParametros && (
          <p className="text-[11px] text-danger-700 font-semibold pl-6 flex items-start gap-1.5">
            <AlertTriangle size={12} className="shrink-0 mt-0.5" />
            <span>
              No hay ningún parámetro de nómina cargado (salario mínimo, auxilio de
              transporte, porcentajes de aportes y prestaciones), así que este mes no se
              liquidó: el devengado, el neto y el costo de arriba están en $0 porque falta
              ese dato, no porque nadie haya trabajado. Las horas sí son reales.
            </span>
          </p>
        )}
      </div>

      {(t.dias_sin_marcacion > 0 || t.tramos_sin_salida > 0 || t.sin_sueldo > 0) && (
        <Aviso tono="info">
          {t.dias_sin_marcacion > 0 && (
            <span className="block">
              Hay {t.dias_sin_marcacion} día(s) con turno asignado, sin marcación y sin
              novedad cargada. Puede ser una falta o una novedad que nadie registró.
            </span>
          )}
          {t.tramos_sin_salida > 0 && (
            <span className="block">
              {t.tramos_sin_salida} turno(s) sin salida marcada: esas horas no se contaron.
            </span>
          )}
          {/* Por MONTO, no por forma: `sin_contrato` es «falta la fila», y el PUT
              de Sueldos crea la fila con salario 0. Contando filas faltantes, el
              dueño leía «2 sin sueldo cargado» cuando eran 3, y el costo del mes
              quedaba corto sin que nada lo dijera. */}
          {t.sin_sueldo > 0 && (
            <span className="block">
              {t.sin_sueldo} barista(s) sin sueldo cargado: sus horas están, su devengado
              da $0 y toda su liquidación queda incompleta. Cargalo en la pestaña Sueldos.
            </span>
          )}
        </Aviso>
      )}

      {/* ── Por barista ── */}
      <div className="space-y-2">
        {data.baristas.map(b => (
          <FilaResumen
            key={b.usuario_id}
            barista={b}
            categorias={data.categorias}
            abierta={abierta === b.usuario_id}
            onToggle={() => setAbierta(abierta === b.usuario_id ? null : b.usuario_id)}
          />
        ))}
      </div>
    </div>
  )
}

function Tarjeta({ titulo, valor, pie }: { titulo: string; valor: string; pie?: string }) {
  return (
    <div className="bg-white rounded-2xl border border-warm-200 px-3 py-2.5">
      <p className="text-[11px] font-semibold text-warm-400">{titulo}</p>
      <p className="text-lg font-bold text-warm-700 font-mono">{valor}</p>
      {pie && <p className="text-[10px] text-warm-400">{pie}</p>}
    </div>
  )
}

/**
 * Un renglón de la cuenta. El signo va en su propia columna fija para que los
 * tres sumandos y el resultado se lean en vertical como una operación, y no
 * como cuatro cifras sueltas que da lo mismo en qué orden estén.
 */
function Renglon({ signo, etiqueta, pie, valor, fuerte }: {
  signo: string; etiqueta: string; pie?: string; valor: number; fuerte?: boolean
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className={`w-3 shrink-0 text-center font-mono ${
        fuerte ? 'text-warm-700 font-bold' : 'text-warm-400'}`}>{signo}</span>
      <span className="flex-1 min-w-0">
        <span className={`block ${fuerte
          ? 'text-sm font-bold text-warm-700' : 'text-xs text-warm-600'}`}>{etiqueta}</span>
        {pie && <span className="block text-[10px] text-warm-400 leading-tight">{pie}</span>}
      </span>
      <span className={`font-mono shrink-0 ${fuerte
        ? 'text-xl font-bold text-forest-700' : 'text-sm text-warm-700'}`}>
        {fmtPesos(valor)}
      </span>
    </div>
  )
}

function FilaResumen({ barista, categorias, abierta, onToggle }: {
  barista: BaristaResumen
  categorias: { clave: string; label: string }[]
  abierta: boolean
  onToggle: () => void
}) {
  const b = barista
  const dif = b.diferencia_horas
  const conCategorias = categorias.filter(c => (b.horas_acreditadas[c.clave] ?? 0) > 0)

  return (
    <div className="bg-white rounded-2xl border border-warm-200 overflow-hidden">
      <button onClick={onToggle} className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-warm-50">
        {abierta ? <ChevronDown size={16} className="text-warm-400" />
                 : <ChevronRight size={16} className="text-warm-400" />}
        <span className="flex-1 text-sm font-bold text-warm-700">{b.nombre}</span>

        <span className="text-xs text-warm-400 hidden sm:block">
          plan {fmtHoras(b.total_planeado)}
        </span>
        <span className="text-sm font-mono font-semibold text-warm-700">
          {fmtHoras(b.total_acreditado)}
        </span>
        {Math.abs(dif) > 0.01 && (
          <span className={`text-xs font-mono font-semibold ${
            dif > 0 ? 'text-clay-600' : 'text-danger-700'}`}>
            {dif > 0 ? '+' : ''}{dif.toFixed(1)}
          </span>
        )}

        {/* Los dos números, cada uno con su nombre. Antes acá iba UNO solo y sin
            etiqueta, y se leía como «lo que le pago a ella» — que es justamente
            lo que no era. */}
        <span className="w-24 text-right shrink-0">
          <span className="block text-[10px] font-semibold text-warm-400 leading-none">
            neto de ella
          </span>
          <span className="block text-sm font-mono text-warm-700">
            {fmtPesos(b.liquidacion.neto_a_pagar)}
          </span>
        </span>
        <span className="w-24 text-right shrink-0 hidden sm:block">
          <span className="block text-[10px] font-semibold text-clay-600 leading-none">
            costo negocio
          </span>
          <span className="block text-sm font-mono font-bold text-clay-600">
            {fmtPesos(b.liquidacion.costo_empleador)}
          </span>
        </span>

        {b.dias_sin_marcacion.length > 0 && (
          <AlertTriangle size={14} className="text-danger-500" />
        )}
      </button>

      {abierta && (
        <div className="border-t border-warm-100 px-4 py-3 space-y-3">
          {/* Horas por categoría */}
          <div>
            <p className="text-xs font-bold text-warm-500 mb-1">Horas que se pagan</p>
            {conCategorias.length === 0 ? (
              <p className="text-xs text-warm-400">No hay horas en el mes.</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
                {conCategorias.map(c => (
                  <div key={c.clave} className="flex justify-between text-xs">
                    <span className="text-warm-500">{c.label}</span>
                    <span className="font-mono text-warm-700">
                      {fmtHoras(b.horas_acreditadas[c.clave])}
                      <span className="text-warm-400 ml-2">
                        {fmtPesos(b.estimado.detalle[c.clave] ?? 0)}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p className="text-[11px] text-warm-400 mt-1">
              {/* `tiene_sueldo` y no `tiene_contrato`: con la fila creada en $0
                  esta línea escribía «sueldo $0 ÷ el divisor», presentando el
                  cero como si fuera un sueldo que alguien cargó. */}
              {b.tiene_sueldo
                ? `Hora ordinaria: ${fmtPesos(b.estimado.valor_hora_ordinaria)} (sueldo ${fmtPesos(b.salario_mensual)} ÷ el divisor de la tasa).`
                : 'Sin sueldo cargado: el devengado queda en $0. Cargalo en la pestaña Sueldos.'}
            </p>
          </div>

          <DetalleLiquidacion l={b.liquidacion} nombre={b.nombre} />

          {/* Planeado vs real */}
          <div className="grid grid-cols-3 gap-2">
            <Mini titulo="Planeado" valor={fmtHoras(b.total_planeado)} />
            <Mini titulo="Marcado" valor={fmtHoras(b.total_real)} />
            <Mini titulo="Diferencia" valor={`${dif > 0 ? '+' : ''}${dif.toFixed(1)} h`} />
          </div>

          {b.tramos_sin_salida > 0 && (
            <p className="text-[11px] text-danger-700">
              {b.tramos_sin_salida} turno(s) sin salida marcada: esas horas no se contaron.
            </p>
          )}

          {/* Novedades */}
          {b.novedades.length > 0 && (
            <div>
              <p className="text-xs font-bold text-warm-500 mb-1">Novedades</p>
              <ul className="space-y-0.5">
                {b.novedades.map(n => (
                  <li key={n.id} className="text-xs text-warm-600">
                    <span className="font-mono text-warm-400">
                      {n.fecha_desde}→{n.fecha_hasta}
                    </span>{' '}
                    {n.label}
                    <span className="text-warm-400">
                      {' '}· {n.acredita_horas ? 'cuenta horas' : 'no cuenta horas'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Día por día */}
          <div>
            <p className="text-xs font-bold text-warm-500 mb-1">Día por día</p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-warm-400">
                    <th className="text-left font-semibold py-1">Fecha</th>
                    <th className="text-right font-semibold">Plan</th>
                    <th className="text-right font-semibold">Marcado</th>
                    <th className="text-left font-semibold pl-3">Qué pasó</th>
                  </tr>
                </thead>
                <tbody>
                  {b.dias.map(d => (
                    <tr key={d.fecha} className="border-t border-warm-100">
                      <td className="py-1 font-mono text-warm-600">{d.fecha}</td>
                      <td className="text-right font-mono text-warm-500">
                        {d.horas_planeadas || '–'}
                      </td>
                      <td className="text-right font-mono text-warm-700">
                        {d.horas_reales || '–'}
                      </td>
                      <td className="pl-3">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${ESTADO_COLOR[d.estado]}`}>
                          {ESTADO_LABEL[d.estado]}
                        </span>
                        {d.novedad && (
                          <span className="text-warm-400 ml-1">{d.novedad.label}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * La liquidación completa de UNA barista, abierta en dos columnas: a la
 * izquierda la cuenta que termina en su neto, a la derecha lo que el negocio
 * paga encima y que ella nunca ve en su recibo.
 */
function DetalleLiquidacion({ l, nombre }: { l: Liquidacion; nombre: string }) {
  const ap = l.aportes_empleador
  const pr = l.prestaciones
  const primerNombre = nombre.split(' ')[0]

  // LOS APORTES NO TIENEN UNA SOLA BASE, así que la pantalla no puede hablar de
  // «la base» en singular. La seguridad social (salud, pensión, ARL) va sobre el
  // IBC, que nunca baja de un mínimo; los parafiscales (SENA, ICBF, caja) van
  // sobre lo REALMENTE devengado y no tienen ese piso. Las dos coinciden casi
  // siempre y se separan justo en medio tiempo — que es donde el error se cobra.
  //
  // Los nombres cambian con la exoneración porque, cuando está prendida, esta
  // liquidación no cobró salud patronal ni SENA ni ICBF (la lista de arriba
  // tampoco los muestra): explicar la base de un aporte que no se pagó es
  // describir un número que no está en la columna.
  const sobreIbc = ap.exonerado ? 'pensión y ARL' : 'salud, pensión y ARL'
  const sobreParafiscales = ap.exonerado
    ? 'la caja de compensación'
    : 'SENA, ICBF y caja de compensación'

  return (
    <div className="rounded-xl border border-warm-200 overflow-hidden">
      <div className="grid grid-cols-1 sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-warm-200">
        {/* Columna de ella */}
        <div className="p-3 space-y-1">
          <p className="text-xs font-bold text-warm-500 mb-1.5">
            Lo que recibe {primerNombre}
          </p>
          <Linea label="Devengado" valor={l.devengado} />
          <Linea
            label="Auxilio de transporte"
            nota={l.auxilio.tiene_derecho
              ? `${l.auxilio.dias} día(s) × ${fmtPesos(l.auxilio.por_dia)}`
              : (l.auxilio.razon ?? 'sin derecho')}
            valor={l.auxilio.total}
          />
          <Linea label="Salud" valor={l.deducciones.salud} resta />
          <Linea label="Pensión" valor={l.deducciones.pension} resta />
          {l.deducciones.fondo_solidaridad > 0 && (
            <Linea label="Fondo de solidaridad pensional"
              valor={l.deducciones.fondo_solidaridad} resta />
          )}
          <div className="border-t border-warm-200 pt-1.5 mt-1.5 flex justify-between items-baseline">
            <span className="text-xs font-bold text-warm-700">Neto a pagar</span>
            <span className="text-base font-mono font-bold text-forest-700">
              {fmtPesos(l.neto_a_pagar)}
            </span>
          </div>
          {/* El piso del mínimo NO es incondicional: `liquidacion.ibc` devuelve 0
              cuando el devengado es 0, porque poner el piso ahí inventaría un
              aporte por alguien que no tuvo jornada. Con la frase única, la
              barista sin sueldo cargado leía «se calculan sobre $0: es el
              devengado con piso de un salario mínimo» — una oración que se
              desmiente a sí misma en su propio renglón. */}
          {l.deducciones.base_ibc > 0 ? (
            <p className="text-[10px] text-warm-400 leading-tight pt-1">
              Salud y pensión se calculan sobre {fmtPesos(l.deducciones.base_ibc)}: es el
              devengado con piso de un salario mínimo, y el auxilio no entra en esa base.
            </p>
          ) : (
            <p className="text-[10px] text-warm-400 leading-tight pt-1">
              No hay salud ni pensión que descontar: sin devengado en el mes no hay base de
              cotización. El piso de un salario mínimo aplica a quien trabajó, no a quien no
              tuvo jornada.
            </p>
          )}
        </div>

        {/* Columna del negocio */}
        <div className="p-3 space-y-1 bg-warm-50">
          <p className="text-xs font-bold text-warm-500 mb-1.5">Lo que paga el negocio encima</p>
          {!ap.exonerado && <Linea label="Salud empleador" valor={ap.salud} />}
          <Linea label="Pensión empleador" valor={ap.pension} />
          <Linea label="ARL" valor={ap.arl} />
          <Linea label="Caja de compensación" valor={ap.caja_compensacion} />
          {!ap.exonerado && <Linea label="SENA" valor={ap.sena} />}
          {!ap.exonerado && <Linea label="ICBF" valor={ap.icbf} />}
          <Linea label="Prima" valor={pr.prima} />
          <Linea label="Cesantías" valor={pr.cesantias} />
          <Linea label="Intereses de cesantías" valor={pr.intereses_cesantias} />
          <Linea label="Vacaciones" valor={pr.vacaciones} />
          {/* Subtotal de ESTA columna. Va antes del costo total a propósito: sin
              él, la lista de arriba no suma el número de abajo y parece rota —
              el costo también lleva el devengado y el auxilio, que están en la
              otra columna porque ella sí los ve. */}
          <div className="border-t border-warm-200 pt-1.5 mt-1.5">
            <Linea label="Aportes + prestaciones" valor={ap.total + pr.total} />
          </div>
          <div className="flex justify-between items-baseline pt-1">
            <span className="text-xs font-bold text-clay-600">Costo total del mes</span>
            <span className="text-base font-mono font-bold text-clay-600">
              {fmtPesos(l.costo_empleador)}
            </span>
          </div>
          <p className="text-[10px] text-warm-400 leading-tight pt-1">
            Costo total = devengado + auxilio + esta columna.
            {l.factor_costo > 0 && ` Es ${fmtFactor(l.factor_costo)} el devengado.`}
            {' '}Prima, cesantías e intereses se liquidan sobre {fmtPesos(pr.base_con_auxilio)}
            {' '}(con auxilio); las vacaciones sobre {fmtPesos(pr.base_sin_auxilio)} (sin auxilio).
          </p>
          {ap.base_ibc > 0 && (
            <p className="text-[10px] text-warm-400 leading-tight pt-1">
              {fmtPesos(ap.base_ibc)} es la base de {sobreIbc} del empleador: el IBC no baja
              de un salario mínimo. {fmtPesos(ap.base_parafiscales)} es la base de
              {' '}{sobreParafiscales}: lo realmente devengado, sin ese piso.
              {ap.base_parafiscales < ap.base_ibc
                && ' Este mes las dos se separan porque el devengado no llega a un mínimo.'}
            </p>
          )}
        </div>
      </div>

      {!ap.exonerado && ap.ahorro_por_exoneracion > 0 && (
        <p className="text-[11px] text-clay-600 bg-clay-50 border-t border-clay-200 px-3 py-2">
          De ese costo, <b className="font-mono">{fmtPesos(ap.ahorro_por_exoneracion)}</b> son
          salud patronal, SENA e ICBF. Si el negocio califica para la exoneración del art.
          114-1, eso no se pagaría. Confirmalo con tu contador; la caja de compensación se
          paga igual.
        </p>
      )}
      {/* La condición lleva las DOS: `confirmar_contador` viene prendido también
          cuando no hay ninguna vigencia cargada, y ahí esta frase escribía
          «vigentes desde ,» sobre una liquidación que no se calculó con ningún
          parámetro. La bandera describía la FORMA del dato, no su contenido. */}
      {l.confirmar_contador && l.vigencia_parametros && (
        <p className="text-[11px] text-clay-600 bg-clay-50 border-t border-clay-200 px-3 py-2">
          Calculado con los parámetros vigentes desde{' '}
          <b className="font-mono">{l.vigencia_parametros}</b>, todavía sin confirmar con tu
          contador.
        </p>
      )}
      {/* El caso que la frase de arriba tapaba. La razón la trae el propio
          payload (`auxilio.razon`), así que se muestra la del backend en vez de
          escribir una segunda versión que mañana diga otra cosa. */}
      {l.vigencia_parametros === null && (
        <p className="text-[11px] text-danger-700 bg-danger-50 border-t border-danger-200 px-3 py-2">
          <b>{l.auxilio.razon ?? 'No hay parámetros de nómina cargados.'}</b> Sin ellos no
          hay con qué liquidar: el devengado, el neto y el costo de esta barista quedaron en
          $0 por falta de ese dato, no por lo que ella haya trabajado. Sus horas del mes, que
          se cuentan aparte, sí están arriba.
        </p>
      )}
    </div>
  )
}

/**
 * Un renglón del detalle. `resta` marca lo que SALE del sueldo de ella: el
 * signo va delante del peso y no dentro del número, para que un $0 restado no
 * termine escrito como «$-0» y para que se distinga de un aporte del negocio.
 */
function Linea({ label, valor, nota, resta }: {
  label: string; valor: number; nota?: string; resta?: boolean
}) {
  return (
    <div className="flex justify-between items-baseline gap-2 text-xs">
      <span className="text-warm-500 min-w-0">
        {label}
        {nota && <span className="block text-[10px] text-warm-400 leading-tight">{nota}</span>}
      </span>
      <span className="font-mono text-warm-700 shrink-0">
        {resta ? '−' : ''}{fmtPesos(valor)}
      </span>
    </div>
  )
}

function Mini({ titulo, valor }: { titulo: string; valor: string }) {
  return (
    <div className="rounded-xl bg-warm-50 px-2 py-1.5 text-center">
      <p className="text-[10px] text-warm-400 font-semibold">{titulo}</p>
      <p className="text-sm font-mono font-bold text-warm-700">{valor}</p>
    </div>
  )
}
