# Remote state stored in GCS so all team members and CI share the same state.
# The bucket must be created manually BEFORE running `terraform init`.
# See: docs/terraform-setup.md for the one-time setup commands.
terraform {
  backend "gcs" {
    bucket = "prod-487713-tfstate" # GCS bucket in the prod project
    prefix = "youtube-analyst"     # folder path inside the bucket
  }
}
