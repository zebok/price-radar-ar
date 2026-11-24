"""Motor unificado de consultas analíticas y búsqueda de precios sobre Polars.

Brinda acceso de alto rendimiento en memoria con Carry-Forward por tienda e
invalidación automática de caché por mtime:
- Búsqueda libre multi-criterio con ordenamiento inteligente (precio, $/kg, descuento)
- Benchmark cross-store en tiempo real para detección de ofertas y caza-bobos
- Oportunidades de stockeo para productos no perecederos
- Cálculo comparativo de la canasta familiar completa entre todas las tiendas
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from .baskets import get_basket_items
from .config import Settings
from .evaluator import MarketBenchmark
from .storage import (
    get_silver_mtime,
    load_active_silver_with_freshness,
    load_all_silver,
)

_ACTIVE_SILVER_CACHE: pl.DataFrame | None = None
_ACTIVE_SILVER_FRESHNESS: dict[str, dict[str, Any]] = {}
_ACTIVE_SILVER_CACHE_KEY: tuple[str, float] | None = None


def invalidate_silver_cache() -> None:
    """Invalida la caché en memoria del dataset Silver activo."""
    global _ACTIVE_SILVER_CACHE, _ACTIVE_SILVER_FRESHNESS, _ACTIVE_SILVER_CACHE_KEY
    _ACTIVE_SILVER_CACHE = None
    _ACTIVE_SILVER_FRESHNESS = {}
    _ACTIVE_SILVER_CACHE_KEY = None


def _get_active_silver_df(base_dir: Path | None = None, force_refresh: bool = False) -> pl.DataFrame:
    """Carga el dataset Silver activo con Carry-Forward por tienda e invalidación automática por mtime."""
    global _ACTIVE_SILVER_CACHE, _ACTIVE_SILVER_FRESHNESS, _ACTIVE_SILVER_CACHE_KEY

    settings = Settings()
    data_dir = Path(base_dir or settings.data_dir)
    current_mtime = get_silver_mtime(data_dir)
    cache_key = (str(data_dir.resolve()), current_mtime)

    if (
        not force_refresh
        and _ACTIVE_SILVER_CACHE is not None
        and not _ACTIVE_SILVER_CACHE.is_empty()
        and _ACTIVE_SILVER_CACHE_KEY == cache_key
    ):
        return _ACTIVE_SILVER_CACHE

    df, freshness = load_active_silver_with_freshness(
        data_dir, max_days=settings.carry_forward_max_days
    )
    if df.is_empty():
        _ACTIVE_SILVER_CACHE = df
        _ACTIVE_SILVER_FRESHNESS = {}
        _ACTIVE_SILVER_CACHE_KEY = cache_key
        return df

    if "scraped_at" in df.columns:
        df = df.sort("scraped_at", descending=True).unique(subset=["store", "product_id"])
    else:
        df = df.unique(subset=["store", "product_id"])

    if "store" in df.columns:
        from .models import build_coto_product_url

        coto_mask = df["store"] == "coto"
        if coto_mask.any():
            names = df["name"].to_list()
            slugs = df["url_slug"].to_list() if "url_slug" in df.columns else [None] * len(df)
            prod_ids = df["product_id"].to_list() if "product_id" in df.columns else [None] * len(df)
            urls = df["product_url"].to_list() if "product_url" in df.columns else [None] * len(df)
            stores = df["store"].to_list()

            new_urls = [
                build_coto_product_url(n, s, p) if st == "coto" else u
                for n, s, p, u, st in zip(names, slugs, prod_ids, urls, stores, strict=True)
            ]
            df = df.with_columns(pl.Series("product_url", new_urls))

    _ACTIVE_SILVER_CACHE = df
    _ACTIVE_SILVER_FRESHNESS = freshness
    _ACTIVE_SILVER_CACHE_KEY = cache_key
    return _ACTIVE_SILVER_CACHE


def get_store_freshness(base_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Retorna la frescura real por supermercado (fresh vs carried_forward)."""
    _get_active_silver_df(base_dir)
    return dict(_ACTIVE_SILVER_FRESHNESS)


