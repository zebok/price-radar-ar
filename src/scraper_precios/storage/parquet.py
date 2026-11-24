"""Módulo de persistencia columnar Parquet con particionamiento Hive (Medallion Architecture).

Estructura:
- bronze/dt=YYYY-MM-DD/store={store}/data.parquet     (Datos crudos de extracción)
- silver/dt=YYYY-MM-DD/products.parquet               (Datos limpios, tipados y normalizados)
- gold/dt=YYYY-MM-DD/{table}.parquet                  (Marts analíticos: cross-store, competitividad, IPC, variaciones)
- metrics/latest_run.json & run_history.parquet       (Observabilidad y Data Quality)

Incluye soporte nativo de Carry-Forward por tienda (last-known-good snapshot) para
que si una cadena falla o bloquea un día, sus últimos precios válidos sigan visibles
con trazabilidad explícita de frescura.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
from loguru import logger

from ..models import ProductRecord


def get_current_date_partition() -> str:
    """Retorna la fecha actual en formato ISO (YYYY-MM-DD) en UTC."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


def list_silver_partitions(base_dir: Path) -> list[tuple[str, Path]]:
    """Retorna lista ordenada (ascendente) de (dt_str, path) de snapshots Silver disponibles."""
    silver_dir = base_dir / "silver"
    if not silver_dir.exists():
        return []
    partitions: list[tuple[str, Path]] = []
    for d in sorted(silver_dir.glob("dt=*")):
        pq = d / "products.parquet"
        if pq.exists():
            dt_str = d.name.replace("dt=", "", 1)
            partitions.append((dt_str, pq))
    return partitions


def get_silver_mtime(base_dir: Path) -> float:
    """Retorna el mayor mtime de los archivos Silver locales para invalidación de caché."""
    partitions = list_silver_partitions(base_dir)
    if not partitions:
        return 0.0
    return max(p.stat().st_mtime for _, p in partitions)


def save_bronze_records(
    records: list[ProductRecord],
    base_dir: Path,
    dt: str | None = None,
) -> list[Path]:
    """Guarda registros crudos particionados por fecha y tienda en Bronze."""
    if not records:
        return []

    from ..pipeline.cleaning import records_to_dataframe

    date_part = dt or get_current_date_partition()
    df = records_to_dataframe(records)
    saved_paths: list[Path] = []

    for store_name in df["store"].unique().to_list():
        store_df = df.filter(pl.col("store") == store_name)
        target_dir = base_dir / "bronze" / f"dt={date_part}" / f"store={store_name}"
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / "data.parquet"

        store_df.write_parquet(file_path, compression="zstd")
        saved_paths.append(file_path)
        logger.info(
            "[Bronze] Guardados {n} registros de {store} en {path}",
            n=len(store_df),
            store=store_name,
            path=file_path,
        )

    return saved_paths


def save_silver_dataframe(
    df: pl.DataFrame,
    base_dir: Path,
    dt: str | None = None,
) -> Path:
    """Guarda el dataset enriquecido y validado en Silver."""
    date_part = dt or get_current_date_partition()
    target_dir = base_dir / "silver" / f"dt={date_part}"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / "products.parquet"

    if "dt" not in df.columns and not df.is_empty():
        df = df.with_columns(pl.lit(date_part).str.to_date("%Y-%m-%d").alias("dt"))

    df.write_parquet(file_path, compression="zstd")
    logger.success(
        "[Silver] Guardados {n} productos procesados en {path}",
        n=len(df),
        path=file_path,
    )
    return file_path


def save_gold_dataframe(
    df: pl.DataFrame,
    base_dir: Path,
    name: str = "cross_store_comparison",
    dt: str | None = None,
) -> Path:
    """Guarda una tabla analítica en la capa Gold."""
    date_part = dt or get_current_date_partition()
    target_dir = base_dir / "gold" / f"dt={date_part}"
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{name}.parquet"

    df.write_parquet(file_path, compression="zstd")
    logger.success(
        "[Gold] Guardada tabla {name} con {n} filas en {path}",
        name=name,
        n=len(df),
        path=file_path,
    )
    return file_path


