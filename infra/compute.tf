locals {
  image = "${var.region}-docker.pkg.dev/${var.project_id}/governance-bot/governance-bot:latest"
}

resource "google_secret_manager_secret" "bot_config" {
  project   = var.project_id
  secret_id = "governance-bot-config"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "bot_config_v1" {
  secret = google_secret_manager_secret.bot_config.id

  secret_data = jsonencode({
    GCP_PROJECT_ID       = var.project_id
    GCP_REGION           = var.region
    BQ_DATASET           = "governance_bot"
    GCS_REPORTS_BUCKET   = google_storage_bucket.reports.name
    PUBSUB_TOPIC_ALERTS  = google_pubsub_topic.alerts.name
    VERTEX_MODEL         = "gemini-1.5-pro"
    LOG_LEVEL            = "INFO"
    TARGET_PROJECTS      = join(",", var.target_projects)
    AUDIT_SCOPE          = "iam,dlp,catalog,lineage,policy,bq,scc,kms"
  })
}

resource "google_cloud_run_v2_job" "governance_bot" {
  project  = var.project_id
  name     = "governance-bot"
  location = var.region

  template {
    template {
      service_account = google_service_account.bot_sa.email
      timeout         = "${var.job_timeout_seconds}s"
      max_retries     = 1

      containers {
        image = local.image

        resources {
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }

        env {
          name = "GCP_PROJECT_ID"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.bot_config.secret_id
              version = "latest"
            }
          }
        }

        env {
          name  = "GCP_REGION"
          value = var.region
        }

        env {
          name  = "TARGET_PROJECTS"
          value = join(",", var.target_projects)
        }

        env {
          name  = "GCS_REPORTS_BUCKET"
          value = google_storage_bucket.reports.name
        }

        env {
          name  = "BQ_DATASET"
          value = "governance_bot"
        }

        env {
          name  = "PUBSUB_TOPIC_ALERTS"
          value = google_pubsub_topic.alerts.name
        }

        env {
          name  = "VERTEX_MODEL"
          value = "gemini-1.5-pro"
        }

        env {
          name  = "LOG_LEVEL"
          value = "INFO"
        }

        env {
          name  = "AUDIT_SCOPE"
          value = "iam,dlp,catalog,lineage,policy,bq,scc,kms"
        }
      }
    }
  }

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  depends_on = [
    google_project_service.apis,
    google_service_account.bot_sa,
    google_artifact_registry_repository.bot_repo,
  ]
}
