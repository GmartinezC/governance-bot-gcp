resource "google_bigquery_dataset" "governance" {
  project    = var.project_id
  dataset_id = "governance_bot"
  location   = var.region
  description = "Dataset del bot de gobierno de datos GCP"

  labels = {
    environment = var.environment
    managed_by  = "terraform"
  }

  depends_on = [google_project_service.apis]
}

resource "google_bigquery_table" "governance_runs" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.governance.dataset_id
  table_id   = "governance_runs"
  description = "Historial de runs del bot de gobierno de datos"

  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "run_date"
  }

  schema = jsonencode([
    { name = "run_id",            type = "STRING",    mode = "REQUIRED", description = "UUID del run" },
    { name = "project_id",        type = "STRING",    mode = "REQUIRED", description = "Proyecto GCP auditado" },
    { name = "run_date",          type = "DATE",      mode = "REQUIRED", description = "Fecha del run" },
    { name = "started_at",        type = "TIMESTAMP", mode = "NULLABLE", description = "Inicio del run" },
    { name = "finished_at",       type = "TIMESTAMP", mode = "NULLABLE", description = "Fin del run" },
    { name = "score_iam",         type = "FLOAT64",   mode = "NULLABLE", description = "Score IAM 0-100" },
    { name = "score_dlp",         type = "FLOAT64",   mode = "NULLABLE", description = "Score DLP 0-100" },
    { name = "score_catalog",     type = "FLOAT64",   mode = "NULLABLE", description = "Score Data Catalog 0-100" },
    { name = "score_lineage",     type = "FLOAT64",   mode = "NULLABLE", description = "Score Data Lineage 0-100" },
    { name = "score_policy",      type = "FLOAT64",   mode = "NULLABLE", description = "Score Org Policy 0-100" },
    { name = "score_bq",          type = "FLOAT64",   mode = "NULLABLE", description = "Score BigQuery 0-100" },
    { name = "score_scc",         type = "FLOAT64",   mode = "NULLABLE", description = "Score SCC 0-100" },
    { name = "score_kms",         type = "FLOAT64",   mode = "NULLABLE", description = "Score KMS/CMEK 0-100" },
    { name = "score_overall",     type = "FLOAT64",   mode = "NULLABLE", description = "Score general ponderado" },
    { name = "findings_count",    type = "INT64",     mode = "NULLABLE", description = "Total de findings" },
    { name = "findings_critical", type = "INT64",     mode = "NULLABLE", description = "Findings CRITICAL" },
    { name = "findings_high",     type = "INT64",     mode = "NULLABLE", description = "Findings HIGH" },
    { name = "report_gcs_path",   type = "STRING",    mode = "NULLABLE", description = "URI GCS del reporte" },
    { name = "status",            type = "STRING",    mode = "NULLABLE", description = "ok | partial | failed" },
  ])
}

resource "google_bigquery_table" "findings" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.governance.dataset_id
  table_id   = "findings"
  description = "Hallazgos individuales detectados por el bot"

  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "detected_at"
  }

  schema = jsonencode([
    { name = "finding_id",     type = "STRING",    mode = "REQUIRED", description = "UUID del finding" },
    { name = "run_id",         type = "STRING",    mode = "REQUIRED", description = "FK al run" },
    { name = "project_id",     type = "STRING",    mode = "REQUIRED", description = "Proyecto GCP" },
    { name = "domain",         type = "STRING",    mode = "REQUIRED", description = "iam|dlp|catalog|lineage|policy|bq|scc|kms" },
    { name = "severity",       type = "STRING",    mode = "REQUIRED", description = "LOW|MEDIUM|HIGH|CRITICAL" },
    { name = "title",          type = "STRING",    mode = "NULLABLE", description = "Título del hallazgo" },
    { name = "description",    type = "STRING",    mode = "NULLABLE", description = "Descripción detallada" },
    { name = "resource",       type = "STRING",    mode = "NULLABLE", description = "Recurso GCP afectado" },
    { name = "recommendation", type = "STRING",    mode = "NULLABLE", description = "Acción recomendada" },
    { name = "detected_at",    type = "TIMESTAMP", mode = "REQUIRED", description = "Cuándo se detectó" },
    { name = "status",         type = "STRING",    mode = "NULLABLE", description = "open | resolved" },
  ])
}
