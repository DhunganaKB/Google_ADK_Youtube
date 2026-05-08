# Deployment Guide — YouTube Analyst on Google Cloud Run

This document records every step taken to set up CI/CD from GitHub → Artifact Registry → Cloud Run.

---

## Architecture Overview

```
Developer pushes to main
        │
        ▼
GitHub Actions (deploy.yml)
        │
        ├─ Authenticates to GCP (service account key)
        ├─ Builds Docker image
        ├─ Pushes to Artifact Registry
        │       us-central1-docker.pkg.dev/deve-487713/youtube-analyst/app
        │
        └─ Deploys to Cloud Run
                Service: youtube-analyst
                Region:  us-central1
                Runtime SA: airbnb-rag-sa@deve-487713.iam.gserviceaccount.com
```

---

## Step 1 — GCP APIs Enabled

The following APIs were enabled on project `deve-487713`:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  --project=deve-487713
```

---

## Step 2 — Artifact Registry Repository

A dedicated Docker registry was created for this project:

```bash
gcloud artifacts repositories create youtube-analyst \
  --repository-format=docker \
  --location=us-central1 \
  --description="Docker images for YouTube Analyst Cloud Run service" \
  --project=deve-487713
```

Image path: `us-central1-docker.pkg.dev/deve-487713/youtube-analyst/app`

---

## Step 3 — Service Account IAM Roles

Service account: `airbnb-rag-sa@deve-487713.iam.gserviceaccount.com`

The following roles were granted (some were pre-existing):

| Role | Purpose | Status |
|---|---|---|
| `roles/run.admin` | Deploy and manage Cloud Run services | Added |
| `roles/iam.serviceAccountUser` | Assign runtime SA during deployment | Added |
| `roles/artifactregistry.writer` | Push Docker images | Added |
| `roles/datastore.user` | Firestore read/write at runtime | Added |
| `roles/aiplatform.user` | Vertex AI / Gemini API calls | Pre-existing |
| `roles/artifactregistry.reader` | Pull Docker images | Pre-existing |
| `roles/storage.objectCreator` | Write GCS artifacts | Pre-existing |
| `roles/storage.objectViewer` | Read GCS artifacts | Pre-existing |

```bash
for ROLE in roles/run.admin roles/iam.serviceAccountUser \
            roles/artifactregistry.writer roles/datastore.user; do
  gcloud projects add-iam-policy-binding deve-487713 \
    --member="serviceAccount:airbnb-rag-sa@deve-487713.iam.gserviceaccount.com" \
    --role="$ROLE" --condition=None --quiet
done
```

---

## Step 4 — Dockerfile

A two-stage Dockerfile was created at the repo root:

- **Stage 1 (builder):** Installs Python dependencies using `uv` into the system Python.
- **Stage 2 (runtime):** Copies only installed packages and app source — no build tools in the final image.
- Cloud Run injects `PORT` at runtime; the app reads it via `$PORT` (default `8080`).

Key decisions:
- `python:3.13-slim` matches the project's `requires-python = ">=3.13,<3.14"`
- `uv sync --frozen --no-dev` ensures the lock file is respected, dev deps excluded
- Two-stage build keeps the final image lean

---

## Step 5 — main.py PORT update

Cloud Run sets the `PORT` environment variable dynamically. Updated `main.py` `start()` function:

```python
port = int(os.environ.get("PORT", 8000))
uvicorn.run("youtube_analyst.main:app", host="0.0.0.0", port=port, reload=True)
```

The `Dockerfile` CMD uses `$PORT` directly so `start()` is not called in the container.

---

## Step 6 — GitHub Secrets

Four secrets were set on `DhunganaKB/Google_ADK_Youtube` using the `gh` CLI.
The SA key was generated and piped directly into `gh secret set` — it was never written to disk.

```bash
# SA key (never written to disk)
gcloud iam service-accounts keys create /dev/stdout \
  --iam-account=airbnb-rag-sa@deve-487713.iam.gserviceaccount.com \
  --project=deve-487713 2>/dev/null \
| gh secret set GCP_SA_KEY --repo DhunganaKB/Google_ADK_Youtube

# Other secrets
gh secret set GCP_PROJECT_ID --body "deve-487713"  --repo DhunganaKB/Google_ADK_Youtube
gh secret set GCP_REGION     --body "us-central1"  --repo DhunganaKB/Google_ADK_Youtube
gh secret set YOUTUBE_API_KEY --body "<key>"       --repo DhunganaKB/Google_ADK_Youtube
```

| Secret | Value |
|---|---|
| `GCP_SA_KEY` | JSON key for `airbnb-rag-sa` |
| `GCP_PROJECT_ID` | `deve-487713` |
| `GCP_REGION` | `us-central1` |
| `YOUTUBE_API_KEY` | YouTube Data API v3 key |

---

## Step 7 — GitHub Actions Workflow

File: `.github/workflows/deploy.yml`
Trigger: every push to `main` (or manual via `workflow_dispatch`)

Pipeline steps:
1. **Checkout** — fetch source
2. **Auth** — authenticate to GCP using `GCP_SA_KEY`
3. **Setup gcloud** — install and configure the Cloud SDK
4. **Docker auth** — configure Docker for `us-central1-docker.pkg.dev`
5. **Build** — `docker build` tagged with git SHA and `latest`
6. **Push** — both tags pushed to Artifact Registry
7. **Deploy** — `gcloud run deploy` with all env vars injected
8. **Print URL** — outputs the live service URL

Cloud Run deployment flags:
```
--memory 2Gi        # agent needs headroom for LLM responses
--cpu 2             # 2 vCPU for concurrent requests
--timeout 300       # 5 min for long agent runs
--min-instances 0   # scale to zero when idle (cost saving)
--max-instances 10  # cap to control costs
--allow-unauthenticated  # public API endpoint
```

---

## Local Development

```bash
cp .env.example .env        # fill in your values
make install                # create .venv with uv
make api_server             # run FastAPI on :8000
```

Test:
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "find latest gen ai videos", "user_id": "kamal", "session_id": "12345"}'
```

---

## Manual Deployment (without CI/CD)

```bash
# Authenticate
gcloud auth configure-docker us-central1-docker.pkg.dev

# Build & push
IMAGE=us-central1-docker.pkg.dev/deve-487713/youtube-analyst/app
docker build -t $IMAGE:latest .
docker push $IMAGE:latest

# Deploy
gcloud run deploy youtube-analyst \
  --image $IMAGE:latest \
  --region us-central1 \
  --project deve-487713 \
  --service-account airbnb-rag-sa@deve-487713.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 300 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=deve-487713,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=1,YOUTUBE_API_KEY=<your-key>"
```

---

## Next Steps / Improvements

- [ ] Move `YOUTUBE_API_KEY` to GCP Secret Manager and mount it in Cloud Run (`--set-secrets`)
- [ ] Add `roles/secretmanager.secretAccessor` to the SA when using Secret Manager
- [ ] Add a `make docker-build` and `make docker-run` target for local container testing
- [ ] Add Artifact Registry image vulnerability scanning
- [ ] Set up a staging environment (push to `staging` branch → separate Cloud Run service)
