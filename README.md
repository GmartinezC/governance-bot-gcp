# Bot Autónomo de Gobierno de Datos en GCP

Bot basado en **Agentic Harness** que audita automáticamente el estado de gobierno de datos en proyectos GCP. Corre como **Cloud Run Job** usando **Gemini 1.5 Pro** (Vertex AI) con un loop ReAct para planificar y ejecutar auditorías de IAM, DLP, Data Catalog, Lineage, Org Policies, BigQuery, SCC y KMS.

---

## Arquitectura

```
[Cloud Scheduler / Eventarc]
         │
         ▼
[Cloud Run Job — Agentic Harness]
  ├── Planner (Gemini 1.5 Pro)
  ├── Executor (ReAct loop)
  ├── Memory (Firestore + Vertex Vector Search)
  └── Tools: IAM · DLP · Catalog · Lineage · Policy · BQ · SCC · KMS
         │
         ▼
[Output: GCS Reports · BigQuery · Pub/Sub Alertas · Looker Studio]
```

Ver `architecture.drawio` para el diagrama completo con iconos GCP.

---

## Pre-requisitos

- [gcloud CLI](https://cloud.google.com/sdk) configurado con proyecto activo
- [Terraform](https://terraform.io) >= 1.6
- [Docker](https://docker.com) para build de imagen
- Proyecto GCP con billing habilitado

---

## Setup rápido

### 1. Clonar y configurar variables

```bash
git clone <repo-url>
cd proyecto-harness
cp .env.example .env
# Editar .env con tus valores
```

### 2. Desplegar infraestructura con Terraform

```bash
cd infra/

# Crear archivo de variables
cat > terraform.tfvars <<EOF
project_id      = "mi-proyecto-gcp"
region          = "us-central1"
environment     = "prod"
gcs_backend_bucket = "mi-proyecto-tfstate"
target_projects = ["proyecto-a", "proyecto-b"]
scheduler_cron  = "0 6 * * *"
alert_email     = "equipo@empresa.com"
EOF

terraform init -backend-config="bucket=mi-proyecto-tfstate"
terraform plan
terraform apply
```

### 3. Build y push de la imagen Docker

```bash
# Autenticar Docker con Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build y push
docker build -t us-central1-docker.pkg.dev/MI_PROYECTO/governance-bot/governance-bot:latest .
docker push us-central1-docker.pkg.dev/MI_PROYECTO/governance-bot/governance-bot:latest
```

### 4. Primer run manual

```bash
gcloud run jobs execute governance-bot \
  --region us-central1 \
  --project MI_PROYECTO
```

---

## Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `GCP_PROJECT_ID` | Proyecto GCP donde corre el bot | — |
| `GCP_REGION` | Región GCP | `us-central1` |
| `TARGET_PROJECTS` | Proyectos a auditar (comma-separated) | — |
| `AUDIT_SCOPE` | Dominios a auditar | `iam,dlp,catalog,lineage,policy,bq,scc,kms` |
| `VERTEX_MODEL` | Modelo Gemini a usar | `gemini-1.5-pro` |
| `GCS_REPORTS_BUCKET` | Bucket para reportes | — |
| `BQ_DATASET` | Dataset BigQuery | `governance_bot` |
| `PUBSUB_TOPIC_ALERTS` | Topic de alertas | `governance-alerts` |
| `LOG_LEVEL` | Nivel de logging | `INFO` |

---

## Uso

### Ver reportes generados

```bash
gsutil ls gs://MI_PROYECTO-governance-reports/reports/
gsutil cat gs://MI_PROYECTO-governance-reports/reports/proyecto-a/2026-05-08/run-id.md
```

### Consultar resultados en BigQuery

```sql
SELECT project_id, run_date, score_overall, findings_critical, findings_high
FROM `MI_PROYECTO.governance_bot.governance_runs`
ORDER BY run_date DESC
LIMIT 20;
```

### Ver alertas en Pub/Sub

```bash
gcloud pubsub subscriptions pull governance-alerts-sub --auto-ack --limit=10
```

### Trigger manual por proyecto específico

```bash
gcloud run jobs execute governance-bot \
  --region us-central1 \
  --update-env-vars TARGET_PROJECTS=proyecto-especifico
```

---

## Estructura del proyecto

```
proyecto-harness/
├── agent/
│   ├── main.py           # Entry point Cloud Run Job
│   ├── config.py         # Configuración via env vars
│   ├── planner.py        # Planner — Gemini 1.5 Pro
│   ├── executor.py       # Executor — loop ReAct
│   ├── memory.py         # Memory Manager
│   ├── state.py          # State Store (Firestore)
│   ├── tools/            # 8 tools GCP nativas
│   └── output/           # Reporter + Alerter
├── infra/                # Terraform IaC
│   ├── apis.tf           # Habilitación de APIs
│   ├── iam.tf            # Service Account + roles
│   ├── storage.tf        # GCS + Firestore + Artifact Registry
│   ├── compute.tf        # Cloud Run Job + Secret Manager
│   ├── scheduler.tf      # Cloud Scheduler + Pub/Sub
│   └── bigquery.tf       # Dataset + tablas
├── Dockerfile
├── requirements.txt
├── cloudbuild.yaml       # CI/CD pipeline
└── architecture.drawio   # Diagrama de arquitectura
```

---

## Costos estimados

Ver `costos-gcp.xlsx` para el detalle por servicio y escenario:

| Escenario | Proyectos | Mensual | Anual |
|-----------|-----------|---------|-------|
| Startup | 1 | ~$207 | ~$2,485 |
| Empresa | 5 | ~$601 | ~$7,215 |
| Enterprise | 20 | ~$2,188 | ~$26,254 |

> El costo mayor es Vertex Vector Search (~$108/mes por nodo base).  
> Reducible con Committed Use Discounts en Vertex AI.

---

## CI/CD

El pipeline `cloudbuild.yaml` se activa en cada push a `main`:
1. Build de imagen Docker
2. Push a Artifact Registry
3. Update del Cloud Run Job con la nueva imagen

```bash
# Conectar Cloud Build al repo
gcloud builds triggers create github \
  --repo-name=proyecto-harness \
  --repo-owner=MI_ORG \
  --branch-pattern=main \
  --build-config=cloudbuild.yaml
```
