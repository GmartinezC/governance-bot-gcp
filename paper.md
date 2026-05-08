# Bot Autónomo de Gobierno de Datos en GCP
## Arquitectura basada en Agentic Harness

**Versión:** 1.0  
**Fecha:** Mayo 2026  
**Clasificación:** Propuesta Técnica — Uso Interno / Cliente

---

## 1. Resumen Ejecutivo

Este documento define la arquitectura de un bot autónomo que monitorea y evalúa el estado de gobierno de datos en entornos GCP. El bot opera bajo el patrón **Agentic Harness**: un agente LLM orquestado (basado en Gemini 1.5 Pro vía Vertex AI) que ejecuta ciclos de planificación y acción usando herramientas nativas de GCP para auditar IAM, DLP, Data Catalog, lineage de datos, políticas organizacionales y cobertura de cifrado. El resultado es un sistema que reemplaza auditorías manuales periódicas por un proceso continuo, con capacidad de detectar desviaciones, generar reportes ejecutivos y disparar alertas automáticas — todo corriendo en infraestructura serverless de GCP sin intervención humana en el loop de operación.

---

## 2. Conceptos Clave

### 2.1 Agentic Harness

Un **Agentic Harness** (también llamado Agent Framework o LLM Agent Scaffold) es la capa de infraestructura que envuelve y controla a un agente LLM, transformándolo de un modelo de texto en un sistema autónomo capaz de actuar en el mundo real.

**Componentes fundamentales:**

| Componente | Función |
|-----------|---------|
| **Planner** | Recibe el objetivo y lo descompone en tareas concretas. Usa razonamiento del LLM. |
| **Executor** | Implementa el loop de acción. Itera: selecciona herramienta → ejecuta → observa resultado → re-planifica. |
| **Tool Registry** | Catálogo de funciones/APIs disponibles que el agente puede invocar. Define inputs, outputs y permisos. |
| **Memory (Short-term)** | Contexto de la sesión actual: qué se ha ejecutado, qué se encontró, en qué paso está. |
| **Memory (Long-term)** | Base de conocimiento persistente: hallazgos anteriores, políticas de referencia, baseline de estado. |
| **State Store** | Persistencia de estado entre runs: qué cambió, qué ya se auditó, qué está pendiente. |

**Patrones de razonamiento comunes:**
- **ReAct** (Reason + Act): el agente razona en texto antes de cada acción, mejorando la trazabilidad.
- **Plan-and-Execute**: separación explícita de fase de planeación y fase de ejecución.
- **Reflexión**: el agente evalúa sus propios resultados y corrige errores antes de reportar.

### 2.2 Data Governance en GCP

El gobierno de datos en GCP abarca cinco dominios:

| Dominio | Servicios GCP | Qué mide |
|---------|--------------|----------|
| **Clasificación** | Cloud DLP, Data Catalog Tags | % de datos clasificados, hallazgos de datos sensibles |
| **Acceso y permisos** | IAM, Org Policy, VPC-SC | Permisos excesivos, cuentas inactivas, primitive roles |
| **Metadata y catálogo** | Data Catalog, BigQuery Information Schema | Cobertura de metadata, tablas sin owner, sin descripción |
| **Lineage** | Data Lineage API, Dataflow, BigQuery | Trazabilidad de transformaciones, pipelines documentados |
| **Compliance y cifrado** | Cloud KMS, SCC, Policy Analyzer | CMEK coverage, findings de SCC, adherencia a org policies |

**Métricas de estado de gobierno (ejemplos):**
- IAM: % de roles primitive (Owner/Editor) vs. curated roles
- DLP: % de datasets BigQuery con inspección DLP ejecutada en últimos 30 días
- Catalog: % de tablas con tags de clasificación asignados
- KMS: % de buckets GCS con CMEK habilitado
- Lineage: % de pipelines con linaje registrado

### 2.3 Bot Autónomo vs. Automatización Tradicional

| Aspecto | Automatización Tradicional | Bot Autónomo (Agentic) |
|---------|--------------------------|----------------------|
| **Lógica** | Scripts fijos, if/else codificados | Razonamiento LLM, adapta el plan según hallazgos |
| **Mantenimiento** | Actualizar código ante cada cambio de API/política | El agente infiere cómo usar nuevas APIs con descripción natural |
| **Manejo de errores** | Falla o ignora errores no contemplados | Detecta el error, decide alternativa, documenta la desviación |
| **Reporte** | Output estructurado fijo | Genera narrativa contextual adaptada al hallazgo |
| **Escalabilidad** | Añadir auditoría nueva = nuevo script | Añadir auditoría nueva = registrar nueva tool en el harness |

