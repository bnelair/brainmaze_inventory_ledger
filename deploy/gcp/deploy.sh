#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy/gcp/deploy.sh
#
# Deploy Brainmaze Inventory Ledger to Google Cloud Platform.
#
# Two strategies are available:
#   1. Compute Engine VM  (persistent disk + Docker Compose)  ← default
#   2. Cloud Run          (serverless, but needs Cloud Storage for persistence)
#
# Prerequisites
# ─────────────
#   • gcloud CLI installed and authenticated  (gcloud auth login)
#   • A GCP project with billing enabled
#   • Compute Engine API and Artifact Registry API enabled
#
# Usage
# ─────
#   chmod +x deploy/gcp/deploy.sh
#   ./deploy/gcp/deploy.sh              # Compute Engine (default)
#   DEPLOY_TARGET=cloudrun ./deploy/gcp/deploy.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:-}"           # REQUIRED
REGION="${GCP_REGION:-us-central1}"
ZONE="${GCP_ZONE:-us-central1-a}"
INSTANCE_NAME="${INSTANCE_NAME:-brainmaze-inventory-ledger}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-small}"
APP_PORT="${APP_PORT:-8501}"
DEPLOY_TARGET="${DEPLOY_TARGET:-compute}"  # compute | cloudrun
APP_REPO_URL="${APP_REPO_URL:-https://github.com/bnelair/brainmaze_inventory_ledger.git}"
GIT_REPO_URL="${GIT_REPO_URL:-}"
GIT_TOKEN="${GIT_TOKEN:-}"

# ── Validation ────────────────────────────────────────────────────────────────
if [[ -z "${PROJECT_ID}" ]]; then
    echo "ERROR: GCP_PROJECT_ID is not set."
    echo "  Export it:  export GCP_PROJECT_ID=my-project-id"
    exit 1
fi

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud CLI not found."; exit 1; }

gcloud config set project "${PROJECT_ID}"

echo "──────────────────────────────────────────────────────────────────────"
echo "  Deploying Brainmaze Inventory Ledger to GCP"
echo "  Project       : ${PROJECT_ID}"
echo "  Region / Zone : ${REGION} / ${ZONE}"
echo "  Target        : ${DEPLOY_TARGET}"
echo "──────────────────────────────────────────────────────────────────────"

