import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Info, Loader2, Save } from 'lucide-react'
import api from '../../api/client'
import { Aviso } from './SemanaGrid'
import { fmtPesos, type ParametroNomina } from './tipos'

/**
 * Parámetros de nómina: el mínimo, el auxilio y los aportes de ley.
 *
 * Hermana de TasasPanel y con la misma disciplina: acá no se afirma nada, se
 * muestra LO QUE ESTÁ CARGADO. Cada vigencia trae su nota (de qué decreto salió)
 * y el cartel de «sin confirmar» hasta que el contador la valide.
 *
 * Tres reglas del backend que esta pantalla tiene que respetar y por qué:
 *
 *   1. `vigente_desde` NO se edita. Cada mes se liquida con la vigencia de SU
 *      fecha, así que correrla reescribiría nóminas ya pagadas. El endpoint
 *      contesta 400 si se manda; acá ni siquiera se ofrece el campo.
 *   2. Escribir CUALQUIER valor baja `confirmar_contador`. Por eso se manda
 *      solo lo que cambió: si el dueño únicamente toca la casilla, el backend
 *      la respeta («lo revisé y está bien»); si mandáramos la fila entera cada
 *      vez, esa casilla no podría volver a subirse nunca.
 *   3. Los porcentajes se GUARDAN en fracción (0.085) y se MUESTRAN en
 *      porcentaje (8,5). La conversión vive en el borde de los inputs, y cada
 *      uno dice su unidad al lado. Sin eso, el dueño teclea «8.5» y guarda 850%.
 */

// Lo que este panel manda al PUT. `nota` y `vigente_desde` quedan afuera: la
// nota es el origen documental de la fila (se lee, no se reescribe desde acá) y
// la fecha el backend la rechaza.
type CampoNumerico =
  | 'smmlv' | 'auxilio_transporte' | 'dias_base_auxilio' | 'tope_auxilio_smmlv'
  | 'salud_empleado' | 'pension_empleado' | 'fsp_desde_smmlv' | 'fsp_tarifa'
  | 'salud_empleador' | 'pension_empleador' | 'arl' | 'caja_compensacion'
  | 'sena' | 'icbf'
  | 'prima' | 'cesantias' | 'intereses_cesantias' | 'vacaciones'

type CampoEditable = CampoNumerico | 'exonerado_114_1' | 'confirmar_contador'

const CAMPOS_EDITABLES: readonly CampoEditable[] = [
  'smmlv', 'auxilio_transporte', 'dias_base_auxilio', 'tope_auxilio_smmlv',
  'salud_empleado', 'pension_empleado', 'fsp_desde_smmlv', 'fsp_tarifa',
  'salud_empleador', 'pension_empleador', 'arl', 'caja_compensacion',
  'sena', 'icbf', 'exonerado_114_1',
  'prima', 'cesantias', 'intereses_cesantias', 'vacaciones',
  'confirmar_contador',
]

/** Solo los campos que difieren del original. Ver la regla 2 del encabezado. */
function cambiosDe(original: ParametroNomina, editada: ParametroNomina): Record<string, number | boolean> {
  const payload: Record<string, number | boolean> = {}
  for (const campo of CAMPOS_EDITABLES) {
    if (editada[campo] !== original[campo]) payload[campo] = editada[campo]
  }
  return payload
}

// Fracción → porcentaje y vuelta. El `toFixed` no es cosmético: 0.0833333 × 100
// da 8.333329999999999 en punto flotante, y ese ruido terminaría guardado.
const aPct = (fraccion: number) => Number(((fraccion || 0) * 100).toFixed(6))
const aFraccion = (pct: number) => Number(((pct || 0) / 100).toFixed(8))

/** Igual que `Parametros.auxilio_por_dia`: divisor 30 fijo, con el mismo guardia. */
const auxilioPorDia = (p: ParametroNomina) =>
  (p.auxilio_transporte || 0) / ((Math.round(p.dias_base_auxilio) || 30))

// El backend valida los porcentajes EN FRACCIÓN y su mensaje lo dice así: «se
// escribe en tanto por uno, entre 0 y 1: el 4% se carga como 0.04, no como 4».
// Ese texto está bien para un cliente de API y es VENENO acá, donde el campo
// pide porcentaje: quien tecleó 850 por error lee «cargalo como 0.04», obedece,
// y guarda 0,04% en vez de 4%. Es el error de cien veces que el propio backend
// cree estar atajando, entrando por la puerta del mensaje de error.
//
// Por eso el detail de un campo de porcentaje NO se muestra crudo: se traduce a
// la unidad de esta pantalla. Los de pesos, SMMLV y días sí se muestran tal
// cual, porque esos hablan en la misma unidad que el input.
const RE_DETAIL_FRACCION = /tanto por uno|no como 4/i

