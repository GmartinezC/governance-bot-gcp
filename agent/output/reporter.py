"""Reporter: genera reportes Markdown y los persiste en GCS y BigQuery."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from google.cloud import bigquery, storage
from jinja2 import Template
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.config import Config

log = structlog.get_logger()

REPORT_TEMPLATE = """
# Reporte de Gobierno de Datos — {{ project_id }}
**Fecha:** {{ date }}  **Run ID:** {{ run_id }}

## Resumen de Scores

| Dominio | Score | Estado |
|---------|-------|--------|
{% for domain, score in scores.items() if domain != "overall" -%}
| {{ domain.upper() }} | {{ "%.1f"|format(score) }} | {{ "🟢" if score > 80 else ("🟡" if score > 50 else "🔴") }} |
{% endfor %}
**Score General: {{ "%.1f"|format(scores.get("overall", 0)) }} {{ "🟢" if scores.get("overall",0) > 80 else ("🟡" if scores.get("overall",0) > 50 else "🔴") }}**

## Hallazgos ({{ findings|length }} total)

{% for f in findings|sort(attribute="severity") -%}
### {{ f.severity }} — {{ f.title }}
- **Recurso:** {{ f.resource }}
- **Dominio:** {{ f.domain }}
- **Descripción:** {{ f.description }}
- **Recomendación:** {{ f.recommendation }}

{% endfor %}
## Top 5 Recomendaciones

{% for r in top_recommendations -%}
{{ loop.index }}. {{ r }}
{% endfor %}

---
*Generado automáticamente por el Bot de Gobierno de Datos GCP*
"""

BQ_SCHEMA = [
    bigquery.SchemaField("run_id", "STRING"),
    bigquery.SchemaField("project_id", "STRING"),
    bigquery.SchemaField("run_date", "DATE"),
    bigquery.SchemaField("started_at", "TIMESTAMP"),
    bigquery.SchemaField("finished_at", "TIMESTAMP"),
    bigquery.SchemaField("score_iam", "FLOAT64"),
    bigquery.SchemaField("score_dlp", "FLOAT64"),
    bigquery.SchemaField("score_catalog", "FLOAT64"),
    bigquery.SchemaField("score_lineage", "FLOAT64"),
    bigquery.SchemaField("score_policy", "FLOAT64"),
    bigquery.SchemaField("score_bq", "FLOAT64"),
    bigquery.SchemaField("score_scc", "FLOAT64"),
    bigquery.SchemaField("score_kms", "FLOAT64"),
    bigquery.SchemaField("score_overall", "FLOAT64"),
    bigquery.SchemaField("findings_count", "INT64"),
    bigquery.SchemaField("findings_critical", "INT64"),
    bigquery.SchemaField("findings_high", "INT64"),
    bigquery.SchemaField("report_gcs_path", "STRING"),
    bigquery.SchemaField("status", "STRING"),
]


class Reporter:
    """Genera reportes de gobierno de datos y los persiste en GCS y BigQuery."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.gcs = storage.Client(project=config.project_id)
        self.bq = bigquery.Client(project=config.project_id)
        self._ensure_bq_table()

    def _ensure_bq_table(self) -> None:
        """Crea la tabla BigQuery si no existe."""
        table_ref = f"{self.config.project_id}.{self.config.bq_dataset}.governance_runs"
        try:
            self.bq.get_table(table_ref)
        except Exception:
            dataset = bigquery.Dataset(f"{self.config.project_id}.{self.config.bq_dataset}")
            dataset.location = self.config.region
            try:
                self.bq.create_dataset(dataset, exists_ok=True)
            except Exception:
                pass
            table = bigquery.Table(table_ref, schema=BQ_SCHEMA)
            table.time_partitioning = bigquery.TimePartitioning(field="run_date")
            try:
                self.bq.create_table(table, exists_ok=True)
                log.info("bq_table_created", table=table_ref)
            except Exception as e:
                log.warning("bq_table_create_failed", error=str(e))

    def generate_report(self, project_id: str, results: dict, scores: dict) -> str:
        """Genera reporte Markdown con scores y findings."""
        findings = results.get("findings", [])
        top_recs = list({
            f["recommendation"]
            for f in sorted(findings, key=lambda x: ["CRITICAL","HIGH","MEDIUM","LOW"].index(x.get("severity","LOW")))
        })[:5]

        return Template(REPORT_TEMPLATE).render(
            project_id=project_id,
            date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            run_id=results.get("run_id", str(uuid.uuid4())),
            scores=scores,
            findings=findings,
            top_recommendations=top_recs,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def save_to_gcs(self, content: str, project_id: str, run_id: str) -> str:
        """Sube el reporte a GCS y retorna el URI gs://."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = f"reports/{project_id}/{date_str}/{run_id}.md"
        bucket = self.gcs.bucket(self.config.gcs_reports_bucket)
        blob = bucket.blob(path)
        blob.upload_from_string(content, content_type="text/markdown")
        uri = f"gs://{self.config.gcs_reports_bucket}/{path}"
        log.info("report_saved_gcs", uri=uri)
        return uri

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def save_to_bigquery(self, results: dict, scores: dict, project_id: str, run_id: str) -> None:
        """Inserta el resultado del run en BigQuery."""
        findings = results.get("findings", [])
        now = datetime.now(timezone.utc)
        row = {
            "run_id": run_id,
            "project_id": project_id,
            "run_date": now.date().isoformat(),
            "started_at": results.get("started_at", now.isoformat()),
            "finished_at": results.get("finished_at", now.isoformat()),
            "score_iam": scores.get("iam", 0.0),
            "score_dlp": scores.get("dlp", 0.0),
            "score_catalog": scores.get("catalog", 0.0),
            "score_lineage": scores.get("lineage", 0.0),
            "score_policy": scores.get("policy", 0.0),
            "score_bq": scores.get("bq", 0.0),
            "score_scc": scores.get("scc", 0.0),
            "score_kms": scores.get("kms", 0.0),
            "score_overall": scores.get("overall", 0.0),
            "findings_count": len(findings),
            "findings_critical": sum(1 for f in findings if f.get("severity") == "CRITICAL"),
            "findings_high": sum(1 for f in findings if f.get("severity") == "HIGH"),
            "report_gcs_path": results.get("report_gcs_path", ""),
            "status": results.get("status", "ok"),
        }
        table_ref = f"{self.config.project_id}.{self.config.bq_dataset}.governance_runs"
        errors = self.bq.insert_rows_json(table_ref, [row])
        if errors:
            log.error("bq_insert_errors", errors=errors)
        else:
            log.info("bq_row_inserted", run_id=run_id, project_id=project_id)
