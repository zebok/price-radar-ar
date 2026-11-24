# ==============================================================================
# Cloud Run Job (Ejecución Batch Diaria del Pipeline ETL)
# ==============================================================================

resource "google_cloud_run_v2_job" "scraper_job" {
  name     = "scraper-daily-job"
  location = var.region

  template {
    task_count = 1

    template {
      service_account = google_service_account.scraper_sa.email
      timeout         = "900s"
      max_retries     = 1

      containers {
        image   = var.image_name
        command = ["scraper"]
        args = [
          "extract",
          "--stores", "all",
          "--basket", "extended",
          "--pages", tostring(var.pages_per_query),
          "--sync-cloud",
          "--export-web"
        ]

        resources {
          limits = {
            cpu    = "1000m"
            memory = "1024Mi"
          }
        }

        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }

        env {
          name  = "GCS_BUCKET_NAME"
          value = google_storage_bucket.lakehouse.name
        }

        env {
          name  = "SCRAPER_DATA_DIR"
          value = "/app/data/scraper-precios"
        }

        env {
          name  = "SCRAPER_MAX_CONCURRENT_REQUESTS"
          value = "4"
        }

        env {
          name  = "SCRAPER_REQUEST_DELAY_SECONDS"
          value = "0.4"
        }
      }
    }
  }

  labels = {
    environment = "production"
    managed_by  = "terraform"
  }

  depends_on = [
    google_storage_bucket_iam_member.storage_writer,
  ]
}
