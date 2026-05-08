"""
Gestión de estado persistente en Firestore.
Mantiene el estado de cada proyecto auditado: scores, findings, historial.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from google.cloud import firestore

from agent.config import Config

logger = structlog.get_logger(__name__)

# Paths en Firestore
_COLLECTION_ROOT = "governance_bot"
_COLLECTION_PROJECTS = "projects"
_SUBCOLLECTION_FINDINGS = "findings"


class StateStore:
    """
    Interfaz con Firestore para persistir el estado del bot de gobierno.

    Estructura de documentos:
        governance_bot/projects/{project_id}          → estado general del proyecto
        governance_bot/projects/{project_id}/findings/{finding_id}  → findings individuales
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self._client = firestore.Client(
            project=config.project_id,
            database=config.firestore_database,
        )
        self._log = logger.bind(component="StateStore")

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _project_ref(self, project_id: str) -> firestore.DocumentReference:
        """Referencia al documento de estado del proyecto."""
        return (
            self._client
            .collection(_COLLECTION_ROOT)
            .document(_COLLECTION_PROJECTS)
            .collection(_COLLECTION_PROJECTS)
            .document(project_id)
        )

    def _findings_ref(self, project_id: str) -> firestore.CollectionReference:
        """Referencia a la subcolección de findings del proyecto."""
        return self._project_ref(project_id).collection(_SUBCOLLECTION_FINDINGS)

    # ------------------------------------------------------------------
    # Estado del proyecto
    # ------------------------------------------------------------------

    def get_project_state(self, project_id: str) -> Dict[str, Any]:
        """
        Obtiene el estado actual de un proyecto.

        Returns:
            Dict con scores, findings_count, last_run y metadata.
            Retorna dict vacío si el proyecto no tiene estado previo.
        """
        try:
            doc = self._project_ref(project_id).get()
            if doc.exists:
                state = doc.to_dict() or {}
                self._log.debug("estado_proyecto_cargado", project_id=project_id)
                return state
            else:
                self._log.info(
                    "proyecto_sin_estado_previo",
                    project_id=project_id,
                )
                return {}
        except Exception as e:
            self._log.error(
                "error_cargando_estado",
                project_id=project_id,
                error=str(e),
            )
            return {}

    def update_project_state(self, project_id: str, state_dict: Dict[str, Any]) -> None:
        """
        Actualiza (merge) el estado de un proyecto en Firestore.

        Args:
            project_id: ID del proyecto GCP.
            state_dict: Datos a actualizar (merge, no reemplaza todo).
        """
        try:
            state_dict["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._project_ref(project_id).set(state_dict, merge=True)
            self._log.info("estado_proyecto_actualizado", project_id=project_id)
        except Exception as e:
            self._log.error(
                "error_actualizando_estado",
                project_id=project_id,
                error=str(e),
            )
            raise

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    def get_open_findings(self, project_id: str) -> List[Dict[str, Any]]:
        """
        Retorna todos los findings abiertos (no resueltos) de un proyecto.

        Returns:
            Lista de dicts con los datos del finding más su ID.
        """
        try:
            query = (
                self._findings_ref(project_id)
                .where("status", "==", "open")
                .order_by("severity_rank", direction=firestore.Query.DESCENDING)
            )
            docs = query.stream()
            findings = []
            for doc in docs:
                data = doc.to_dict() or {}
                data["finding_id"] = doc.id
                findings.append(data)
            self._log.debug(
                "findings_abiertos_cargados",
                project_id=project_id,
                count=len(findings),
            )
            return findings
        except Exception as e:
            self._log.error(
                "error_cargando_findings",
                project_id=project_id,
                error=str(e),
            )
            return []

    def add_finding(self, project_id: str, finding: Dict[str, Any]) -> str:
        """
        Agrega un nuevo finding a Firestore.

        Args:
            project_id: ID del proyecto auditado.
            finding: Datos del finding (severity, domain, description, etc.).

        Returns:
            finding_id generado.
        """
        # Mapa de severidad a número para poder ordenar
        severity_rank = {
            "CRITICAL": 4,
            "HIGH": 3,
            "MEDIUM": 2,
            "LOW": 1,
            "INFO": 0,
        }

        finding_id = finding.get("finding_id") or str(uuid.uuid4())
        doc = {
            **finding,
            "finding_id": finding_id,
            "status": "open",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "severity_rank": severity_rank.get(
                finding.get("severity", "INFO").upper(), 0
            ),
        }

        try:
            self._findings_ref(project_id).document(finding_id).set(doc)
            self._log.info(
                "finding_agregado",
                project_id=project_id,
                finding_id=finding_id,
                severity=finding.get("severity"),
                domain=finding.get("domain"),
            )
            return finding_id
        except Exception as e:
            self._log.error(
                "error_agregando_finding",
                project_id=project_id,
                error=str(e),
            )
            raise

    def resolve_finding(self, project_id: str, finding_id: str) -> None:
        """
        Marca un finding como resuelto.

        Args:
            project_id: ID del proyecto.
            finding_id: ID del finding a resolver.
        """
        try:
            self._findings_ref(project_id).document(finding_id).update({
                "status": "resolved",
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            })
            self._log.info(
                "finding_resuelto",
                project_id=project_id,
                finding_id=finding_id,
            )
        except Exception as e:
            self._log.error(
                "error_resolviendo_finding",
                project_id=project_id,
                finding_id=finding_id,
                error=str(e),
            )
            raise
