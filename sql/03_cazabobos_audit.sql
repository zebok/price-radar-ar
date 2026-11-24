-- ============================================================================
-- 03. Auditoría de Promociones "Caza-bobos" (Falsos Descuentos Cross-Store)
-- Detecta productos anunciados con descuento (>= 10% off) cuyo precio final
-- promocional sigue siendo >5% MÁS CARO que el precio regular en otro súper
-- para el mismo código de barras EAN.
-- ============================================================================

WITH cheapest_regular AS (
    SELECT
        ean_clean,
        ARG_MIN(store, price) AS rival_store,
        MIN(price) AS rival_price,
        ARG_MIN(product_url, price) AS rival_url
    FROM active_silver_products
    WHERE ean_clean IS NOT NULL
      AND ean_clean != ''
      AND available = TRUE
    GROUP BY ean_clean
    HAVING COUNT(DISTINCT store) >= 2
)
SELECT
    p.store AS promo_store,
    p.name AS product_name,
    p.ean_clean,
    ROUND(p.list_price, 2) AS advertised_list_price,
    ROUND(p.price, 2) AS promo_price,
    ROUND(p.verified_discount_pct, 1) AS advertised_discount_pct,
    r.rival_store,
    ROUND(r.rival_price, 2) AS rival_price,
    ROUND(((p.price - r.rival_price) / r.rival_price) * 100.0, 1) AS overprice_vs_rival_pct,
    p.product_url AS promo_url,
    r.rival_url
FROM active_silver_products p
INNER JOIN cheapest_regular r
    ON p.ean_clean = r.ean_clean
   AND p.store != r.rival_store
WHERE p.verified_discount_pct >= 10.0
  AND p.price > r.rival_price * 1.05
  AND (p.price / r.rival_price) <= 4.0
ORDER BY overprice_vs_rival_pct DESC
LIMIT 25;
