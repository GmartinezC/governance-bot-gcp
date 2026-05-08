"""BigQuery Tool: audita datasets, tablas y audit logs en BigQuery."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import structlog
from google.cloud import bigquery
from tenacity import retry, stop_after_attempt, wait_exponential
from agent.tools.registry import BaseTool

log = structlog.get_logger()


class BigQueryTool(BaseTool):
    name = "bigquery_audit"
    description = "Audita BigQuery: detecta tablas sin descripción, datasets sin etiquetas y accesos inusuales."

    def __init__(self, config) -> None:
        self.config = config
        self.bq_client = bigquery.Client(project=config.project_id)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def run(self, project_id: str, **kwargs) -> dict:
        findings = []
        metadata = {}
        score = 100.0

        try:
            # Listar datasets del proyecto
            datasets = list(self.bq_client.list_datasets(project=project_id))
            total_datasets = len(datasets)
            unlabeled = 0
            tables_no_desc = 0
            total_tables = 0

            for ds_item in datasets[:20]:  # limitar a 20 datasets
                ds = self.bq_client.get_dataset(ds_item.reference)
                if not ds.labels:
                    unlabeled += 1
                    findings.append(self._finding(
                        project_id, "LOW",
                        f"Dataset sin etiquetas: {ds_item.dataset_id}",
                        f"El dataset '{ds_item.dataset_id}' no tiene labels de clasificación.",
                        f"{project_id}.{ds_item.dataset_id}",
                        "Agregar labels: data_classification, data_owner, environment."
                    ))

                # Revisar tablas sin descripción
                tables = list(self.bq_client.list_tables(ds_item.reference))
                total_tables += len(tables)
                for tbl_item in tables[:10]:
                    tbl = self.bq_client.get_table(tbl_item.reference)
                    if not tbl.description:
                        tables_no_desc += 1
                        if tables_no_desc <= 10:
                            findings.append(self._finding(
                                project_id, "LOW",
                                f"Tabla sin descripción: {tbl_item.table_id}",
                                f"La tabla '{ds_item.dataset_id}.{tbl_item.table_id}' no tiene descripción.",
                                f"{project_id}.{ds_item.dataset_id}.{tbl_item.table_id}",
                                "Agregar descripción técnica y de negocio a la tabla en BigQuery."
                            ))

            metadata = {
                "total_datasets": total_datasets,
                "unlabeled_datasets": unlabeled,
                "total_tables": total_tables,
                "tables_without_description": tables_no_desc,
            }
            deductions = (unlabeled * 5) + (min(tables_no_desc, 10) * 3)
            score = max(0.0, 100.0 - deductions)

        except Exception as e:
            log.warning("bq_tool_error", project_id=project_id, error=str(e))
            score = 50.0
            findings.append(self._finding(
                project_id, "MEDIUM", "Error al auditar BigQuery",
                str(e), f"projects/{project_id}",
                "Verificar que BigQuery API esté habilitada y el SA tenga roles/bigquery.dataViewer."
            ))

        return {"tool": self.name, "project_id": project_id,
                "status": "ok", "findings": findings, "score": score, "metadata": metadata}

    def _finding(self, project_id, severity, title, description, resource, recommendation) -> dict:
        return {
            "finding_id": str(uuid.uuid4()), "project_id": project_id,
            "domain": "bq", "severity": severity, "title": title,
            "description": description, "resource": resource,
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(), "status": "open",
        }
