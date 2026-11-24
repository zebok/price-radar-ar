#!/usr/bin/env bash
# ==============================================================================
# Despliegue Opcional en Google Cloud Platform (Cloud Storage + Cloud Run Job)
# Requiere definir GCP_PROJECT_ID en el entorno:
#   export GCP_PROJECT_ID="mi-proyecto-gcp"
#   ./scripts/deploy_cloud.sh
# ==============================================================================

set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?Definí GCP_PROJECT_ID antes de ejecutar (ej: export GCP_PROJECT_ID=mi-proyecto)}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET_NAME:-${PROJECT_ID}-lakehouse}"
SERVICE_ACCOUNT_NAME="scraper-runner-sa"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_TAG="gcr.io/${PROJECT_ID}/scraper-precios:latest"
JOB_NAME="scraper-daily-job"
SCHEDULER_JOB_NAME="daily-supermarket-scraper-trigger"
CRON_SCHEDULE="0 6 * * *"
TIMEZONE="America/Argentina/Buenos_Aires"

echo "=============================================================================="
echo " Despliegue en GCP (Always Free Tier) — Lakehouse Parquet + Cloud Run Job"
echo "=============================================================================="
echo " • Proyecto GCP     : $PROJECT_ID"
echo " • Región           : $REGION"
echo " • Bucket Lakehouse : gs://$BUCKET_NAME"
echo " • Cloud Run Job    : $JOB_NAME"
echo " • Cron Diario      : $CRON_SCHEDULE ($TIMEZONE)"
echo "=============================================================================="

gcloud config set project "$PROJECT_ID"

echo "[1/5] Habilitando APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    storage.googleapis.com \
    cloudscheduler.googleapis.com

echo "[2/5] Configurando Bucket Lakehouse (gs://${BUCKET_NAME})..."
if ! gcloud storage buckets describe "gs://${BUCKET_NAME}" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${BUCKET_NAME}" \
        --location="$REGION" \
        --default-storage-class="STANDARD" \
        --uniform-bucket-level-access
fi

cat << 'EOF' > /tmp/gcs_lifecycle.json
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {"age": 365}
    }
  ]
}
EOF
gcloud storage buckets update "gs://${BUCKET_NAME}" --lifecycle-file=/tmp/gcs_lifecycle.json
rm -f /tmp/gcs_lifecycle.json

echo "[3/5] Configurando Service Account IAM..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
        --display-name="Service Account para Scraper de Precios"
fi

for ROLE in "roles/storage.objectAdmin" "roles/run.invoker"; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
        --role="$ROLE" \
        --quiet >/dev/null
done

echo "[4/5] Compilando imagen Docker con Cloud Build..."
gcloud builds submit --tag "$IMAGE_TAG" .

echo "[5/5] Configurando Cloud Run Job y Cloud Scheduler..."
JOB_ARGS=(
    --image="$IMAGE_TAG"
    --region="$REGION"
    --service-account="$SERVICE_ACCOUNT_EMAIL"
    --tasks=1
    --max-retries=1
    --task-timeout=1800s
    --cpu=1
    --memory=1Gi
    --command="scraper"
    --args="extract,--stores,all,--basket,extended,--pages,2,--sync-cloud"
    --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},GCS_BUCKET_NAME=${BUCKET_NAME},SCRAPER_DATA_DIR=/app/data/scraper-precios"
)

if gcloud run jobs describe "$JOB_NAME" --region="$REGION" >/dev/null 2>&1; then
    gcloud run jobs update "$JOB_NAME" "${JOB_ARGS[@]}"
else
    gcloud run jobs create "$JOB_NAME" "${JOB_ARGS[@]}"
fi

JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"
if gcloud scheduler jobs describe "$SCHEDULER_JOB_NAME" --location="$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$SCHEDULER_JOB_NAME" \
        --location="$REGION" \
        --schedule="$CRON_SCHEDULE" \
        --time-zone="$TIMEZONE" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="$SERVICE_ACCOUNT_EMAIL"
else
    gcloud scheduler jobs create http "$SCHEDULER_JOB_NAME" \
        --location="$REGION" \
        --schedule="$CRON_SCHEDULE" \
        --time-zone="$TIMEZONE" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="$SERVICE_ACCOUNT_EMAIL"
fi

echo "Despliegue completado. Ejecutá una prueba con:"
echo "  gcloud run jobs execute $JOB_NAME --region=$REGION"
