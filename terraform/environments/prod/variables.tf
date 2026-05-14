variable "project_id" {
  description = "GCP Project ID for the production environment"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run and Artifact Registry"
  type        = string
  default     = "us-central1"
}

variable "sa_name" {
  description = "Service account ID for the Cloud Run runtime identity"
  type        = string
  default     = "youtube-analyst-sa"
}

variable "firestore_location" {
  description = "Firestore location ID (nam5 = multi-region US)"
  type        = string
  default     = "nam5"
}
