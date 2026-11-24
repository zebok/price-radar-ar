"""Capa Gold Analítica (Marts BI listos para DuckDB, Web App y consumo analítico).

Construye 4 tablas Gold particionadas por fecha (`gold/dt=YYYY-MM-DD/*.parquet`):
1. `cross_store_comparison`: comparación por EAN compartido entre ≥2 cadenas.
2. `store_competitiveness`: win-rate, cobertura, precio medio/mediano y descuento verificado por cadena.
3. `daily_basket_index`: valuación histórica de la canasta básica por tienda + estrategia partida (IPC propio).
4. `price_changes`: variaciones de precios (subas y bajas) entre snapshots consecutivos / semanales.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from ..baskets import get_basket_items
from ..storage.parquet import get_current_date_partition, save_gold_dataframe
from .cross_store import match_products_cross_store


def build_store_competitiveness_mart(active_silver_df: pl.DataFrame) -> pl.DataFrame:
    """Calcula métricas enriquecidas de competitividad por supermercado."""
    if active_silver_df.is_empty():
        return pl.DataFrame()

    matched = match_products_cross_store(active_silver_df)
    total_matched = len(matched)

    if not matched.is_empty():
        cheapest_counts = (
            matched.group_by("cheapest_store")
            .len()
            .rename({"len": "times_cheapest", "cheapest_store": "store"})
        )
    else:
        cheapest_counts = pl.DataFrame(
            schema={"store": pl.Utf8, "times_cheapest": pl.UInt32}
        )

    disc_col = (
        "verified_discount_pct"
        if "verified_discount_pct" in active_silver_df.columns
        else "discount_pct"
    )

    ean_expr = (
        (pl.col("ean_clean").is_not_null() & (pl.col("ean_clean") != "")).mean() * 100.0
        if "ean_clean" in active_silver_df.columns
        else pl.lit(0.0)
    )

    stats = (
        active_silver_df.group_by("store")
        .agg([
            pl.len().alias("total_catalog_products"),
            pl.col("available").sum().alias("in_stock_products"),
            pl.col("price").mean().round(2).alias("avg_catalog_price"),
            pl.col("price").median().round(2).alias("median_catalog_price"),
            pl.col(disc_col).drop_nulls().mean().round(2).alias("avg_verified_discount_pct"),
            (pl.col(disc_col).is_not_null() & (pl.col(disc_col) >= 15.0)).sum().alias("deals_15pct_count"),
            ean_expr.round(1).alias("ean_coverage_pct"),
        ])
        .join(cheapest_counts, on="store", how="left")
        .with_columns([
            pl.col("times_cheapest").fill_null(0).cast(pl.Int64),
            (
                (pl.col("times_cheapest").fill_null(0) / float(total_matched) * 100.0).round(1)
                if total_matched > 0
                else pl.lit(0.0)
            ).alias("win_rate_pct"),
            pl.col("avg_verified_discount_pct").fill_null(0.0),
        ])
        .sort(["times_cheapest", "avg_catalog_price"], descending=[True, False])
    )
    return stats


def _normalize_date_column(df: pl.DataFrame) -> pl.DataFrame:
    if "dt" in df.columns and "scraped_at" in df.columns:
        return df.with_columns(
            pl.coalesce([
                pl.col("dt").cast(pl.Utf8),
                pl.col("scraped_at").dt.strftime("%Y-%m-%d"),
            ]).alias("date_str")
        )
    if "dt" in df.columns:
        return df.with_columns(pl.col("dt").cast(pl.Utf8).alias("date_str"))
    if "scraped_at" in df.columns:
        return df.with_columns(pl.col("scraped_at").dt.strftime("%Y-%m-%d").alias("date_str"))
    return df.with_columns(pl.lit(get_current_date_partition()).alias("date_str"))


def build_daily_basket_index_mart(
    all_silver_df: pl.DataFrame,
    basket_type: str = "core",
) -> pl.DataFrame:
    """Calcula el costo diario de la canasta básica por tienda y la compra partida óptima."""
    if all_silver_df.is_empty():
        return pl.DataFrame()

    df = _normalize_date_column(all_silver_df)
    items = get_basket_items(basket_type=basket_type)
    if not items:
        return pl.DataFrame()

    dates = sorted(d for d in df["date_str"].unique().to_list() if d)
    rows: list[dict[str, Any]] = []

    for d in dates:
        day_df = df.filter(pl.col("date_str") == d)
        if day_df.is_empty():
            continue

        stores = sorted(day_df["store"].unique().to_list())
        store_acc: dict[str, dict[str, Any]] = {
            s: {"cost": 0.0, "found": 0} for s in stores
        }
        split_cost = 0.0
        split_found = 0

        for it in items:
            words = [w.lower().strip() for w in it.query.split() if len(w.strip()) > 1]
            if not words:
                continue
            cond = pl.lit(True)
            for w in words:
                cond = cond & (
                    pl.col("name").str.to_lowercase().str.contains(w, literal=True)
                    | pl.col("brand").fill_null("").str.to_lowercase().str.contains(w, literal=True)
                )
            matched = day_df.filter(cond)
            if matched.is_empty():
                continue

            if it.preferred_brands:
                b_cond = pl.lit(False)
                for b in it.preferred_brands:
                    b_cond = b_cond | pl.col("brand").fill_null("").str.to_lowercase().str.contains(
                        b.lower(), literal=True
                    )
                pref = matched.filter(b_cond)
                if not pref.is_empty():
                    matched = pref

            by_store = matched.group_by("store").agg(pl.col("price").min().alias("min_p"))
            best_for_item: float | None = None
            for r in by_store.to_dicts():
                s = r["store"]
                p = float(r["min_p"])
                store_acc[s]["cost"] += p
                store_acc[s]["found"] += 1
                if best_for_item is None or p < best_for_item:
                    best_for_item = p

            if best_for_item is not None:
                split_cost += best_for_item
                split_found += 1

        total_items = len(items)
        for s in stores:
            found = store_acc[s]["found"]
            rows.append({
                "dt": d,
                "store": s,
                "basket_type": basket_type,
                "basket_cost_ars": round(store_acc[s]["cost"], 2),
                "items_found": found,
                "total_basket_items": total_items,
                "coverage_pct": round((found / total_items) * 100, 1),
            })

        rows.append({
            "dt": d,
            "store": "split_optimal",
            "basket_type": basket_type,
            "basket_cost_ars": round(split_cost, 2),
            "items_found": split_found,
            "total_basket_items": total_items,
            "coverage_pct": round((split_found / total_items) * 100, 1),
        })

    if not rows:
        return pl.DataFrame()

    return pl.DataFrame(rows).sort(["dt", "store"])


def build_price_changes_mart(all_silver_df: pl.DataFrame) -> pl.DataFrame:
    """Calcula variaciones de precio (subas y bajas) entre el primer y último snapshot disponible."""
    if all_silver_df.is_empty():
        return pl.DataFrame()

    df = _normalize_date_column(all_silver_df)
    dates = sorted(d for d in df["date_str"].unique().to_list() if d)
    if len(dates) < 2:
        return pl.DataFrame()

    start_date, end_date = dates[0], dates[-1]
    macro_col = (
        pl.col("macro_category")
        if "macro_category" in df.columns
        else pl.lit("otros").alias("macro_category")
    )

    df_start = (
        df.filter(pl.col("date_str") == start_date)
        .unique(subset=["store", "product_id"])
        .select([
            "store",
            "product_id",
            "name",
            "brand",
            macro_col,
            pl.col("price").alias("price_start"),
        ])
    )
    df_end = (
        df.filter(pl.col("date_str") == end_date)
        .unique(subset=["store", "product_id"])
        .select([
            "store",
            "product_id",
            pl.col("price").alias("price_end"),
            "product_url",
        ])
    )

    joined = df_start.join(df_end, on=["store", "product_id"], how="inner")
    if joined.is_empty():
        return pl.DataFrame()

    return (
        joined.with_columns([
            pl.lit(start_date).alias("start_date"),
            pl.lit(end_date).alias("end_date"),
            (pl.col("price_end") - pl.col("price_start")).round(2).alias("change_ars"),
            (
                ((pl.col("price_end") - pl.col("price_start")) / pl.col("price_start")) * 100.0
            )
            .round(2)
            .alias("change_pct"),
        ])
        .with_columns(
            pl.when(pl.col("change_pct") > 1.0)
            .then(pl.lit("subio"))
            .when(pl.col("change_pct") < -1.0)
            .then(pl.lit("bajo"))
            .otherwise(pl.lit("estable"))
            .alias("direction")
        )
        .sort("change_pct", descending=True)
    )


def build_and_save_gold_marts(
    active_silver_df: pl.DataFrame,
    all_silver_df: pl.DataFrame,
    output_dir: Path,
    dt: str | None = None,
) -> dict[str, tuple[Path, int]]:
    """Genera y guarda todas las tablas analíticas de la capa Gold."""
    date_part = dt or get_current_date_partition()
    saved: dict[str, tuple[Path, int]] = {}

    cross_df = match_products_cross_store(active_silver_df)
    if not cross_df.is_empty():
        p = save_gold_dataframe(cross_df, output_dir, name="cross_store_comparison", dt=date_part)
        saved["cross_store_comparison"] = (p, len(cross_df))

    comp_df = build_store_competitiveness_mart(active_silver_df)
    if not comp_df.is_empty():
        p = save_gold_dataframe(comp_df, output_dir, name="store_competitiveness", dt=date_part)
        saved["store_competitiveness"] = (p, len(comp_df))

    basket_df = build_daily_basket_index_mart(all_silver_df if not all_silver_df.is_empty() else active_silver_df)
    if not basket_df.is_empty():
        p = save_gold_dataframe(basket_df, output_dir, name="daily_basket_index", dt=date_part)
        saved["daily_basket_index"] = (p, len(basket_df))

    changes_df = build_price_changes_mart(all_silver_df)
    if not changes_df.is_empty():
        p = save_gold_dataframe(changes_df, output_dir, name="price_changes", dt=date_part)
        saved["price_changes"] = (p, len(changes_df))

    return saved
