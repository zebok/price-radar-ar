# ==============================================================================
# IAM & Service Accounts (Principio de Menor Privilegio)
# ==============================================================================

resource "google_service_account" "scraper_sa" {
  account_id   = "scraper-runner-sa"
  display_name = "Service Account para Scraper de Precios (Cloud Run Job)"
  description  = "Identidad de servicio que ejecuta el ETL y escribe capas Parquet en GCS"
}

# 1. Permiso para leer/escribir archivos Parquet en el bucket Lakehouse
resource "google_storage_bucket_iam_member" "storage_writer" {
  bucket = google_storage_bucket.lakehouse.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.scraper_sa.email}"
}

# 2. Permiso para que Cloud Scheduler invoque el Cloud Run Job
resource "google_project_iam_member" "run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scraper_sa.email}"
}