---

## 3. Arquitectura de la Solución

### 3.1 Visión General

El sistema opera como un **Cloud Run Job** que se activa por scheduler o eventos, ejecuta el ciclo agéntico completo, y persiste resultados en BigQuery y Cloud Storage. No hay servidor permanente — el harness se instancia, trabaja, reporta y termina.

```
[Trigger] → [Cloud Run Job: Agentic Harness] → [GCP APIs: Tools] → [Output: BQ + GCS + Alertas]
                        ↕
              [Firestore: State] + [Vertex Vector Search: Long-term Memory]
```

### 3.2 Componentes del Harness

#### Planner
- Implementado como llamada a **Gemini 1.5 Pro** con un system prompt que define el rol de auditor de gobierno.
- Recibe: scope del proyecto GCP, contexto de runs anteriores (desde State Store), objetivo del run.
- Produce: lista ordenada de tareas de auditoría con herramientas asignadas.
- Ejemplo de output del planner:
  ```
  Tarea 1: Auditar IAM del proyecto X → usar iam_analyzer_tool
  Tarea 2: Verificar cobertura DLP en datasets BigQuery → usar dlp_scanner_tool
  Tarea 3: Revisar tablas sin tags en Data Catalog → usar data_catalog_tool
  ...
  ```

#### Executor
- Implementa el loop **ReAct**: para cada tarea, genera un "pensamiento" (razonamiento), selecciona la tool, ejecuta, observa el resultado, y decide si continuar o re-planificar.
- Maneja reintentos, timeouts, y errores de API de forma autónoma.
- Acumula observaciones en memoria short-term durante el run.

#### Memory Manager
- **Short-term:** dict en memoria del proceso (contexto del run actual, máx. ~100K tokens con Gemini).
- **Long-term:** embeddings de hallazgos, políticas y baselines almacenados en **Vertex Vector Search**. En cada run, recupera los N hallazgos más similares para detectar regresiones o mejoras.

#### State Store (Firestore)
- Documento por proyecto auditado con:
  - Timestamp del último run
  - Scores de gobierno por dominio (0-100)
  - Lista de findings abiertos
  - Hash de configuraciones para detectar cambios
- Permite al planner saber qué cambió desde la última auditoría y priorizar.

#### Tool Registry
- Cada tool es una función Python con schema JSON (compatible con Vertex AI Function Calling).
- El LLM selecciona tools por nombre y descripción — no por código hardcodeado.
- Agregar una nueva auditoría = registrar una nueva función con su descripción.

### 3.3 Servicios GCP Utilizados y Justificación

| Servicio | Rol en la Arquitectura | Justificación |
|----------|----------------------|---------------|
| **Vertex AI (Gemini 1.5 Pro)** | LLM del agente (planner + executor) | Nativo GCP, función calling integrada, contexto 1M tokens |
| **Cloud Run Jobs** | Runtime del harness | Serverless, sin gestión de infra, paga por uso, escala a 0 |
| **Cloud Scheduler** | Trigger periódico | Integración nativa con Cloud Run Jobs |
| **Eventarc** | Trigger por eventos | Reacciona a cambios IAM, DLP alerts en tiempo real |
| **Firestore** | State Store | Latencia baja, sin esquema rígido, ideal para documentos de estado |
| **Vertex Vector Search** | Long-term memory | Managed vector DB en GCP, integración directa con Vertex AI Embeddings |
| **Cloud Asset Inventory** | Inventario de recursos | Vista unificada de assets, IAM policies, org policies |
| **Cloud DLP** | Inspección de datos sensibles | API nativa para clasificación y detección de PII/sensible |
| **Data Catalog** | Metadata y tags | Repositorio centralizado de metadata de GCP |
| **Data Lineage API** | Linaje de datos | Tracking automático de transformaciones en BigQuery/Dataflow |
| **Security Command Center** | Findings de seguridad | Centraliza vulnerabilidades, misconfigurations, compliance |
| **BigQuery** | Audit logs + resultados | Análisis de logs AUDIT, almacenamiento de resultados históricos |
| **Cloud KMS** | Verificación CMEK | Auditar cobertura de cifrado gestionado por cliente |
| **Cloud Storage** | Reportes generados | Almacenamiento de reportes HTML/JSON por run |
| **Pub/Sub + Cloud Monitoring** | Alertas | Notificaciones a Slack/email/webhook |
| **Secret Manager** | Credenciales | Gestión segura de secrets sin hardcoding |

