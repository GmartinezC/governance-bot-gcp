"""
Configuración central del bot de gobierno de datos.
Lee variables de entorno y provee una instancia singleton de Config.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


# Dominios soportados para el scope de auditoría
ALL_AUDIT_DOMAINS = ["iam", "dlp", "catalog", "lineage", "policy", "bq", "scc", "kms"]


class Config(BaseSettings):
    """
    Configuración del bot leída desde variables de entorno o archivo .env.
    Usar `get_config()` para obtener la instancia singleton.
    """

    # --- GCP General ---
    project_id: str = Field(..., alias="GCP_PROJECT_ID")
    region: str = Field("us-central1", alias="GCP_REGION")

    # --- Firestore ---
    firestore_database: str = Field("(default)", alias="FIRESTORE_DATABASE")

    # --- BigQuery ---
    bq_dataset: str = Field("governance_bot", alias="BQ_DATASET")

    # --- Cloud Storage ---
    gcs_reports_bucket: str = Field(..., alias="GCS_REPORTS_BUCKET")

    # --- Pub/Sub ---
    pubsub_topic_alerts: str = Field(..., alias="PUBSUB_TOPIC_ALERTS")

    # --- Vertex AI ---
    vertex_model: str = Field("gemini-1.5-pro", alias="VERTEX_MODEL")

    # --- Logging ---
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # --- Proyectos a auditar (comma-separated string) ---
    target_projects_raw: str = Field("", alias="TARGET_PROJECTS")

    # --- Scope de auditoría (comma-separated string) ---
    audit_scope_raw: str = Field("full", alias="AUDIT_SCOPE")

    @property
    def target_projects(self) -> List[str]:
        return [p.strip() for p in self.target_projects_raw.split(",") if p.strip()]

    @property
    def audit_scope(self) -> List[str]:
        raw = self.audit_scope_raw.strip().lower()
        if not raw or raw == "full":
            return ALL_AUDIT_DOMAINS
        return [s.strip() for s in raw.split(",") if s.strip()]

    # --- Parámetros de ejecución ---
    max_retries: int = Field(3, alias="MAX_RETRIES")
    run_timeout_seconds: int = Field(1800, alias="RUN_TIMEOUT_SECONDS")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
        "extra": "ignore",
    }

    @property
    def pubsub_topic_path(self) -> str:
        """Path completo del topic de Pub/Sub."""
        return f"projects/{self.project_id}/topics/{self.pubsub_topic_alerts}"

    @property
    def bq_table_runs(self) -> str:
        """Tabla BQ para los resultados de ejecución."""
        return f"{self.project_id}.{self.bq_dataset}.governance_runs"

    @property
    def bq_table_findings(self) -> str:
        """Tabla BQ para los findings individuales."""
        return f"{self.project_id}.{self.bq_dataset}.governance_findings"


@lru_cache(maxsize=1)
def get_config() -> Config:
    """
    Retorna la instancia singleton de Config.
    Se cachea para evitar múltiples lecturas de env vars.
    """
    return Config()
