-- ============================================================================
-- 01. Índice Diario de Inflación de Canasta (CTEs + Window Functions LAG)
-- Calcula la evolución del costo total de la canasta por supermercado y
-- estrategia de compra partida óptima, con variación día contra día (%).
-- ============================================================================

WITH ordered_basket AS (
    SELECT
        dt,
        store,
        basket_cost_ars,
        items_found,
        total_basket_items,
        coverage_pct,
        LAG(basket_cost_ars) OVER (PARTITION BY store ORDER BY dt) AS prev_cost_ars,
        FIRST_VALUE(basket_cost_ars) OVER (PARTITION BY store ORDER BY dt) AS base_cost_ars
    FROM gold_basket_index
    WHERE basket_cost_ars > 0
)
SELECT
    dt,
    store,
    ROUND(basket_cost_ars, 2) AS basket_cost_ars,
    items_found,
    coverage_pct,
    ROUND(
        CASE
            WHEN prev_cost_ars IS NOT NULL AND prev_cost_ars > 0
            THEN ((basket_cost_ars - prev_cost_ars) / prev_cost_ars) * 100.0
            ELSE 0.0
        END,
        2
    ) AS dod_inflation_pct,
    ROUND(
        CASE
            WHEN base_cost_ars IS NOT NULL AND base_cost_ars > 0
            THEN (basket_cost_ars / base_cost_ars) * 100.0
            ELSE 100.0
        END,
        2
    ) AS cpi_index_base100
FROM ordered_basket
ORDER BY dt DESC, basket_cost_ars ASC;
