"""DLP Tool: audita datos sensibles con Cloud DLP."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
import structlog
from google.cloud import dlp_v2
from tenacity import retry, stop_after_attempt, wait_exponential
from agent.tools.registry import BaseTool

log = structlog.get_logger()


class DLPTool(BaseTool):
    name = "dlp_scanner"
    description = "Audita cobertura de Cloud DLP: detecta datasets sin inspección reciente y datos sensibles expuestos."

    def __init__(self, config) -> None:
        self.config = config
        self.dlp_client = dlp_v2.DlpServiceClient()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def run(self, project_id: str, **kwargs) -> dict:
        findings = []
        metadata = {}
        try:
            parent = f"projects/{project_id}"
            jobs = list(self.dlp_client.list_dlp_jobs(
                request=dlp_v2.ListDlpJobsRequest(parent=parent, type_=dlp_v2.DlpJobType.INSPECT_JOB)
            ))
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            recent_jobs = [j for j in jobs if j.create_time and j.create_time.ToDatetime(tzinfo=timezone.utc) > cutoff]
            metadata = {"total_jobs": len(jobs), "recent_jobs": len(recent_jobs)}

            if not recent_jobs:
                findings.append(self._finding(
                    project_id, "HIGH",
                    "Sin inspecciones DLP en los últimos 30 días",
                    "No se encontraron DLP inspection jobs recientes. Los datos sensibles pueden estar sin detectar.",
                    f"projects/{project_id}",
                    "Configurar DLP inspection jobs periódicos para datasets BigQuery y buckets GCS."
                ))
                score = 20.0
            else:
                score = min(100.0, 60.0 + len(recent_jobs) * 10)

            # Revisar findings de jobs recientes
            for job in recent_jobs[:5]:
                if job.inspect_details and job.inspect_details.result:
                    result = job.inspect_details.result
                    if result.info_type_stats:
                        for stat in result.info_type_stats:
                            if stat.count > 0:
                                findings.append(self._finding(
                                    project_id, "MEDIUM",
                                    f"Datos sensibles detectados: {stat.info_type.name}",
                                    f"Se encontraron {stat.count} instancias de {stat.info_type.name}.",
                                    job.name,
                                    f"Revisar y clasificar datos de tipo {stat.info_type.name}. Considerar enmascaramiento."
                                ))

        except Exception as e:
            log.warning("dlp_tool_error", project_id=project_id, error=str(e))
            score = 50.0
            findings.append(self._finding(
                project_id, "MEDIUM", "Error al consultar Cloud DLP",
                str(e), f"projects/{project_id}",
                "Verificar que Cloud DLP API esté habilitada y el SA tenga roles/dlp.reader."
            ))

        return {"tool": self.name, "project_id": project_id,
                "status": "ok", "findings": findings, "score": score, "metadata": metadata}

    def _finding(self, project_id, severity, title, description, resource, recommendation) -> dict:
        return {
            "finding_id": str(uuid.uuid4()), "project_id": project_id,
            "domain": "dlp", "severity": severity, "title": title,
            "description": description, "resource": resource,
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(), "status": "open",
        }
