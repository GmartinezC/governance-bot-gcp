resource "google_service_account" "bot_sa" {
  project      = var.project_id
  account_id   = "governance-bot-sa"
  display_name = "Governance Bot Service Account"
  description  = "SA de mínimo privilegio para el bot de gobierno de datos"
}

locals {
  bot_roles = [
    "roles/cloudasset.viewer",
    "roles/dlp.reader",
    "roles/datacatalog.viewer",
    "roles/iam.securityReviewer",
    "roles/securitycenter.findingsViewer",
    "roles/bigquery.dataViewer",
    "roles/bigquery.jobUser",
    "roles/cloudkms.viewer",
    "roles/orgpolicy.policyViewer",
    "roles/datalineage.viewer",
    "roles/monitoring.viewer",
    "roles/run.invoker",
    "roles/storage.objectCreator",
    "roles/pubsub.publisher",
    "roles/datastore.user",
    "roles/secretmanager.secretAccessor",
  ]
}

resource "google_project_iam_member" "bot_sa_roles" {
  for_each = toset(local.bot_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.bot_sa.email}"

  depends_on = [google_project_service.apis]
}

resource "google_service_account_iam_member" "bot_sa_token_creator" {
  service_account_id = google_service_account.bot_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.bot_sa.email}"
}
