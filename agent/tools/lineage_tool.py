"""Lineage Tool: audita trazabilidad de datos con Data Lineage API."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import structlog
from google.cloud import datacatalog_lineage_v1
from tenacity import retry, stop_after_attempt, wait_exponential
from agent.tools.registry import BaseTool

log = structlog.get_logger()


class LineageTool(BaseTool):
    name = "data_lineage"
    description = "Audita linaje de datos: detecta pipelines sin trazabilidad y transformaciones no documentadas."

    def __init__(self, config) -> None:
        self.config = config
        self.lineage_client = datacatalog_lineage_v1.LineageClient()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def run(self, project_id: str, **kwargs) -> dict:
        findings = []
        metadata = {}
        try:
            parent = f"projects/{project_id}/locations/{self.config.region}"
            processes = list(self.lineage_client.list_processes(parent=parent))
            total = len(processes)
            metadata = {"total_processes": total}

            if total == 0:
                findings.append(self._finding(
                    project_id, "MEDIUM",
                    "Sin procesos de linaje registrados",
                    "No se encontraron procesos de linaje en Data Lineage API. "
                    "Los pipelines de datos no tienen trazabilidad documentada.",
                    f"projects/{project_id}",
                    "Habilitar linaje automático en BigQuery y registrar procesos Dataflow en Data Lineage API."
                ))
                score = 30.0
            else:
                # Revisar procesos sin runs recientes
                orphan_count = 0
                for process in processes[:20]:
                    runs = list(self.lineage_client.list_runs(parent=process.name))
                    if not runs:
                        orphan_count += 1
                        findings.append(self._finding(
                            project_id, "LOW",
                            f"Proceso de linaje sin runs: {process.display_name}",
                            f"El proceso '{process.display_name}' no tiene runs registrados.",
                            process.name,
                            "Verificar que el pipeline esté activo o eliminar el proceso si está obsoleto."
                        ))
                score = max(0.0, 100.0 - (orphan_count / max(total, 1) * 50))

        except Exception as e:
            log.warning("lineage_tool_error", project_id=project_id, error=str(e))
            score = 50.0
            findings.append(self._finding(
                project_id, "MEDIUM", "Error al consultar Data Lineage API",
                str(e), f"projects/{project_id}",
                "Verificar que Data Lineage API esté habilitada y el SA tenga roles/datalineage.viewer."
            ))

        return {"tool": self.name, "project_id": project_id,
                "status": "ok", "findings": findings, "score": score, "metadata": metadata}

    def _finding(self, project_id, severity, title, description, resource, recommendation) -> dict:
        return {
            "finding_id": str(uuid.uuid4()), "project_id": project_id,
            "domain": "lineage", "severity": severity, "title": title,
            "description": description, "resource": resource,
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(), "status": "open",
        }
