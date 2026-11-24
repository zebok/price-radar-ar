"""Módulo de Observabilidad y Reporte de Calidad de Datos (Data Quality).

Calcula y persiste métricas trazables por cada ejecución del pipeline:
- Embudo Bronze → Silver → Gold con conteo exacto de descartes por regla técnica
- Cobertura de códigos EAN y tasa de emparejamiento cross-store
- Salud operacional de APIs por supermercado (latencia, éxito, circuit breaker)
- Frescura real de datos por cadena (fresh vs carried_forward)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from ..extractors.base import ExtractorMetrics
from ..storage.parquet import get_current_date_partition, load_active_silver_with_freshness


def build_quality_report(
    *,
    dt: str,
    mode: str,
    metrics_list: list[ExtractorMetrics],
    cleaning_report: dict[str, int],
    silver_df: pl.DataFrame,
    active_silver_df: pl.DataFrame,
    cross_store_df: pl.DataFrame,
    store_freshness: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Construye el reporte estructurado de calidad y observabilidad de la corrida."""
    now_iso = datetime.now(UTC).isoformat()
    active_count = len(active_silver_df)

    # Cobertura de EAN, URL directa e imagen sobre el catálogo activo
    ean_valid_count = 0
    unique_eans = 0
    url_valid_count = 0
    img_valid_count = 0
    if not active_silver_df.is_empty():
        if "ean_clean" in active_silver_df.columns:
            valid_eans = active_silver_df.filter(
                pl.col("ean_clean").is_not_null() & (pl.col("ean_clean") != "")
            )
            ean_valid_count = len(valid_eans)
            unique_eans = valid_eans["ean_clean"].n_unique()
        if "product_url" in active_silver_df.columns:
            url_valid_count = active_silver_df.filter(
                pl.col("product_url").is_not_null() & pl.col("product_url").str.starts_with("https://")
            ).height
        if "image_url" in active_silver_df.columns:
            img_valid_count = active_silver_df.filter(
                pl.col("image_url").is_not_null() & pl.col("image_url").str.starts_with("https://")
            ).height

    ean_coverage_pct = round((ean_valid_count / active_count) * 100, 1) if active_count > 0 else 0.0
    url_coverage_pct = round((url_valid_count / active_count) * 100, 1) if active_count > 0 else 0.0
    image_coverage_pct = round((img_valid_count / active_count) * 100, 1) if active_count > 0 else 0.0
    cross_store_eans = len(cross_store_df)
    match_rate_pct = round((cross_store_eans / unique_eans) * 100, 1) if unique_eans > 0 else 0.0

    # Combinar rechazos del extractor + rechazos en Silver
    extractor_rejections: dict[str, int] = {}
    stores_summary: list[dict[str, Any]] = []
    seen_stores: set[str] = set()

    for m in metrics_list:
        s_key = m.store_key or m.store_name.lower()
        seen_stores.add(s_key)
        for reason, cnt in m.rejection_counts.items():
            extractor_rejections[reason] = extractor_rejections.get(reason, 0) + cnt

        fresh_info = store_freshness.get(s_key, {})
        entry = m.to_dict()
        entry["freshness_status"] = fresh_info.get("status", "missing")
        entry["last_dt"] = fresh_info.get("last_dt")
        entry["age_days"] = fresh_info.get("age_days")
        entry["active_products"] = fresh_info.get("products_count", 0)
        stores_summary.append(entry)

    # Incluir tiendas servidas por carry-forward que no estuvieron en metrics_list
    for s_key, fresh_info in sorted(store_freshness.items()):
        if s_key in seen_stores:
            continue
        stores_summary.append({
            "store_key": s_key,
            "store_name": s_key.title(),
            "status": "carried_forward",
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "success_rate_pct": None,
            "avg_latency_ms": None,
            "duration_seconds": 0.0,
            "records_extracted": 0,
            "throughput_records_sec": 0.0,
            "circuit_open": False,
            "rejection_counts": {},
            "error_message": None,
            "freshness_status": fresh_info.get("status", "carried_forward"),
            "last_dt": fresh_info.get("last_dt"),
            "age_days": fresh_info.get("age_days", 0),
            "active_products": fresh_info.get("products_count", 0),
        })

    stores_healthy = sum(1 for s in stores_summary if s["status"] == "ok")
    carried_forward_stores = [
        s["store_key"] for s in stores_summary if s["freshness_status"] == "carried_forward"
    ]

    bronze_rows = int(cleaning_report.get("input_rows", 0))
    total_rejected_extractor = sum(extractor_rejections.values())
    total_candidates_seen = bronze_rows + total_rejected_extractor

    return {
        "run_timestamp_utc": now_iso,
        "dt": dt,
        "mode": mode,
        "funnel": {
            "candidates_seen": total_candidates_seen,
            "extractor_rejections": extractor_rejections,
            "bronze_rows": bronze_rows,
            "silver_cleaning_drops": {
                "out_of_stock": cleaning_report.get("dropped_out_of_stock", 0),
                "price_out_of_bounds": cleaning_report.get("dropped_price_out_of_bounds", 0),
                "invalid_name": cleaning_report.get("dropped_invalid_name", 0),
                "non_retail": cleaning_report.get("dropped_non_retail", 0),
                "duplicates": cleaning_report.get("dropped_duplicates", 0),
            },
            "silver_rows_today": len(silver_df),
            "active_silver_rows": active_count,
            "unique_valid_eans": unique_eans,
            "gold_cross_store_eans": cross_store_eans,
        },
        "quality_kpis": {
            "ean_coverage_pct": ean_coverage_pct,
            "url_coverage_pct": url_coverage_pct,
            "image_coverage_pct": image_coverage_pct,
            "cross_store_match_rate_pct": match_rate_pct,
            "stores_total": len(stores_summary),
            "stores_healthy": stores_healthy,
            "carried_forward_stores": carried_forward_stores,
        },
        "stores": stores_summary,
    }


