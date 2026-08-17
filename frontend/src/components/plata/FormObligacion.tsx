import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Building2, Plus, Save } from 'lucide-react'
import api from '../../api/client'
import { conMiles, soloDigitos } from '../../utils/plata'
import { hoyBogota } from '../../utils/fechaLocal'
import { detalleDeError } from './banco'
import { Categoria, CORPORATIVO, Obligacion, Tienda } from './tipos'
import {
  Campo, CLS_INPUT, CLS_INPUT_PLATA, CLS_BOTON_GUARDAR, CLS_BOTON_SUAVE,
  ErrorCampo, teclas,
} from './campos'

/**
 * Cargar o corregir una obligación — LA FILA, no un modal.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * DOS COSAS PASAN ACÁ, Y LA SEGUNDA NO EXISTÍA
 * ═════════════════════════════════════════════════════════════════════════════
 * ALTA: pedido textual, «no quiero desplegar pestañas para agregar una
 * obligación». Antes eran 3 clicks (abrir el cajón, abrir el modal, llenar).
 *
 * EDICIÓN: el backend acepta los diez campos por `PATCH /costos/obligaciones/{id}`
 * (routers/costos.py + schemas/costos.py: `ObligacionUpdate` con `exclude_unset`)
 * desde siempre, y el frontend le mandaba UNO solo, `fecha_vencimiento`. O sea
 * que corregir el monto del arriendo obligaba a ANULAR y volver a cargar — y eso
 * se lleva puestos los pagos ya registrados, que quedan colgando de una
 * obligación anulada. Con el formulario a la vista, editar cuesta lo mismo que
 * cargar.
 *
 * ═════════════════════════════════════════════════════════════════════════════
 * LO QUE NO SE PUEDE PERDER
 * ═════════════════════════════════════════════════════════════════════════════
 *  - EL AVISO DE «VENCE» VACÍO, EN VIVO. Sin fecha la obligación se guarda igual
 *    y cuenta en el resultado del mes, pero NO entra a la agenda ni a la
 *    proyección. Enterarse después —viendo la agenda vacía— es exactamente lo
 *    que hace pensar que el módulo no guardó nada.
 *  - DEVENGO ≠ VENCIMIENTO. El devengo es el mes al que PERTENECE el costo
 *    (manda en el P&L); el vencimiento es cuándo se paga (manda en la agenda).
 *  - CORPORATIVO NO ES «TODAS». El arriendo y la nómina no pertenecen a ninguna
 *    sede: `tienda_id` va en null y esa es una respuesta, no un dato faltante.
 *  - «HOY» SALE DEL RELOJ DE COLOMBIA. La versión vieja de este formulario usaba
 *    `new Date().toLocaleDateString('en-CA')` —el reloj del NAVEGADOR— para
 *    precargar el devengo. Con el admin viajando, o con la tablet mal
 *    configurada, el costo se devengaba en el día equivocado: la misma familia
 *    de error (una fecha que está CERCA de la correcta) que este módulo viene
 *    arrastrando.
 */