def search_products(
    query: str | None = None,
    store: str | None = None,
    category: str | None = None,
    min_discount: float | None = None,
    sort_by: str = "price_asc",
    limit: int = 50,
    offset: int = 0,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Búsqueda granular y paginada en el catálogo Silver."""
    df = _get_active_silver_df(base_dir)
    if df.is_empty():
        return {"total": 0, "results": [], "limit": limit, "offset": offset}

    filtered = df

    # 1. Filtro por tienda
    if store and store.strip().lower() != "all":
        st = store.strip().lower()
        filtered = filtered.filter(pl.col("store").str.to_lowercase() == st)

    # 2. Filtro por categoría
    if category and category.strip():
        cat = category.strip().lower()
        filtered = filtered.filter(pl.col("category").str.to_lowercase().str.contains(cat, literal=True))

    # 3. Filtro por descuento
    if min_discount is not None and min_discount > 0:
        disc_col = "verified_discount_pct" if "verified_discount_pct" in filtered.columns else "discount_pct"
        filtered = filtered.filter(
            pl.col(disc_col).is_not_null() & (pl.col(disc_col) >= float(min_discount))
        )

    # 4. Filtro por término de búsqueda (búsqueda de palabras)
    if query and query.strip():
        words = [w.lower().strip() for w in query.strip().split() if w.strip()]
        for w in words:
            # Buscar en name_clean, name, brand, category
            cond = (
                pl.col("name").str.to_lowercase().str.contains(w, literal=True)
                | pl.col("brand").fill_null("").str.to_lowercase().str.contains(w, literal=True)
            )
            if "name_clean" in filtered.columns:
                cond = cond | pl.col("name_clean").fill_null("").str.to_lowercase().str.contains(w, literal=True)
            filtered = filtered.filter(cond)

    total_count = len(filtered)
    if total_count == 0:
        return {"total": 0, "results": [], "limit": limit, "offset": offset}

    # 5. Ordenamiento
    if sort_by == "price_desc":
        filtered = filtered.sort("price", descending=True)
    elif sort_by == "discount_desc":
        disc_col = "verified_discount_pct" if "verified_discount_pct" in filtered.columns else "discount_pct"
        filtered = filtered.sort(disc_col, descending=True, nulls_last=True)
    elif sort_by == "unit_price_asc" and "unit_price_std" in filtered.columns:
        filtered = filtered.sort("unit_price_std", descending=False, nulls_last=True)
    else:  # 'price_asc' por defecto
        filtered = filtered.sort("price", descending=False)

    # 6. Paginación
    paged = filtered.slice(offset, limit)

    # Convertir a diccionarios seguros para JSON
    records = paged.to_dicts()
    for r in records:
        if isinstance(r.get("scraped_at"), pl.Series):
            r["scraped_at"] = str(r["scraped_at"])
        elif hasattr(r.get("scraped_at"), "isoformat"):
            r["scraped_at"] = r["scraped_at"].isoformat()

    return {
        "total": total_count,
        "results": records,
        "limit": limit,
        "offset": offset,
    }


def find_benchmark_for_product(
    product_name: str,
    brand: str | None = None,
    category: str | None = None,
    base_dir: Path | None = None,
) -> MarketBenchmark:
    """Busca los precios vigentes de un producto en todos los competidores."""
    df = _get_active_silver_df(base_dir)
    if df.is_empty():
        return MarketBenchmark(
            cheapest_store=None,
            cheapest_price=None,
            cheapest_product_name=None,
            cheapest_product_url=None,
            average_market_price=None,
            total_matches_found=0,
            competitor_prices=[],
        )

    # Normalizar palabras clave de búsqueda (ej: "yerba", "playadito")
    query_words = [w.lower().strip() for w in product_name.replace("/", " ").replace("-", " ").split()]
    # Filtrar stopwords comunes
    stopwords = {"de", "la", "el", "en", "con", "sin", "x", "kg", "gr", "g", "ml", "l", "litro", "kilo"}
    clean_words = [w for w in query_words if len(w) > 1 and w not in stopwords]

    if not clean_words:
        clean_words = query_words

    matched = df
    for w in clean_words:
        matched = matched.filter(
            pl.col("name").str.to_lowercase().str.contains(w, literal=True)
            | pl.col("brand").fill_null("").str.to_lowercase().str.contains(w, literal=True)
        )

    if brand and brand.strip():
        b_clean = brand.strip().lower()
        matched = matched.filter(
            pl.col("brand").fill_null("").str.to_lowercase().str.contains(b_clean, literal=True)
        )

    if matched.is_empty():
        # Fallback más flexible: si no encuentra con todas las palabras, buscar con la primera y segunda
        if len(clean_words) >= 2:
            matched = df.filter(
                (pl.col("name").str.to_lowercase().str.contains(clean_words[0], literal=True))
                | (pl.col("name").str.to_lowercase().str.contains(clean_words[1], literal=True))
            )

    if matched.is_empty():
        return MarketBenchmark(
            cheapest_store=None,
            cheapest_price=None,
            cheapest_product_name=None,
            cheapest_product_url=None,
            average_market_price=None,
            total_matches_found=0,
            competitor_prices=[],
        )

    # Ordenar por precio ascendente
    sorted_df = matched.sort("price", descending=False)
    cheapest_row = sorted_df.row(0, named=True)

    prices_list: list[dict[str, Any]] = []
    # Quedarnos con el producto más barato por tienda
    by_store = sorted_df.group_by("store").agg([
        pl.col("price").min().alias("min_price"),
        pl.col("name").first().alias("sample_name"),
        pl.col("product_url").first().alias("url"),
        pl.col("unit_price_std").first().alias("unit_price_std"),
        pl.col("unit_measure").first().alias("unit_measure"),
    ]).sort("min_price", descending=False)

    for row in by_store.to_dicts():
        prices_list.append({
            "store": row["store"],
            "price": float(row["min_price"]),
            "product_name": row["sample_name"],
            "unit_price_std": row.get("unit_price_std"),
            "unit_measure": row.get("unit_measure"),
            "product_url": row.get("url"),
        })

    avg_p = float(sorted_df["price"].mean())

    return MarketBenchmark(
        cheapest_store=cheapest_row["store"],
        cheapest_price=float(cheapest_row["price"]),
        cheapest_product_name=cheapest_row["name"],
        cheapest_product_url=cheapest_row.get("product_url"),
        average_market_price=round(avg_p, 2),
        total_matches_found=len(sorted_df),
        competitor_prices=prices_list,
    )


def get_stockup_deals(
    min_discount: float = 20.0,
    categories: list[str] | None = None,
    limit: int = 30,
    base_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Identifica oportunidades de compra por volumen (stockeo) en productos de larga vida útil."""
    df = _get_active_silver_df(base_dir)
    if df.is_empty():
        return []

    target_cats = [c.lower() for c in (categories or ["almacen", "limpieza", "higiene", "perfumeria", "bebidas", "congelados"])]

    disc_col = "verified_discount_pct" if "verified_discount_pct" in df.columns else "discount_pct"

    deals = df.filter(
        pl.col(disc_col).is_not_null()
        & (pl.col(disc_col) >= float(min_discount))
        & pl.col("category").is_not_null()
    )

    if target_cats:
        cat_filter = pl.lit(False)
        for tc in target_cats:
            cat_filter = cat_filter | pl.col("category").str.to_lowercase().str.contains(tc, literal=True)
        deals = deals.filter(cat_filter)

    if deals.is_empty():
        return []

    # Ordenar por mayor porcentaje de descuento
    deals = deals.sort(disc_col, descending=True).limit(limit)

    results = deals.to_dicts()
    for r in results:
        if hasattr(r.get("scraped_at"), "isoformat"):
            r["scraped_at"] = r["scraped_at"].isoformat()
    return results


def compare_basket_across_stores(
    basket_type: str = "core",
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Calcula el costo total de la canasta (core o ampliada) en cada supermercado.

    Retorna:
    - Costo total por tienda
    - Productos presentes vs faltantes por tienda
    - Estrategia 'Compra Óptima Dividida' (comprar cada ítem en su tienda más barata)
    - Ahorro potencial total
    """
    items = get_basket_items(basket_type=basket_type)
    df = _get_active_silver_df(base_dir)

    if df.is_empty() or not items:
        return {
            "basket_type": basket_type,
            "total_basket_items": len(items),
            "stores_summary": {},
            "split_purchase_strategy": {},
            "best_single_store": None,
        }

    available_stores = df["store"].unique().to_list()
    store_costs: dict[str, dict[str, Any]] = {
        s: {"total_cost": 0.0, "items_found": 0, "missing_items": [], "items": []}
        for s in available_stores
    }

    split_optimal_items: list[dict[str, Any]] = []
    split_total_cost = 0.0

    for item in items:
        # Buscar en el df el producto más económico de este ítem
        item_words = [w.lower().strip() for w in item.query.split()]
        q_filter = pl.lit(True)
        for w in item_words:
            q_filter = q_filter & (
                pl.col("name").str.to_lowercase().str.contains(w, literal=True)
                | pl.col("brand").fill_null("").str.to_lowercase().str.contains(w, literal=True)
            )

        matched_item = df.filter(q_filter)

        # Si especificó marcas preferidas, filtrar primero por esas marcas
        if item.preferred_brands and not matched_item.is_empty():
            brand_filter = pl.lit(False)
            for pb in item.preferred_brands:
                brand_filter = brand_filter | pl.col("brand").fill_null("").str.to_lowercase().str.contains(pb.lower(), literal=True)
            brand_matched = matched_item.filter(brand_filter)
            if not brand_matched.is_empty():
                matched_item = brand_matched

        item_best_price: float | None = None
        item_best_store: str | None = None
        item_best_name: str | None = None

        for s in available_stores:
            s_matched = matched_item.filter(pl.col("store") == s)
            if not s_matched.is_empty():
                s_min_row = s_matched.sort("price", descending=False).row(0, named=True)
                p = float(s_min_row["price"])
                store_costs[s]["total_cost"] = round(store_costs[s]["total_cost"] + p, 2)
                store_costs[s]["items_found"] += 1
                store_costs[s]["items"].append({
                    "basket_id": item.id,
                    "item_name": item.name,
                    "matched_product": s_min_row["name"],
                    "price": p,
                    "unit_price_std": s_min_row.get("unit_price_std"),
                    "unit_measure": s_min_row.get("unit_measure"),
                })

                if item_best_price is None or p < item_best_price:
                    item_best_price = p
                    item_best_store = s
                    item_best_name = s_min_row["name"]
            else:
                store_costs[s]["missing_items"].append({
                    "basket_id": item.id,
                    "item_name": item.name,
                    "query": item.query,
                })

        if item_best_price is not None:
            split_total_cost += item_best_price
            split_optimal_items.append({
                "basket_id": item.id,
                "item_name": item.name,
                "store": item_best_store,
                "product_name": item_best_name,
                "price": item_best_price,
            })

    # Calcular mejor tienda individual (con mayor cobertura y menor costo relativo)
    eligible_stores = [
        (s, data) for s, data in store_costs.items() if data["items_found"] > 0
    ]
    best_single_store = None
    if eligible_stores:
        # Priorizar tiendas con mayor cobertura de ítems y luego menor costo total
        eligible_stores.sort(key=lambda x: (-x[1]["items_found"], x[1]["total_cost"]))
        best_name, best_data = eligible_stores[0]
        best_single_store = {
            "store": best_name,
            "total_cost": best_data["total_cost"],
            "items_found": best_data["items_found"],
            "coverage_pct": round((best_data["items_found"] / len(items)) * 100, 1),
        }

    return {
        "basket_type": basket_type,
        "total_basket_items": len(items),
        "stores_summary": store_costs,
        "best_single_store": best_single_store,
        "split_purchase_strategy": {
            "total_cost": round(split_total_cost, 2),
            "items_covered": len(split_optimal_items),
            "optimal_items": split_optimal_items,
        },
    }


def get_price_trend_for_product(
    query: str,
    store: str | None = None,
    days: int = 7,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Calcula la tendencia y variación de precio de un producto a lo largo de la semana.

    Retorna:
    - direction: 'subio' | 'bajo' | 'estable' | 'sin_datos'
    - change_pct: variación porcentual entre el inicio y final del período
    - price_start / price_current
    - history_by_date: serie temporal para graficar
    - by_store: desglose por supermercado
    """
    settings = Settings()
    data_dir = base_dir or settings.data_dir
    df = load_all_silver(data_dir, max_days=days)

    if df.is_empty():
        return {
            "query": query,
            "has_data": False,
            "direction": "sin_datos",
            "change_pct": 0.0,
            "message": "No se encontraron datos históricos de precios.",
            "history_by_date": [],
            "by_store": [],
        }

    # Normalizar columna de fecha (date_str: 'YYYY-MM-DD')
    if "dt" in df.columns and "scraped_at" in df.columns:
        df = df.with_columns(
            pl.coalesce([
                pl.col("dt").cast(pl.Utf8),
                pl.col("scraped_at").dt.strftime("%Y-%m-%d"),
            ]).alias("date_str")
        )
    elif "dt" in df.columns:
        df = df.with_columns(pl.col("dt").cast(pl.Utf8).alias("date_str"))
    elif "scraped_at" in df.columns:
        df = df.with_columns(
            pl.col("scraped_at").dt.strftime("%Y-%m-%d").alias("date_str")
        )
    else:
        return {
            "query": query,
            "has_data": False,
            "direction": "sin_datos",
            "change_pct": 0.0,
            "message": "Falta columna temporal en dataset.",
            "history_by_date": [],
            "by_store": [],
        }

    # Filtrar por términos de búsqueda (búsqueda de palabras)
    filtered = df
    if query and query.strip():
        words = [w.lower().strip() for w in query.strip().split() if w.strip()]
        for w in words:
            cond = (
                pl.col("name").str.to_lowercase().str.contains(w, literal=True)
                | pl.col("brand").fill_null("").str.to_lowercase().str.contains(w, literal=True)
            )
            if "name_clean" in filtered.columns:
                cond = cond | pl.col("name_clean").fill_null("").str.to_lowercase().str.contains(w, literal=True)
            filtered = filtered.filter(cond)

    if store and store.strip().lower() != "all":
        filtered = filtered.filter(pl.col("store").str.to_lowercase() == store.strip().lower())

    if filtered.is_empty():
        return {
            "query": query,
            "has_data": False,
            "direction": "sin_datos",
            "change_pct": 0.0,
            "message": f"No se encontraron productos coincidentes con '{query}'.",
            "history_by_date": [],
            "by_store": [],
        }

    available_dates = sorted([d for d in filtered["date_str"].unique().to_list() if d is not None])
    if len(available_dates) == 1:
        d = available_dates[0]
        cur_p = float(filtered.select(pl.col("price").min()).item())
        avg_p = float(filtered.select(pl.col("price").mean()).item())
        return {
            "query": query,
            "has_data": True,
            "period_days": 1,
            "start_date": d,
            "end_date": d,
            "direction": "estable",
            "change_pct": 0.0,
            "price_start": cur_p,
            "price_current": cur_p,
            "price_average_current": round(avg_p, 2),
            "history_by_date": [{"date": d, "min_price": cur_p, "avg_price": round(avg_p, 2)}],
            "by_store": [],
        }

    start_date = available_dates[0]
    end_date = available_dates[-1]

    df_start = filtered.filter(pl.col("date_str") == start_date)
    df_end = filtered.filter(pl.col("date_str") == end_date)

    price_start = float(df_start.select(pl.col("price").min()).item())
    price_current = float(df_end.select(pl.col("price").min()).item())

    if price_start > 0:
        change_pct = round(((price_current - price_start) / price_start) * 100, 2)
    else:
        change_pct = 0.0

    if change_pct > 1.0:
        direction = "subio"
    elif change_pct < -1.0:
        direction = "bajo"
    else:
        direction = "estable"

    # Serie temporal histórica por fecha
    history_by_date: list[dict[str, Any]] = []
    for d in available_dates:
        sub = filtered.filter(pl.col("date_str") == d)
        min_p = float(sub.select(pl.col("price").min()).item())
        avg_p = float(sub.select(pl.col("price").mean()).item())
        history_by_date.append({
            "date": d,
            "min_price": round(min_p, 2),
            "avg_price": round(avg_p, 2),
            "sample_count": len(sub),
        })

    # Desglose por tienda
    by_store: list[dict[str, Any]] = []
    stores_present = sorted(filtered["store"].unique().to_list())
    for s in stores_present:
        st_sub_start = df_start.filter(pl.col("store") == s)
        st_sub_end = df_end.filter(pl.col("store") == s)
        if not st_sub_start.is_empty() and not st_sub_end.is_empty():
            p_s = float(st_sub_start.select(pl.col("price").min()).item())
            p_e = float(st_sub_end.select(pl.col("price").min()).item())
            diff_p = round(((p_e - p_s) / p_s) * 100, 2) if p_s > 0 else 0.0
            st_dir = "subio" if diff_p > 1.0 else "bajo" if diff_p < -1.0 else "estable"
            by_store.append({
                "store": s,
                "direction": st_dir,
                "change_pct": diff_p,
                "price_start": p_s,
                "price_current": p_e,
            })

    return {
        "query": query,
        "has_data": True,
        "period_days": (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days or len(available_dates),
        "start_date": start_date,
        "end_date": end_date,
        "direction": direction,
        "change_pct": change_pct,
        "price_start": price_start,
        "price_current": price_current,
        "history_by_date": history_by_date,
        "by_store": by_store,
    }


def get_weekly_market_trends(
    days: int = 7,
    limit: int = 15,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Analiza la evolución de precios general de toda la canasta en la semana.

    Calcula la variación promedio de precios (inflación semanal observada) y detecta
    los productos que más subieron y los que más bajaron.
    """
    settings = Settings()
    data_dir = base_dir or settings.data_dir
    df = load_all_silver(data_dir, max_days=days)

    if df.is_empty():
        return {
            "period_days": days,
            "basket_weekly_inflation_pct": 0.0,
            "tracked_products_count": 0,
            "top_increases": [],
            "top_drops": [],
        }

    if "dt" in df.columns and "scraped_at" in df.columns:
        df = df.with_columns(
            pl.coalesce([
                pl.col("dt").cast(pl.Utf8),
                pl.col("scraped_at").dt.strftime("%Y-%m-%d"),
            ]).alias("date_str")
        )
    elif "dt" in df.columns:
        df = df.with_columns(pl.col("dt").cast(pl.Utf8).alias("date_str"))
    elif "scraped_at" in df.columns:
        df = df.with_columns(
            pl.col("scraped_at").dt.strftime("%Y-%m-%d").alias("date_str")
        )
    else:
        return {
            "period_days": days,
            "basket_weekly_inflation_pct": 0.0,
            "tracked_products_count": 0,
            "top_increases": [],
            "top_drops": [],
        }

    available_dates = sorted([d for d in df["date_str"].unique().to_list() if d is not None])
    if len(available_dates) < 2:
        return {
            "period_days": len(available_dates),
            "start_date": available_dates[0] if available_dates else None,
            "end_date": available_dates[0] if available_dates else None,
            "basket_weekly_inflation_pct": 0.0,
            "tracked_products_count": len(df),
            "top_increases": [],
            "top_drops": [],
        }

    start_date = available_dates[0]
    end_date = available_dates[-1]

    # Tomar la extracción más reciente de cada producto en start_date y end_date
    df_start = (
        df.filter(pl.col("date_str") == start_date)
        .unique(subset=["store", "product_id"])
        .select(["store", "product_id", "name", "brand", "price"])
        .rename({"price": "price_start"})
    )
    df_end = (
        df.filter(pl.col("date_str") == end_date)
        .unique(subset=["store", "product_id"])
        .select(["store", "product_id", "name", "brand", "price"])
        .rename({"price": "price_end"})
    )

    # Join de productos presentes en ambas fechas
    joined = df_start.join(df_end, on=["store", "product_id"], how="inner")
    if joined.is_empty():
        return {
            "period_days": days,
            "start_date": start_date,
            "end_date": end_date,
            "basket_weekly_inflation_pct": 0.0,
            "tracked_products_count": 0,
            "top_increases": [],
            "top_drops": [],
        }

    joined = joined.with_columns(
        (
            ((pl.col("price_end") - pl.col("price_start")) / pl.col("price_start")) * 100
        ).round(2).alias("change_pct")
    )

    avg_inflation = float(joined.select(pl.col("change_pct").mean()).item())

    # Top incrementos (mayores aumentos en la semana)
    top_increases = (
        joined.filter(pl.col("change_pct") > 0)
        .sort("change_pct", descending=True)
        .slice(0, limit)
        .to_dicts()
    )

    # Top caídas (rebajas / ofertas nuevas)
    top_drops = (
        joined.filter(pl.col("change_pct") < 0)
        .sort("change_pct", descending=False)
        .slice(0, limit)
        .to_dicts()
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "basket_weekly_inflation_pct": round(avg_inflation, 2),
        "tracked_products_count": len(joined),
        "top_increases": top_increases,
        "top_drops": top_drops,
    }


MACRO_CATEGORIES: dict[str, list[str]] = {
    "almacen": [
        "galletita", "chocolate", "cereal", "alfajor", "snack", "caramelo", "chicle",
        "aceite", "vinagre", "arroz", "legumbre", "pasta", "fideo", "harina",
        "enlatado", "conserva", "especia", "condimento", "salsa", "mayonesa",
        "ketchup", "mostaza", "mermelada", "dulce", "golosina", "encurtido",
        "aceituna", "reposteria", "azucar", "edulcorante", "sal", "caldo",
        "aderezo", "postre", "tostada", "bizcochito", "budin", "sopa", "tapa",
    ],
    "bebidas": [
        "vino", "cerveza", "gaseosa", "cola", "agua", "jugo", "aperitivo",
        "espumante", "whisky", "gin", "vodka", "licor", "fernet", "bebida",
        "isotonica", "champagne", "sidra", "amargo", "vermouth", "blancas", "energizante",
    ],
    "desayuno": [
        "cafe", "té", "te ", "yerba", "mate", "infusion", "cacao", "tostada",
        "bizcochito", "magdalena", "budin", "mermelada", "dulce de leche",
    ],
    "lacteos": [
        "leche", "queso", "yogur", "manteca", "crema", "fiambre", "embutido",
        "ricotta", "margarina", "untable",
    ],
    "limpieza": [
        "limpieza", "ropa", "suavizante", "lavandina", "detergente", "desinfectante",
        "insecticida", "rollo", "papel de cocina", "trapo", "esponja", "bolsa",
        "escoba", "calzado", "desodorante de ambiente", "lustra", "limpiador",
        "antigrasa", "quitamancha", "lavavajilla",
    ],
    "perfumeria": [
        "shampoo", "acondicionador", "jabon", "desodorante", "dental", "diente",
        "cepillo", "femenina", "toallita", "protector", "afeitado", "maquinita",
        "crema corporal", "crema facial", "panal", "cuidado", "algodon", "coloracion",
        "perfume", "higiene", "papel higienico",
    ],
    "congelados": [
        "congelad", "hamburguesa", "milanesa", "papas fritas", "helado", "nugget",
        "pizza congelada",
    ],
    "frescos": [
        "carne", "pollo", "pescado", "fruta", "verdura", "cerdo", "vacuna",
        "achura", "panaderia", "vegetal", "frescos", "novillito", "lomo",
        "bife", "picada", "asado",
    ],
}


STANDARD_CATEGORIES: list[dict[str, Any]] = [
    {"id": "aceites_condimentos", "name": "Aceites, Vinagres y Condimentos", "keywords": ["aceite", "vinagre", "mayonesa", "ketchup", "mostaza", "salsa", "especia", "sal", "caldo", "aderezo"]},
    {"id": "arroz_legumbres", "name": "Arroz, Legumbres y Harinas", "keywords": ["arroz", "legumbre", "lenteja", "garbanzo", "harina", "polenta", "premezcla", "pan rallado"]},
    {"id": "pastas_fideos", "name": "Fideos y Pastas", "keywords": ["pasta", "fideo", "spaghetti", "tallarin", "ñoqui", "raviol"]},
    {"id": "galletitas_tostadas", "name": "Galletitas y Tostadas", "keywords": ["galletita", "bizcochito", "tostada", "galleta"]},
    {"id": "chocolates_alfajores", "name": "Chocolates y Alfajores", "keywords": ["chocolate", "alfajor", "bombon"]},
    {"id": "golosinas_caramelos", "name": "Golosinas y Caramelos", "keywords": ["caramelo", "chicle", "golosina", "turron"]},
    {"id": "snacks_frutos_secos", "name": "Snacks y Frutos Secos", "keywords": ["snack", "papas fritas", "mani", "frutas secas", "fruto seco"]},
    {"id": "enlatados_conservas", "name": "Enlatados y Conservas", "keywords": ["conserva", "enlatado", "atun", "caballa", "choclo", "arveja", "tomate", "aceituna", "encurtido", "pickle"]},
    {"id": "yerba_mate", "name": "Yerba Mate", "keywords": ["yerba"]},
    {"id": "cafe_te_infusiones", "name": "Café, Té e Infusiones", "keywords": ["cafe", "té", "te ", "saquito", "infusion", "cacao"]},
    {"id": "azucar_endulzantes", "name": "Azúcar, Endulzantes y Mermeladas", "keywords": ["azucar", "edulcorante", "mermelada", "dulce"]},
    {"id": "cervezas", "name": "Cervezas", "keywords": ["cerveza"]},
    {"id": "vinos_espumantes", "name": "Vinos y Espumantes", "keywords": ["vino", "espumante", "champagne", "sidra"]},
    {"id": "gaseosas_aguas", "name": "Gaseosas y Aguas", "keywords": ["gaseosa", "cola", "agua", "soda"]},
    {"id": "jugos_isotonicas", "name": "Jugos e Isotónicas", "keywords": ["jugo", "isotonica", "polvo"]},
    {"id": "bebidas_alcohol", "name": "Bebidas con Alcohol y Licores", "keywords": ["fernet", "aperitivo", "gin", "vodka", "whisky", "licor", "vermouth", "amargo", "blancas"]},
    {"id": "leches", "name": "Leches y Bebidas Vegetales", "keywords": ["leche"]},
    {"id": "quesos", "name": "Quesos", "keywords": ["queso"]},
    {"id": "yogures_postres", "name": "Yogures y Postres", "keywords": ["yogur", "postre", "flan", "gelatina"]},
    {"id": "fiambres_embutidos", "name": "Fiambres, Embutidos y Mantecas", "keywords": ["fiambre", "jamon", "salame", "manteca", "crema"]},
    {"id": "carnes_pescados", "name": "Carnes y Pescados", "keywords": ["carne", "pollo", "pescado", "cerdo", "novillito", "asado", "bife", "merluza"]},
    {"id": "frutas_verduras", "name": "Frutas y Verduras", "keywords": ["fruta", "verdura", "papa", "cebolla", "tomate", "lechuga", "banana", "manzana", "vegetal"]},
    {"id": "congelados", "name": "Congelados", "keywords": ["congelad", "hamburguesa", "milanesa", "helado", "nugget", "pizza"]},
    {"id": "limpieza_ropa", "name": "Limpieza de Ropa", "keywords": ["ropa", "suavizante", "jabon para ropa", "quitamancha"]},
    {"id": "limpieza_hogar", "name": "Limpieza del Hogar y Cocina", "keywords": ["detergente", "lavavajilla", "lavandina", "desinfectante", "limpiador", "rollo", "papel de cocina", "trapo", "esponja", "bolsa"]},
    {"id": "shampoo_acondicionador", "name": "Shampoo y Acondicionador", "keywords": ["shampoo", "acondicionador", "capilar"]},
    {"id": "cuidado_bucal", "name": "Cuidado Bucal", "keywords": ["dental", "diente", "cepillo"]},
    {"id": "desodorantes_perfumeria", "name": "Desodorantes y Perfumería", "keywords": ["desodorante", "antitranspirante", "perfume", "colonia"]},
    {"id": "jabones_cuidado_personal", "name": "Jabones y Cuidado Personal", "keywords": ["jabon", "toallita", "femenina", "afeitado", "maquinita", "crema corporal", "crema facial", "papel higienico"]},
]


def get_catalog_categories(base_dir: Path | None = None, min_count: int = 1) -> list[dict[str, Any]]:
    """Devuelve las 29 categorías canónicas de supermercado con su conteo consolidado."""
    df = _get_active_silver_df(base_dir)
    if df.is_empty() or "category" not in df.columns:
        return []

    cat_col_lower = pl.col("category").fill_null("").str.to_lowercase()
    results = []
    for cat in STANDARD_CATEGORIES:
        conds = [cat_col_lower.str.contains(kw, literal=True) for kw in cat["keywords"]]
        cnt = df.filter(pl.any_horizontal(conds)).height
        if cnt >= min_count:
            results.append({
                "id": cat["id"],
                "category": cat["name"],
                "count": cnt,
            })

    return sorted(results, key=lambda x: x["category"])


def get_cross_store_catalog(
    query: str | None = None,
    store: str | None = None,
    cheapest_store: str | None = None,
    category: str | None = None,
    macro_category: str | None = None,
    min_stores: int = 1,
    min_spread: float | None = None,
    eans: list[str] | None = None,
    sort_by: str = "spread_desc",
    limit: int = 40,
    offset: int = 0,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Catálogo cross-store ultra-rápido en memoria con comparación multi-tienda y detección de la opción más barata."""
    df = _get_active_silver_df(base_dir)
    if df.is_empty():
        return {"total": 0, "results": [], "limit": limit, "offset": offset}

    from .filters import (
        MAX_CROSS_STORE_SPREAD_RATIO,
        MAX_PRICE_SANITY_ARS,
        MIN_PRICE_SANITY_ARS,
    )

    # 1. Filtro base de sanidad y stock
    valid = df.filter(
        (pl.col("price") >= MIN_PRICE_SANITY_ARS)
        & (pl.col("price") <= MAX_PRICE_SANITY_ARS)
        & pl.col("available").fill_null(False)
        & pl.col("ean_clean").is_not_null()
        & (pl.col("ean_clean") != "")
    )

    # 2. Filtro por EANs específicos (favoritos del usuario)
    if eans:
        clean_eans = [e.strip() for e in eans if e and e.strip()]
        if clean_eans:
            valid = valid.filter(pl.col("ean_clean").is_in(clean_eans))

    if valid.is_empty():
        return {"total": 0, "results": [], "limit": limit, "offset": offset}

    # 3. Agrupación por EAN
    agg = valid.group_by("ean_clean").agg([
        pl.col("name").first().alias("name"),
        pl.col("brand_clean").first().alias("brand"),
        pl.col("category").first().alias("category"),
        pl.col("image_url").drop_nulls().first().alias("image_url"),
        pl.col("store").n_unique().alias("stores_count"),
        pl.col("store").alias("stores_list"),
        pl.col("price").min().alias("cheapest_price"),
        pl.col("price").max().alias("max_price"),
        pl.col("price").mean().round(2).alias("avg_price"),
        pl.col("verified_discount_pct").max().fill_null(0.0).alias("max_discount_pct"),
        pl.col("store").sort_by("price").first().alias("cheapest_store"),
        pl.col("store").sort_by("price", descending=True).first().alias("most_expensive_store"),
        pl.struct([
            "store",
            "name",
            "price",
            "list_price",
            pl.col("verified_discount_pct").alias("discount_pct"),
            "product_url",
            "unit_price_std",
            "unit_measure",
        ]).sort_by("price").alias("store_details"),
    ])

    # 4. Cálculo de brechas y regla spread gate
    agg = agg.with_columns([
        (((pl.col("max_price") - pl.col("cheapest_price")) / pl.col("cheapest_price")) * 100.0)
        .round(1)
        .alias("savings_spread_pct"),
        (pl.col("max_price") - pl.col("cheapest_price")).round(2).alias("savings_amount"),
    ]).filter(
        (pl.col("stores_count") == 1)
        | (pl.col("max_price") / pl.col("cheapest_price") <= MAX_CROSS_STORE_SPREAD_RATIO)
    )

    # 5. Filtros opcionales
    if min_stores and min_stores > 1:
        agg = agg.filter(pl.col("stores_count") >= min_stores)

    if store and store.lower().strip() != "all":
        selected_stores = [s.strip().lower() for s in store.split(",") if s.strip() and s.strip().lower() != "all"]
        if selected_stores:
            conditions = [pl.col("stores_list").list.contains(st) for st in selected_stores]
            agg = agg.filter(pl.any_horizontal(conditions))

    if cheapest_store and cheapest_store.lower().strip() != "all":
        c_st = cheapest_store.lower().strip()
        agg = agg.filter(pl.col("cheapest_store") == c_st)

    if macro_category and macro_category.lower().strip() in MACRO_CATEGORIES:
        m_kws = MACRO_CATEGORIES[macro_category.lower().strip()]
        m_conds = [pl.col("category").fill_null("").str.to_lowercase().str.contains(kw, literal=True) for kw in m_kws]
        agg = agg.filter(pl.any_horizontal(m_conds))

    if category and category.strip():
        raw_cats = [c.strip() for c in category.split(",") if c.strip() and c.strip().lower() != "all"]
        keywords_to_match: set[str] = set()
        for c_val in raw_cats:
            c_lower = c_val.lower()
            found = False
            for std in STANDARD_CATEGORIES:
                if c_lower == std["id"] or c_lower == std["name"].lower():
                    keywords_to_match.update(std["keywords"])
                    found = True
                    break
            if not found:
                keywords_to_match.add(c_lower)

        if keywords_to_match:
            cat_conds = [pl.col("category").fill_null("").str.to_lowercase().str.contains(kw, literal=True) for kw in keywords_to_match]
            agg = agg.filter(pl.any_horizontal(cat_conds))

    if min_spread and min_spread > 0:
        agg = agg.filter(pl.col("savings_spread_pct") >= float(min_spread))

    if query and query.strip():
        words = [w.lower().strip() for w in query.strip().split() if w.strip()]
        for w in words:
            cond = (
                pl.col("name").str.to_lowercase().str.contains(w, literal=True)
                | pl.col("brand").fill_null("").str.to_lowercase().str.contains(w, literal=True)
                | pl.col("ean_clean").str.contains(w, literal=True)
            )
            agg = agg.filter(cond)

    total_count = len(agg)
    if total_count == 0:
        return {"total": 0, "results": [], "limit": limit, "offset": offset}

    # 6. Ordenamiento
    if sort_by == "price_asc":
        agg = agg.sort("cheapest_price", descending=False)
    elif sort_by == "price_desc":
        agg = agg.sort("cheapest_price", descending=True)
    elif sort_by == "discount_desc":
        agg = agg.sort(["max_discount_pct", "savings_spread_pct"], descending=[True, True])
    elif sort_by == "discount_asc":
        agg = agg.sort(["max_discount_pct", "savings_spread_pct"], descending=[False, False])
    elif sort_by == "spread_desc":
        agg = agg.sort("savings_spread_pct", descending=True)
    elif sort_by == "spread_asc":
        agg = agg.sort("savings_spread_pct", descending=False)
    elif sort_by == "stores_desc":
        agg = agg.sort(["stores_count", "savings_spread_pct"], descending=[True, True])
    elif sort_by == "name_asc":
        agg = agg.sort("name", descending=False)
    else:  # Por defecto
        agg = agg.sort("cheapest_price", descending=False)

    # 7. Paginación
    paged = agg.slice(offset, limit)
    records = paged.to_dicts()

    # Formatear detalle de tiendas como diccionario indexado por nombre de tienda
    for r in records:
        details = r.pop("store_details", [])
        store_map = {}
        for d in details:
            store_name = d.get("store")
            if store_name:
                store_map[store_name] = {
                    "price": d.get("price"),
                    "list_price": d.get("list_price"),
                    "discount_pct": d.get("discount_pct"),
                    "product_url": d.get("product_url"),
                    "unit_price_std": d.get("unit_price_std"),
                    "unit_measure": d.get("unit_measure"),
                }
        r["stores"] = store_map
        r["store_prices"] = details

    return {
        "total": total_count,
        "results": records,
        "limit": limit,
        "offset": offset,
    }

