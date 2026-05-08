"""Alerter: publica findings HIGH/CRITICAL a Pub/Sub."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from google.cloud import pubsub_v1
from tenacity import retry, stop_after_attempt, wait_exponential

from agent.config import Config

log = structlog.get_logger()

ALERT_SEVERITIES = {"HIGH", "CRITICAL"}


class Alerter:
    """Publica alertas de gobierno de datos a Pub/Sub."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = self.publisher.topic_path(
            config.project_id, config.pubsub_topic_alerts
        )

    def send_alerts(self, project_id: str, findings: list[dict]) -> int:
        """Filtra findings HIGH/CRITICAL y los publica. Retorna count enviado."""
        high_findings = [
            f for f in findings if f.get("severity") in ALERT_SEVERITIES
        ]
        count = 0
        for finding in high_findings:
            try:
                self._publish(self._format_alert(finding))
                count += 1
            except Exception as e:
                log.error("alert_publish_failed", finding_id=finding.get("finding_id"), error=str(e))

        log.info("alerts_sent", project_id=project_id, count=count, total_findings=len(findings))
        return count

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _publish(self, payload: dict) -> None:
        """Publica un mensaje a Pub/Sub."""
        data = json.dumps(payload).encode("utf-8")
        future = self.publisher.publish(
            self.topic_path,
            data,
            severity=payload.get("severity", ""),
            domain=payload.get("domain", ""),
        )
        future.result(timeout=30)

    def _format_alert(self, finding: dict) -> dict:
        """Formatea el payload del mensaje de alerta."""
        return {
            "finding_id": finding.get("finding_id", ""),
            "project_id": finding.get("project_id", ""),
            "domain": finding.get("domain", ""),
            "severity": finding.get("severity", ""),
            "title": finding.get("title", ""),
            "resource": finding.get("resource", ""),
            "description": finding.get("description", ""),
            "recommendation": finding.get("recommendation", ""),
            "detected_at": finding.get("detected_at", datetime.now(timezone.utc).isoformat()),
            "alert_sent_at": datetime.now(timezone.utc).isoformat(),
        }
