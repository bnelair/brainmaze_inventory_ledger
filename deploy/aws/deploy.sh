#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy/aws/deploy.sh
#
# Deploy Brainmaze Inventory Ledger to AWS using CloudFormation.
#
# Prerequisites
# ─────────────
#   • AWS CLI installed and configured  (aws configure)
#   • An EC2 Key Pair already created in the target region
#   • Docker installed locally (for optional ECR push)
#
# Usage
# ─────
#   chmod +x deploy/aws/deploy.sh
#   ./deploy/aws/deploy.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuration (edit these or export as environment variables) ─────────────
STACK_NAME="${STACK_NAME:-brainmaze-inventory-ledger}"
AWS_REGION="${AWS_REGION:-us-east-1}"
KEY_PAIR_NAME="${KEY_PAIR_NAME:-}"          # REQUIRED – name of your EC2 key pair
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.small}"
ALLOWED_CIDR="${ALLOWED_CIDR:-0.0.0.0/0}"  # Restrict to your IP for production
APP_PORT="${APP_PORT:-8501}"
GIT_REPO_URL="${GIT_REPO_URL:-}"
GIT_TOKEN="${GIT_TOKEN:-}"
GIT_CRYPT_KEY="${GIT_CRYPT_KEY:-}"
APP_REPO_URL="${APP_REPO_URL:-https://github.com/bnelair/brainmaze_inventory_ledger.git}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/cloudformation.yml"

# ── Validation ────────────────────────────────────────────────────────────────
if [[ -z "${KEY_PAIR_NAME}" ]]; then
    echo "ERROR: KEY_PAIR_NAME is not set."
    echo "  Export it:  export KEY_PAIR_NAME=my-key-pair"
    exit 1
fi

command -v aws >/dev/null 2>&1 || { echo "ERROR: AWS CLI not found."; exit 1; }

echo "──────────────────────────────────────────────────"
echo "  Deploying Brainmaze Inventory Ledger to AWS"
echo "  Stack    : ${STACK_NAME}"
echo "  Region   : ${AWS_REGION}"
echo "  Key Pair : ${KEY_PAIR_NAME}"
echo "──────────────────────────────────────────────────"

# ── Deploy / update CloudFormation stack ─────────────────────────────────────
aws cloudformation deploy \
    --region "${AWS_REGION}" \
    --template-file "${TEMPLATE}" \
    --stack-name "${STACK_NAME}" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
        KeyPairName="${KEY_PAIR_NAME}" \
        InstanceType="${INSTANCE_TYPE}" \
        AllowedCIDR="${ALLOWED_CIDR}" \
        AppPort="${APP_PORT}" \
        GitRepoUrl="${GIT_REPO_URL}" \
        GitToken="${GIT_TOKEN}" \
        GitCryptKey="${GIT_CRYPT_KEY}" \
        AppRepoUrl="${APP_REPO_URL}" \
    --no-fail-on-empty-changeset

# ── Retrieve outputs ─────────────────────────────────────────────────────────
echo ""
echo "✅  Deployment complete.  Stack outputs:"
aws cloudformation describe-stacks \
    --region "${AWS_REGION}" \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs" \
    --output table

APP_URL=$(aws cloudformation describe-stacks \
    --region "${AWS_REGION}" \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='AppURL'].OutputValue" \
    --output text)

echo ""
echo "  🌐  Application URL: ${APP_URL}"
echo "  ℹ️   Note: The instance may take 2-3 minutes to finish initialisation."
echo "  ℹ️   SSH:  ssh -i ~/.ssh/${KEY_PAIR_NAME}.pem ec2-user@<PublicIP>"
