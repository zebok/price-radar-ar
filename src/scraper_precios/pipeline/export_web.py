"""Exportador de snapshots estáticos para la Web App / PWA (GitHub Pages $0).

Transforma el Lakehouse Parquet (Silver + Gold + Quality) en 3 archivos JSON
compactos dentro de `web/data/` para que la app funcione en <10ms en el navegador
sin requerir ningún backend encendido:
- `catalog.json`: catálogo consolidado cross-store con precios y links por súper.
- `analytics.json`: competitividad, inflación de canasta, variaciones, caza-bobos y stockeo.
- `quality.json`: frescura por supermercado y métricas de Data Quality de la última corrida.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from ..analytics.duckdb_runner import run_executive_report
from ..filters import MAX_CROSS_STORE_SPREAD_RATIO, MAX_PRICE_SANITY_ARS, MIN_PRICE_SANITY_ARS
from ..storage.parquet import (
    get_current_date_partition,
    load_active_silver_with_freshness,
    load_all_silver,
)
from .cleaning import infer_macro_category
from .gold import build_price_changes_mart
from .quality import load_latest_quality_report


def _ensure_macro_category(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty() or "macro_category" in df.columns:
        return df
    cats = df["category"].to_list() if "category" in df.columns else [None] * len(df)
    names = df["name_clean"].to_list() if "name_clean" in df.columns else [str(n).lower() for n in df["name"].to_list()]
    return df.with_columns(
        pl.Series("macro_category", [infer_macro_category(c, n) for c, n in zip(cats, names, strict=True)])
    )


def _build_compact_catalog(
    active_df: pl.DataFrame,
    store_freshness: dict[str, dict[str, Any]],
    max_items: int = 8000,
) -> dict[str, Any]:
    """Genera un catálogo agrupado por EAN (y fallback por producto) ultra compacto."""
    latest_dt = max(
        (info["last_dt"] for info in store_freshness.values() if info.get("last_dt")),
        default=get_current_date_partition(),
    )

    if active_df.is_empty():
        return {
            "meta": {
                "generated_at_utc": datetime.now(UTC).isoformat(),
                "latest_dt": latest_dt,
                "total_items": 0,
                "cross_store_items": 0,
                "stores_freshness": store_freshness,
            },
            "items": [],
        }

    df = _ensure_macro_category(active_df).filter(
        (pl.col("price") >= MIN_PRICE_SANITY_ARS)
        & (pl.col("price") <= MAX_PRICE_SANITY_ARS)
        & pl.col("available").fill_null(True)
    )

    disc_col = "verified_discount_pct" if "verified_discount_pct" in df.columns else "discount_pct"
    if "promo_label" not in df.columns:
        df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias("promo_label"))

    # Clave de agrupación: EAN válido si existe; sino clave única de tienda+producto
    df = df.with_columns(
        pl.when(pl.col("ean_clean").is_not_null() & (pl.col("ean_clean") != ""))
        .then(pl.col("ean_clean"))
        .otherwise(pl.col("store") + ":" + pl.col("product_id"))
        .alias("_group_key")
    )

    # Deduplicar por (_group_key, store) quedándonos con el menor precio en esa tienda
    df = df.sort("price", descending=False).unique(subset=["_group_key", "store"], keep="first")

    agg = df.group_by("_group_key").agg([
        pl.col("ean_clean").drop_nulls().first().alias("ean"),
        pl.col("name").first().alias("name"),
        pl.col("brand_clean").first().alias("brand"),
        pl.col("macro_category").first().alias("cat"),
        pl.col("image_url").drop_nulls().first().alias("img"),
        pl.col("unit_measure").sort_by("price").first().alias("u"),
        pl.col("unit_price_std").sort_by("price").first().alias("up"),
        pl.col("store").n_unique().alias("n"),
        pl.col("price").min().round(2).alias("min"),
        pl.col("price").max().round(2).alias("max"),
        pl.col(disc_col).max().fill_null(0.0).round(1).alias("disc"),
        pl.col("promo_label").is_not_null().any().alias("has_promo"),
        pl.col("store").sort_by("price").first().alias("best"),
        pl.struct([
            "store",
            "price",
            "list_price",
            pl.col(disc_col).alias("disc"),
            "promo_label",
            "unit_price_std",
            "product_url",
        ])
        .sort_by("price")
        .alias("_stores_list"),
    ])

    agg = (
        agg.with_columns(
            (((pl.col("max") - pl.col("min")) / pl.col("min")) * 100.0)
            .round(1)
            .alias("sp")
        )
        .filter(
            (pl.col("n") == 1)
            | (pl.col("max") / pl.col("min") <= MAX_CROSS_STORE_SPREAD_RATIO)
        )
        # Priorizar productos comparables en múltiples tiendas y luego ofertas
        .sort(["n", "sp", "disc"], descending=[True, True, True])
        .head(max_items)
    )

    items: list[dict[str, Any]] = []
    cross_store_count = 0

    for row in agg.to_dicts():
        n_stores = int(row["n"])
        if n_stores >= 2:
            cross_store_count += 1

        stores_map: dict[str, dict[str, Any]] = {}
        for st in row["_stores_list"]:
            st_key = st.get("store")
            if not st_key:
                continue
            price_val = round(float(st["price"]), 2)
            entry: dict[str, Any] = {"p": price_val}
            lp_raw = st.get("list_price")
            disc_raw = st.get("disc")
            if lp_raw is not None and float(lp_raw) > price_val and disc_raw:
                entry["lp"] = round(float(lp_raw), 2)
                entry["d"] = round(float(disc_raw), 1)
            if st.get("promo_label"):
                entry["pl"] = str(st["promo_label"])
            if st.get("unit_price_std") is not None:
                entry["up"] = round(float(st["unit_price_std"]), 2)
            if st.get("product_url"):
                entry["url"] = st["product_url"]
            stores_map[st_key] = entry

        item_obj: dict[str, Any] = {
            "id": row["ean"] or row["_group_key"],
            "name": row["name"],
            "brand": row["brand"] or "",
            "cat": row["cat"] or "otros",
            "u": row["u"] or "$/item",
            "up": round(float(row["up"]), 2) if row.get("up") is not None else round(float(row["min"]), 2),
            "min": round(float(row["min"]), 2),
            "max": round(float(row["max"]), 2),
            "sp": float(row["sp"] or 0.0),
            "disc": float(row["disc"] or 0.0),
            "best": row["best"],
            "n": n_stores,
            "s": stores_map,
        }
        if row.get("has_promo"):
            item_obj["hp"] = True
        if row.get("ean"):
            item_obj["ean"] = row["ean"]
        if row.get("img"):
            item_obj["img"] = row["img"]
        items.append(item_obj)

    return {
        "meta": {
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "latest_dt": latest_dt,
            "total_items": len(items),
            "cross_store_items": cross_store_count,
            "stores_freshness": store_freshness,
        },
        "items": items,
    }


def _build_analytics_payload(
    base_dir: Path,
    active_df: pl.DataFrame,
    all_silver_df: pl.DataFrame,
) -> dict[str, Any]:
    """Genera el bundle JSON para el Dashboard BI usando las vistas DuckDB + Gold."""
    sql_results = run_executive_report(base_dir)
    competitiveness = sql_results.get("02_store_competitiveness", [])
    basket_history = sql_results.get("01_basket_inflation", [])
    cazabobos_examples = sql_results.get("03_cazabobos_audit", [])[:15]
    unit_leaders = sql_results.get("04_unit_price_leaders", [])[:24]

    # Variaciones semanales / históricas
    changes_df = build_price_changes_mart(all_silver_df)
    top_increases: list[dict[str, Any]] = []
    top_drops: list[dict[str, Any]] = []
    avg_inflation = 0.0
    tracked_count = 0
    start_date = None
    end_date = None
    product_trends: dict[str, dict[str, Any]] = {}

    if not changes_df.is_empty():
        tracked_count = len(changes_df)
        avg_inflation = round(float(changes_df.select(pl.col("change_pct").mean()).item() or 0.0), 2)
        start_date = str(changes_df["start_date"][0])
        end_date = str(changes_df["end_date"][0])

        top_increases = (
            changes_df.filter(pl.col("change_pct") > 0)
            .sort("change_pct", descending=True)
            .head(12)
            .to_dicts()
        )
        top_drops = (
            changes_df.filter(pl.col("change_pct") < 0)
            .sort("change_pct", descending=False)
            .head(12)
            .to_dicts()
        )

        # Mapa rápido de tendencia por EAN para badges en Favoritos (modo estático)
        if not active_df.is_empty() and "ean_clean" in active_df.columns:
            ean_map = (
                active_df.filter(pl.col("ean_clean").is_not_null())
                .select(["store", "product_id", "ean_clean"])
                .unique(subset=["store", "product_id"])
            )
            with_ean = changes_df.join(ean_map, on=["store", "product_id"], how="inner")
            if not with_ean.is_empty():
                ean_trends = with_ean.group_by("ean_clean").agg(
                    pl.col("change_pct").mean().round(1).alias("pct")
                )
                for r in ean_trends.to_dicts():
                    pct = float(r["pct"])
                    direction = "subio" if pct > 1.0 else "bajo" if pct < -1.0 else "estable"
                    product_trends[str(r["ean_clean"])] = {"dir": direction, "pct": pct}

    # Stockeo no perecedero (>= 20% descuento verificado)
    stockup_deals: list[dict[str, Any]] = []
    category_breakdown: list[dict[str, Any]] = []
    if not active_df.is_empty():
        df_cat = _ensure_macro_category(active_df)
        disc_col = "verified_discount_pct" if "verified_discount_pct" in df_cat.columns else "discount_pct"

        stock_df = (
            df_cat.filter(
                pl.col("macro_category").is_in(["almacen", "limpieza", "perfumeria", "bebidas", "desayuno"])
                & pl.col(disc_col).is_not_null()
                & (pl.col(disc_col) >= 15.0)
            )
            .sort(disc_col, descending=True)
            .head(24)
            .select(["store", "name", "brand", "macro_category", "price", "list_price", disc_col, "unit_price_std", "unit_measure", "product_url"])
        )
        stockup_deals = [
            {
                "store": r["store"],
                "name": r["name"],
                "brand": r.get("brand") or "",
                "cat": r["macro_category"],
                "price": round(float(r["price"]), 2),
                "list_price": round(float(r["list_price"]), 2) if r.get("list_price") else None,
                "discount_pct": round(float(r[disc_col]), 1),
                "unit_price_std": round(float(r["unit_price_std"]), 2) if r.get("unit_price_std") else None,
                "unit_measure": r.get("unit_measure") or "$/item",
                "product_url": r.get("product_url"),
            }
            for r in stock_df.to_dicts()
        ]

        cat_df = (
            df_cat.group_by("macro_category")
            .agg([
                pl.len().alias("products_count"),
                pl.col("price").median().round(2).alias("median_price"),
                (pl.col(disc_col).is_not_null() & (pl.col(disc_col) >= 15.0)).sum().alias("deals_count"),
            ])
            .sort("products_count", descending=True)
        )
        category_breakdown = cat_df.to_dicts()

    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "competitiveness": competitiveness,
        "basket_history": basket_history,
        "weekly_trends": {
            "start_date": start_date,
            "end_date": end_date,
            "basket_weekly_inflation_pct": avg_inflation,
            "tracked_products_count": tracked_count,
            "top_increases": top_increases,
            "top_drops": top_drops,
        },
        "cazabobos_examples": cazabobos_examples,
        "unit_price_leaders": unit_leaders,
        "stockup_deals": stockup_deals,
        "category_breakdown": category_breakdown,
        "product_trends": product_trends,
    }


def export_web_bundle(
    base_dir: Path,
    web_dir: Path,
    *,
    max_items: int = 8000,
) -> dict[str, Path]:
    """Exporta el bundle estático completo en `{web_dir}/data/`."""
    data_out = web_dir / "data"
    data_out.mkdir(parents=True, exist_ok=True)

    active_df, store_freshness = load_active_silver_with_freshness(base_dir, max_days=7)
    all_silver_df = load_all_silver(base_dir, max_days=30)

    catalog_payload = _build_compact_catalog(active_df, store_freshness, max_items=max_items)
    analytics_payload = _build_analytics_payload(base_dir, active_df, all_silver_df)
    quality_payload = load_latest_quality_report(base_dir)

    # Adjuntar histórico de corridas si existe
    history_path = base_dir / "metrics" / "run_history.parquet"
    if history_path.exists():
        try:
            hist_df = pl.read_parquet(history_path).tail(30)
            quality_payload["run_history"] = hist_df.to_dicts()
        except Exception:
            quality_payload["run_history"] = []
    else:
        quality_payload.setdefault("run_history", [])

    catalog_path = data_out / "catalog.json"
    analytics_path = data_out / "analytics.json"
    quality_path = data_out / "quality.json"

    # Compact JSON (separators sin espacios innecesarios) para descarga mínima en 4G
    catalog_path.write_text(
        json.dumps(catalog_payload, ensure_ascii=False, separators=(",", ":"), default=str),
        encoding="utf-8",
    )
    analytics_path.write_text(
        json.dumps(analytics_payload, ensure_ascii=False, separators=(",", ":"), default=str),
        encoding="utf-8",
    )
    quality_path.write_text(
        json.dumps(quality_payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    logger.success(
        "[Export Web] Bundle estático generado en {} ({} productos, {:.1f} KB catalog.json)",
        data_out,
        catalog_payload["meta"]["total_items"],
        catalog_path.stat().st_size / 1024,
    )
    return {
        "catalog": catalog_path,
        "analytics": analytics_path,
        "quality": quality_path,
    }
