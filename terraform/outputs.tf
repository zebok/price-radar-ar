output "project_id" {
  description = "ID del proyecto en Google Cloud"
  value       = var.project_id
}

output "lakehouse_bucket_url" {
  description = "URI del bucket de Cloud Storage (Lakehouse Parquet)"
  value       = "gs://${google_storage_bucket.lakehouse.name}"
}

output "cloud_run_job_name" {
  description = "Nombre del Cloud Run Job"
  value       = google_cloud_run_v2_job.scraper_job.name
}

output "scheduler_job_name" {
  description = "Nombre del trigger en Cloud Scheduler"
  value       = google_cloud_scheduler_job.daily_scraper.name
}

output "service_account_email" {
  description = "Email de la Service Account que ejecuta el job"
  value       = google_service_account.scraper_sa.email
}
