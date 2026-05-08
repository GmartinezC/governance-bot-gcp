"""
Planner del agente de gobierno de datos.
Usa Gemini (Vertex AI) para generar el plan de auditoría en función del
estado previo del proyecto y el scope solicitado.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from vertexai.generative_models import GenerationConfig, GenerativeModel

from agent.config import Config

logger = structlog.get_logger(__name__)

# ------------------------------------------------------------------
# System prompt del Planner
# ------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
Eres un auditor experto en Gobierno de Datos en Google Cloud Platform.
Tu rol es analizar el estado actual de un proyecto GCP y crear un plan
de auditoría estructurado y priorizado.

CONTEXTO DE TU ROL:
- Trabajas para una consultora de tecnología cloud que realiza auditorías de gobierno de datos.
- Debes ser preciso, técnico y orientado a riesgos reales del negocio.
- Prioriza los dominios con mayor riesgo según el estado previo y el scope solicitado.

DOMINIOS DE AUDITORÍA:
- iam: Gestión de identidades y accesos (IAM policies, service accounts, privilegios excesivos)
- dlp: Prevención de pérdida de datos (datos sensibles expuestos, clasificación)
- catalog: Data Catalog (metadata, etiquetas, clasificación de activos)
- lineage: Linaje de datos (trazabilidad, dependencias entre datasets/tablas)
- policy: Políticas de organización y compliance (org policies, constraints)
- bq: BigQuery governance (datasets públicos, permisos, encriptación, retención)
- scc: Security Command Center (findings de seguridad activos, misconfigurations)
- kms: Gestión de claves (KMS keys, rotación, CMEK en servicios críticos)

REGLAS DE GENERACIÓN DEL PLAN:
1. Solo incluye tareas para los dominios en el scope solicitado.
2. Si hay findings abiertos de alta severidad de runs anteriores, agrégalos con mayor prioridad.
3. Limita el plan a máximo 15 tareas (calidad > cantidad).
4. Cada tarea debe mapear a exactamente una tool disponible.
5. Prioridad: 1=baja, 2=media, 3=alta, 4=crítica.

TOOLS DISPONIBLES:
- iam_audit: Audita IAM policies, service accounts y privilegios en el proyecto.
- dlp_scan: Ejecuta DLP inspection en datasets y buckets del proyecto.
- catalog_check: Verifica cobertura de Data Catalog y calidad de metadata.
- lineage_check: Analiza el linaje de datos en BigQuery y Dataflow.
- policy_check: Revisa org policies y constraints aplicadas al proyecto.
- bq_governance: Audita datasets de BigQuery (permisos, encriptación, labels).
- scc_findings: Lee findings activos de Security Command Center.
- kms_audit: Audita claves KMS, rotación y uso de CMEK.

FORMATO DE RESPUESTA (JSON puro, sin markdown, sin texto adicional):
[
  {
    "task_id": "string único",
    "tool": "nombre_de_la_tool",
    "description": "descripción clara de qué auditar y por qué",
    "priority": 1-4
  }
]
"""


