resource "google_pubsub_topic" "alerts" {
  project = var.project_id
  name    = "governance-alerts"

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  depends_on = [google_project_service.apis]
}

resource "google_pubsub_subscription" "alerts_sub" {
  project = var.project_id
  name    = "governance-alerts-sub"
  topic   = google_pubsub_topic.alerts.name

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s" # 7 días

  expiration_policy {
    ttl = "2678400s" # 31 días
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "google_service_account" "scheduler_sa" {
  project      = var.project_id
  account_id   = "governance-bot-scheduler"
  display_name = "Governance Bot Scheduler SA"
}

resource "google_project_iam_member" "scheduler_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

resource "google_cloud_scheduler_job" "daily_run" {
  project     = var.project_id
  region      = var.region
  name        = "governance-bot-daily"
  description = "Ejecuta el bot de gobierno de datos diariamente"
  schedule    = var.scheduler_cron
  time_zone   = "America/Santiago"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/governance-bot:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_sa.email
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloud_run_v2_job.governance_bot,
  ]
}
