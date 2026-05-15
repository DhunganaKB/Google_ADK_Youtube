# ── 1. Enable required GCP APIs ──────────────────────────────────────────────
#
# These are the APIs the YouTube Analyst app needs in the target project.
# disable_on_destroy = false means Terraform will NOT turn them off if you
# run `terraform destroy` — safer for shared projects.
#
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",                  # Cloud Run
    "artifactregistry.googleapis.com",     # Artifact Registry (Docker images)
    "firestore.googleapis.com",            # Firestore (session storage)
    "aiplatform.googleapis.com",           # Vertex AI / Gemini
    "youtube.googleapis.com",              # YouTube Data API v3
    "iam.googleapis.com",                  # IAM (service accounts, roles)
    "cloudresourcemanager.googleapis.com", # Resource Manager (needed by Terraform)
    "secretmanager.googleapis.com",        # Secret Manager (API keys at runtime)
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ── 2. Artifact Registry repository ──────────────────────────────────────────
#
# Stores the Docker image that Cloud Run pulls at deploy time.
# Named "youtube-analyst" to match the dev registry convention.
#
resource "google_artifact_registry_repository" "youtube_analyst" {
  project       = var.project_id
  location      = var.region
  repository_id = "youtube-analyst"
  description   = "Docker images for YouTube Analyst"
  format        = "DOCKER"

  depends_on = [google_project_service.apis]
}

# ── 3. Runtime Service Account for Cloud Run ──────────────────────────────────
#
# This is the identity Cloud Run containers run as.
# Separate from the deployer SA (which builds + pushes images via CI/CD).
#
resource "google_service_account" "cloud_run_sa" {
  project      = var.project_id
  account_id   = var.sa_name
  display_name = "YouTube Analyst Cloud Run Runtime SA"
  description  = "Identity used by Cloud Run containers at runtime"
}

# ── 4. IAM roles for the runtime SA ──────────────────────────────────────────
#
# Principle of least privilege — only the roles the app actually needs.
#
resource "google_project_iam_member" "sa_roles" {
  for_each = toset([
    "roles/datastore.user",               # Read/write Firestore (session storage)
    "roles/secretmanager.secretAccessor", # Read secrets (YOUTUBE_API_KEY)
    "roles/aiplatform.user",              # Call Vertex AI / Gemini models
    "roles/logging.logWriter",            # Write structured logs to Cloud Logging
    "roles/monitoring.metricWriter",      # Write metrics to Cloud Monitoring
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"

  depends_on = [google_project_service.apis]
}

# ── 5. Firestore native-mode database ────────────────────────────────────────
#
# "(default)" is the primary database name used by the app.
# location_id "nam5" = multi-region US (best for production resilience).
# prevent_destroy = true: Firestore databases hold session state — never
# accidentally delete this with `terraform destroy`.
#
resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.apis]

  lifecycle {
    prevent_destroy = true
  }
}

# ── 6. Grant runtime SA read access to Artifact Registry ─────────────────────
#
# Cloud Run needs to pull the Docker image. Without this, the deploy succeeds
# but the container fails to start (image pull error).
#
resource "google_artifact_registry_repository_iam_member" "cloud_run_reader" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.youtube_analyst.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}
