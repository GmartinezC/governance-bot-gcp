variable "project_id" {
  description = "ID del proyecto GCP donde se despliega la infraestructura."
  type        = string
}

variable "region" {
  description = "Región GCP para desplegar los recursos."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Entorno de despliegue (prod, staging, dev)."
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["prod", "staging", "dev"], var.environment)
    error_message = "El entorno debe ser 'prod', 'staging' o 'dev'."
  }
}

variable "gcs_backend_bucket" {
  description = "Nombre del bucket GCS para el backend de Terraform."
  type        = string
}

variable "target_projects" {
  description = "Lista de project IDs a auditar por el bot de gobierno."
  type        = list(string)
}

variable "scheduler_cron" {
  description = "Expresión cron para el Cloud Scheduler (schedule diario del bot)."
  type        = string
  default     = "0 6 * * *"
}

variable "alert_email" {
  description = "Email para recibir alertas de findings HIGH/CRITICAL."
  type        = string
}

variable "job_timeout_seconds" {
  description = "Timeout del Cloud Run Job en segundos"
  type        = number
  default     = 1800
}