def load_latest_silver(base_dir: Path) -> pl.DataFrame:
    """Carga el dataset Silver más reciente disponible (local o GCS)."""
    partitions = list_silver_partitions(base_dir)
    if partitions:
        return pl.read_parquet(partitions[-1][1])

    gcs_bucket = os.getenv("GCS_BUCKET_NAME")
    if gcs_bucket:
        try:
            from ..cloud.gcs import sync_latest_silver_from_gcs

            synced_path = sync_latest_silver_from_gcs(gcs_bucket, base_dir)
            if synced_path and synced_path.exists():
                return pl.read_parquet(synced_path)
        except Exception as e:
            logger.debug("[Silver] Error intentando sincronizar desde GCS: {}", e)

    return pl.DataFrame()


def load_all_silver(base_dir: Path, max_days: int = 30) -> pl.DataFrame:
    """Carga snapshots Silver históricos (locales o desde GCS) para análisis temporal."""
    partitions = list_silver_partitions(base_dir)

    gcs_bucket = os.getenv("GCS_BUCKET_NAME")
    if gcs_bucket and len(partitions) < 2:
        try:
            from ..cloud.gcs import sync_silver_history_from_gcs

            sync_silver_history_from_gcs(gcs_bucket, base_dir, max_days=max_days)
            partitions = list_silver_partitions(base_dir)
        except Exception as e:
            logger.debug("[Silver] Error al intentar sincronizar historial desde GCS: {}", e)

    if not partitions:
        return pl.DataFrame()

    selected = partitions[-max_days:] if max_days > 0 else partitions
    dfs: list[pl.DataFrame] = []
    for dt_str, pq in selected:
        part_df = pl.read_parquet(pq)
        if "dt" not in part_df.columns and not part_df.is_empty():
            part_df = part_df.with_columns(pl.lit(dt_str).str.to_date("%Y-%m-%d").alias("dt"))
        dfs.append(part_df)

    return pl.concat(dfs, how="diagonal_relaxed")


def load_active_silver_with_freshness(
    base_dir: Path,
    max_days: int = 7,
) -> tuple[pl.DataFrame, dict[str, dict[str, Any]]]:
    """Construye el snapshot Silver activo aplicando Carry-Forward por tienda.

    Para cada tienda presente en los últimos `max_days` snapshots, toma únicamente
    su partición más reciente (last-known-good). Si hoy falló un supermercado pero
    ayer respondió bien, sus precios siguen activos con estado `'carried_forward'`.
    """
    partitions = list_silver_partitions(base_dir)
    if not partitions:
        latest = load_latest_silver(base_dir)
        if latest.is_empty():
            return pl.DataFrame(), {}
        partitions = list_silver_partitions(base_dir)

    if not partitions:
        return pl.DataFrame(), {}

    recent = partitions[-max_days:] if max_days > 0 else partitions
    latest_dt_str = recent[-1][0]
    latest_dt_obj = datetime.strptime(latest_dt_str, "%Y-%m-%d").date()

    # Recorremos de más reciente a más antiguo tomando el primer snapshot válido de cada tienda
    store_frames: dict[str, pl.DataFrame] = {}
    freshness: dict[str, dict[str, Any]] = {}

    for dt_str, pq_path in reversed(recent):
        part_df = pl.read_parquet(pq_path)
        if part_df.is_empty() or "store" not in part_df.columns:
            continue

        if "dt" not in part_df.columns:
            part_df = part_df.with_columns(pl.lit(dt_str).str.to_date("%Y-%m-%d").alias("dt"))

        dt_obj = datetime.strptime(dt_str, "%Y-%m-%d").date()
        age_days = max(0, (latest_dt_obj - dt_obj).days)

        for store_key in part_df["store"].unique().to_list():
            if store_key in store_frames:
                continue
            store_df = part_df.filter(pl.col("store") == store_key)
            if store_df.is_empty():
                continue

            store_frames[store_key] = store_df
            last_scraped = None
            if "scraped_at" in store_df.columns:
                max_ts = store_df.select(pl.col("scraped_at").max()).item()
                if hasattr(max_ts, "isoformat"):
                    last_scraped = max_ts.isoformat()

            freshness[store_key] = {
                "store": store_key,
                "last_dt": dt_str,
                "last_scraped_at": last_scraped,
                "age_days": age_days,
                "products_count": len(store_df),
                "status": "fresh" if age_days == 0 else "carried_forward",
            }

    if not store_frames:
        return pl.DataFrame(), {}

    combined = pl.concat(list(store_frames.values()), how="diagonal_relaxed")
    return combined, freshness
