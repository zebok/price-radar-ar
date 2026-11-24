"""Módulo de persistencia y almacenamiento particionado."""

from .parquet import (
    get_current_date_partition,
    get_silver_mtime,
    list_silver_partitions,
    load_active_silver_with_freshness,
    load_all_silver,
    load_latest_silver,
    save_bronze_records,
    save_gold_dataframe,
    save_silver_dataframe,
)

__all__ = [
    "get_current_date_partition",
    "get_silver_mtime",
    "list_silver_partitions",
    "load_active_silver_with_freshness",
    "load_all_silver",
    "load_latest_silver",
    "save_bronze_records",
    "save_gold_dataframe",
    "save_silver_dataframe",
]
