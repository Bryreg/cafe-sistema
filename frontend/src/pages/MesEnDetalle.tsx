import { useCallback, useMemo, useState } from 'react'
import { ArrowLeft, Wallet } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import { Dato, ambos, datoListo } from '../api/dato'
import { useDato } from '../api/useDato'
import { FranjaDeConfianza } from '../components/ui'
import {
  RentabilidadData, PorProductoData, PulsoData,
  computeOutliers, computeInsumosSinCosto,
} from '../components/rentabilidad/helpers'
import ResultadoView from '../components/rentabilidad/ResultadoView'
import { Categoria, Tienda } from '../components/plata/tipos'
import { hoyBogota } from '../utils/fechaLocal'

// ─── El mes en detalle ───────────────────────────────────────────────────────
//
// ═════════════════════════════════════════════════════════════════════════════
// POR QUÉ ESTO DEJÓ DE SER UNA PESTAÑA
// ═════════════════════════════════════════════════════════════════════════════
// El margen y el piso son EL MISMO HECHO dicho de dos maneras. «Margen 53%» es
// un número para interpretar; «hoy hay que vender $2.340.000» es algo que se
// puede hacer antes de abrir el local. Teniendo el segundo, el primero no se
// gana un lugar en la pantalla de todos los días.
//
// Dos piezas de acá SÍ se lo ganaron y subieron al piso: el desglose de costos
// (que es el numerador) y el ranking de proveedores (que es de dónde sale el
// denominador). El resto —margen bruto, margen neto, el semáforo, el margen por
// producto, el duelo de sedes, la escalera del P&L, el pulso de comportamiento—
// vive acá, a un link del pie.
//
// ── NADA SE BORRÓ ─────────────────────────────────────────────────────────
// `ResultadoView` se monta ENTERO y sin tocar. Los caminos que solo existían
// adentro suyo siguen existiendo, en el mismo componente y con el mismo código:
// adoptar un egreso suelto (`/costos/egresos/{id}/adoptar`), borrar un alias
// aprendido, correr el backfill de costos, el simulador de precios y el menú.
// Mover una pantalla no puede ser una forma silenciosa de sacarle botones.

function mesActualBogota(): { desde: string; hasta: string } {
  const s = hoyBogota()
  const [y, m] = s.split('-')
  return { desde: `${y}-${m}-01`, hasta: s }
}

export default function MesEnDetalle() {
  const navigate = useNavigate()
  const [refresco, setRefresco] = useState(0)
  const refrescarTodo = useCallback(() => setRefresco(n => n + 1), [])

  const pulso = useDato<PulsoData>(
    () => api.get('/rentabilidad/pulso'), 'el pulso del mes',
    'No se pudo leer el pulso del mes.')

  const prodData = useDato<PorProductoData>(
    () => api.get('/rentabilidad/por-producto'), 'los productos',
    'No se pudieron leer los productos.', [refresco])

  const plMes = useDato<RentabilidadData>(
    () => {
      const { desde, hasta } = mesActualBogota()
      return api.get('/rentabilidad/', { params: { desde, hasta } })
    },
    'el resultado del mes', 'No se pudo leer el resultado del mes.', [refresco])

  const categorias = useDato<Categoria[]>(
    () => api.get('/costos/categorias'), 'las categorías de gasto',
    'No se pudieron leer las categorías.')

  const tiendas = useDato<Tienda[]>(
    () => api.get('/auth/tiendas'), 'las sedes', 'No se pudieron leer las sedes.')

  const fuentes = useMemo(
    () => [pulso, prodData, plMes, categorias, tiendas],
    [pulso, prodData, plMes, categorias, tiendas])

  /**
   * Lo que le falta a los datos para que el margen sea real.
   *
   * Los DOS tienen que estar. El viejo `plMes && !plMes.resumen...` cortaba en
   * el `&&` y sumaba 0 cuando el P&L no volvía: un resultado del mes muerto
   * aportaba cero pendientes, exactamente igual que un mes con todo cargado, y
   * «datos sanos» podía afirmarse con el arriendo entero faltando.
   */
  const pendientesDatos: Dato<number> = useMemo(() => {
    const base = ambos(prodData.dato, plMes.dato)
    if (base.estado !== 'listo') return base
    const [prod, pl] = base.valor
    const out = computeOutliers(prod.productos)
    if (out.estado !== 'listo') return out
    const ins = computeInsumosSinCosto(prod.productos)
    if (ins.estado !== 'listo') return ins
    // SIN `|| 0`: `facturas_pendientes_de_costos` es `number` en el contrato, así
    // que el fallback no se podía disparar — pero escribía a mano el idioma que
    // este módulo vino a matar, y sobre el peor renglón posible. Este número es
    // el que decide si río abajo se puede afirmar «datos sanos»: un campo que
    // faltara y cayera a cero restaría pendientes de una cuenta que después se
    // publica como un verde.
    return datoListo(
      out.valor.length + ins.valor.length
      + prod.facturas_pendientes_de_costos
      + (pl.resumen.tiene_costos_fijos ? 0 : 1))
  }, [prodData.dato, plMes.dato])

  const volver = useCallback(() => navigate('/plata'), [navigate])

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <button onClick={volver}
          className="flex items-center gap-1 min-h-[46px] px-2 -ml-2 rounded-xl text-sm font-bold
                     text-forest hover:bg-warm-100">
          <ArrowLeft size={16} /> El piso
        </button>
        <Wallet size={18} className="text-forest" />
        <h1 className="text-lg font-bold text-warm-700">El mes en detalle</h1>
      </div>

      <p className="text-[11px] text-warm-500 px-1 leading-relaxed">
        Esto es para <b>interpretar</b> el mes. Lo que se decide todos los días —cuánto hay que
        vender hoy, qué hay que pagar, si se llega a fin de mes— está en{' '}
        <button onClick={volver} className="font-bold text-forest underline decoration-dotted">
          El piso
        </button>.
      </p>

      <FranjaDeConfianza fuentes={fuentes} />

      <ResultadoView
        pulso={pulso} prodData={prodData} plMes={plMes}
        categorias={categorias} tiendas={tiendas}
        pendientesDatos={pendientesDatos}
        refreshKey={refresco}
        onRefrescarProductos={prodData.recargar}
        onIrALaPlata={volver}
        onCambio={refrescarTodo} />
    </div>
  )
}
