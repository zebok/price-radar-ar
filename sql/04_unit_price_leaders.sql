-- ============================================================================
-- 04. Ranking Anti-Reduflación: Mejores Precios Unitarios ($/kg y $/L)
-- Utiliza ROW_NUMBER() OVER (PARTITION BY ...) para encontrar las 3 opciones
-- más económicas por kilo o litro en cada macro-categoría.
-- ============================================================================

WITH ranked_unit_prices AS (
    SELECT
        macro_category,
        unit_measure,
        store,
        name,
        brand_clean AS brand,
        ROUND(price, 2) AS package_price_ars,
        ROUND(unit_price_std, 2) AS unit_price_ars,
        product_url,
        ROW_NUMBER() OVER (
            PARTITION BY macro_category, unit_measure
            ORDER BY unit_price_std ASC, price ASC
        ) AS rn
    FROM active_silver_products
    WHERE available = TRUE
      AND unit_measure IN ('$/kg', '$/L')
      AND unit_price_std IS NOT NULL
      AND unit_price_std >= 100
      AND macro_category IS NOT NULL
      AND macro_category != 'otros'
)
SELECT
    macro_category,
    unit_measure,
    rn AS rank_in_category,
    store,
    name,
    brand,
    package_price_ars,
    unit_price_ars
FROM ranked_unit_prices
WHERE rn <= 3
ORDER BY macro_category ASC, unit_measure ASC, rn ASC;
