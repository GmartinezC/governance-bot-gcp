"""
Executor: implementa el loop ReAct (Reason + Act) del agente de gobierno.
Coordina el ciclo completo de auditoría por proyecto.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog

from agent.config import Config
from agent.memory import MemoryManager
from agent.planner import Planner
from agent.state import StateStore

logger = structlog.get_logger(__name__)

# Scores máximos por dominio (para normalización)
DOMAIN_WEIGHTS = {
    "iam": 1.5,      # IAM tiene mayor peso — impacto directo en seguridad
    "dlp": 1.3,      # DLP — riesgo de exposición de datos sensibles
    "scc": 1.2,      # Security Command Center findings
    "kms": 1.1,      # Gestión de claves
    "policy": 1.0,
    "bq": 1.0,
    "catalog": 0.9,
    "lineage": 0.8,
}


from agent.tools.registry import ToolRegistry as _ToolRegistry

class _ToolRegistryStub:
    """Compatibilidad hacia atrás — usar ToolRegistry directamente."""

    def execute(self, tool_name: str, project_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Stub — no debería usarse en producción."""
        return {
            "tool": tool_name,
            "project_id": project_id,
            "status": "stub",
            "findings": [],
            "score": 75,
            "details": f"[STUB] Tool '{tool_name}' no implementada aún (Parte 2)",
        }


# ------------------------------------------------------------------
# Executor principal
# ------------------------------------------------------------------