def save_quality_report(report: dict[str, Any], base_dir: Path) -> tuple[Path, Path]:
    """Persiste `metrics/latest_run.json` y agrega una fila en `metrics/run_history.parquet`."""
    metrics_dir = base_dir / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)

    json_path = metrics_dir / "latest_run.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Registro plano para histórico de ejecuciones en Parquet
    funnel = report.get("funnel", {})
    kpis = report.get("quality_kpis", {})
    history_row = pl.DataFrame([{
        "run_timestamp_utc": report.get("run_timestamp_utc", ""),
        "dt": report.get("dt", get_current_date_partition()),
        "mode": report.get("mode", "unknown"),
        "bronze_rows": int(funnel.get("bronze_rows", 0)),
        "silver_rows_today": int(funnel.get("silver_rows_today", 0)),
        "active_silver_rows": int(funnel.get("active_silver_rows", 0)),
        "gold_cross_store_eans": int(funnel.get("gold_cross_store_eans", 0)),
        "ean_coverage_pct": float(kpis.get("ean_coverage_pct", 0.0)),
        "cross_store_match_rate_pct": float(kpis.get("cross_store_match_rate_pct", 0.0)),
        "stores_healthy": int(kpis.get("stores_healthy", 0)),
        "stores_total": int(kpis.get("stores_total", 0)),
        "carried_forward_count": len(kpis.get("carried_forward_stores", [])),
    }])

    history_path = metrics_dir / "run_history.parquet"
    if history_path.exists():
        try:
            existing = pl.read_parquet(history_path)
            combined = pl.concat([existing, history_row], how="diagonal_relaxed").tail(365)
            combined.write_parquet(history_path, compression="zstd")
        except Exception as e:
            logger.warning("[Metrics] Error concatenando run_history.parquet: {}. Sobrescribiendo.", e)
            history_row.write_parquet(history_path, compression="zstd")
    else:
        history_row.write_parquet(history_path, compression="zstd")

    logger.info("[Metrics] Reporte de Data Quality guardado en {}", json_path)
    return json_path, history_path


def load_latest_quality_report(base_dir: Path) -> dict[str, Any]:
    """Carga el último reporte de calidad o lo infiere en vivo desde los snapshots Silver."""
    json_path = base_dir / "metrics" / "latest_run.json"
    if json_path.exists():
        try:
            return json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("[Metrics] No se pudo leer {}: {}", json_path, e)

    # Fallback determinístico sobre los datos existentes (útil en modo demo o snapshots previos)
    active_df, freshness = load_active_silver_with_freshness(base_dir)
    if active_df.is_empty():
        return {
            "run_timestamp_utc": datetime.now(UTC).isoformat(),
            "dt": get_current_date_partition(),
            "mode": "snapshot",
            "funnel": {
                "candidates_seen": 0,
                "extractor_rejections": {},
                "bronze_rows": 0,
                "silver_cleaning_drops": {},
                "silver_rows_today": 0,
                "active_silver_rows": 0,
                "unique_valid_eans": 0,
                "gold_cross_store_eans": 0,
            },
            "quality_kpis": {
                "ean_coverage_pct": 0.0,
                "cross_store_match_rate_pct": 0.0,
                "stores_total": 0,
                "stores_healthy": 0,
                "carried_forward_stores": [],
            },
            "stores": [],
        }

    from .cross_store import match_products_cross_store

    cross_df = match_products_cross_store(active_df)
    latest_dt = max((f["last_dt"] for f in freshness.values() if f.get("last_dt")), default=get_current_date_partition())
    return build_quality_report(
        dt=latest_dt,
        mode="snapshot",
        metrics_list=[],
        cleaning_report={"input_rows": len(active_df)},
        silver_df=active_df,
        active_silver_df=active_df,
        cross_store_df=cross_df,
        store_freshness=freshness,
    )
