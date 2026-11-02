#!/usr/bin/env bash
# =============================================================================
# Kalika ERP — Cloud Run + Cloud SQL deployment script
#
# Builds the full-stack app (frontend built inside the image, served by the
# FastAPI backend), pushes to Google Artifact Registry, deploys one Cloud Run
# service, and connects it to Cloud SQL.
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh <PROJECT_ID> [REGION] [SERVICE] [IMAGE]
#
# Defaults:
#   PROJECT_ID  : gen-lang-client-0132243782   (set below)
#   REGION      : asia-south1
#   SERVICE     : kalika-erp
#   IMAGE       : asia-south1-docker.pkg.dev/<PROJECT_ID>/kalika-erp/app:latest
# =============================================================================
set -euo pipefail

PROJECT_ID="${1:-gen-lang-client-0132243782}"
REGION="${2:-asia-south1}"
SERVICE="${3:-kalika-erp}"
REPO="${4:-kalika-erp}"
TAG="${5:-latest}"

# Cloud SQL values (EDIT THESE to match your instance)
CLOUD_SQL_INSTANCE="${CLOUD_SQL_INSTANCE:-kalika-erp-db}"        # instance name
CLOUD_SQL_DB_NAME="${CLOUD_SQL_DB_NAME:-kalika_erp}"             # database
CLOUD_SQL_DB_USER="${CLOUD_SQL_DB_USER:-kalika_app}"             # app user
# NOTE: password is NOT read here — set as CLOUD_SQL_DB_PASS env var, or via
# Secret Manager. The script uses Secret Manager secret "kalika-db-password".

CLOUD_SQL_CONNECTION="${PROJECT_ID}:${REGION}:${CLOUD_SQL_INSTANCE}"

IMAGE="$(dirname "$REPO")/$REPO/app:$TAG"
if [[ "$REPO" != *"/"* ]]; then
  IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/app:${TAG}"
fi

echo "🔄 Project : ${PROJECT_ID}"
echo "🔄 Region  : ${REGION}"
echo "🔄 Service : ${SERVICE}"
echo "🔄 Image   : ${IMAGE}"
echo "🔄 Cloud SQL connection : ${CLOUD_SQL_CONNECTION}"

# ---------------------------------------------------------------------------
# Preflight: gcloud present & authenticated & billing project set
# ---------------------------------------------------------------------------
command -v gcloud >/dev/null 2>&1 || { echo "✗ gcloud CLI not installed"; exit 1; }
if [[ -z "$(gcloud config get-value project 2>/dev/null)" ]]; then
  echo "📌 Setting project to ${PROJECT_ID}"
  gcloud config set project "${PROJECT_ID}"
fi

echo ""
echo "=== 1/6  Enabling required APIs ==="
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  --project="${PROJECT_ID}"

echo ""
echo "=== 2/6  Creating Artifact Registry repo (if missing) ==="
if ! gcloud artifacts repositories describe "$REPO" --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker --location="${REGION}" \
    --description="Kalika ERP images" --project="${PROJECT_ID}"
fi

echo ""
echo "=== 3/6  Building & pushing image (frontend built inside Docker) ==="
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions="_REGION=${REGION},_REPO=${REPO},_TAG=${TAG},_PROJECT=${PROJECT_ID}" .

echo ""
echo "=== 4/6  Locating Cloud SQL password from Secret Manager ==="
DB_SECRET="${DB_SECRET:-kalika-db-password}"
if gcloud secrets describe "$DB_SECRET" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  DB_PASS_VERSION="$(gcloud secrets versions access latest --secret="$DB_SECRET" --project="${PROJECT_ID}")"
else
  echo "✗ Secret '${DB_SECRET}' not found. Create it first:"
  echo "    echo -n '<your-db-password>' | gcloud secrets create ${DB_SECRET} --replication-policy=automatic --data-file=- --project=${PROJECT_ID}"
  exit 1
fi

