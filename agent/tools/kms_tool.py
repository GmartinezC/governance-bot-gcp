"""KMS Tool: audita cobertura CMEK en BigQuery y GCS."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import structlog
from google.cloud import bigquery, storage
from tenacity import retry, stop_after_attempt, wait_exponential
from agent.tools.registry import BaseTool

log = structlog.get_logger()


class KMSTool(BaseTool):
    name = "kms_checker"
    description = "Audita cobertura CMEK: verifica cifrado gestionado por cliente en BigQuery datasets y GCS buckets."

    def __init__(self, config) -> None:
        self.config = config
        self.bq_client = bigquery.Client(project=config.project_id)
        self.gcs_client = storage.Client(project=config.project_id)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def run(self, project_id: str, **kwargs) -> dict:
        findings = []
        metadata = {}
        total = 0
        with_cmek = 0

        try:
            # BigQuery datasets
            datasets = list(self.bq_client.list_datasets(project=project_id))
            for ds_item in datasets[:20]:
                total += 1
                ds = self.bq_client.get_dataset(ds_item.reference)
                if ds.default_encryption_configuration and ds.default_encryption_configuration.kms_key_name:
                    with_cmek += 1
                else:
                    findings.append(self._finding(
                        project_id, "MEDIUM",
                        f"Dataset BigQuery sin CMEK: {ds_item.dataset_id}",
                        f"El dataset '{ds_item.dataset_id}' usa cifrado por defecto de Google, no CMEK.",
                        f"{project_id}.{ds_item.dataset_id}",
                        "Configurar default_encryption_configuration con una Cloud KMS key para el dataset."
                    ))

            # GCS buckets
            buckets = list(self.gcs_client.list_buckets(project=project_id))
            for bucket in buckets[:20]:
                total += 1
                bucket.reload()
                if bucket.default_kms_key_name:
                    with_cmek += 1
                else:
                    findings.append(self._finding(
                        project_id, "MEDIUM",
                        f"Bucket GCS sin CMEK: {bucket.name}",
                        f"El bucket '{bucket.name}' usa cifrado por defecto de Google, no CMEK.",
                        f"gs://{bucket.name}",
                        "Configurar default_kms_key_name en el bucket con una Cloud KMS key."
                    ))

            metadata = {"total_resources": total, "with_cmek": with_cmek,
                        "bq_datasets": len(datasets), "gcs_buckets": len(buckets)}
            score = (with_cmek / total * 100) if total > 0 else 100.0

        except Exception as e:
            log.warning("kms_tool_error", project_id=project_id, error=str(e))
            score = 50.0
            findings.append(self._finding(
                project_id, "MEDIUM", "Error al verificar CMEK",
                str(e), f"projects/{project_id}",
                "Verificar que Cloud KMS API esté habilitada y el SA tenga roles/cloudkms.viewer."
            ))

        return {"tool": self.name, "project_id": project_id,
                "status": "ok", "findings": findings, "score": score, "metadata": metadata}

    def _finding(self, project_id, severity, title, description, resource, recommendation) -> dict:
        return {
            "finding_id": str(uuid.uuid4()), "project_id": project_id,
            "domain": "kms", "severity": severity, "title": title,
            "description": description, "resource": resource,
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(), "status": "open",
        }
