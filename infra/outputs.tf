output "service_account_email" {
  description = "Email del Service Account del bot"
  value       = google_service_account.bot_sa.email
}

output "cloud_run_job_name" {
  description = "Nombre del Cloud Run Job"
  value       = google_cloud_run_v2_job.governance_bot.name
}

output "reports_bucket_name" {
  description = "Nombre del bucket GCS de reportes"
  value       = google_storage_bucket.reports.name
}

output "bq_dataset_id" {
  description = "ID del dataset BigQuery"
  value       = google_bigquery_dataset.governance.dataset_id
}

output "pubsub_topic_id" {
  description = "ID del topic Pub/Sub de alertas"
  value       = google_pubsub_topic.alerts.id
}

output "scheduler_job_name" {
  description = "Nombre del Cloud Scheduler job"
  value       = google_cloud_scheduler_job.daily_run.name
}

output "artifact_registry_repo" {
  description = "URI del repositorio Artifact Registry"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/governance-bot"
}