# ─────────────────────────────────────────────────────────────────────────────
# Strategy 1: Compute Engine VM
# ─────────────────────────────────────────────────────────────────────────────
deploy_compute_engine() {
    echo ""
    echo "▶  Creating Compute Engine instance…"

    # Build startup script inline — secrets are NOT embedded here; the operator
    # must copy .env to the instance post-provisioning (see instructions below).
    STARTUP=$(cat <<STARTUP
#!/bin/bash
set -euo pipefail
exec > /var/log/brainmaze-init.log 2>&1

apt-get update -y
apt-get install -y docker.io docker-compose git curl

systemctl enable --now docker
usermod -aG docker "\$(logname 2>/dev/null || echo ubuntu)"

cd /opt
git clone ${APP_REPO_URL} brainmaze-ledger
cd brainmaze-ledger

# .env will be written by the operator after provisioning – see deploy output.
cat > .env <<ENV
APP_PORT=${APP_PORT}
GIT_AUTH_METHOD=PAT
GIT_TOKEN=REPLACE_ME
GIT_REPO_URL=REPLACE_ME
GIT_BRANCH=main
ENV

docker-compose build
docker-compose up -d

echo "Brainmaze Inventory Ledger started on port ${APP_PORT}"
STARTUP
)

    gcloud compute instances create "${INSTANCE_NAME}" \
        --zone="${ZONE}" \
        --machine-type="${MACHINE_TYPE}" \
        --image-family=ubuntu-2204-lts \
        --image-project=ubuntu-os-cloud \
        --boot-disk-size=30GB \
        --boot-disk-type=pd-ssd \
        --tags=brainmaze-ledger \
        --metadata="startup-script=${STARTUP}"

    # Firewall rule for app port
    gcloud compute firewall-rules create "allow-brainmaze-${APP_PORT}" \
        --direction=INGRESS \
        --action=ALLOW \
        --rules="tcp:${APP_PORT}" \
        --target-tags=brainmaze-ledger \
        --source-ranges=0.0.0.0/0 \
        --description="Allow Brainmaze Inventory Ledger web UI" \
        2>/dev/null || echo "  Firewall rule already exists – skipping."

    EXTERNAL_IP=$(gcloud compute instances describe "${INSTANCE_NAME}" \
        --zone="${ZONE}" \
        --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

    echo ""
    echo "✅  VM provisioned."
    echo "  External IP  : ${EXTERNAL_IP}"
    echo "  App URL      : http://${EXTERNAL_IP}:${APP_PORT}"
    echo "  SSH          : gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE}"
    echo ""
    echo "⚠️  ACTION REQUIRED — update secrets on the VM:"
    echo "  gcloud compute ssh ${INSTANCE_NAME} --zone=${ZONE} -- \\"
    echo "    'sudo sed -i \"s|GIT_TOKEN=REPLACE_ME|GIT_TOKEN=<your-token>|\" /opt/brainmaze-ledger/.env && \\"
    echo "     sudo sed -i \"s|GIT_REPO_URL=REPLACE_ME|GIT_REPO_URL=<your-repo-url>|\" /opt/brainmaze-ledger/.env && \\"
    echo "     cd /opt/brainmaze-ledger && sudo docker-compose restart'"
    echo ""
    echo "  ℹ️   Startup script is running – wait ~3 minutes for the app to be ready."
}

# ─────────────────────────────────────────────────────────────────────────────
# Strategy 2: Cloud Run
# ─────────────────────────────────────────────────────────────────────────────
deploy_cloud_run() {
    IMAGE_NAME="gcr.io/${PROJECT_ID}/brainmaze-inventory-ledger"

    echo ""
    echo "▶  Enabling required GCP APIs…"
    gcloud services enable run.googleapis.com artifactregistry.googleapis.com

    echo "▶  Building and pushing Docker image to GCR…"
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

    gcloud builds submit "${REPO_ROOT}" \
        --tag="${IMAGE_NAME}:latest" \
        --region="${REGION}"

    echo "▶  Deploying to Cloud Run…"
    # Preferred: use Secret Manager so GIT_TOKEN is never visible in process args or logs.
    # If the secret 'brainmaze-git-token' doesn't exist yet, fall back to env var.
    # To create the secret:
    #   echo -n "${GIT_TOKEN}" | gcloud secrets create brainmaze-git-token --data-file=-
    if gcloud secrets describe brainmaze-git-token --project="${PROJECT_ID}" >/dev/null 2>&1; then
        gcloud run deploy "${INSTANCE_NAME}" \
            --image="${IMAGE_NAME}:latest" \
            --region="${REGION}" \
            --platform=managed \
            --port="${APP_PORT}" \
            --allow-unauthenticated \
            --memory=512Mi \
            --cpu=1 \
            --set-env-vars="DATA_DIR=/tmp/data,REPORTS_DIR=/tmp/reports,GIT_REPO_URL=${GIT_REPO_URL}" \
            --update-secrets="GIT_TOKEN=brainmaze-git-token:latest"
    else
        echo "  ⚠️  Secret 'brainmaze-git-token' not found in Secret Manager."
        echo "       Falling back to env var. For production, create the secret:"
        echo "       echo -n \"\${GIT_TOKEN}\" | gcloud secrets create brainmaze-git-token --data-file=-"
        gcloud run deploy "${INSTANCE_NAME}" \
            --image="${IMAGE_NAME}:latest" \
            --region="${REGION}" \
            --platform=managed \
            --port="${APP_PORT}" \
            --allow-unauthenticated \
            --memory=512Mi \
            --cpu=1 \
            --set-env-vars="DATA_DIR=/tmp/data,REPORTS_DIR=/tmp/reports,GIT_TOKEN=${GIT_TOKEN},GIT_REPO_URL=${GIT_REPO_URL}"
    fi

    SERVICE_URL=$(gcloud run services describe "${INSTANCE_NAME}" \
        --region="${REGION}" \
        --format="value(status.url)")

    echo ""
    echo "✅  Cloud Run service deployed."
    echo "  App URL : ${SERVICE_URL}"
    echo "  ⚠️   Note: Cloud Run has ephemeral storage. Configure a Git remote"
    echo "       (☁️ Git Sync page) to persist data between deployments."
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
if [[ "${DEPLOY_TARGET}" == "cloudrun" ]]; then
    deploy_cloud_run
else
    deploy_compute_engine
fi
