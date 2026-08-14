import { useEffect, useState } from 'react'
import api from '../../api/client'
import { Check, Loader2, Save, Wand2 } from 'lucide-react'
import { Aviso } from './SemanaGrid'
import { fmtPesos, type Contrato } from './tipos'

/**
 * Sueldo pactado por barista. Es el insumo de TODA la nómina del mes: de acá
 * sale el valor de la hora ordinaria, y de ahí el devengado, el auxilio, las
 * deducciones, el neto y el costo para el negocio que muestra el Resumen.
 *
 * El sueldo se puede escribir de dos maneras y NO son equivalentes:
 *
 *   - En PESOS: el número queda congelado. Cuando en enero sube el mínimo,
 *     alguien tiene que acordarse de venir a cambiarlo. Nadie se acuerda.
 *   - En SMMLV: se guarda «1 mínimo» y cada mes se resuelve contra el mínimo
 *     VIGENTE de ese mes. Sube solo en enero, y recalcular un mes viejo sigue
 *     dando el mínimo de ese año, no el de hoy.
 *
 * Por eso el botón de arriba existe: la cafetería paga mínimos, y dejarlas a
 * todas en SMMLV es lo que hace que el sistema no quede desactualizado solo.
 */

interface Props { tiendaId: number }

/** El sueldo de este contrato está atado al mínimo, no a un número tecleado. */
// «Está en UN mínimo», no «tiene algún múltiplo cargado». Con lo segundo, una
// supervisora guardada en 1,5 SMMLV contaba como ya ajustada: el confirm decía
// «todas ya están en 1 SMMLV, ¿aplicar igual?» —falso— y el dueño aceptaba
// creyendo que no pasaba nada. El backend ahora la saltea y la devuelve en
// `omitidas`, pero la cuenta de acá tenía que dejar de mentir igual.
const enMinimos = (c: Contrato) => (c.salario_en_smmlv ?? 0) === 1
const conOtroMultiplo = (c: Contrato) =>
  (c.salario_en_smmlv ?? 0) > 0 && (c.salario_en_smmlv ?? 0) !== 1
// DOS PREGUNTAS DISTINTAS Y NO SE PUEDEN MEZCLAR. `enMinimos` es «está en UN
// mínimo» y solo sirve para la cuenta del botón masivo. Todo lo demás —qué
// input dibujar, quién tiene sueldo, quién está en pesos— pregunta si el
// sueldo está ATADO AL MÍNIMO, valga 1 o 1,5. Usando `enMinimos` para las dos,
// la supervisora de 1,5 SMMLV se dibujaba en modo «Pesos» con el input en $0 y
// la tarjeta la contaba como «sin sueldo cargado», mientras el Resumen la
// liquidaba a $2,6 M: dos pantallas diciendo cosas opuestas de la misma persona.
const atadoAlMinimo = (c: Contrato) => (c.salario_en_smmlv ?? 0) > 0

/**
 * Una barista que el ajuste masivo NO tocó. Hoy la única razón es el contrato
 * inactivo, pero la razón viaja como texto DEL BACKEND: es él quien decide a
 * quién saltea, y reescribir el motivo acá garantiza que el día que agregue un
 * caso la pantalla explique el viejo.
 */
interface Omitida { usuario_id: number; nombre: string; razon: string }

/**
 * Respuesta de `POST /horarios/contratos/ajustar-al-minimo`.
 *
 * Se tipa acá y no en tipos.ts porque es la respuesta de UNA acción de esta
 * pantalla, no una entidad del módulo. `omitidas` venía en el payload desde el
 * primer día y esta pantalla lo tiraba: por eso el confirm prometía un número
 * (todas las filas) y el aviso posterior mostraba otro (las que de verdad
 * cambiaron), sin que nada explicara la diferencia.
 */
