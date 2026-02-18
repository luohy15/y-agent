#!/bin/bash
set -e

# Deploy a full preview stack for a branch
# Usage: ./scripts/deploy-preview.sh <branch-name>

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

BRANCH_NAME="${1:?Usage: deploy-preview.sh <branch-name>}"
DOMAIN_NAME="${DOMAIN_NAME:-yovy.app}"
AWS_REGION="${AWS_REGION:-us-east-1}"

# Sanitize branch name
SANITIZED=$(echo "$BRANCH_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//' | cut -c1-28)
STACK_NAME="y-agent-${SANITIZED}"
SUBDOMAIN="${SANITIZED}"

echo "=== Preview Deployment ==="
echo "Branch:    $BRANCH_NAME"
echo "Sanitized: $SANITIZED"
echo "Stack:     $STACK_NAME"
echo "URL:       https://${SUBDOMAIN}.${DOMAIN_NAME}"
echo ""

# ============================================================================
# 1. Deploy SAM stack
# ============================================================================
echo "--- Deploying SAM stack ---"
./scripts/deploy.sh "$BRANCH_NAME"

# ============================================================================
# 2. Read stack outputs
# ============================================================================
echo "--- Reading stack outputs ---"
get_output() {
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
        --output text
}

export WEB_BUCKET_NAME=$(get_output "WebBucketName")
export CLOUDFRONT_DISTRIBUTION_ID=$(get_output "CloudFrontDistributionId")
CF_DOMAIN=$(get_output "CloudFrontDomainName")

echo "Web Bucket:    $WEB_BUCKET_NAME"
echo "CF Dist ID:    $CLOUDFRONT_DISTRIBUTION_ID"
echo "CF Domain:     $CF_DOMAIN"

# ============================================================================
# 3. Deploy web assets
# ============================================================================
echo "--- Deploying web assets ---"
./scripts/deploy-web.sh

# ============================================================================
# 4. Upsert DNS record
# ============================================================================
echo "--- Upserting DNS record ---"
./scripts/upsert-dns.sh "$SUBDOMAIN" "$CF_DOMAIN"

# ============================================================================
# Done
# ============================================================================
echo ""
echo "=== Preview deployed ==="
echo "URL: https://${SUBDOMAIN}.${DOMAIN_NAME}"
echo ""
