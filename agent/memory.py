"""
Gestión de memoria del agente.

- Memoria de corto plazo: dict en memoria, vive mientras dura el run.
- Memoria de largo plazo: stubs para Vertex Vector Search (implementación futura).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class MemoryManager:
    """
    Gestiona el contexto acumulado durante un run de auditoría.

    La memoria de corto plazo almacena observaciones del ciclo ReAct actual.
    La memoria de largo plazo (búsqueda semántica) está preparada como stub
    para una implementación futura con Vertex AI Vector Search.
    """

    def __init__(self) -> None:
        # Memoria de corto plazo: contexto del run actual
        self.short_term: Dict[str, Any] = {}
        self._observations_log: List[Dict[str, Any]] = []
        self._log = logger.bind(component="MemoryManager")

    # ------------------------------------------------------------------
    # Memoria de corto plazo
    # ------------------------------------------------------------------

    def add_observation(self, key: str, value: Any) -> None:
        """
        Guarda una observación en la memoria de corto plazo.

        Args:
            key: Clave descriptiva (ej. "iam_audit_result", "dlp_findings").
            value: Valor a almacenar (cualquier tipo serializable).
        """
        self.short_term[key] = value
        entry = {
            "key": key,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": type(value).__name__,
        }
        self._observations_log.append(entry)
        self._log.debug("observacion_guardada", key=key, type=type(value).__name__)

    def get_context(self) -> str:
        """
        Retorna el contexto acumulado como string formateado.
        Útil para incluir en prompts de Gemini.

        Returns:
            String con todas las observaciones en formato legible.
        """
        if not self.short_term:
            return "No hay observaciones previas en esta sesión."

        lines = ["=== Contexto acumulado del run actual ==="]
        for key, value in self.short_term.items():
            lines.append(f"\n### {key}")
            if isinstance(value, (dict, list)):
                # Serializar estructuras complejas como JSON indentado
                try:
                    lines.append(json.dumps(value, indent=2, ensure_ascii=False, default=str))
                except (TypeError, ValueError):
                    lines.append(str(value))
            else:
                lines.append(str(value))

        return "\n".join(lines)

    def get_observation(self, key: str, default: Any = None) -> Any:
        """
        Recupera una observación específica de la memoria de corto plazo.

        Args:
            key: Clave a buscar.
            default: Valor por defecto si no existe.
        """
        return self.short_term.get(key, default)

    def get_all_keys(self) -> List[str]:
        """Retorna todas las claves almacenadas en la memoria de corto plazo."""
        return list(self.short_term.keys())

    def clear(self) -> None:
        """
        Limpia la memoria de corto plazo.
        Llamar al inicio de cada nuevo run de auditoría.
        """
        cleared_count = len(self.short_term)
        self.short_term.clear()
        self._observations_log.clear()
        self._log.info("memoria_limpiada", observaciones_previas=cleared_count)

    def get_observations_log(self) -> List[Dict[str, Any]]:
        """Retorna el log cronológico de observaciones (para auditoría/debug)."""
        return list(self._observations_log)

    # ------------------------------------------------------------------
    # Memoria de largo plazo — STUBS para Vertex Vector Search
    # ------------------------------------------------------------------

    def store_finding_embedding(self, finding: Dict[str, Any]) -> None:
        """
        [STUB] Almacena el embedding de un finding en Vertex AI Vector Search.

        TODO: Implementar con Vertex AI Vector Search.
        - Generar embedding del finding usando text-embedding-004 o similar.
        - Upsert en el índice vectorial de Vector Search.
        - Permite búsqueda semántica de findings similares históricos.

        Args:
            finding: Dict con los datos del finding a indexar.
        """
        self._log.warning(
            "store_finding_embedding_stub",
            mensaje="TODO: Vertex Vector Search — embedding no almacenado",
            finding_id=finding.get("finding_id"),
            domain=finding.get("domain"),
        )
        # Por ahora solo guardamos en memoria de corto plazo como fallback
        embeddings_key = "pending_embeddings"
        pending = self.short_term.get(embeddings_key, [])
        pending.append(finding.get("finding_id", "unknown"))
        self.short_term[embeddings_key] = pending

    def search_similar_findings(
        self, query: str, n: int = 5
    ) -> List[Dict[str, Any]]:
        """
        [STUB] Busca findings similares usando búsqueda semántica vectorial.

        TODO: Implementar con Vertex AI Vector Search.
        - Generar embedding de la query.
        - Consultar el índice de Vector Search.
        - Retornar los n findings más similares con score de similitud.

        Args:
            query: Texto de búsqueda (descripción del issue a buscar).
            n: Número máximo de resultados.

        Returns:
            Lista vacía hasta que se implemente Vector Search.
        """
        self._log.warning(
            "search_similar_findings_stub",
            mensaje="TODO: Vertex Vector Search — búsqueda semántica no disponible",
            query_preview=query[:100],
            n=n,
        )
        return []