export default function FormObligacion({
  categorias, tiendas, editando, onListo, onCancelar,
}: {
  categorias: Categoria[]
  tiendas: Tienda[]
  /** null = alta. Con valor = corrección de esa obligación. */
  editando?: Obligacion | null
  /** Guardó: quien monta recarga. Recibe true si fue un alta (para el aviso). */
  onListo: (fueAlta: boolean) => void
  /** Solo en edición: cerrar sin guardar. */
  onCancelar?: () => void
}) {
  const hoy = hoyBogota()
  const e = editando ?? null

  const [concepto, setConcepto] = useState(e?.concepto ?? '')
  const [categoriaId, setCategoriaId] = useState(
    String(e?.categoria_id ?? categorias[0]?.id ?? ''))
  const [monto, setMonto] = useState(e ? String(Math.round(e.monto)) : '')
  const [devengo, setDevengo] = useState(e?.fecha_devengo ?? hoy)
  const [vence, setVence] = useState(e?.fecha_vencimiento ?? '')
  const [beneficiario, setBeneficiario] = useState(e?.beneficiario ?? '')
  const [sede, setSede] = useState(e ? (e.tienda_id == null ? CORPORATIVO : String(e.tienda_id)) : CORPORATIVO)
  const [nota, setNota] = useState(e?.nota ?? '')
  const [error, setError] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [ultimo, setUltimo] = useState('')

  const refConcepto = useRef<HTMLInputElement>(null)

  // EL DEFAULT SE SINCRONIZA CUANDO LLEGA EL CATÁLOGO. El useState corre en el
  // PRIMER render, cuando la lista todavía está vacía porque el fetch va en un
  // useEffect del padre. Sin esto el estado quedaba en '' para siempre —el
  // componente no remonta— y el resultado era el peor posible: el select se ve
  // CON una opción elegida (React marca la primera cuando el value controlado
  // no matchea ninguna) y el botón «Guardar» gris, sin explicación. El dueño
  // tecleaba todo y no podía guardar. No pisa lo que ya eligió: solo llena el
  // hueco.
  useEffect(() => {
    if (!categoriaId && categorias.length) setCategoriaId(String(categorias[0].id))
  }, [categorias, categoriaId])

  const listo = !!concepto.trim() && Number(monto) > 0 && !!devengo && !!categoriaId

  const guardar = async () => {
    if (!listo) return
    setGuardando(true); setError('')
    const cuerpo = {
      categoria_id: Number(categoriaId),
      concepto: concepto.trim(),
      beneficiario: beneficiario.trim() || null,
      monto: Number(monto),
      fecha_devengo: devengo,
      fecha_vencimiento: vence || null,
      // Corporativo = sin sede: es el caso del arriendo y la nómina.
      tienda_id: sede === CORPORATIVO ? null : Number(sede),
      nota: nota.trim() || null,
    }
    try {
      if (e) {
        await api.patch(`/costos/obligaciones/${e.id}`, cuerpo)
        onListo(false)
      } else {
        await api.post('/costos/obligaciones', cuerpo)
        setUltimo(`${concepto.trim()} · ${conMiles(monto)}`)
        // Se limpia lo que cambia de una carga a la otra y se CONSERVA lo que
        // se repite (categoría, devengo, sede): cargar el arriendo y la luz del
        // mismo mes son dos conceptos y dos montos, no ocho campos de nuevo.
        setConcepto(''); setMonto(''); setBeneficiario(''); setNota('')
        refConcepto.current?.focus()
        onListo(true)
      }
    } catch (err) {
      setError(detalleDeError(err, 'No se pudo guardar. Reintentá.'))
    } finally { setGuardando(false) }
  }

  return (
    <div className={`px-3 py-3 space-y-2 ${e ? 'bg-forest-50 border-y border-forest-100' : 'bg-warm-50 border-b border-warm-100'}`}
      onKeyDown={teclas({ listo, guardar, cancelar: onCancelar })}>
      <div className="flex items-center gap-1.5">
        {e ? <Save size={13} className="text-forest shrink-0" />
           : <Plus size={13} className="text-forest shrink-0" />}
        <p className="text-[11px] font-bold uppercase tracking-wide text-warm-500">
          {e ? `Corregir «${e.concepto}»` : 'Cargar una obligación'}
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 items-end">
        <Campo label="Concepto" ancho="col-span-2">
          <input ref={refConcepto} value={concepto} onChange={ev => setConcepto(ev.target.value)}
            placeholder="Arriendo agosto, energía, nómina quincena…" className={CLS_INPUT} />
        </Campo>
        <Campo label="Categoría">
          <select value={categoriaId} onChange={ev => setCategoriaId(ev.target.value)} className={CLS_INPUT}>
            {categorias.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </select>
        </Campo>
        <Campo label="Monto">
          <input type="text" inputMode="numeric" value={conMiles(monto)}
            onChange={ev => setMonto(soloDigitos(ev.target.value))} placeholder="0"
            aria-label="Monto de la obligación" className={CLS_INPUT_PLATA} />
        </Campo>

        <Campo label="Mes al que pertenece">
          <input type="date" value={devengo} onChange={ev => setDevengo(ev.target.value)}
            className={CLS_INPUT} />
        </Campo>
        <Campo label="Vence (opcional)">
          <input type="date" value={vence} onChange={ev => setVence(ev.target.value)}
            className={CLS_INPUT} />
        </Campo>
        <Campo label="Beneficiario (opcional)">
          <input value={beneficiario} onChange={ev => setBeneficiario(ev.target.value)}
            placeholder="A quién se le paga" className={CLS_INPUT} />
        </Campo>
        <Campo label="Sede">
          <select value={sede} onChange={ev => setSede(ev.target.value)} className={CLS_INPUT}>
            <option value={CORPORATIVO}>Corporativo / todas</option>
            {tiendas.map(t => <option key={t.id} value={t.id}>{t.nombre}</option>)}
          </select>
        </Campo>

        <Campo label="Nota (opcional)" ancho="col-span-2 sm:col-span-3">
          <input value={nota} onChange={ev => setNota(ev.target.value)} className={CLS_INPUT} />
        </Campo>
        <div className="col-span-2 sm:col-span-1 flex gap-2">
          {onCancelar && (
            <button type="button" onClick={onCancelar} className={CLS_BOTON_SUAVE}>Cancelar</button>
          )}
          <button type="button" onClick={guardar} disabled={guardando || !listo}
            className={`${CLS_BOTON_GUARDAR} flex-1`}>
            {guardando ? 'Guardando…' : e ? 'Guardar cambios' : 'Guardar'}
          </button>
        </div>
      </div>

      {/* EN VIVO: sin fecha de pago el costo se guarda y cuenta en el resultado,
          pero no se agenda. Decirlo después es lo que hace pensar que no guardó. */}
      {!vence && (
        <p className="text-[11px] text-gold-700 bg-gold-50 border border-gold-200 rounded-lg px-2.5 py-1.5 flex items-start gap-1.5">
          <AlertCircle size={12} className="mt-0.5 shrink-0" />
          <span>
            Sin «Vence» se guarda igual y cuenta en el resultado del mes, pero <b>no entra a la
            agenda ni a la proyección</b>: queda en «Sin fecha de pago» hasta que le pongas una.
          </span>
        </p>
      )}

      <p className="text-[11px] text-warm-400 leading-snug flex items-start gap-1.5">
        <Building2 size={12} className="mt-0.5 shrink-0" />
        <span>
          «Mes al que pertenece» es el devengo: decide en qué mes pesa el costo en el resultado,
          aunque se pague otro día. Si el gasto no es de una sede puntual (arriendo, nómina),
          dejalo en Corporativo.
        </span>
      </p>

      <ErrorCampo msg={error} />
      {!e && !error && ultimo && (
        <p className="text-[11px] font-semibold text-success-600">Guardada: {ultimo}</p>
      )}
    </div>
  )
}
