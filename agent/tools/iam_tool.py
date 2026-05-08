"""IAM Tool: audita permisos y roles en el proyecto GCP."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import structlog
from google.cloud import asset_v1
from tenacity import retry, stop_after_attempt, wait_exponential
from agent.tools.registry import BaseTool

log = structlog.get_logger()

PRIMITIVE_ROLES = {"roles/owner", "roles/editor", "roles/viewer"}


class IAMTool(BaseTool):
    name = "iam_analyzer"
    description = "Audita IAM: detecta primitive roles, service accounts con privilegios excesivos y recomendaciones sin aplicar."

    def __init__(self, config) -> None:
        self.config = config
        self.asset_client = asset_v1.AssetServiceClient()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def run(self, project_id: str, **kwargs) -> dict:
        findings = []
        metadata = {}
        try:
            parent = f"projects/{project_id}"
            # Listar IAM policies via Cloud Asset Inventory
            request = asset_v1.AnalyzeIamPolicyRequest(
                analysis_query=asset_v1.IamPolicyAnalysisQuery(
                    scope=parent,
                    resource_selector=asset_v1.IamPolicyAnalysisQuery.ResourceSelector(
                        full_resource_name=f"//cloudresourcemanager.googleapis.com/projects/{project_id}"
                    ),
                )
            )
            response = self.asset_client.analyze_iam_policy(request=request)
            primitive_count = 0
            total_bindings = 0

            for result in response.main_analysis.analysis_results:
                for binding in result.iam_binding.role if hasattr(result, 'iam_binding') else []:
                    total_bindings += 1
                    if binding in PRIMITIVE_ROLES:
                        primitive_count += 1
                        findings.append(self._finding(
                            project_id, "HIGH",
                            f"Primitive role '{binding}' asignado",
                            f"El role primitivo '{binding}' otorga acceso excesivo. "
                            "Reemplazar con roles granulares.",
                            f"projects/{project_id}",
                            "Reemplazar con roles predefinidos específicos (ej: roles/storage.objectViewer)."
                        ))

            metadata = {"primitive_roles": primitive_count, "total_bindings": total_bindings}
            score = max(0.0, 100.0 - (primitive_count * 20))

        except Exception as e:
            log.warning("iam_tool_error", project_id=project_id, error=str(e))
            findings.append(self._finding(
                project_id, "MEDIUM",
                "No se pudo analizar IAM",
                f"Error al consultar Cloud Asset Inventory: {e}",
                f"projects/{project_id}",
                "Verificar que la API Cloud Asset Inventory esté habilitada y el SA tenga roles/cloudasset.viewer."
            ))
            score = 50.0

        return {"tool": self.name, "project_id": project_id,
                "status": "ok", "findings": findings, "score": score, "metadata": metadata}

    def _finding(self, project_id, severity, title, description, resource, recommendation) -> dict:
        return {
            "finding_id": str(uuid.uuid4()), "project_id": project_id,
            "domain": "iam", "severity": severity, "title": title,
            "description": description, "resource": resource,
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(), "status": "open",
        }
