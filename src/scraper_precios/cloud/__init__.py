"""Módulos de integración con Google Cloud Storage (GCS)."""

from .gcs import (
    sync_latest_silver_from_gcs,
    sync_silver_history_from_gcs,
    upload_parquet_to_gcs,
)

__all__ = [
    "sync_latest_silver_from_gcs",
    "sync_silver_history_from_gcs",
    "upload_parquet_to_gcs",
]
