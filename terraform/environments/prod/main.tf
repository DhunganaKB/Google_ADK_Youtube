terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0" # pinned — prevents surprise upgrades
    }
  }
}

# Authenticates using GOOGLE_APPLICATION_CREDENTIALS env var set by
# google-github-actions/auth in the GitHub Actions workflow.
provider "google" {
  project = var.project_id
  region  = var.region
}

# Call the reusable module that knows how to set up a YouTube Analyst environment.
# If you ever need a "staging" env, create terraform/environments/staging/ and
# point it at the same module with different variable values.
module "youtube_analyst" {
  source = "../../modules/youtube-analyst"

  project_id         = var.project_id
  region             = var.region
  sa_name            = var.sa_name
  firestore_location = var.firestore_location
}
