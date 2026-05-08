# PROJECT_CONTEXT.md — Memoria del Proyecto
> Archivo de referencia compartido entre todas las partes del desarrollo.
> Actualizar al completar cada parte.

---

## Descripción General

**Proyecto:** Bot Autónomo de Gobierno de Datos en GCP  
**Patrón:** Agentic Harness (ReAct loop con Gemini 1.5 Pro)  
**Runtime:** Cloud Run Jobs (serverless, se activa por scheduler o eventos)  
**Lenguaje:** Python 3.12  
**IaC:** Terraform  

---

## Estructura de Carpetas

```
proyecto-harness/
├── agent/                        # Código Python del agente
│   ├── __init__.py
│   ├── main.py                   # Entry point Cloud Run Job
│   ├── config.py                 # Config via Pydantic + env vars
│   ├── planner.py                # Planner — llama a Gemini para crear plan de tareas
│   ├── executor.py               # Executor — loop ReAct
│   ├── memory.py                 # Memory Manager (short-term + stubs long-term)
│   ├── state.py                  # State Store — Firestore
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py           # Tool Registry — registra y resuelve tools
│   │   ├── iam_tool.py           # Cloud Asset Inventory + IAM Recommender
│   │   ├── dlp_tool.py           # Cloud DLP — inspección de datos sensibles
│   │   ├── catalog_tool.py       # Data Catalog — metadata y tags
│   │   ├── lineage_tool.py       # Data Lineage API
│   │   ├── policy_tool.py        # Org Policy + VPC-SC
│   │   ├── bigquery_tool.py      # BigQuery Audit — Information Schema + logs
│   │   ├── scc_tool.py           # Security Command Center — findings
│   │   └── kms_tool.py           # Cloud KMS — CMEK coverage
│   └── output/
│       ├── __init__.py
│       ├── reporter.py           # Genera reporte MD + sube a GCS + escribe BQ
│       └── alerting.py           # Pub/Sub — alertas por findings HIGH/CRITICAL
├── infra/                        # Terraform IaC
│   ├── main.tf                   # Provider, backend
│   ├── variables.tf              # Variables de entrada
│   ├── outputs.tf                # Outputs del deployment
│   ├── apis.tf                   # Habilita APIs GCP requeridas
│   ├── iam.tf                    # Service Account + roles (mínimo privilegio)
│   ├── storage.tf                # GCS bucket (reportes) + Firestore + Artifact Registry
│   ├── compute.tf                # Cloud Run Job + Secret Manager
│   ├── scheduler.tf              # Cloud Scheduler + Eventarc
│   └── bigquery.tf               # Dataset + tablas (governance_runs, findings)
├── Dockerfile                    # Imagen Python 3.12 slim
├── requirements.txt
├── .env.example
├── cloudbuild.yaml               # CI/CD pipeline
├── PROJECT_CONTEXT.md            # Este archivo
└── README.md
```

---

## Variables de Entorno (`.env.example`)

```env
GCP_PROJECT_ID=my-project-id
GCP_REGION=us-central1
FIRESTORE_DATABASE=(default)
BQ_DATASET=governance_bot
GCS_REPORTS_BUCKET=my-project-governance-reports
PUBSUB_TOPIC_ALERTS=governance-alerts
VERTEX_MODEL=gemini-1.5-pro
LOG_LEVEL=INFO
TARGET_PROJECTS=project-a,project-b,project-c
AUDIT_SCOPE=iam,dlp,catalog,lineage,policy,bq,scc,kms
```

---

## Interfaces Clave (contratos entre módulos)

### Config (`agent/config.py`)
```python
class Config(BaseSettings):
    project_id: str
    region: str = "us-central1"
    firestore_database: str = "(default)"
    bq_dataset: str = "governance_bot"
    gcs_reports_bucket: str
    pubsub_topic_alerts: str
    vertex_model: str = "gemini-1.5-pro"
    log_level: str = "INFO"
    target_projects: list[str]   # parsed from comma-separated env var
    audit_scope: list[str]       # parsed from comma-separated env var
    max_retries: int = 3
    run_timeout_seconds: int = 1800
```

