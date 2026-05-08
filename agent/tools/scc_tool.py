"""SCC Tool: audita findings de Security Command Center."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import structlog
from google.cloud import securitycenter_v1
from tenacity import retry, stop_after_attempt, wait_exponential
from agent.tools.registry import BaseTool

log = structlog.get_logger()

SEVERITY_MAP = {
    securitycenter_v1.Finding.Severity.CRITICAL: "CRITICAL",
    securitycenter_v1.Finding.Severity.HIGH:     "HIGH",
    securitycenter_v1.Finding.Severity.MEDIUM:   "MEDIUM",
    securitycenter_v1.Finding.Severity.LOW:      "LOW",
}


class SCCTool(BaseTool):
    name = "scc_analyzer"
    description = "Audita Security Command Center: lista findings activos HIGH y CRITICAL relacionados con gobierno de datos."

    def __init__(self, config) -> None:
        self.config = config
        self.scc_client = securitycenter_v1.SecurityCenterClient()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def run(self, project_id: str, **kwargs) -> dict:
        findings = []
        metadata = {}

        try:
            parent = f"projects/{project_id}/sources/-"
            request = securitycenter_v1.ListFindingsRequest(
                parent=parent,
                filter='state="ACTIVE" AND (severity="CRITICAL" OR severity="HIGH")',
                page_size=50,
            )
            results = list(self.scc_client.list_findings(request=request))
            critical = sum(1 for r in results if r.finding.severity == securitycenter_v1.Finding.Severity.CRITICAL)
            high = sum(1 for r in results if r.finding.severity == securitycenter_v1.Finding.Severity.HIGH)
            metadata = {"total_active": len(results), "critical": critical, "high": high}

            for result in results[:20]:
                f = result.finding
                sev = SEVERITY_MAP.get(f.severity, "MEDIUM")
                findings.append(self._finding(
                    project_id, sev,
                    f.category or "SCC Finding",
                    f.description or "Finding activo en Security Command Center.",
                    f.resource_name or f"projects/{project_id}",
                    "Revisar y remediar el finding en Security Command Center."
                ))

            deductions = (critical * 15) + (high * 8)
            score = max(0.0, 100.0 - deductions)

        except Exception as e:
            log.warning("scc_tool_error", project_id=project_id, error=str(e))
            score = 50.0
            findings.append(self._finding(
                project_id, "MEDIUM", "Error al consultar SCC",
                str(e), f"projects/{project_id}",
                "Verificar que SCC API esté habilitada y el SA tenga roles/securitycenter.findingsViewer."
            ))

        return {"tool": self.name, "project_id": project_id,
                "status": "ok", "findings": findings, "score": score, "metadata": metadata}

    def _finding(self, project_id, severity, title, description, resource, recommendation) -> dict:
        return {
            "finding_id": str(uuid.uuid4()), "project_id": project_id,
            "domain": "scc", "severity": severity, "title": title,
            "description": description, "resource": resource,
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(), "status": "open",
        }
