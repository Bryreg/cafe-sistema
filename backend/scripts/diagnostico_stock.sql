-- Diagnóstico de stock — correr en la consola de la base de PRODUCCIÓN (Render → PSQL Command).
-- Solo LEE. No modifica nada.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1) ¿Están configurados los umbrales?
--    Si `con_minimo` es cerca de 0, el motor de pedidos está apagado: ningún
--    producto avisa nada hasta que el stock llega exactamente a 0. El esquema
--    crea los tres umbrales en 0 por default (models.py:303-305), así que un
--    producto que nadie configuró a mano nace inerte.
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
  COUNT(*)                                                   AS filas_inventario,
  COUNT(*) FILTER (WHERE COALESCE(stock_minimo,  0) > 0)     AS con_minimo,
  COUNT(*) FILTER (WHERE COALESCE(stock_critico, 0) > 0)     AS con_critico,
  COUNT(*) FILTER (WHERE COALESCE(stock_ideal,   0) > 0)     AS con_ideal
FROM inventario;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2) ¿Hay consumo medido? El motor de pedidos calcula "días que me quedan" como
--    stock / consumo_diario sobre las salidas de los últimos 30 días. Si esto da
--    0 filas, ese eje tampoco opera y todo cae al umbral mínimo de arriba.
-- ─────────────────────────────────────────────────────────────────────────────
SELECT COUNT(DISTINCT producto_id) AS productos_con_salidas_30d
FROM movimientos_inventario
WHERE tipo = 'salida' AND fecha >= NOW() - INTERVAL '30 days';

-- ─────────────────────────────────────────────────────────────────────────────
-- 3) Los negativos, con la causa probable de cada uno.
--    Un negativo NO es un error del sistema: es el sistema diciendo que se
--    consumió más de lo que se registró que entró. La venta descuenta siempre
--    (pos.py:464, allow_negative) porque una venta jamás puede fallar por
--    contabilidad. Lo que falta es el registro de la entrada.
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
  t.nombre                                    AS sede,
  p.nombre                                    AS producto,
  ROUND(i.stock_actual::numeric, 2)           AS stock,
  p.unidad_medida                             AS unidad,
  CASE
    WHEN p.controla_stock
         AND COALESCE(p.precio_venta, 0) = 0
         AND EXISTS (SELECT 1 FROM producto_insumos pi WHERE pi.producto_id = p.id)
      THEN 'PREPARABLE — se vendió sin registrar la preparación'
    WHEN NOT EXISTS (SELECT 1 FROM movimientos_inventario m
                     WHERE m.producto_id = p.id AND m.tienda_id = i.tienda_id
                       AND m.tipo = 'entrada')
      THEN 'NUNCA se registró una entrada de este producto en esta sede'
    WHEN (SELECT MAX(m.fecha) FROM movimientos_inventario m
          WHERE m.producto_id = p.id AND m.tienda_id = i.tienda_id
            AND m.tipo = 'entrada') < NOW() - INTERVAL '60 days'
      THEN 'la última entrada es de hace más de 60 días — factura sin cargar'
    ELSE 'se consumió más de lo que se registró que entró'
  END                                         AS causa_probable,
  (SELECT COUNT(*) FROM producto_insumos pi WHERE pi.insumo_id = p.id)
                                              AS lo_consumen_n_recetas,
  (SELECT MAX(m.fecha) FROM movimientos_inventario m
   WHERE m.producto_id = p.id AND m.tienda_id = i.tienda_id AND m.tipo = 'entrada')
                                              AS ultima_entrada
FROM inventario i
JOIN productos p ON p.id = i.producto_id
JOIN tiendas   t ON t.id = i.tienda_id
WHERE i.stock_actual < 0
ORDER BY i.stock_actual ASC;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4) Sospecha de UNIDAD MAL CARGADA en la receta.
--    Si la receta dice "18" pensando en gramos pero el insumo se mide en kg,
--    cada venta descuenta 18 kg en vez de 18 g: el stock se desploma en horas.
--    Estas filas son las candidatas — receta con cantidad grande sobre un insumo
--    medido en unidad grande.
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
  pr.nombre        AS producto_vendido,
  ins.nombre       AS insumo,
  pi.cantidad      AS dice_la_receta,
  ins.unidad_medida AS unidad_del_insumo
FROM producto_insumos pi
JOIN productos pr  ON pr.id  = pi.producto_id
JOIN productos ins ON ins.id = pi.insumo_id
WHERE (LOWER(ins.unidad_medida) IN ('kg','lt','l','litro','litros') AND pi.cantidad >= 5)
   OR (LOWER(ins.unidad_medida) IN ('gr','g','gramos','ml')         AND pi.cantidad < 0.5)
ORDER BY pi.cantidad DESC;