class Executor:
    """
    Implementa el loop ReAct para ejecutar la auditoría de un proyecto GCP.

    Flujo por proyecto:
        1. Carga estado previo (StateStore)
        2. Genera plan (Planner → Gemini)
        3. Loop ReAct: ejecuta cada tarea, observa resultado, actualiza memoria
        4. Calcula GovernanceScore por dominio
        5. Persiste resultados y retorna resumen
    """

    def __init__(
        self,
        config: Config,
        planner: Planner,
        memory: MemoryManager,
        tool_registry: Any,
        state_store: StateStore,
    ) -> None:
        self.config = config
        self.planner = planner
        self.memory = memory
        self.tool_registry = tool_registry
        self.state_store = state_store
        self._log = logger.bind(component="Executor")

    def run(self, project_id: str) -> Dict[str, Any]:
        """
        Ejecuta el ciclo completo de auditoría para un proyecto.

        Args:
            project_id: ID del proyecto GCP a auditar.

        Returns:
            Dict con:
              - project_id: str
              - run_id: str (UUID único por ejecución)
              - scores: dict dominio → 0-100
              - findings: list de findings encontrados
              - tasks_executed: int
              - tasks_failed: int
              - duration_seconds: float
              - status: "completed" | "partial" | "failed"
              - started_at: ISO timestamp
              - completed_at: ISO timestamp
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        self._log = self._log.bind(project_id=project_id, run_id=run_id)

        self._log.info("run_iniciado", started_at=started_at.isoformat())

        # Limpiar memoria de runs anteriores
        self.memory.clear()

        results: Dict[str, Any] = {
            "project_id": project_id,
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "tasks_results": {},
            "findings": [],
            "scores": {},
            "tasks_executed": 0,
            "tasks_failed": 0,
            "status": "failed",  # Se actualiza al final si OK
        }

        try:
            # 1. Cargar estado previo del proyecto
            state = self.state_store.get_project_state(project_id)
            self._log.info(
                "estado_cargado",
                tiene_estado=bool(state),
                findings_abiertos=state.get("open_findings_count", 0),
            )

            # Cargar findings abiertos para incluir en el contexto del planner
            open_findings = self.state_store.get_open_findings(project_id)
            state["open_findings"] = open_findings

            # 2. Generar plan con Gemini
            plan = self.planner.create_plan(
                project_id=project_id,
                state=state,
                scope=self.config.audit_scope,
            )
            self._log.info("plan_generado", num_tareas=len(plan))
            self.memory.add_observation("plan", plan)

            # 3. Loop ReAct: ejecutar cada tarea
            for task in plan:
                task_result = self._reason_and_act(task, project_id)
                task_id = task["task_id"]
                results["tasks_results"][task_id] = task_result

                if task_result["status"] == "success":
                    results["tasks_executed"] += 1
                    # Acumular findings del resultado
                    task_findings = task_result.get("findings", [])
                    results["findings"].extend(task_findings)

                    # Persistir findings nuevos en Firestore
                    for finding in task_findings:
                        if finding.get("severity") in ("CRITICAL", "HIGH", "MEDIUM"):
                            try:
                                self.state_store.add_finding(project_id, finding)
                                # Stub de embedding para búsqueda futura
                                self.memory.store_finding_embedding(finding)
                            except Exception as e:
                                self._log.warning(
                                    "error_persistiendo_finding",
                                    error=str(e),
                                    finding_id=finding.get("finding_id"),
                                )
                else:
                    results["tasks_failed"] += 1
                    self._log.warning(
                        "tarea_fallida",
                        task_id=task_id,
                        error=task_result.get("error"),
                    )

            # 4. Calcular GovernanceScore por dominio
            results["scores"] = self._calculate_scores(results["tasks_results"])

            # 5. Actualizar estado del proyecto en Firestore
            completed_at = datetime.now(timezone.utc)
            duration = (completed_at - started_at).total_seconds()

            new_state = {
                "last_run": completed_at.isoformat(),
                "last_run_id": run_id,
                "scores": results["scores"],
                "open_findings_count": len([
                    f for f in results["findings"]
                    if f.get("severity") in ("CRITICAL", "HIGH", "MEDIUM")
                ]),
                "last_duration_seconds": duration,
            }
            self.state_store.update_project_state(project_id, new_state)

            # Determinar status final
            if results["tasks_failed"] == 0:
                results["status"] = "completed"
            elif results["tasks_executed"] > 0:
                results["status"] = "partial"
            else:
                results["status"] = "failed"

            results["completed_at"] = completed_at.isoformat()
            results["duration_seconds"] = duration

            self._log.info(
                "run_completado",
                status=results["status"],
                duration_seconds=round(duration, 2),
                tasks_executed=results["tasks_executed"],
                tasks_failed=results["tasks_failed"],
                findings_count=len(results["findings"]),
                scores=results["scores"],
            )

        except Exception as e:
            completed_at = datetime.now(timezone.utc)
            results["completed_at"] = completed_at.isoformat()
            results["duration_seconds"] = (completed_at - started_at).total_seconds()
            results["error"] = str(e)
            results["status"] = "failed"
            self._log.error("run_fallido_critico", error=str(e), exc_info=True)

        return results

    def _reason_and_act(self, task: Dict[str, Any], project_id: str) -> Dict[str, Any]:
        """
        Ejecuta una tarea individual del plan (un paso del loop ReAct).

        Razón: evalúa qué tool usar y cómo, dado el contexto acumulado.
        Acción: invoca la tool y registra el resultado.

        Args:
            task: Dict con task_id, tool, description, priority.
            project_id: ID del proyecto a auditar.

        Returns:
            Dict con: status, tool, task_id, findings, score, details, duration_ms.
        """
        task_id = task["task_id"]
        tool_name = task["tool"]
        description = task["description"]
        priority = task.get("priority", 2)

        self._log.info(
            "ejecutando_tarea",
            task_id=task_id,
            tool=tool_name,
            priority=priority,
            description=description[:100],
        )

        start_time = time.monotonic()
        attempt = 0
        max_attempts = self.config.max_retries

        last_error: Optional[Exception] = None

        while attempt < max_attempts:
            attempt += 1
            try:
                # RAZÓN: incluir contexto acumulado en la ejecución
                context = self.memory.get_context()

                # ACCIÓN: llamar a la tool correspondiente
                tool_result = self.tool_registry.run_tool(
                    tool_name,
                    project_id=project_id,
                )

                duration_ms = int((time.monotonic() - start_time) * 1000)

                result = {
                    "status": "success",
                    "tool": tool_name,
                    "task_id": task_id,
                    "findings": tool_result.get("findings", []),
                    "score": tool_result.get("score"),
                    "details": tool_result.get("details", ""),
                    "duration_ms": duration_ms,
                    "attempt": attempt,
                }

                # Guardar observación en memoria de corto plazo
                self.memory.add_observation(f"result_{task_id}", {
                    "tool": tool_name,
                    "findings_count": len(result["findings"]),
                    "score": result["score"],
                    "details_preview": str(tool_result.get("details", ""))[:200],
                })

                self._log.info(
                    "tarea_exitosa",
                    task_id=task_id,
                    tool=tool_name,
                    duration_ms=duration_ms,
                    findings_count=len(result["findings"]),
                    score=result.get("score"),
                )

                return result

            except Exception as e:
                last_error = e
                self._log.warning(
                    "error_en_tarea",
                    task_id=task_id,
                    tool=tool_name,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(e),
                )
                if attempt < max_attempts:
                    # Backoff lineal simple entre reintentos
                    time.sleep(2 * attempt)

        # Todos los intentos fallaron
        duration_ms = int((time.monotonic() - start_time) * 1000)
        self._log.error(
            "tarea_fallida_definitivo",
            task_id=task_id,
            tool=tool_name,
            intentos=attempt,
            error=str(last_error),
        )

        return {
            "status": "failed",
            "tool": tool_name,
            "task_id": task_id,
            "findings": [],
            "score": None,
            "details": f"Falló tras {attempt} intentos",
            "error": str(last_error),
            "duration_ms": duration_ms,
            "attempt": attempt,
        }

    def _calculate_scores(self, task_results: Dict[str, Any]) -> Dict[str, int]:
        """
        Calcula el GovernanceScore por dominio a partir de los resultados de las tareas.

        La lógica:
        - Cada tarea tiene un score 0-100 (retornado por la tool).
        - Si múltiples tareas corresponden al mismo dominio, se promedia ponderado.
        - Tareas fallidas contribuyen con score 0 a su dominio.
        - Dominios sin tareas no aparecen en el resultado.

        Args:
            task_results: Dict task_id → resultado de la tarea.

        Returns:
            Dict dominio → score 0-100.
        """
        # Mapeo de tool name → dominio
        tool_to_domain = {
            "iam_audit": "iam",
            "dlp_scan": "dlp",
            "catalog_check": "catalog",
            "lineage_check": "lineage",
            "policy_check": "policy",
            "bq_governance": "bq",
            "scc_findings": "scc",
            "kms_audit": "kms",
        }

        domain_scores: Dict[str, List[int]] = {}

        for task_id, result in task_results.items():
            tool_name = result.get("tool", "")
            domain = tool_to_domain.get(tool_name)

            if not domain:
                # Intentar inferir dominio del task_id o tool name
                for d in DOMAIN_WEIGHTS:
                    if d in tool_name or d in task_id:
                        domain = d
                        break

            if not domain:
                continue

            if result["status"] == "success" and result.get("score") is not None:
                raw_score = int(result["score"])
            else:
                # Tarea fallida: penalización
                raw_score = 0

            if domain not in domain_scores:
                domain_scores[domain] = []
            domain_scores[domain].append(raw_score)

        # Calcular score final por dominio (promedio de todas las tareas del dominio)
        final_scores: Dict[str, int] = {}
        for domain, scores in domain_scores.items():
            if scores:
                avg = sum(scores) / len(scores)
                final_scores[domain] = round(avg)

        if final_scores:
            self._log.info("scores_calculados", scores=final_scores)
        else:
            self._log.warning("no_se_calcularon_scores", task_results_count=len(task_results))

        return final_scores
