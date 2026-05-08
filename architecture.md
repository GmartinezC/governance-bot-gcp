# Arquitectura: Bot Autónomo de Gobierno de Datos en GCP

## Diagrama de Arquitectura

```mermaid
graph TD
    %% ─── TRIGGERS ───
    SCHED["⏰ Cloud Scheduler\n(cron diario / semanal)"]
    EVT["📡 Eventarc\n(cambios IAM, DLP alerts)"]
    MANUAL["👤 Trigger Manual\n(API Gateway / Cloud Run HTTP)"]

    %% ─── AGENTIC HARNESS ───
    subgraph HARNESS["🧠 Agentic Harness — Cloud Run (Job)"]
        PLANNER["📋 Planner\n(Gemini 1.5 Pro via Vertex AI)\nDescompone objetivo → tareas"]
        EXECUTOR["⚙️ Executor\nLoop ReAct: plan → tool → observe → re-plan"]
        MEMORY["💾 Memory Manager\nShort-term: contexto de sesión\nLong-term: Vertex Vector Search"]
        STATE["🗂️ State Store\nFirestore: estado de auditoría,\nresultados previos, diff tracking"]
        TOOLREG["🔧 Tool Registry\nRegistro de herramientas disponibles"]
    end

    %% ─── TOOL LAYER — GCP APIs ───
    subgraph TOOLS["🛠️ Tool Layer — GCP Native APIs"]
        T_IAM["IAM Analyzer Tool\nCloud Asset Inventory API\nIAM Recommender API"]
        T_DLP["DLP Scanner Tool\nCloud DLP API\nInspect + de-identify jobs"]
        T_CATALOG["Data Catalog Tool\nData Catalog API\nMetadata, tags, lineage"]
        T_LINEAGE["Lineage Tool\nData Lineage API\n(BigQuery + Dataflow)"]
        T_POLICY["Policy Tool\nOrg Policy API\nVPC-SC / Access Context Manager"]
        T_BQ["BigQuery Audit Tool\nBigQuery API\nInformation Schema + AUDIT_LOG"]
        T_SCC["Security Command Center Tool\nSCC API\nFindings, vulnerabilities"]
        T_CMEK["Encryption Tool\nCloud KMS API\nCMEK coverage check"]
    end

    %% ─── DATA SOURCES ───
    subgraph SOURCES["📦 Fuentes de Datos GCP"]
        BQ["BigQuery\nDatasets / Tables"]
        GCS["Cloud Storage\nBuckets / Objects"]
        SPANNER["Cloud Spanner"]
        PSQL["Cloud SQL / AlloyDB"]
        LOGBQ["Log Sink → BigQuery\nAudit Logs"]
    end

    %% ─── VECTOR MEMORY ───
    subgraph VMEM["🗄️ Memoria Vectorial"]
        VS["Vertex Vector Search\nEmbeddings de hallazgos\npasados y políticas"]
        EMBED["Vertex AI Embeddings\ntext-embedding-004"]
    end

    %% ─── OUTPUT ───
    subgraph OUTPUT["📤 Output Layer"]
        RPT["📊 Report Builder\nMarkdown / HTML / JSON\nCloud Storage bucket"]
        ALERT["🚨 Alerting\nCloud Monitoring Alerts\nPub/Sub → alertas downstream"]
        DASH["📈 Dashboard\nLooker Studio\n(conectado a BQ results table)"]
        NOTIFY["💬 Notificaciones\nCloud Pub/Sub → \nSlack / Email / Webhook"]
        AUDIT_LOG["📝 Audit Trail\nBigQuery tabla de resultados\nhistórico de runs"]
    end

    %% ─── SEGURIDAD ───
    subgraph SEC["🔐 Seguridad"]
        SA["Service Account\n(mínimo privilegio)"]
        SECRET["Secret Manager\nAPI keys, tokens"]
        VPCSC["VPC Service Controls\nPerímetro de datos"]
    end

    %% ─── FLUJO PRINCIPAL ───
    SCHED --> HARNESS
    EVT --> HARNESS
    MANUAL --> HARNESS

    PLANNER --> EXECUTOR
    EXECUTOR <--> MEMORY
    EXECUTOR <--> STATE
    EXECUTOR --> TOOLREG
    TOOLREG --> TOOLS

    TOOLS --> SOURCES

    MEMORY <--> VMEM
    EMBED --> VS

    EXECUTOR --> OUTPUT
    PLANNER --> OUTPUT

    %% ─── SEGURIDAD ───
    SA -.->|"autentica"| HARNESS
    SECRET -.->|"credenciales"| HARNESS
    VPCSC -.->|"perimetro"| SOURCES

    %% ─── ESTILO ───
    classDef trigger fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef harness fill:#e3f2fd,stroke:#1565c0,color:#0d47a1
    classDef tool fill:#fff3e0,stroke:#e65100,color:#bf360c
    classDef source fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c
    classDef output fill:#e0f2f1,stroke:#00695c,color:#004d40
    classDef security fill:#fce4ec,stroke:#880e4f,color:#560027
    classDef memory fill:#fff8e1,stroke:#f57f17,color:#e65100

    class SCHED,EVT,MANUAL trigger
    class PLANNER,EXECUTOR,MEMORY,STATE,TOOLREG harness
    class T_IAM,T_DLP,T_CATALOG,T_LINEAGE,T_POLICY,T_BQ,T_SCC,T_CMEK tool
    class BQ,GCS,SPANNER,PSQL,LOGBQ source
    class RPT,ALERT,DASH,NOTIFY,AUDIT_LOG output
    class SA,SECRET,VPCSC security
    class VS,EMBED memory
```

## Leyenda de Capas

| Capa | Componentes | Tecnología |
|------|-------------|------------|
| **Orquestación** | Planner, Executor, Memory, State, Tool Registry | Cloud Run Jobs + Gemini 1.5 Pro |
| **Herramientas** | 8 tools especializadas | GCP Native APIs |
| **Memoria** | Short-term (sesión) + Long-term (vectorial) | Firestore + Vertex Vector Search |
| **Triggers** | Scheduled, Event-driven, Manual | Cloud Scheduler + Eventarc |
| **Output** | Reportes, alertas, dashboard, audit trail | GCS + BigQuery + Looker Studio |
| **Seguridad** | Service Account, Secret Manager, VPC-SC | GCP IAM + KMS |
```
