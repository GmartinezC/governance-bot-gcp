locals {
  required_apis = [
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "cloudkms.googleapis.com",
    "dlp.googleapis.com",
    "datacatalog.googleapis.com",
    "datalineage.googleapis.com",
    "securitycenter.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "firestore.googleapis.com",
    "pubsub.googleapis.com",
    "cloudscheduler.googleapis.com",
    "eventarc.googleapis.com",
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "monitoring.googleapis.com",
    "cloudbuild.googleapis.com",
    "orgpolicy.googleapis.com",
    "cloudasset.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)
  project  = var.project_id
  service  = each.value

  disable_on_destroy         = false
  disable_dependent_services = false
}
