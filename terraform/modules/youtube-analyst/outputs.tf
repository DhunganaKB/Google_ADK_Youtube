output "artifact_registry_url" {
  description = "Base Docker registry URL — use this in the deploy workflow IMAGE env var"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.youtube_analyst.repository_id}"
}

output "service_account_email" {
  description = "Runtime SA email — pass this to `gcloud run deploy --service-account`"
  value       = google_service_account.cloud_run_sa.email
}

output "firestore_database" {
  description = "Firestore database name used by the app"
  value       = google_firestore_database.default.name
}

output "enabled_apis" {
  description = "APIs enabled by this module"
  value       = [for svc in google_project_service.apis : svc.service]
}
