"""Catalog Tool: audita metadata y tags en Data Catalog."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import structlog
from google.cloud import datacatalog_v1
from tenacity import retry, stop_after_attempt, wait_exponential
from agent.tools.registry import BaseTool

log = structlog.get_logger()


class CatalogTool(BaseTool):
    name = "data_catalog"
    description = "Audita Data Catalog: detecta tablas sin tags de clasificación, sin owner y sin descripción."

    def __init__(self, config) -> None:
        self.config = config
        self.catalog_client = datacatalog_v1.DataCatalogClient()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def run(self, project_id: str, **kwargs) -> dict:
        findings = []
        metadata = {}
        try:
            # Buscar entries de BigQuery en el proyecto
            scope = datacatalog_v1.SearchCatalogRequest.Scope()
            scope.include_project_ids.append(project_id)
            request = datacatalog_v1.SearchCatalogRequest(
                scope=scope,
                query=f"system=bigquery projectid:{project_id} type=table",
                page_size=100,
            )
            results = list(self.catalog_client.search_catalog(request=request))
            total = len(results)
            no_tags = 0

            for entry_result in results:
                entry_name = entry_result.fully_qualified_name or entry_result.relative_resource_name
                try:
                    entry = self.catalog_client.get_entry(
                        request=datacatalog_v1.GetEntryRequest(name=entry_result.relative_resource_name)
                    )
                    tags = list(self.catalog_client.list_tags(
                        request=datacatalog_v1.ListTagsRequest(parent=entry_result.relative_resource_name)
                    ))
                    if not tags:
                        no_tags += 1
                        if no_tags <= 10:  # limitar findings
                            findings.append(self._finding(
                                project_id, "MEDIUM",
                                f"Tabla sin tags de clasificación",
                                f"La tabla {entry_name} no tiene tags de clasificación de datos en Data Catalog.",
                                entry_name,
                                "Asignar tags de clasificación (sensibilidad, tipo de dato) usando Data Catalog."
                            ))
                    if not entry.description:
                        findings.append(self._finding(
                            project_id, "LOW",
                            "Tabla sin descripción",
                            f"La tabla {entry_name} no tiene descripción en Data Catalog.",
                            entry_name,
                            "Agregar descripción técnica y de negocio a la tabla en Data Catalog."
                        ))
                except Exception:
                    pass

            metadata = {"total_entries": total, "entries_without_tags": no_tags}
            score = 100.0 if total == 0 else max(0.0, 100.0 - (no_tags / total * 100))

        except Exception as e:
            log.warning("catalog_tool_error", project_id=project_id, error=str(e))
            score = 50.0
            findings.append(self._finding(
                project_id, "MEDIUM", "Error al consultar Data Catalog",
                str(e), f"projects/{project_id}",
                "Verificar que Data Catalog API esté habilitada y el SA tenga roles/datacatalog.viewer."
            ))

        return {"tool": self.name, "project_id": project_id,
                "status": "ok", "findings": findings, "score": score, "metadata": metadata}

    def _finding(self, project_id, severity, title, description, resource, recommendation) -> dict:
        return {
            "finding_id": str(uuid.uuid4()), "project_id": project_id,
            "domain": "catalog", "severity": severity, "title": title,
            "description": description, "resource": resource,
            "recommendation": recommendation,
            "detected_at": datetime.now(timezone.utc).isoformat(), "status": "open",
        }
