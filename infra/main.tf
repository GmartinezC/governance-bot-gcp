terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # NOTA: el backend GCS no acepta variables — configurar en el comando init:
  # terraform init -backend-config="bucket=MI_PROYECTO-tfstate" \
  #               -backend-config="prefix=terraform/governance-bot"
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  common_labels = {
    project     = "governance-bot"
    environment = var.environment
    managed_by  = "terraform"
  }
}
