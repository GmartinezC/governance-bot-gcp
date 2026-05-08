"""Tool Registry: registra y resuelve tools del agente."""
from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

log = structlog.get_logger()


class BaseTool(ABC):
    """Interfaz base para todas las tools GCP."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, project_id: str, **kwargs) -> dict:
        """
        Ejecuta la tool y retorna:
        {
          "tool": str, "project_id": str, "status": "ok"|"error",
          "findings": list[dict], "score": float, "metadata": dict
        }
        """


class ToolRegistry:
    """Registra y resuelve tools disponibles para el agente."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        log.debug("tool_registered", name=tool.name)

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise KeyError(f"Tool '{name}' no registrada. Disponibles: {self.list_tools()}")
        return self._tools[name]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def run_tool(self, name: str, project_id: str, **kwargs) -> dict:
        """Ejecuta una tool por nombre con manejo de errores."""
        try:
            tool = self.get(name)
            log.info("tool_running", tool=name, project_id=project_id)
            result = tool.run(project_id, **kwargs)
            log.info("tool_completed", tool=name, status=result.get("status"),
                     findings=len(result.get("findings", [])), score=result.get("score"))
            return result
        except Exception as e:
            log.error("tool_failed", tool=name, project_id=project_id, error=str(e))
            return {"tool": name, "project_id": project_id, "status": "error",
                    "findings": [], "score": 0.0, "metadata": {"error": str(e)}}

    def register_defaults(self, config) -> None:
        """Registra las 8 tools estándar de gobierno de datos."""
        from agent.tools.iam_tool import IAMTool
        from agent.tools.dlp_tool import DLPTool
        from agent.tools.catalog_tool import CatalogTool
        from agent.tools.lineage_tool import LineageTool
        from agent.tools.policy_tool import PolicyTool
        from agent.tools.bigquery_tool import BigQueryTool
        from agent.tools.scc_tool import SCCTool
        from agent.tools.kms_tool import KMSTool

        for tool_cls in [IAMTool, DLPTool, CatalogTool, LineageTool,
                         PolicyTool, BigQueryTool, SCCTool, KMSTool]:
            self.register(tool_cls(config))
        log.info("default_tools_registered", count=len(self._tools))