### Tool (interfaz base de todas las tools)
```python
class BaseTool:
    name: str                    # identificador único, ej: "iam_analyzer"
    description: str             # descripción en lenguaje natural para el LLM
    
    def run(self, project_id: str, **kwargs) -> dict:
        """
        Retorna dict con:
        {
          "tool": str,
          "project_id": str,
          "status": "ok" | "error",
          "findings": list[dict],   # lista de hallazgos
          "score": float,           # 0-100 score del dominio
          "metadata": dict          # datos adicionales
        }
        """
```

### Finding (estructura estándar)
```python
{
    "finding_id": str,           # UUID
    "project_id": str,
    "domain": str,               # iam | dlp | catalog | lineage | policy | bq | scc | kms
    "severity": str,             # LOW | MEDIUM | HIGH | CRITICAL
    "title": str,
    "description": str,
    "resource": str,             # recurso GCP afectado
    "recommendation": str,
    "detected_at": str,          # ISO datetime
    "status": str                # open | resolved
}
```

### GovernanceScore (estructura de scores)
```python
{
    "iam": float,        # 0-100
    "dlp": float,
    "catalog": float,
    "lineage": float,
    "policy": float,
    "bq": float,
    "scc": float,
    "kms": float,
    "overall": float     # promedio ponderado
}
```

### ToolRegistry (`agent/tools/registry.py`)
```python
class ToolRegistry:
    def register(self, tool: BaseTool) -> None
    def get(self, name: str) -> BaseTool
    def list_tools(self) -> list[str]
    def run_tool(self, name: str, project_id: str, **kwargs) -> dict
```

### StateStore (`agent/state.py`)
```python
class StateStore:
    # Firestore: colección "governance_bot", doc "projects/{project_id}"
    def get_project_state(self, project_id: str) -> dict
    def update_project_state(self, project_id: str, state: dict) -> None
    def get_open_findings(self, project_id: str) -> list[dict]
    def add_finding(self, project_id: str, finding: dict) -> None
    def resolve_finding(self, project_id: str, finding_id: str) -> None
```

### Planner (`agent/planner.py`)
```python
class Planner:
    def create_plan(self, project_id: str, state: dict, scope: list[str]) -> list[dict]:
        """
        Retorna:
        [
          {
            "task_id": str,
            "tool": str,           # nombre de la tool a ejecutar
            "description": str,
            "priority": int        # 1=alta, 2=media, 3=baja
          }
        ]
        """
```

### Executor (`agent/executor.py`)
```python
class Executor:
    def run(self, project_id: str) -> dict:
        """
        Retorna:
        {
          "project_id": str,
          "run_id": str,
          "started_at": str,
          "finished_at": str,
          "scores": GovernanceScore,
          "findings": list[Finding],
          "tasks_completed": int,
          "tasks_failed": int,
          "status": "ok" | "partial" | "failed"
        }
        """
```

---

## BigQuery Schema

### Tabla: `governance_runs`
| Campo | Tipo | Descripción |
|-------|------|-------------|
| run_id | STRING | UUID del run |
| project_id | STRING | Proyecto auditado |
| run_date | DATE | Fecha del run |
| started_at | TIMESTAMP | Inicio |
| finished_at | TIMESTAMP | Fin |
| score_iam | FLOAT64 | Score IAM 0-100 |
| score_dlp | FLOAT64 | Score DLP 0-100 |
| score_catalog | FLOAT64 | Score Catalog 0-100 |
| score_lineage | FLOAT64 | Score Lineage 0-100 |
| score_policy | FLOAT64 | Score Policy 0-100 |
| score_bq | FLOAT64 | Score BQ 0-100 |
| score_scc | FLOAT64 | Score SCC 0-100 |
| score_kms | FLOAT64 | Score KMS 0-100 |
| score_overall | FLOAT64 | Score general |
| findings_count | INT64 | Total findings |
| findings_critical | INT64 | Findings CRITICAL |
| findings_high | INT64 | Findings HIGH |
| report_gcs_path | STRING | Path del reporte en GCS |
| status | STRING | ok/partial/failed |

