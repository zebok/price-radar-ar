"""Módulo de subida y sincronización hacia Google Cloud Storage (GCS).

Soporta carga real con google-cloud-storage y modo dry-run / fallback local
cuando no hay credenciales de GCP configuradas en el entorno.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

try:
    from google.cloud import storage
    GCP_STORAGE_AVAILABLE = True
except ImportError:
    GCP_STORAGE_AVAILABLE = False


def _is_gcp_configured(project_id: str | None = None) -> bool:
    return bool(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT_ID")
        or os.getenv("K_SERVICE")
        or project_id
    )


def upload_parquet_to_gcs(
    local_path: Path,
    bucket_name: str,
    blob_name: str,
    *,
    project_id: str | None = None,
) -> str:
    """Sube un archivo Parquet a Google Cloud Storage preservando la ruta Hive."""
    target_uri = f"gs://{bucket_name}/{blob_name}"

    if not local_path.exists():
        logger.warning("[GCS] Archivo local no existe: {}", local_path)
        return target_uri

    resolved_project = project_id or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")

    if GCP_STORAGE_AVAILABLE and _is_gcp_configured(resolved_project):
        try:
            client = storage.Client(project=resolved_project)
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            blob.upload_from_filename(
                str(local_path),
                content_type="application/octet-stream",
            )
            logger.success("[GCS] Archivo subido con éxito a {}", target_uri)
            return target_uri
        except Exception as e:
            logger.error("[GCS] Error al subir a GCS {}: {}", target_uri, e)
            logger.info("[GCS] Continuando en modo local...")
            return target_uri

    logger.info(
        "[GCS Dry-Run] Simulación de subida: {} -> {} ({} bytes)",
        local_path.name,
        target_uri,
        local_path.stat().st_size,
    )
    return target_uri


def sync_latest_silver_from_gcs(
    bucket_name: str,
    base_dir: Path,
    *,
    project_id: str | None = None,
) -> Path | None:
    """Descarga el snapshot Silver más reciente desde GCS si no existe localmente."""
    if not GCP_STORAGE_AVAILABLE or not bucket_name:
        return None

    resolved_project = project_id or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not _is_gcp_configured(resolved_project):
        return None

    try:
        client = storage.Client(project=resolved_project)
        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix="silver/dt="))
        parquet_blobs = [b for b in blobs if b.name.endswith(".parquet")]
        if not parquet_blobs:
            return None

        parquet_blobs.sort(key=lambda b: b.name, reverse=True)
        latest_blob = parquet_blobs[0]

        local_path = base_dir / latest_blob.name
        if local_path.exists():
            return local_path

        local_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("[GCS] Descargando snapshot Silver desde {}...", latest_blob.name)
        latest_blob.download_to_filename(str(local_path))
        logger.success("[GCS] Snapshot Silver sincronizado con éxito en {}", local_path)
        return local_path
    except Exception as e:
        logger.warning("[GCS] Error al intentar sincronizar Silver desde GCS: {}", e)
        return None


def sync_silver_history_from_gcs(
    bucket_name: str,
    base_dir: Path,
    *,
    max_days: int = 7,
    project_id: str | None = None,
) -> list[Path]:
    """Descarga los últimos snapshots Silver disponibles en GCS para análisis de tendencias temporales."""
    if not GCP_STORAGE_AVAILABLE or not bucket_name:
        return []

    resolved_project = project_id or os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not _is_gcp_configured(resolved_project):
        return []

    try:
        client = storage.Client(project=resolved_project)
        bucket = client.bucket(bucket_name)
        blobs = list(bucket.list_blobs(prefix="silver/dt="))
        parquet_blobs = [b for b in blobs if b.name.endswith(".parquet")]
        if not parquet_blobs:
            return []

        parquet_blobs.sort(key=lambda b: b.name, reverse=True)
        selected_blobs = parquet_blobs[:max_days]

        downloaded_paths: list[Path] = []
        for blob in selected_blobs:
            local_path = base_dir / blob.name
            if not local_path.exists():
                local_path.parent.mkdir(parents=True, exist_ok=True)
                logger.info("[GCS] Descargando snapshot histórico {}", blob.name)
                blob.download_to_filename(str(local_path))
            downloaded_paths.append(local_path)

        return downloaded_paths
    except Exception as e:
        logger.warning("[GCS] Error al sincronizar historial Silver desde GCS: {}", e)
        return []



