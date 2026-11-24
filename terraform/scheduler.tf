# ==============================================================================
# Cloud Scheduler (Trigger Diario Cron)
# ==============================================================================

resource "google_cloud_scheduler_job" "daily_scraper" {
  name        = "daily-supermarket-scraper-trigger"
  description = "Dispara el Cloud Run Job diariamente a las 06:00 AM (Argentina)"
  schedule    = var.cron_schedule
  time_zone   = var.cron_timezone
  region      = var.region

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.scraper_job.name}:run"

    oauth_token {
      service_account_email = google_service_account.scraper_sa.email
    }
  }

  retry_config {
    retry_count = 1
  }

  depends_on = [
    google_cloud_run_v2_job.scraper_job,
    google_project_iam_member.run_invoker,
  ]
}