function mensajeError(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  if (typeof detail !== 'string' || detail.length === 0) return fallback
  if (RE_DETAIL_FRACCION.test(detail)) {
    const campo = detail.match(/«([^»]+)»/)?.[1]
    return `${campo ? `«${campo}»` : 'Ese porcentaje'} tiene que quedar entre 0 y 100 %. `
      + 'Acá se escribe como porcentaje: 8,5 es 8,5%, no 0,085.'
  }
  return detail
}

export default function ParametrosNominaPanel() {
  const [filas, setFilas] = useState<ParametroNomina[]>([])
  // Copia intacta de lo que devolvió el servidor, para saber QUÉ cambió.
  const [originales, setOriginales] = useState<Record<number, ParametroNomina>>({})
  const [loading, setLoading] = useState(true)
  const [guardando, setGuardando] = useState<number | null>(null)
  const [guardado, setGuardado] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const cargar = () => {
    setLoading(true)
    api.get<ParametroNomina[]>('/horarios/parametros-nomina')
      .then(({ data }) => {
        setFilas(data)
        setOriginales(Object.fromEntries(data.map(p => [p.id, p])))
      })
      .catch(e => setError(mensajeError(e, 'No se pudieron cargar los parámetros de nómina.')))
      .finally(() => setLoading(false))
  }
  useEffect(cargar, [])

  const patch = (id: number, cambios: Partial<ParametroNomina>) => {
    setFilas(prev => prev.map(p => (p.id === id ? { ...p, ...cambios } : p)))
    setGuardado(null)
  }

  const guardar = async (fila: ParametroNomina) => {
    const payload = cambiosDe(originales[fila.id], fila)
    if (Object.keys(payload).length === 0) return
    setGuardando(fila.id); setError(null)
    try {
      const { data } = await api.put<ParametroNomina>(
        `/horarios/parametros-nomina/${fila.id}`, payload)
      // Se reemplaza con LO QUE CONTESTÓ el servidor y no con lo tecleado: si
      // tocaste un número, el backend bajó el cartel de «sin confirmar» y la
      // pantalla tiene que mostrar eso, no lo que estaba antes en la casilla.
      setFilas(prev => prev.map(p => (p.id === data.id ? data : p)))
      setOriginales(prev => ({ ...prev, [data.id]: data }))
      setGuardado(fila.id)
    } catch (e) {
      setError(mensajeError(e, 'No se pudo guardar la vigencia.'))
    } finally { setGuardando(null) }
  }

  if (loading) {
    return <p className="text-sm text-warm-400 py-10 text-center animate-pulse">Cargando…</p>
  }

  const sinConfirmar = filas.filter(p => p.confirmar_contador).length

  return (
    <div className="space-y-4">
      {error && <Aviso tono="error">{error}</Aviso>}

      <div className="bg-white rounded-2xl border border-warm-200 p-4 space-y-1">
        <p className="text-sm font-bold text-warm-700">Cómo se usan estos parámetros</p>
        <p className="text-xs text-warm-500">
          Cada mes se liquida con la vigencia de SU fecha (la última que empezó antes o
          el mismo día), no con la de hoy: por eso recalcular un mes viejo siempre da lo
          mismo. Son valores editables, y lo que sale de acá es un piso verificable —
          no lleva retención en la fuente, embargos, libranzas ni el redondeo de PILA.
        </p>
        <p className="text-xs text-warm-500">
          Los porcentajes se escriben acá <b>como porcentaje</b> (8,5 es 8,5%); el sistema
          los guarda como fracción. Apenas escribís un valor, el cartel de «sin confirmar»
          se cae solo: ese número ya no es el que sembró el sistema, es el tuyo.
        </p>
        {sinConfirmar > 0 && (
          <p className="text-xs text-clay-600 font-semibold flex items-center gap-1.5 pt-1">
            <AlertTriangle size={13} />
            {sinConfirmar} vigencia(s) todavía sin confirmar con tu contador. Revisá la nota
            de cada una y destildá «sin confirmar» cuando te las valide.
          </p>
        )}
      </div>

      {filas.length === 0 && (
        <Aviso tono="info">
          No hay vigencias cargadas. Sin ellas no se sabe cuánto vale el salario mínimo y
          la nómina no se puede liquidar.
        </Aviso>
      )}

      {filas.map(p => {
        const original = originales[p.id]
        const pendientes = Object.keys(cambiosDe(original, p)).length
        const dias = Math.round(p.dias_base_auxilio) || 30
        const topeAuxilio = (p.smmlv || 0) * (p.tope_auxilio_smmlv || 0)
        const umbralFsp = (p.smmlv || 0) * (p.fsp_desde_smmlv || 0)
        // Los tres que apaga la exoneración, sobre una barista de 1 SMMLV: ahí
        // el IBC (salud) y el devengado (SENA/ICBF) coinciden, así que la suma
        // es exactamente lo que el backend informa como ahorro_por_exoneracion.
        const ahorroExoneracion =
          (p.smmlv || 0) * ((p.salud_empleador || 0) + (p.sena || 0) + (p.icbf || 0))

        return (
          <div key={p.id} className="bg-white rounded-2xl border border-warm-200 p-4 space-y-4">
            {/* ── Cabecera de la vigencia ── */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-bold text-warm-700 font-mono">
                Desde {p.vigente_desde}
              </span>
              {p.confirmar_contador && (
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-clay-100 text-clay-600">
                  sin confirmar
                </span>
              )}
              {pendientes > 0 && (
                <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-warm-100 text-warm-600">
                  {pendientes} cambio(s) sin guardar
                </span>
              )}
              <div className="flex-1" />
              <button
                onClick={() => guardar(p)}
                disabled={guardando === p.id || pendientes === 0}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-forest text-white hover:bg-forest/90 disabled:opacity-40"
              >
                {guardando === p.id ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                Guardar
              </button>
              {guardado === p.id && (
                <span className="flex items-center gap-1 text-xs text-forest-700 font-medium">
                  <Check size={12} /> guardado
                </span>
              )}
            </div>

            <p className="text-[11px] text-warm-400">
              La fecha se muestra pero no se edita: moverla cambiaría con qué números se
              recalculan meses que ya se pagaron. Si está mal, va una vigencia nueva.
            </p>

            {/* ── 1. Lo que se decreta cada enero ── */}
            <Grupo
              titulo="Lo que se decreta cada enero"
              porque="Salen por decreto en diciembre y rigen desde el 1 de enero. Los contratos pactados «en mínimos» se resuelven contra este valor, así que en enero esos sueldos suben solos."
            >
              <CampoPesos label="Salario mínimo (SMMLV)" value={p.smmlv}
                onChange={v => patch(p.id, { smmlv: v })} />
              <CampoPesos label="Auxilio de transporte" value={p.auxilio_transporte}
                onChange={v => patch(p.id, { auxilio_transporte: v })} />
            </Grupo>

            {/* ── 2. Reglas del auxilio ── */}
            <Grupo
              titulo="Reglas del auxilio"
              porque="El auxilio no es salario, pero se paga y entra en la base de prima, cesantías e intereses. Se prorratea por día con divisor fijo (no por los días del mes), y a quien va medio día se le paga el día completo."
            >
              <CampoNum label="Días base del auxilio" sufijo="días" step={1} entero
                value={p.dias_base_auxilio}
                onChange={v => patch(p.id, { dias_base_auxilio: v })} />
              <CampoNum label="Tope del derecho" sufijo="SMMLV" step="any"
                value={p.tope_auxilio_smmlv}
                onChange={v => patch(p.id, { tope_auxilio_smmlv: v })} />
            </Grupo>
            <p className="text-[11px] text-warm-400 -mt-2">
              Con estos valores el auxilio vale <b className="font-mono">{fmtPesos(auxilioPorDia(p))}</b> por
              día (dividido en {dias}), y lo cobra quien gane hasta{' '}
              <b className="font-mono">{fmtPesos(topeAuxilio)}</b> al mes. Por encima de ese
              sueldo no se paga. Incapacidad, vacaciones, licencia, permiso no remunerado
              y ausencia descuentan días de auxilio.
            </p>

            {/* ── 3. Lo que se le descuenta a la barista ── */}
            <Grupo
              titulo="Lo que se le descuenta a la barista"
              porque="Sale de su propio sueldo y se calcula sobre el IBC: lo devengado con piso de un mínimo (una media jornada cotiza igual sobre un mínimo entero). El auxilio de transporte no entra en esa base."
            >
              <CampoPct label="Salud (empleada)" value={p.salud_empleado}
                onChange={v => patch(p.id, { salud_empleado: v })} />
              <CampoPct label="Pensión (empleada)" value={p.pension_empleado}
                onChange={v => patch(p.id, { pension_empleado: v })} />
              <CampoNum label="Solidaridad desde" sufijo="SMMLV" step="any"
                value={p.fsp_desde_smmlv}
                onChange={v => patch(p.id, { fsp_desde_smmlv: v })} />
              <CampoPct label="Tarifa solidaridad" value={p.fsp_tarifa}
                onChange={v => patch(p.id, { fsp_tarifa: v })} />
            </Grupo>
            <p className="text-[11px] text-warm-400 -mt-2">
              El fondo de solidaridad pensional recién arranca con un IBC de{' '}
              <b className="font-mono">{fmtPesos(umbralFsp)}</b>: con sueldo mínimo da cero, y
              se calcula igual para que el día que haya un sueldo alto no pase por alto.
            </p>

            {/* ── 4. Lo que paga el negocio ── */}
            <Grupo
              titulo="Lo que paga el negocio"
              porque="Va por encima del sueldo, no se le descuenta a nadie. Salud, pensión y ARL sobre el IBC (con piso de un mínimo); SENA, ICBF y caja sobre lo realmente devengado."
            >
              <CampoPct label="Salud (patronal)" value={p.salud_empleador}
                onChange={v => patch(p.id, { salud_empleador: v })} />
              <CampoPct label="Pensión (patronal)" value={p.pension_empleador}
                onChange={v => patch(p.id, { pension_empleador: v })} />
              <CampoPct label="ARL" value={p.arl}
                onChange={v => patch(p.id, { arl: v })} />
              <CampoPct label="Caja de compensación" value={p.caja_compensacion}
                onChange={v => patch(p.id, { caja_compensacion: v })} />
              <CampoPct label="SENA" value={p.sena}
                onChange={v => patch(p.id, { sena: v })} />
              <CampoPct label="ICBF" value={p.icbf}
                onChange={v => patch(p.id, { icbf: v })} />
            </Grupo>

            {/* La ARL no es un número de ley suelto: depende de CÓMO opera la
                sede, y es lo único de esta pantalla que puede cambiar sin que
                cambie ninguna norma. Por eso se explica al lado del campo. */}
            <div className="rounded-xl border border-warm-200 bg-warm-50 px-3 py-2 space-y-1">
              <p className="text-xs font-bold text-warm-700 flex items-center gap-1.5">
                <Info size={13} className="text-warm-400" /> Por qué la ARL está en {aPct(p.arl)}%
              </p>
              <p className="text-[11px] text-warm-500 leading-relaxed">
                La clase I (0,522%) es la de cafetería con expendio <b>a la mesa</b>. Dos
                cambios de operación la mueven, y ninguno avisa: pasar a autoservicio la
                sube a clase II (1,044%) y hornear pan o pastelería en la sede, a clase III
                (2,436%) — casi cinco veces la de hoy. El día que eso pase, este campo es
                el que hay que corregir.
              </p>
            </div>

            {/* Exoneración: es la línea más cara de la pantalla y la que más
                fácil queda mal puesta, porque la condición que la sostiene se
                pierde sola (se va gente) sin que nadie toque el sistema. */}
            <div className="rounded-xl border border-warm-200 bg-warm-50 px-3 py-2 space-y-1.5">
              <label className="flex items-center gap-2 text-xs font-bold text-warm-700">
                <input
                  type="checkbox" checked={p.exonerado_114_1}
                  onChange={e => patch(p.id, { exonerado_114_1: e.target.checked })}
                  className="h-4 w-4 rounded border-warm-200 text-forest focus:ring-forest"
                />
                Exonerado de aportes (art. 114-1 ET)
              </label>
              <p className="text-[11px] text-warm-500 leading-relaxed">
                Prendido apaga tres cosas: <b>salud patronal ({aPct(p.salud_empleador)}%),
                SENA ({aPct(p.sena)}%) e ICBF ({aPct(p.icbf)}%)</b>. La caja de compensación
                ({aPct(p.caja_compensacion)}%) <b>se sigue pagando siempre</b>: la exoneración
                nunca la apaga, y ahí es donde se equivoca casi todo el mundo que dice
                «estoy exonerado de parafiscales». Sobre una barista que gana el mínimo son{' '}
                <b className="font-mono">{fmtPesos(ahorroExoneracion)}</b> al mes.
              </p>
              <p className="text-[11px] text-warm-500 leading-relaxed">
                {/* La casilla de arriba es EDITABLE, así que afirmar su estado en
                    indicativo era escribir una constante sobre un dato variable: al
                    destildarla, el texto seguía diciendo «está prendido». */}
                {p.exonerado_114_1
                  ? <>Está <b>prendido</b> porque MEDIUM CAFÉ es <b>persona natural con dos
                      o más trabajadores</b>, que es justo lo que exige la norma.{' '}</>
                  : <>Está <b>apagado</b>: se están liquidando salud patronal, SENA e ICBF
                      por cada barista. Si sos persona natural con dos o más trabajadores,
                      la norma te exonera y acá estás pagando de más.{' '}</>}
                Se pierde si alguna vez quedás con un solo empleado: ahí vuelven a deberse
                esos tres aportes por el período completo, no desde el día en que alguien se
                dé cuenta. El resumen del mes te avisa si ve menos de dos contratos activos,
                pero cuenta los que están cargados acá: si tenés trabajadores fuera del
                sistema, esta casilla es la que hay que revisar.
              </p>
            </div>

            {/* ── 5. Prestaciones ── */}
            <Grupo
              titulo="Prestaciones"
              porque="Provisión mensual: no se paga este mes, pero se debe. Prima, cesantías e intereses van sobre el devengado MÁS el auxilio; las vacaciones solo sobre el devengado."
            >
              <CampoPct label="Prima" value={p.prima}
                onChange={v => patch(p.id, { prima: v })} />
              <CampoPct label="Cesantías" value={p.cesantias}
                onChange={v => patch(p.id, { cesantias: v })} />
              <CampoPct label="Intereses de cesantías" value={p.intereses_cesantias}
                onChange={v => patch(p.id, { intereses_cesantias: v })} />
              <CampoPct label="Vacaciones" value={p.vacaciones}
                onChange={v => patch(p.id, { vacaciones: v })} />
            </Grupo>

            {p.nota && <p className="text-[11px] text-warm-500 leading-relaxed">{p.nota}</p>}

            <label className="flex items-center gap-2 text-xs text-warm-600">
              <input
                type="checkbox" checked={p.confirmar_contador}
                onChange={e => patch(p.id, { confirmar_contador: e.target.checked })}
                className="h-4 w-4 rounded border-warm-200 text-forest focus:ring-forest"
              />
              Todavía sin confirmar con el contador
            </label>
            <p className="text-[11px] text-warm-400 -mt-2">
              Si no cambiaste ningún valor, guardar manda solo esta casilla: sirve para
              decir «lo revisé y está bien como está». Si tocaste un número, el sistema la
              destilda solo al guardar.
            </p>
          </div>
        )
      })}
    </div>
  )
}

/** Bloque de campos agrupado como los agrupa la ley, con el porqué arriba. */
function Grupo({ titulo, porque, children }: {
  titulo: string; porque: string; children: React.ReactNode
}) {
  return (
    <div className="space-y-2">
      <div>
        <p className="text-xs font-bold text-warm-700">{titulo}</p>
        <p className="text-[11px] text-warm-400 leading-relaxed">{porque}</p>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">{children}</div>
    </div>
  )
}

function CampoPesos({ label, value, onChange }: {
  label: string; value: number; onChange: (v: number) => void
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold text-warm-400">{label}</span>
      <div className="flex items-center gap-1">
        <span className="text-xs text-warm-400">$</span>
        <input
          type="number" step="any" value={value}
          onChange={e => onChange(Number(e.target.value))}
          className="mt-0.5 w-full border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono"
        />
      </div>
      {/* Eco formateado: es el que hace saltar a la vista un cero de más. */}
      <span className="text-[10px] text-warm-400 font-mono">{fmtPesos(value)}</span>
    </label>
  )
}

function CampoNum({ label, value, onChange, sufijo, step, entero }: {
  label: string; value: number; onChange: (v: number) => void
  sufijo?: string; step?: number | 'any'; entero?: boolean
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold text-warm-400">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number" step={step ?? 'any'} value={value}
          // El backend tipa los días como entero: mandarle 30,5 rebota con un
          // 422 de validación en vez de con un mensaje que se entienda.
          onChange={e => onChange(entero ? Math.round(Number(e.target.value)) : Number(e.target.value))}
          className="mt-0.5 w-full border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono"
        />
        {sufijo && <span className="text-xs text-warm-400 whitespace-nowrap">{sufijo}</span>}
      </div>
    </label>
  )
}

/**
 * Porcentaje adentro, fracción afuera. `step="any"` y no `step="1"` como en
 * Tasas: acá hay valores con decimales que un paso entero destruiría (la ARL es
 * 0,522% y la prima 8,3333%), y redondear a entero cambiaría la nómina.
 */
function CampoPct({ label, value, onChange }: {
  label: string; value: number; onChange: (v: number) => void
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-semibold text-warm-400">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number" step="any" value={aPct(value)}
          onChange={e => onChange(aFraccion(Number(e.target.value)))}
          className="mt-0.5 w-full border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono"
        />
        <span className="text-xs text-warm-400">%</span>
      </div>
    </label>
  )
}
