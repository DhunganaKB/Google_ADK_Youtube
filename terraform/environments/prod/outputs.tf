output "artifact_registry_url" {
  description = "Docker image base URL — set this as IMAGE in deploy-prod.yml"
  value       = module.youtube_analyst.artifact_registry_url
}

output "service_account_email" {
  description = "Runtime SA email — set this in the gcloud run deploy --service-account flag"
  value       = module.youtube_analyst.service_account_email
}

output "firestore_database" {
  description = "Firestore database name"
  value       = module.youtube_analyst.firestore_database
}