### 3.4 Flujo de Operación del Agente

```
1. TRIGGER (Scheduler / Eventarc / Manual)
   └─► Cloud Run Job arranca

2. INICIALIZACIÓN
   └─► Lee State Store (Firestore): runs anteriores, findings abiertos
   └─► Recupera contexto relevante de Long-term Memory (Vertex Vector Search)
   └─► Configura Tool Registry con credenciales de Secret Manager

3. PLANNING (Gemini 1.5 Pro)
   └─► Input: objetivo + contexto + state
   └─► Output: plan de auditoría priorizado

4. EXECUTION LOOP (ReAct)
   Para cada tarea en el plan:
   a. Gemini razona: "Voy a verificar X porque..."
   b. Selecciona tool del registry
   c. Ejecuta tool (llamada a GCP API)
   d. Observa resultado
   e. Actualiza short-term memory
   f. Re-evalúa: ¿continuar? ¿escalar? ¿re-planificar?

5. SCORING & SYNTHESIS
   └─► Calcula scores de gobierno por dominio (0-100)
   └─► Compara contra baseline en State Store
   └─► Genera narrativa de hallazgos con Gemini

6. OUTPUT
   └─► Escribe reporte a Cloud Storage (HTML/JSON/Markdown)
   └─► Actualiza tabla de resultados en BigQuery
   └─► Publica findings críticos a Pub/Sub → alertas
   └─► Actualiza State Store (Firestore) con nuevo estado

7. MEMORIA
   └─► Vectoriza hallazgos nuevos y los indexa en Vertex Vector Search
   └─► Cloud Run Job termina
```

---

## 4. Capacidades del Agente

### 4.1 Qué Audita

**IAM y Permisos**
- Detección de primitive roles (Owner, Editor, Viewer) en producción
- Service Accounts con roles excesivos
- Cuentas de usuario externas con acceso a proyectos internos
- Bindings de IAM no modificados en >180 días
- Recomendaciones del IAM Recommender sin aplicar

**Cloud DLP**
- % de datasets BigQuery con DLP inspection jobs ejecutados en últimos 30 días
- Hallazgos de datos sensibles sin clasificar: PII, credenciales, datos financieros
- Buckets GCS públicos o con datos sensibles no cifrados
- Comparación de hallazgos DLP entre períodos (tendencia)

**Data Catalog**
- Tablas BigQuery sin tags de clasificación de datos
- Recursos sin owner asignado en Data Catalog
- Tablas sin descripción o metadata incompleta
- Cobertura de business glossary terms

**Data Lineage**
- Pipelines Dataflow/BigQuery sin lineage registrado
- Tablas de destino sin trazabilidad de origen
- Transformaciones no documentadas en Data Catalog

**Compliance y Org Policies**
- Verificación de org policies críticas: `constraints/iam.disableServiceAccountKeyCreation`, `constraints/storage.uniformBucketLevelAccess`, etc.
- Cobertura CMEK en BigQuery datasets y GCS buckets
- Findings abiertos en Security Command Center (HIGH / CRITICAL)
- VPC Service Controls: proyectos fuera del perímetro

### 4.2 Cómo Evalúa el Estado de Gobierno

El agente calcula un **Governance Score** por dominio (0-100) basado en métricas ponderadas:

```
Score IAM = 
  (% roles curated vs primitive) × 0.4 +
  (% SA con privilegio mínimo) × 0.3 +
  (% recomendaciones IAM aplicadas) × 0.3

Score DLP =
  (% datasets con inspección reciente) × 0.5 +
  (% hallazgos críticos resueltos) × 0.5

Score Catalog =
  (% tablas con tags) × 0.4 +
  (% recursos con owner) × 0.3 +
  (% recursos con descripción) × 0.3

Score General = promedio ponderado de dominios
```

El LLM interpreta los scores en contexto: un score de 75 en IAM puede ser crítico si hubo un incremento en roles Owner en los últimos 7 días.

### 4.3 Cómo Reporta y Alerta

