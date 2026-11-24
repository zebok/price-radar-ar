"""Orquestador unificado del pipeline ETL (Bronze → Silver → Gold → Quality → Export).

Compartido entre la CLI (`scraper extract`) y la API (`POST /v1/extract`).
Ejecuta las tiendas en paralelo con aislamiento total de fallos: si un supermercado
falla o abre su circuit breaker, el resto completa normalmente y el snapshot activo
mantiene los últimos datos válidos de la tienda caída (Carry-Forward).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from ..baskets import get_basket_queries
from ..cloud import upload_parquet_to_gcs
from ..config import Settings, parse_store_selection
from ..extractors import ExtractorMetrics, get_extractor, list_available_stores
from ..models import ProductRecord
from ..storage.parquet import (
    get_current_date_partition,
    load_active_silver_with_freshness,
    load_all_silver,
    save_bronze_records,
    save_silver_dataframe,
)
from ..taxonomy import get_store_categories
from .cleaning import clean_and_enrich_with_report, records_to_dataframe
from .cross_store import match_products_cross_store
from .gold import build_and_save_gold_marts
from .quality import build_quality_report, save_quality_report


@dataclass
class PipelineRunResult:
    """Resultado consolidado de una ejecución completa del pipeline ETL."""

    dt: str
    mode: str
    stores_requested: list[str]
    metrics: list[ExtractorMetrics] = field(default_factory=list)
    bronze_paths: list[Path] = field(default_factory=list)
    silver_path: Path | None = None
    gold_paths: dict[str, tuple[Path, int]] = field(default_factory=dict)
    quality_report: dict[str, Any] = field(default_factory=dict)
    silver_df: pl.DataFrame = field(default_factory=pl.DataFrame)
    active_silver_df: pl.DataFrame = field(default_factory=pl.DataFrame)
    matched_df: pl.DataFrame = field(default_factory=pl.DataFrame)
    store_freshness: dict[str, dict[str, Any]] = field(default_factory=dict)


async def _extract_single_store(
    store_key: str,
    *,
    is_fmcg_mode: bool,
    fmcg_categories: list[str] | None,
    queries: list[str],
    max_pages: int,
    settings: Settings,
) -> tuple[list[ProductRecord], ExtractorMetrics]:
    """Ejecuta la extracción aislada de un único supermercado."""
    extractor = get_extractor(
        store_key,
        max_concurrent=settings.max_concurrent_requests,
        request_delay_seconds=settings.request_delay_seconds,
        circuit_breaker_threshold=settings.circuit_breaker_threshold,
    )
    records: list[ProductRecord] = []

    try:
        async with extractor:
            if is_fmcg_mode:
                targets = get_store_categories(store_key, canonical_filter=fmcg_categories)
                if not targets:
                    logger.warning("[{}] Sin categorías FMCG configuradas para el filtro.", store_key)
                for target in targets:
                    if extractor.metrics.circuit_open:
                        break
                    cat_records = await extractor.extract_category(
                        target.identifier,
                        max_pages=max_pages,
                        page_size=50,
                    )
                    records.extend(cat_records)
            else:
                for query in queries:
                    if extractor.metrics.circuit_open:
                        break
                    q_records = await extractor.extract_query(query, max_pages=max_pages)
                    records.extend(q_records)
    except Exception as exc:
        logger.error("[{}] Error inesperado en extracción aislada: {}", store_key, exc)
        extractor.metrics.error_message = str(exc)

    return records, extractor.metrics


async def run_etl_pipeline(
    *,
    stores: list[str] | str = "all",
    queries: list[str] | None = None,
    basket_type: str | None = None,
    fmcg: bool = False,
    categories: list[str] | None = None,
    max_pages: int = 1,
    output_dir: Path | None = None,
    sync_to_cloud: bool = False,
    dt: str | None = None,
    settings: Settings | None = None,
) -> PipelineRunResult:
    """Ejecuta el pipeline completo en paralelo con carry-forward, Gold y Data Quality."""
    cfg = settings or Settings()
    base_dir = Path(output_dir or cfg.data_dir)
    date_part = dt or get_current_date_partition()
    available = list_available_stores()

    selected_stores, invalid_stores = parse_store_selection(stores, available)
    if invalid_stores:
        logger.warning("Tiendas ignoradas por no estar registradas: {}", invalid_stores)
    if not selected_stores:
        raise ValueError(f"Ninguna tienda válida seleccionada. Disponibles: {available}")

    is_fmcg_mode = bool(fmcg or categories)
    resolved_queries: list[str] = []
    if is_fmcg_mode:
        mode = "fmcg"
    elif queries:
        mode = "query"
        resolved_queries = list(queries)
    else:
        b_type = basket_type or cfg.basket_type or "core"
        mode = f"basket:{b_type}"
        resolved_queries = get_basket_queries(basket_type=b_type)

    # 1. Extracción paralela aislada por supermercado
    tasks = [
        _extract_single_store(
            s_key,
            is_fmcg_mode=is_fmcg_mode,
            fmcg_categories=categories,
            queries=resolved_queries,
            max_pages=max_pages,
            settings=cfg,
        )
        for s_key in selected_stores
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_records: list[ProductRecord] = []
    metrics_list: list[ExtractorMetrics] = []
    for s_key, res in zip(selected_stores, results, strict=True):
        if isinstance(res, Exception):
            logger.error("[{}] Fallo crítico aislado: {}", s_key, res)
            failed_metric = ExtractorMetrics(
                store_name=s_key.title(),
                store_key=s_key,
                requests_failed=1,
                error_message=str(res),
            )
            metrics_list.append(failed_metric)
        else:
            store_records, store_metrics = res
            all_records.extend(store_records)
            metrics_list.append(store_metrics)

    # 2. Bronze & Silver de la corrida de hoy (si hubo al menos 1 registro)
    bronze_paths: list[Path] = []
    silver_path: Path | None = None
    silver_df = pl.DataFrame()
    cleaning_report: dict[str, int] = {"input_rows": 0, "output_rows": 0}

    if all_records:
        bronze_paths = save_bronze_records(all_records, base_dir, dt=date_part)
        raw_df = records_to_dataframe(all_records)
        silver_df, cleaning_report = clean_and_enrich_with_report(raw_df)
        if not silver_df.is_empty():
            silver_path = save_silver_dataframe(silver_df, base_dir, dt=date_part)

    # 3. Carry-Forward: construir catálogo activo combinando hoy + últimos snapshots válidos
    active_silver_df, store_freshness = load_active_silver_with_freshness(
        base_dir, max_days=cfg.carry_forward_max_days
    )
    all_silver_df = load_all_silver(base_dir, max_days=30)

    # 4. Capa Gold Analítica (4 marts)
    gold_paths: dict[str, tuple[Path, int]] = {}
    matched_df = pl.DataFrame()
    if not active_silver_df.is_empty():
        matched_df = match_products_cross_store(active_silver_df)
        gold_paths = build_and_save_gold_marts(
            active_silver_df=active_silver_df,
            all_silver_df=all_silver_df,
            output_dir=base_dir,
            dt=date_part,
        )

    # 5. Reporte de Calidad & Observabilidad
    quality_report = build_quality_report(
        dt=date_part,
        mode=mode,
        metrics_list=metrics_list,
        cleaning_report=cleaning_report,
        silver_df=silver_df,
        active_silver_df=active_silver_df,
        cross_store_df=matched_df,
        store_freshness=store_freshness,
    )
    save_quality_report(quality_report, base_dir)

    # 6. Invalidar caché en memoria del motor de consultas
    from ..query_engine import invalidate_silver_cache

    invalidate_silver_cache()

    # 7. Sincronización opcional a GCS
    gcs_bucket = os.getenv("GCS_BUCKET_NAME") or cfg.gcs_bucket
    gcp_project = os.getenv("GCP_PROJECT_ID")
    if sync_to_cloud and gcs_bucket:
        for bp in bronze_paths:
            upload_parquet_to_gcs(bp, gcs_bucket, str(bp.relative_to(base_dir)), project_id=gcp_project)
        if silver_path:
            upload_parquet_to_gcs(
                silver_path, gcs_bucket, str(silver_path.relative_to(base_dir)), project_id=gcp_project
            )
        for gold_path, _ in gold_paths.values():
            upload_parquet_to_gcs(
                gold_path, gcs_bucket, str(gold_path.relative_to(base_dir)), project_id=gcp_project
            )

    return PipelineRunResult(
        dt=date_part,
        mode=mode,
        stores_requested=selected_stores,
        metrics=metrics_list,
        bronze_paths=bronze_paths,
        silver_path=silver_path,
        gold_paths=gold_paths,
        quality_report=quality_report,
        silver_df=silver_df,
        active_silver_df=active_silver_df,
        matched_df=matched_df,
        store_freshness=store_freshness,
    )
