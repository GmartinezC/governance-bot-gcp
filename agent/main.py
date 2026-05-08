"""
agent/main.py — Entry point del Cloud Run Job.

Orquesta la auditoría de gobierno de datos sobre los proyectos GCP
configurados en TARGET_PROJECTS. Por cada proyecto: planifica, ejecuta,
genera reporte, persiste en GCS/BQ y envía alertas.
"""

import sys
import traceback

import structlog

from agent.config import Config
from agent.state import StateStore
from agent.memory import MemoryManager
from agent.planner import Planner
from agent.tools.registry import ToolRegistry
from agent.executor import Executor
from agent.output.reporter import Reporter
from agent.output.alerting import Alerter


def _configure_logging(log_level: str) -> None:
    """Configura structlog con JSON renderer compatible con Cloud Logging."""
    import logging

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    """Punto de entrada principal del Cloud Run Job."""

    # Config primero (necesitamos log_level antes de configurar logging)
    config = Config()
    _configure_logging(config.log_level)

    log = structlog.get_logger("main")
    log.info(
        "governance_bot.start",
        projects=config.target_projects,
        scope=config.audit_scope,
        model=config.vertex_model,
    )

    # Inicialización de componentes compartidos
    state_store = StateStore(config=config)
    memory_manager = MemoryManager(config=config)
    planner = Planner(config=config, memory=memory_manager)
    registry = ToolRegistry()
    registry.register_defaults(config)   # registra las 8 tools GCP
    reporter = Reporter(config=config)
    alerter = Alerter(config=config)

    executor = Executor(
        config=config,
        state_store=state_store,
        memory=memory_manager,
        planner=planner,
        registry=registry,
    )

    # Métricas globales del run
    results_per_project: dict[str, dict] = {}
    projects_ok: list[str] = []
    projects_failed: list[str] = []

    for project_id in config.target_projects:
        project_log = log.bind(project_id=project_id)
        project_log.info("governance_bot.project.start")

        try:
            # ── Ejecutar auditoría ─────────────────────────────────────────
            result = executor.run(project_id)
            results_per_project[project_id] = result

            scores: dict = result.get("scores", {})
            findings: list[dict] = result.get("findings", [])
            run_id: str = result["run_id"]

            project_log.info(
                "governance_bot.project.executed",
                run_id=run_id,
                status=result.get("status"),
                tasks_completed=result.get("tasks_completed"),
                tasks_failed=result.get("tasks_failed"),
                findings_count=len(findings),
                score_overall=scores.get("overall"),
            )

            # ── Reporte ───────────────────────────────────────────────────
            report_md = reporter.generate_report(
                project_id=project_id,
                results=result,
                scores=scores,
            )

            gcs_uri = reporter.save_to_gcs(
                content=report_md,
                project_id=project_id,
                run_id=run_id,
            )
            project_log.info("governance_bot.report.saved_gcs", uri=gcs_uri)

            reporter.save_to_bigquery(
                results=result,
                scores=scores,
                project_id=project_id,
                run_id=run_id,
            )
            project_log.info("governance_bot.report.saved_bq")

            # ── Alertas ───────────────────────────────────────────────────
            alerts_sent = alerter.send_alerts(
                project_id=project_id,
                findings=findings,
            )
            project_log.info("governance_bot.alerts.sent", count=alerts_sent)

            projects_ok.append(project_id)

        except Exception as exc:  # noqa: BLE001
            project_log.error(
                "governance_bot.project.failed",
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            projects_failed.append(project_id)
            # Continúa con los demás proyectos

    # ── Resumen final ─────────────────────────────────────────────────────
    total = len(config.target_projects)
    log.info(
        "governance_bot.finish",
        total_projects=total,
        ok=len(projects_ok),
        failed=len(projects_failed),
        projects_ok=projects_ok,
        projects_failed=projects_failed,
    )

    if projects_failed:
        log.warning(
            "governance_bot.exit.partial",
            message="Algunos proyectos fallaron. Revisar logs.",
        )
        sys.exit(1)

    log.info("governance_bot.exit.ok")
    sys.exit(0)


if __name__ == "__main__":
    main()
