"""Módulo de análisis comparativo de precios cross-store (Gold Layer).

Identifica el mismo producto en diferentes supermercados (vía EAN o matching),
calcula brechas de precio (% ahorro), detecta la tienda más barata y resume
canastas de compra comparativas.
"""

from __future__ import annotations

import polars as pl

from ..filters import (
    MAX_CROSS_STORE_SAVINGS_PCT,
    MAX_CROSS_STORE_SPREAD_RATIO,
    MAX_PRICE_SANITY_ARS,
    MAX_VERIFIED_DISCOUNT_PCT,
    MIN_PRICE_SANITY_ARS,
)


def match_products_cross_store(df: pl.DataFrame) -> pl.DataFrame:
    """Compara precios entre supermercados para productos con EAN idéntico.

    Retorna sólo aquellos productos que existen en al menos 2 tiendas distintas,
    calculando la brecha porcentual de precio, la tienda más económica y la más cara.
    """
    if df.is_empty():
        return pl.DataFrame()

    # Filtramos a productos que tengan EAN válido, estén en stock y en la banda de precios
    avail_filter = (
        pl.col("available").fill_null(False)
        if "available" in df.columns
        else pl.lit(True)
    )

    with_ean = df.filter(
        pl.col("ean_clean").is_not_null()
        & (pl.col("ean_clean") != "")
        & (pl.col("price") >= MIN_PRICE_SANITY_ARS)
        & (pl.col("price") <= MAX_PRICE_SANITY_ARS)
        & avail_filter
    )

    if with_ean.is_empty():
        return pl.DataFrame()

    # Agrupamos por EAN para calcular agregaciones
    aggregated = (
        with_ean.group_by("ean_clean")
        .agg([
            pl.col("name").first().alias("product_name"),
            pl.col("brand_clean").first().alias("brand"),
            pl.col("store").n_unique().alias("stores_count"),
            pl.col("store").alias("stores_list"),
            pl.col("price").min().alias("min_price"),
            pl.col("price").max().alias("max_price"),
            pl.col("price").mean().round(2).alias("avg_price"),
            # Tienda más barata
            pl.col("store")
            .sort_by("price")
            .first()
            .alias("cheapest_store"),
            # Tienda más cara
            pl.col("store")
            .sort_by("price", descending=True)
            .first()
            .alias("most_expensive_store"),
        ])
        # Solo productos que existen en 2 o más tiendas
        .filter(pl.col("stores_count") >= 2)
    )

    if aggregated.is_empty():
        return pl.DataFrame()

    # Cálculo del porcentaje de brecha / ahorro
    # Regla 4: Descartar ratios superiores a 4x (ahorro > 300%) para evitar sachets vs packs de 24
    result = (
        aggregated.with_columns([
            (
                ((pl.col("max_price") - pl.col("min_price")) / pl.col("min_price"))
                * 100.0
            )
            .round(1)
            .alias("savings_spread_pct")
        ])
        .filter(
            (pl.col("max_price") / pl.col("min_price") <= MAX_CROSS_STORE_SPREAD_RATIO)
            & (pl.col("savings_spread_pct") <= MAX_CROSS_STORE_SAVINGS_PCT)
        )
        .sort("savings_spread_pct", descending=True)
    )

    return result


def get_top_discounts(
    df: pl.DataFrame, min_discount_pct: float = 10.0, limit: int = 50
) -> pl.DataFrame:
    """Filtra y ordena los productos con mejores descuentos del mercado."""
    if df.is_empty():
        return pl.DataFrame()

    discount_col = "verified_discount_pct" if "verified_discount_pct" in df.columns else "discount_pct"

    return (
        df.filter(
            pl.col(discount_col).is_not_null()
            & (pl.col(discount_col) >= min_discount_pct)
            & (pl.col(discount_col) <= MAX_VERIFIED_DISCOUNT_PCT)
            & pl.col("available")
        )
        .sort(discount_col, descending=True)
        .limit(limit)
        .select([
            "store",
            "name",
            "brand",
            "price",
            "list_price",
            discount_col,
            "product_url",
        ])
    )


def compute_store_competitiveness(df: pl.DataFrame) -> pl.DataFrame:
    """Calcula un índice de competitividad por tienda:

    - Total de productos listados
    - Precio promedio de catálogo
    - Cantidad de veces que fue la opción más barata en productos compartidos
    """
    if df.is_empty():
        return pl.DataFrame()

    matched = match_products_cross_store(df)
    cheapest_counts = (
        matched.group_by("cheapest_store")
        .len()
        .rename({"len": "times_cheapest", "cheapest_store": "store"})
    ) if not matched.is_empty() else pl.DataFrame(schema={"store": pl.Utf8, "times_cheapest": pl.UInt32})

    store_stats = (
        df.group_by("store")
        .agg([
            pl.len().alias("total_catalog_products"),
            pl.col("price").mean().round(2).alias("avg_catalog_price"),
            pl.col("available").sum().alias("in_stock_products"),
        ])
        .join(cheapest_counts, on="store", how="left")
        .with_columns(pl.col("times_cheapest").fill_null(0))
        .sort("times_cheapest", descending=True)
    )

    return store_stats
