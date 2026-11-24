# ==============================================================================
# Cloud Storage Bucket (Lakehouse Medallion: Bronze / Silver / Gold)
# ==============================================================================

resource "google_storage_bucket" "lakehouse" {
  name                        = var.bucket_name
  location                    = "US" # US multi-region o us-central1 califican para el Always Free de 5GB
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false

  # Regla de ciclo de vida para nunca superar los 5 GB gratuitos
  lifecycle_rule {
    condition {
      age = 365 # Archivos más viejos de 1 año se eliminan
    }
    action {
      type = "Delete"
    }
  }

  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 30
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    environment = "production"
    managed_by  = "terraform"
    project     = "scraper-precios"
  }
}
