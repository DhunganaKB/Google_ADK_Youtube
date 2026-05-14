variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region for Cloud Run and Artifact Registry"
  type        = string
  default     = "us-central1"
}

variable "sa_name" {
  description = "Service account ID for the Cloud Run runtime identity"
  type        = string
  default     = "youtube-analyst-sa"
}

variable "firestore_location" {
  description = "Firestore multi-region or region location ID"
  type        = string
  default     = "nam5" # multi-region US (covers us-central, us-east, us-west)
}
