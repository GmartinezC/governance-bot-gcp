"""Policy Tool: audita Org Policies en el proyecto GCP."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import structlog
from google.cloud import orgpolicy_v2
from tenacity import retry, stop_after_attempt, wait_exponential
from agent.tools.registry import BaseTool

log = structlog.get_logger()

CRITICAL_CONSTRAINTS = [
    ("constraints/iam.disableServiceAccountKeyCreation", "Deshabilita creación de keys de SA"),
    ("constraints/storage.uniformBucketLevelAccess",     "Fuerza acceso uniforme en GCS"),
    ("constraints/compute.requireOsLogin",               "Requiere OS Login en VMs"),
    ("constraints/iam.disableServiceAccountCreation",    "Deshabilita creación de SAs"),
    ("constraints/compute.restrictPublicIpOnInstances",  "Restringe IPs públicas en VMs"),
]


class PolicyTool(BaseTool):
    name = "policy_analyzer"
    description = "Audita Org Policies: verifica constraints críticos de seguridad y gobierno de datos."

    def __init__(self, config) -> None:
        self.config = config
        self.policy_client = orgpolicy_v2.OrgPolicyClient()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def run(self, project_id: str, **kwargs) -> dict:
        findings = []
        applied_count = 0

        for constraint, description in CRITICAL_CONSTRAINTS:
            try:
                name = f"projects/{project_id}/policies/{constraint}"
                policy = self.policy_client.get_policy(request=orgpolicy_v2.GetPolicyRequest(name=name))
                if policy and policy.spec and policy.spec.rules:
                    applied_count += 1
                else:
                    findings.append(self._finding(
                        project_id, "HIGH",
                        f"Org Policy no aplicada: {constraint}",
                        f"La policy '{constraint}' ({description}) no está configurada en el proyecto.",
                        f"projects/{project_id}",
                        f"Aplicar la constraint '{constraint}' para reforzar el gobierno de datos."
                    ))
            except Exception as e:
                # Policy no encontrada = no aplicada
                if "NOT_FOUND" in str(e) or "404" in str(e):
                    findings.append(self._finding(
                        project_id, "MEDIUM",
                        f"Org Policy ausente: {constraint}",
                        f"La constraint '{constraint}' ({description}) no está definida.",
                        f"projects/{project_id}",
                        f"Evaluar y aplicar '{constraint}' según política de seguridad organizacional."
                    ))
                else:
                    log.warning("policy_check_error", constraint=constraint, error=str(e))

        total = len(CRITICAL_CONSTRAINTS)
        score = (applied_count / total) * 100 if total > 0 else 0.0
        metadata = {"constraints_checked": total, "constraints_applied": applied_count}

        return {"tool": self.name, "project_id": project_id,
                "status": "ok", "findings": findings, "score": score, "metadata": metadata}

    def _finding(self, project_id, severity, title, description, resource, recommendation) -> dict:
        return {
            "finding_id": str(uuid.uuid4()), "project_id": project_id,
            "domain": "policy", "severity": severity, "title": title,
            "description": description, "resource": resource,
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(), "status": "open",
        }