class Planner:
    """
    Genera el plan de auditoría usando Gemini via Vertex AI.
    Implementa retry automático ante errores transitorios de la API.
    """

    def __init__(self, config: Config, vertexai_client: Optional[Any] = None) -> None:
        """
        Args:
            config: Configuración del bot.
            vertexai_client: Cliente de Vertex AI ya inicializado (para testing/inyección).
                             Si es None, se crea un GenerativeModel directamente.
        """
        self.config = config
        self._log = logger.bind(component="Planner")

        if vertexai_client is not None:
            self._model = vertexai_client
        else:
            self._model = GenerativeModel(
                model_name=config.vertex_model,
                system_instruction=PLANNER_SYSTEM_PROMPT,
            )

        self._generation_config = GenerationConfig(
            temperature=0.2,       # Baja creatividad — queremos respuestas consistentes
            max_output_tokens=4096,
            response_mime_type="application/json",
        )

    def create_plan(
        self,
        project_id: str,
        state: Dict[str, Any],
        scope: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Genera el plan de auditoría para un proyecto.

        Args:
            project_id: ID del proyecto GCP a auditar.
            state: Estado previo del proyecto (scores, findings, last_run).
            scope: Lista de dominios a auditar.

        Returns:
            Lista de tareas ordenadas por prioridad descendente.
            Cada tarea tiene: task_id, tool, description, priority.
        """
        self._log.info(
            "creando_plan",
            project_id=project_id,
            scope=scope,
            tiene_estado_previo=bool(state),
        )

        prompt = self._build_prompt(project_id, state, scope)

        try:
            plan = self._call_gemini_with_retry(prompt)
            # Ordenar por prioridad descendente (crítico primero)
            plan.sort(key=lambda t: t.get("priority", 0), reverse=True)
            self._log.info(
                "plan_creado",
                project_id=project_id,
                num_tareas=len(plan),
            )
            return plan
        except Exception as e:
            self._log.error(
                "error_creando_plan",
                project_id=project_id,
                error=str(e),
            )
            # Fallback: plan básico con todas las tools del scope
            return self._fallback_plan(scope)

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _call_gemini_with_retry(self, prompt: str) -> List[Dict[str, Any]]:
        """
        Llama a Gemini con retry automático.
        El decorador @retry maneja reintentos con backoff exponencial.

        Args:
            prompt: Prompt del usuario para esta llamada.

        Returns:
            Lista de tareas parseada desde el JSON de respuesta.
        """
        response = self._model.generate_content(
            prompt,
            generation_config=self._generation_config,
        )

        raw_text = response.text.strip()
        self._log.debug("respuesta_gemini_cruda", preview=raw_text[:200])

        return self._parse_plan_response(raw_text)

    def _build_prompt(
        self,
        project_id: str,
        state: Dict[str, Any],
        scope: List[str],
    ) -> str:
        """
        Construye el prompt del usuario con el contexto del proyecto.

        Args:
            project_id: ID del proyecto.
            state: Estado previo (scores, findings abiertos, etc.).
            scope: Dominios solicitados.
        """
        # Extraer información relevante del estado previo
        scores_previos = state.get("scores", {})
        findings_abiertos = state.get("open_findings_count", 0)
        ultimo_run = state.get("last_run", "nunca")
        findings_criticos = [
            f for f in state.get("open_findings", [])
            if f.get("severity") in ("CRITICAL", "HIGH")
        ]

        prompt_parts = [
            f"PROYECTO A AUDITAR: {project_id}",
            f"SCOPE SOLICITADO: {', '.join(scope)}",
            f"",
            f"ESTADO PREVIO DEL PROYECTO:",
            f"- Último run: {ultimo_run}",
            f"- Findings abiertos totales: {findings_abiertos}",
        ]

        if scores_previos:
            prompt_parts.append("- Scores anteriores por dominio:")
            for domain, score in scores_previos.items():
                emoji = "🔴" if score < 50 else ("🟡" if score < 80 else "🟢")
                prompt_parts.append(f"  {emoji} {domain}: {score}/100")

        if findings_criticos:
            prompt_parts.append(f"")
            prompt_parts.append(f"FINDINGS CRÍTICOS/ALTOS PENDIENTES ({len(findings_criticos)}):")
            for f in findings_criticos[:5]:  # Máximo 5 para no inflar el prompt
                prompt_parts.append(
                    f"  - [{f.get('severity')}] {f.get('domain', '?')}: {f.get('description', 'N/A')}"
                )

        prompt_parts.extend([
            f"",
            f"Genera el plan de auditoría JSON para este proyecto.",
            f"Incluye SOLO dominios del scope solicitado: {', '.join(scope)}.",
            f"Si hay findings críticos pendientes, prioriza esos dominios.",
        ])

        return "\n".join(prompt_parts)

    def _parse_plan_response(self, raw_text: str) -> List[Dict[str, Any]]:
        """
        Parsea la respuesta JSON de Gemini.
        Maneja casos donde el modelo incluye texto extra o markdown.

        Args:
            raw_text: Texto crudo de la respuesta del modelo.

        Returns:
            Lista de dicts con las tareas del plan.
        """
        # Intentar parsear directamente
        try:
            plan = json.loads(raw_text)
            if isinstance(plan, list):
                return self._validate_tasks(plan)
        except json.JSONDecodeError:
            pass

        # Fallback: buscar JSON array en el texto
        match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if match:
            try:
                plan = json.loads(match.group())
                if isinstance(plan, list):
                    return self._validate_tasks(plan)
            except json.JSONDecodeError:
                pass

        self._log.error("error_parseando_respuesta_gemini", raw_preview=raw_text[:500])
        raise ValueError(f"No se pudo parsear la respuesta del modelo como JSON array")

    def _validate_tasks(self, tasks: List[Any]) -> List[Dict[str, Any]]:
        """
        Valida y normaliza las tareas del plan.
        Descarta tareas malformadas, completa campos faltantes.

        Args:
            tasks: Lista cruda de tareas desde Gemini.

        Returns:
            Lista filtrada y normalizada de tareas válidas.
        """
        valid_tasks = []
        seen_ids: set = set()

        for i, task in enumerate(tasks):
            if not isinstance(task, dict):
                continue

            # Asegurar campos mínimos
            task_id = task.get("task_id") or f"task_{i+1:03d}"
            tool = task.get("tool", "")
            description = task.get("description", "Sin descripción")
            priority = int(task.get("priority", 2))

            # Evitar duplicados
            if task_id in seen_ids:
                task_id = f"{task_id}_{i}"
            seen_ids.add(task_id)

            # Validar prioridad en rango
            priority = max(1, min(4, priority))

            valid_tasks.append({
                "task_id": task_id,
                "tool": tool,
                "description": description,
                "priority": priority,
            })

        return valid_tasks

    def _fallback_plan(self, scope: List[str]) -> List[Dict[str, Any]]:
        """
        Plan de fallback cuando Gemini no puede generar el plan.
        Crea una tarea por cada dominio del scope con prioridad media.

        Args:
            scope: Dominios a auditar.

        Returns:
            Plan básico con una tarea por dominio.
        """
        tool_map = {
            "iam": "iam_audit",
            "dlp": "dlp_scan",
            "catalog": "catalog_check",
            "lineage": "lineage_check",
            "policy": "policy_check",
            "bq": "bq_governance",
            "scc": "scc_findings",
            "kms": "kms_audit",
        }

        self._log.warning("usando_plan_fallback", scope=scope)

        return [
            {
                "task_id": f"fallback_{domain}",
                "tool": tool_map.get(domain, f"{domain}_audit"),
                "description": f"Auditoría de dominio {domain} (plan fallback)",
                "priority": 2,
            }
            for domain in scope
            if domain in tool_map
        ]
