-- ============================================================================
-- 02. Competitividad e Índice Relativo de Precios por Supermercado
-- Combina cobertura de catálogo, tasa de victorias en productos compartidos
-- (win-rate por EAN) y el Índice Relativo vs la mediana del mercado (100 = par).
-- ============================================================================

WITH shared_eans AS (
    SELECT
        ean_clean,
        MEDIAN(price) AS market_median_price,
        MIN(price) AS market_min_price,
        COUNT(DISTINCT store) AS store_count
    FROM active_silver_products
    WHERE ean_clean IS NOT NULL
      AND ean_clean != ''
      AND available = TRUE
    GROUP BY ean_clean
    HAVING COUNT(DISTINCT store) >= 2
),
store_vs_market AS (
    SELECT
        p.store,
        p.ean_clean,
        p.price,
        (p.price / s.market_median_price) * 100.0 AS price_index_vs_median,
        CASE WHEN p.price = s.market_min_price THEN 1 ELSE 0 END AS is_cheapest
    FROM active_silver_products p
    INNER JOIN shared_eans s ON p.ean_clean = s.ean_clean
    WHERE p.available = TRUE
),
catalog_stats AS (
    SELECT
        store,
        COUNT(*) AS catalog_products,
        ROUND(AVG(price), 2) AS avg_price_ars,
        ROUND(MEDIAN(price), 2) AS median_price_ars,
        ROUND(AVG(COALESCE(verified_discount_pct, 0)), 2) AS avg_discount_pct,
        SUM(CASE WHEN verified_discount_pct >= 15 THEN 1 ELSE 0 END) AS deals_15pct_plus
    FROM active_silver_products
    WHERE available = TRUE
    GROUP BY store
)
SELECT
    c.store,
    c.catalog_products,
    c.median_price_ars,
    COALESCE(COUNT(m.ean_clean), 0) AS comparable_eans,
    COALESCE(SUM(m.is_cheapest), 0) AS times_cheapest,
    ROUND(COALESCE(AVG(m.is_cheapest) * 100.0, 0.0), 1) AS win_rate_pct,
    ROUND(COALESCE(AVG(m.price_index_vs_median), 100.0), 2) AS price_index_vs_median,
    c.deals_15pct_plus
FROM catalog_stats c
LEFT JOIN store_vs_market m ON c.store = m.store
GROUP BY
    c.store,
    c.catalog_products,
    c.median_price_ars,
    c.deals_15pct_plus
ORDER BY price_index_vs_median ASC, win_rate_pct DESC;