**Reportes periódicos (scheduled):**
- Reporte ejecutivo: score general, tendencia, top 5 hallazgos
- Reporte técnico detallado: findings por dominio, recursos afectados, remediaciones sugeridas
- Comparativo temporal: delta vs. run anterior y vs. baseline inicial
- Formatos: HTML (para email/Looker), JSON (para integración), Markdown (para wikis/Confluence)

**Alertas en tiempo real (event-driven):**
- Finding CRITICAL en SCC → alerta inmediata a Pub/Sub
- Cambio IAM que aumenta exposure → alert en <5 minutos vía Eventarc
- Datos sensibles nuevos detectados por DLP → notificación al data owner

**Dashboard continuo:**
- Tabla de resultados en BigQuery actualizada en cada run
- Looker Studio conectado para visualización histórica de governance scores
- Tendencias por proyecto, por dominio, por período

---

## 5. Stack Tecnológico Recomendado

### LLM: Gemini 1.5 Pro en Vertex AI
- **Por qué Gemini:** integración nativa con Function Calling de Vertex AI, ventana de contexto de 1M tokens (crítico para procesar grandes inventarios de assets), sin egress de datos fuera de GCP.
- **Modelo secundario:** Gemini 1.5 Flash para tareas de clasificación/scoring de bajo costo.
- **Embeddings:** `text-embedding-004` para vectorización de hallazgos.

### Orquestación: Google ADK (Agent Development Kit) + LangGraph
- **Google ADK:** framework oficial de Google para agentes con Vertex AI. Integración directa con Function Calling, soporte para multi-agent.
- **LangGraph:** para implementar el grafo de estados del loop ReAct con control explícito de flujo. Más flexible que ADK para patrones complejos.
- **Recomendación:** usar ADK como base, LangGraph para lógica de control del executor.

### Infraestructura: Cloud Run Jobs
- **Por qué Jobs vs Services:** el agente no necesita estar corriendo 24/7 — se activa, trabaja, termina. Jobs es más económico y simple.
- **Alternativa para orquestaciones largas:** Cloud Composer (Airflow) si el flujo supera 1 hora o requiere DAG complejo con paralelismo por proyecto.
- **Container:** imagen Python con ADK/LangGraph, empaquetada en Artifact Registry.

### Storage
- **Firestore (Native mode):** state store del agente. Documentos por proyecto. Consistencia eventual aceptable para este caso.
- **Vertex Vector Search:** long-term memory. Índice ANN con embeddings de hallazgos. Actualización batch post-run.
- **BigQuery:** historial de resultados, audit logs, tabla de findings para análisis SQL.
- **Cloud Storage:** reportes generados (HTML, JSON, Markdown) con lifecycle policy de retención.

### Resumen del Stack

```
LLM:           Gemini 1.5 Pro (Vertex AI)
Embeddings:    text-embedding-004 (Vertex AI)
Framework:     Google ADK + LangGraph
Runtime:       Cloud Run Jobs (Python 3.12)
State:         Firestore (Native)
Vector Memory: Vertex Vector Search
Data Store:    BigQuery + Cloud Storage
Secrets:       Secret Manager
Triggers:      Cloud Scheduler + Eventarc
Alerts:        Pub/Sub + Cloud Monitoring
Dashboard:     Looker Studio → BigQuery
Registry:      Artifact Registry (container images)
```

---

## 6. Consideraciones de Seguridad y Costo

### Seguridad

**Principio de mínimo privilegio:**
El Service Account del agente requiere roles de solo lectura en la mayoría de los servicios. Roles recomendados:
- `roles/cloudasset.viewer`
- `roles/dlp.reader`
- `roles/datacatalog.viewer`
- `roles/iam.securityReviewer`
- `roles/securitycenter.findingsViewer`
- `roles/bigquery.dataViewer` + `roles/bigquery.jobUser`
- `roles/cloudkms.viewer`

**El agente NO debe tener:**
- `roles/editor` ni `roles/owner`
- Capacidad de modificar IAM policies
- Acceso a datos de producción más allá de metadata y muestras DLP

**Otros controles:**
- VPC Service Controls: el Cloud Run Job corre dentro del perímetro de datos
- Todos los secrets en Secret Manager (no env vars)
- Logs de auditoría del propio agente en Cloud Logging
- Revisión periódica de los findings del agente sobre sí mismo (dogfooding)

### Estimación de Costos (mensual, proyecto único)