echo ""
echo "=== 4b/6  Locating JWT secret ==="
JWT_SECRET="${JWT_SECRET:-}"
JWT_SECRET_NAME="${JWT_SECRET_SECRET:-kalika-jwt-secret}"
if [[ -z "$JWT_SECRET" ]] && gcloud secrets describe "$JWT_SECRET_NAME" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  JWT_SECRET="$(gcloud secrets versions access latest --secret="$JWT_SECRET_NAME" --project="${PROJECT_ID}")"
fi
if [[ -z "$JWT_SECRET" ]]; then
  echo "✗ JWT_SECRET not set. Create a secret first, then re-run:"
  echo "    echo -n '$(openssl rand -hex 32)' | gcloud secrets create ${JWT_SECRET_NAME} --replication-policy=automatic --data-file=- --project=${PROJECT_ID}"
  echo "  You can also export JWT_SECRET=<value> and re-run."
  exit 1
fi

echo ""
echo "=== 4c/6  Locating Mail password from Secret Manager (optional) ==="
MAIL_SECRET="${MAIL_SECRET:-kalika-mail-password}"
MAIL_ENABLED="False"
MAIL_SECRET_ARG=""
if gcloud secrets describe "$MAIL_SECRET" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  MAIL_ENABLED="True"
  MAIL_SECRET_ARG=",MAIL_PASSWORD=$MAIL_SECRET:latest"
  echo "✓ Mail secret found; email will be enabled."
else
  echo "  Mail secret not found; email disabled. Create it to enable:"
  echo "    echo -n '<your-app-password>' | gcloud secrets create ${MAIL_SECRET} --replication-policy=automatic --data-file=- --project=${PROJECT_ID}"
fi

echo ""
echo "=== 5/6  Deploying Cloud Run service + connecting to Cloud SQL ==="
gcloud run deploy "$SERVICE" \
  --image="${IMAGE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=3 \
  --timeout=120 \
  --set-cloudsql-instances="${CLOUD_SQL_CONNECTION}" \
  --set-env-vars="\
CLOUD_SQL_DB_NAME=${CLOUD_SQL_DB_NAME},\
CLOUD_SQL_DB_USER=${CLOUD_SQL_DB_USER},\
CLOUD_SQL_CONNECTION_NAME=${CLOUD_SQL_CONNECTION},\
JWT_SECRET=${JWT_SECRET},\
DB_SECRET=${DB_SECRET},\
REPORT_DIR=/app/reports,\
GCS_BUCKET=kalisoftai-datahub,\
GCS_EXCEL_FILE=Kalika_inventory/Daily Report Aug-26.xlsx,\
MAIL_ENABLED=${MAIL_ENABLED},\
MAIL_USERNAME=${MAIL_USERNAME:-kalikaenterprises@gmail.com},\
MAIL_FROM=${MAIL_FROM:-kalikaenterprises@gmail.com}" \
  --set-secrets="CLOUD_SQL_DB_PASS=$DB_SECRET:latest${MAIL_SECRET_ARG}"

# Give Cloud Run's default compute service account SQL Client + storage read roles
RUNNER_SA="$(gcloud run services describe "$SERVICE" --region="${REGION}" --project="${PROJECT_ID}" --format='value(spec.template.spec.serviceAccountName)')"
if [[ -n "$RUNNER_SA" ]]; then
  echo "🔐 Ensuring ${RUNNER_SA} has roles/cloudsql.client"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNNER_SA}" \
    --role="roles/cloudsql.client" --condition=None >/dev/null 2>&1 || echo "  (iam binding may need manual grant)"
  echo "🔐 Ensuring ${RUNNER_SA} has roles/storage.objectViewer"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNNER_SA}" \
    --role="roles/storage.objectViewer" --condition=None >/dev/null 2>&1 || echo "  (storage role may need manual grant)"
fi

# Ensure 100% traffic always goes to the newest revision (avoids stale traffic pinning)
gcloud run services update-traffic "$SERVICE" --region="${REGION}" --project="${PROJECT_ID}" --to-latest

echo ""
echo "=== 6/6  Deployment done ==="
URL="$(gcloud run services describe "$SERVICE" --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
echo "📎 Service URL  : ${URL}"
echo "🔎 Health check : ${URL}/health"
echo ""
echo "If /health shows database:error, run data migration next (see docs below)."