### Tabla: `findings`
| Campo | Tipo | Descripción |
|-------|------|-------------|
| finding_id | STRING | UUID |
| run_id | STRING | FK a governance_runs |
| project_id | STRING | Proyecto |
| domain | STRING | Dominio (iam/dlp/etc.) |
| severity | STRING | LOW/MEDIUM/HIGH/CRITICAL |
| title | STRING | Título del hallazgo |
| description | STRING | Descripción |
| resource | STRING | Recurso GCP afectado |
| recommendation | STRING | Acción recomendada |
| detected_at | TIMESTAMP | Cuándo se detectó |
| status | STRING | open/resolved |

---

## Terraform — Recursos a crear

| Recurso | Nombre | Módulo |
|---------|--------|--------|
| Service Account | `governance-bot-sa` | `iam.tf` |
| IAM Roles | viewer roles listados abajo | `iam.tf` |
| GCS Bucket | `{project_id}-governance-reports` | `storage.tf` |
| Firestore DB | `(default)` native mode | `storage.tf` |
| Artifact Registry | `governance-bot` | `storage.tf` |
| Cloud Run Job | `governance-bot` | `compute.tf` |
| Secret Manager | `governance-bot-config` | `compute.tf` |
| BQ Dataset | `governance_bot` | `bigquery.tf` |
| BQ Table | `governance_runs` | `bigquery.tf` |
| BQ Table | `findings` | `bigquery.tf` |
| Cloud Scheduler | `governance-bot-daily` | `scheduler.tf` |
| Pub/Sub Topic | `governance-alerts` | `scheduler.tf` |
| Eventarc Trigger | `governance-iam-changes` | `scheduler.tf` |

### IAM Roles del Service Account
- `roles/cloudasset.viewer`
- `roles/dlp.reader`
- `roles/datacatalog.viewer`
- `roles/iam.securityReviewer`
- `roles/securitycenter.findingsViewer`
- `roles/bigquery.dataViewer`
- `roles/bigquery.jobUser`
- `roles/cloudkms.viewer`
- `roles/orgpolicy.policyViewer`
- `roles/datalineage.viewer`
- `roles/monitoring.viewer`
- `roles/run.invoker` (para self-trigger)
- `roles/storage.objectCreator` (para GCS reports)
- `roles/pubsub.publisher` (para alertas)
- `roles/datastore.user` (para Firestore)

---

## Estado de Implementación

| Parte | Contenido | Estado |
|-------|-----------|--------|
| Parte 1 | Core agente (main, config, planner, executor, memory, state, output) | ⏳ En progreso |
| Parte 2 | Tools GCP (registry + 8 tools) | ⏳ Pendiente |
| Parte 3 | Terraform IaC + Dockerfile + README | ⏳ Pendiente |

---

## Decisiones de Diseño

1. **Google ADK vs LangGraph:** Usar LangGraph para el ReAct loop por mayor control del grafo de estados. ADK como opción futura.
2. **Firestore:** Native mode. Colección `governance_bot`, subcollección `projects`.
3. **Cloud Run Jobs** (no Services): el agente no está corriendo 24/7.
4. **structlog:** para logging JSON compatible con Cloud Logging.
5. **Pydantic v2:** para Config y validación de datos.
6. **tenacity:** para retries en llamadas a APIs GCP y Gemini.
7. **Jinja2:** para templates de reportes Markdown/HTML.
8. **Vertex AI SDK directo** (no LangChain wrapper) para llamadas a Gemini — más control y menos dependencias.