| Componente | Estimado Mensual |
|-----------|-----------------|
| Vertex AI Gemini 1.5 Pro (4 runs/día × ~50K tokens) | ~USD 80-150 |
| Vertex AI Embeddings | ~USD 5-10 |
| Cloud Run Jobs (4 runs/día × ~10 min) | ~USD 5-15 |
| Firestore (operaciones de lectura/escritura) | ~USD 5-10 |
| Vertex Vector Search (índice small) | ~USD 50-80 |
| BigQuery (storage + queries) | ~USD 10-20 |
| Cloud Storage (reportes) | ~USD 1-3 |
| Cloud DLP (inspección 10 datasets/día) | ~USD 20-40 |
| **Total estimado** | **~USD 175-325/mes** |

> **Optimización:** reducir frecuencia de Gemini 1.5 Pro usando Flash para tareas de scoring, batch DLP jobs semanales en lugar de diarios, y compartir índice Vector Search entre proyectos.

---

## 7. Roadmap Sugerido

### Fase 1 — Foundation (Semanas 1-4)
**Objetivo:** Agente funcional para un proyecto GCP, auditando IAM y DLP.

- [ ] Setup infraestructura base: Cloud Run Job, Firestore, Secret Manager
- [ ] Implementar harness básico con Google ADK: planner + executor (ReAct)
- [ ] Desarrollar tool IAM Analyzer (Cloud Asset Inventory + IAM Recommender)
- [ ] Desarrollar tool DLP Scanner (Cloud DLP API)
- [ ] Output: reporte JSON + tabla BigQuery
- [ ] Trigger: Cloud Scheduler diario
- [ ] Alertas básicas vía Pub/Sub para findings CRITICAL

**Criterio de éxito:** agente corre sin intervención y genera reporte de IAM + DLP coherente.

### Fase 2 — Cobertura Completa (Semanas 5-10)
**Objetivo:** Cobertura de los 5 dominios de gobierno, multi-proyecto, dashboard.

- [ ] Agregar tools: Data Catalog, Data Lineage, Org Policy, SCC, KMS
- [ ] Implementar Governance Score por dominio con comparativo temporal
- [ ] Habilitar long-term memory (Vertex Vector Search)
- [ ] Soporte multi-proyecto (un run por proyecto, o un run paralelo)
- [ ] Dashboard Looker Studio conectado a BigQuery
- [ ] Trigger event-driven vía Eventarc (cambios IAM, DLP alerts)
- [ ] Reportes HTML ejecutivos a Cloud Storage

**Criterio de éxito:** cobertura completa de 5 dominios, detecta regresiones entre runs, dashboard funcional.

### Fase 3 — Inteligencia y Escala (Semanas 11-16)
**Objetivo:** Agente proactivo, multi-tenant, con remediación asistida.

- [ ] Reflexión post-run: el agente evalúa calidad de sus propios hallazgos
- [ ] Sugerencias de remediación con código Terraform / gcloud cuando aplica
- [ ] Integración con JIRA/Ticketing para abrir tickets automáticos en findings críticos
- [ ] Soporte para múltiples organizaciones GCP (configuración por tenant)
- [ ] Comparativa de madurez entre proyectos/equipos
- [ ] Fine-tuning de Gemini con historial de auditorías para mejorar scoring domain-specific
- [ ] SLA tracking: ¿en cuánto tiempo se resuelven los findings críticos?

**Criterio de éxito:** agente genera tickets de remediación accionables, opera en >5 proyectos GCP simultáneamente.

---

## Apéndice: Referencias Técnicas

- [Google ADK Documentation](https://cloud.google.com/vertex-ai/docs/agent-builder)
- [Vertex AI Function Calling](https://cloud.google.com/vertex-ai/docs/generative-ai/multimodal/function-calling)
- [Cloud DLP API](https://cloud.google.com/dlp/docs)
- [Data Catalog API](https://cloud.google.com/data-catalog/docs)
- [Data Lineage API](https://cloud.google.com/data-catalog/docs/concepts/about-data-lineage)
- [Cloud Asset Inventory](https://cloud.google.com/asset-inventory/docs)
- [Security Command Center](https://cloud.google.com/security-command-center/docs)
- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [Vertex Vector Search](https://cloud.google.com/vertex-ai/docs/vector-search/overview)

---

*Documento generado por el equipo técnico. Para uso en propuestas cliente, revisar estimados de costo con precios actuales de GCP Pricing Calculator.*