interface AjusteAlMinimo {
  ajustadas: number
  ya_estaban: number
  omitidas: Omitida[]
  /** El efecto que no se ve: atar a alguien al SMMLV hace que sus meses YA
   *  CERRADOS dejen de liquidarse con el número en pesos que tenían y pasen a
   *  usar el mínimo de su año. Para quien ya ganaba el mínimo no cambia nada;
   *  para el resto sí, y el margen de esos meses se mueve. */
  reinterpreta_meses_cerrados: boolean
}

export default function SueldosPanel({ tiendaId }: Props) {
  const [items, setItems] = useState<Contrato[]>([])
  const [loading, setLoading] = useState(true)
  const [guardando, setGuardando] = useState<number | null>(null)
  const [guardado, setGuardado] = useState<number | null>(null)
  const [ajustando, setAjustando] = useState(false)
  const [aviso, setAviso] = useState<string | null>(null)
  const [omitidas, setOmitidas] = useState<Omitida[]>([])
  const [reinterpreta, setReinterpreta] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const cargar = () =>
    api.get<Contrato[]>('/horarios/contratos', { params: { tienda_id: tiendaId } })
      .then(r => r.data)

  useEffect(() => {
    setLoading(true)
    cargar()
      .then(setItems)
      .catch(() => setError('No se pudieron cargar los sueldos.'))
      .finally(() => setLoading(false))
  }, [tiendaId])

  const patch = (usuarioId: number, cambios: Partial<Contrato>) => {
    setItems(prev => prev.map(c => (c.usuario_id === usuarioId ? { ...c, ...cambios } : c)))
    setGuardado(null)
  }

  const guardar = async (c: Contrato) => {
    setGuardando(c.usuario_id); setError(null); setAviso(null); setOmitidas([])
    try {
      await api.put(`/horarios/contratos/${c.usuario_id}`, {
        salario_mensual: c.salario_mensual,
        salario_en_smmlv: c.salario_en_smmlv,
        horas_semana_pactadas: c.horas_semana_pactadas,
        fecha_ingreso: c.fecha_ingreso,
        activo: c.activo,
        nota: c.nota,
      })
      setGuardado(c.usuario_id)
      // Se recarga en vez de confiar en el estado local: el sueldo resuelto lo
      // calcula el backend contra el mínimo vigente, y adivinarlo acá sería
      // justamente el tipo de número inventado que esta pantalla no puede tener.
      setItems(await cargar())
    } catch { setError('No se pudo guardar.') }
    finally { setGuardando(null) }
  }

  /**
   * Deja a TODAS LAS ACTIVAS en 1 SMMLV de un golpe.
   *
   * Cuántas cambiaron se cuenta comparando la lista de antes contra la que
   * devuelve el backend después, no leyendo un contador de la respuesta: así el
   * número que se muestra es lo que efectivamente quedó guardado.
   *
   * EL CONFIRM CUENTA LO MISMO QUE EL ENDPOINT VA A TOCAR. El backend saltea al
   * contrato inactivo —para no reescribirle el sueldo a quien ya no trabaja acá
   * y cambiarle los meses viejos— y lo devuelve en `omitidas`. Contando todas
   * las filas, el confirm prometía más baristas de las que se iban a ajustar y
   * el aviso posterior, que sí cuenta lo guardado, lo desmentía dos segundos
   * después: dos números distintos para la misma acción, sin explicación.
   */
  const ajustarTodasAlMinimo = async () => {
    // `activo` es el mismo criterio que usa el endpoint: viene en true cuando
    // ni siquiera hay contrato todavía —esa sí se ajusta, el backend le crea
    // uno— y en false solo cuando hay un contrato apagado, que es justo el que
    // saltea. Los dos lados cuentan lo mismo porque leen el mismo campo.
    const activas = items.filter(c => c.activo)
    // Quien tiene un múltiplo distinto de 1 NO entra: el backend la saltea
    // porque bajarla sería recortarle el sueldo, no ajustarlo.
    const protegidas = activas.filter(conOtroMultiplo)
    const faltantes = activas.filter(c => !enMinimos(c) && !conOtroMultiplo(c)).length
    const inactivas = items.length - activas.length
    const nota = (inactivas > 0
      ? ` No se toca a ${inactivas} con el contrato inactivo: su sueldo queda como está.`
      : '')
      + (protegidas.length > 0
        ? ` Tampoco se toca a ${protegidas.map(c => c.nombre).join(', ')}: `
          + 'gana(n) por encima del mínimo a propósito.'
        : '')
    if (!confirm(
      (faltantes === 0
        ? 'Todas las activas ya están en 1 SMMLV. ¿Aplicar igual?'
        : `Esto deja a ${faltantes} barista(s) activa(s) en 1 SMMLV. Los pesos que tengan ` +
          'escritos quedan guardados pero dejan de usarse para liquidar. ¿Seguimos?') + nota
    )) return

    setAjustando(true); setError(null); setAviso(null); setGuardado(null); setOmitidas([])
    try {
      const { data } = await api.post<AjusteAlMinimo>(
        '/horarios/contratos/ajustar-al-minimo', null,
        { params: { tienda_id: tiendaId } })
      const antes = new Map(items.map(c => [c.usuario_id, c.salario_en_smmlv ?? null]))
      const despues = await cargar()
      setItems(despues)
      const cambiadas = despues.filter(
        c => (antes.get(c.usuario_id) ?? null) !== (c.salario_en_smmlv ?? null)).length
      setAviso(cambiadas === 0
        ? 'No cambió ninguna: ya estaban todas en 1 SMMLV.'
        : `${cambiadas} barista(s) quedaron en 1 SMMLV.`)
      // Quiénes quedaron afuera y por qué, con el nombre a la vista: «cambiaron
      // 3» sin esta lista deja al dueño creyendo que la cuarta también se
      // ajustó y que el sistema le contó mal.
      setOmitidas(data.omitidas ?? [])
      setReinterpreta(Boolean(data.reinterpreta_meses_cerrados))
    } catch { setError('No se pudo ajustar al salario mínimo.') }
    finally { setAjustando(false) }
  }

  if (loading) {
    return <p className="text-sm text-warm-400 py-10 text-center animate-pulse">Cargando…</p>
  }

  // El mínimo vigente para poder mostrar a cuántos pesos equivale «1 SMMLV».
  // Si el backend no lo manda, se intenta despejarlo de alguna que YA esté en
  // mínimos; y si tampoco, se queda en 0 y la pantalla simplemente no dice el
  // peso. Nunca se inventa un mínimo para poder escribir una cifra.
  const desdeCampo = items.find(c => (c.smmlv_vigente || 0) > 0)?.smmlv_vigente || 0
  const despejado = items.find(c => atadoAlMinimo(c) && c.salario_resuelto > 0)
  const smmlv = desdeCampo || (despejado
    ? despejado.salario_resuelto / (despejado.salario_en_smmlv as number)
    : 0)

  // Solo las ACTIVAS, igual que el confirm del botón que está al lado. Contando
  // todas, esta línea decía «hay 5» y el confirm «esto deja a 4»: dos números
  // para la misma cosa a diez píxeles de distancia.
  // Por MONTO y no por forma: `enMinimos` mira solo `salario_en_smmlv`, así que
  // una barista sin NADA escrito caía del lado «pesos fijos». En una sede recién
  // cargada la tarjeta afirmaba que las 5 tenían sueldo en pesos cuando ninguna
  // tenía sueldo, y contradecía al aviso de «sin sueldo cargado» del Resumen.
  const enPesosFijos = items.filter(
    c => c.activo && !atadoAlMinimo(c) && c.salario_mensual > 0).length
  const sinSueldo = items.filter(
    c => c.activo && !atadoAlMinimo(c) && c.salario_mensual <= 0).length

  return (
    <div className="space-y-3">
      {error && <Aviso tono="error">{error}</Aviso>}
      {aviso && <Aviso tono="ok">{aviso}</Aviso>}
      {/* Va pegado al aviso de arriba y no adentro: son dos hechos distintos
          —cuántas cambiaron y a cuántas ni se las intentó— y mezclarlos en una
          sola frase es lo que hacía que el número no cerrara. */}
      {/* El efecto retroactivo, que es el que nadie ve venir: el múltiplo se
          resuelve contra el mínimo de la FECHA LIQUIDADA, así que un mes ya
          cerrado deja de usar el número en pesos con el que se liquidó. Solo
          se avisa cuando de verdad pasa —alguien tenía otro número— porque un
          cartel que sale siempre se deja de leer. */}
      {reinterpreta && (
        <Aviso tono="info">
          <span className="block">
            Alguna quedó atada al mínimo viniendo de un sueldo en pesos distinto.{' '}
            <b>Sus meses ya cerrados se recalculan con el mínimo del año que
            correspondía</b>, no con el número que tenían escrito, así que el costo y
            el margen de esos meses se mueven. Si eso no es lo que querés, escribile
            el sueldo en pesos en su fila.
          </span>
        </Aviso>
      )}
      {omitidas.length > 0 && (
        <Aviso tono="info">
          <span className="block font-semibold">
            {omitidas.length} barista(s) quedaron sin ajustar
          </span>
          {omitidas.map(o => (
            <span key={o.usuario_id} className="block">
              {o.nombre} — {o.razon}
            </span>
          ))}
          <span className="block mt-1">
            El ajuste no las toca a propósito: reescribirle el sueldo a un contrato apagado
            le cambiaría los meses que ya se liquidaron.
          </span>
        </Aviso>
      )}

      <div className="bg-white rounded-2xl border border-warm-200 p-4">
        <p className="text-sm font-bold text-warm-700">Para qué sirve esto</p>
        <p className="text-xs text-warm-500 mt-1">
          El sueldo mensual se divide por el «divisor hora/mes» de la tasa vigente para sacar
          el valor de la hora ordinaria, y sobre ese valor se aplican los recargos: eso es el
          DEVENGADO del mes. Con ese devengado, el Resumen calcula el auxilio de transporte,
          salud y pensión, los aportes del empleador y las prestaciones, y muestra el neto de
          ella y el costo para el negocio. Sigue siendo un ESTIMADO: no incluye retención en
          la fuente, embargos, libranzas ni el redondeo de aportes de PILA.
        </p>
      </div>

      {/* ── Acción en bloque ── */}
      <div className="bg-white rounded-2xl border border-warm-200 p-4 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[16rem]">
          <p className="text-sm font-bold text-warm-700">Sueldos atados al mínimo</p>
          <p className="text-xs text-warm-500 mt-0.5">
            {smmlv > 0
              ? <>Hoy 1 SMMLV son <b className="font-mono text-warm-700">{fmtPesos(smmlv)}</b>. </>
              : null}
            Un sueldo guardado «en SMMLV» se resuelve cada mes contra el mínimo vigente de ese
            mes: en enero sube solo y los meses viejos se siguen recalculando con el mínimo del
            año que correspondía.
            {enPesosFijos > 0 && (
              <> Ahora mismo hay <b>{enPesosFijos}</b> activa(s) con el sueldo escrito en
              pesos fijos.</>
            )}
            {sinSueldo > 0 && (
              <> Y <b>{sinSueldo}</b> sin ningún sueldo cargado: sus horas se cuentan pero
              valen $0, así que el costo del mes queda corto.</>
            )}
          </p>
        </div>
        <button
          onClick={ajustarTodasAlMinimo}
          disabled={ajustando}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-forest text-white hover:bg-forest/90 disabled:opacity-40"
        >
          {ajustando ? <Loader2 size={13} className="animate-spin" /> : <Wand2 size={13} />}
          Ajustar todas al salario mínimo
        </button>
      </div>

      <div className="bg-white rounded-2xl border border-warm-200 divide-y divide-warm-100">
        {items.map(c => {
          const smmlvMode = atadoAlMinimo(c)
          return (
            <div key={c.usuario_id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <span className="text-sm font-semibold text-warm-700 min-w-[8rem]">{c.nombre}</span>

              {/* Cómo está escrito el sueldo. No es un detalle de formato: define
                  si el número se queda quieto o se mueve con el mínimo. */}
              <div className="flex rounded-lg border border-warm-200 overflow-hidden">
                <button
                  onClick={() => patch(c.usuario_id, { salario_en_smmlv: null })}
                  className={`px-2.5 py-1 text-[11px] font-semibold ${
                    smmlvMode ? 'text-warm-500 hover:bg-warm-50' : 'bg-forest text-white'}`}
                >
                  Pesos
                </button>
                <button
                  onClick={() => patch(c.usuario_id, { salario_en_smmlv: c.salario_en_smmlv || 1 })}
                  className={`px-2.5 py-1 text-[11px] font-semibold border-l border-warm-200 ${
                    smmlvMode ? 'bg-forest text-white' : 'text-warm-500 hover:bg-warm-50'}`}
                >
                  SMMLV
                </button>
              </div>

              {smmlvMode ? (
                <label className="flex items-center gap-1.5">
                  <span className="text-[11px] font-semibold text-warm-400">Salarios mínimos</span>
                  <input
                    type="number" step="0.5" min="0"
                    value={c.salario_en_smmlv ?? 1}
                    onChange={e => patch(c.usuario_id, {
                      salario_en_smmlv: Number(e.target.value) || 0,
                    })}
                    className="w-16 border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono text-right"
                  />
                  <span className="text-[11px] text-warm-500 font-mono">
                    {smmlv > 0
                      // Es la misma cuenta que hace el backend (múltiplo × mínimo
                      // vigente), así que el número de acá y el que se liquida no
                      // pueden separarse. Sin mínimo conocido no se escribe nada.
                      ? `× SMMLV = ${fmtPesos((c.salario_en_smmlv || 0) * smmlv)}`
                      : '× SMMLV'}
                  </span>
                </label>
              ) : (
                <label className="flex items-center gap-1.5">
                  <span className="text-[11px] font-semibold text-warm-400">Sueldo mensual</span>
                  <input
                    type="text" inputMode="numeric"
                    value={(c.salario_mensual || 0).toLocaleString('es-CO')}
                    onChange={e => patch(c.usuario_id, {
                      salario_mensual: Number(e.target.value.replace(/[^\d]/g, '')) || 0,
                    })}
                    className="w-32 border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono text-right"
                  />
                </label>
              )}

              <label className="flex items-center gap-1.5">
                <span className="text-[11px] font-semibold text-warm-400">Horas/semana pactadas</span>
                <input
                  type="number" step="any"
                  value={c.horas_semana_pactadas ?? ''}
                  placeholder="máx. de la tasa"
                  onChange={e => patch(c.usuario_id, {
                    horas_semana_pactadas: e.target.value === '' ? null : Number(e.target.value),
                  })}
                  className="w-20 border border-warm-200 rounded-lg px-2 py-1 text-sm font-mono text-right"
                />
              </label>

              <div className="flex-1" />
              <button
                onClick={() => guardar(c)}
                disabled={guardando === c.usuario_id}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-forest text-white hover:bg-forest/90 disabled:opacity-40"
              >
                {guardando === c.usuario_id
                  ? <Loader2 size={12} className="animate-spin" />
                  : <Save size={12} />}
                Guardar
              </button>
              {guardado === c.usuario_id && (
                <span className="flex items-center gap-1 text-xs text-forest-700">
                  <Check size={12} /> ok
                </span>
              )}
            </div>
          )
        })}
      </div>

      <p className="text-[11px] text-warm-400">
        El valor de la hora ordinaria de cada barista sale del divisor hora/mes de la tasa,
        que podés ver y editar en «Tasas», y aparece calculado por persona en el Resumen del
        mes. Acá no se muestra para que no haya dos versiones del mismo número.
      </p>
    </div>
  )
}
