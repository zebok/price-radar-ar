variable "project_id" {
  description = "ID del proyecto en Google Cloud Platform"
  type        = string
}

variable "region" {
  description = "Región de GCP para Cloud Run, GCS y Cloud Scheduler (us-central1 entra en Always Free Tier)"
  type        = string
  default     = "us-central1"
}

variable "bucket_name" {
  description = "Nombre globalmente único del bucket de Cloud Storage para el Lakehouse Medallion"
  type        = string
}

variable "image_name" {
  description = "URI de la imagen Docker en Artifact Registry o GCR"
  type        = string
}

variable "cron_schedule" {
  description = "Expresión cron para ejecución diaria (06:00 AM hora Argentina)"
  type        = string
  default     = "0 6 * * *"
}

variable "cron_timezone" {
  description = "Zona horaria del Cloud Scheduler"
  type        = string
  default     = "America/Argentina/Buenos_Aires"
}

variable "pages_per_query" {
  description = "Páginas por búsqueda en cada extracción diaria"
  type        = number
  default     = 2
}
