#!/bin/bash
set -e

# Delete a preview deployment stack, S3 bucket contents, and DNS record
# Usage: ./scripts/delete-preview.sh <branch-name>

BRANCH_NAME="${1:?Usage: delete-preview.sh <branch-name>}"
DOMAIN_NAME="${DOMAIN_NAME:-yovy.app}"
AWS_REGION="${AWS_REGION:-us-east-1}"

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

# Sanitize branch name
SANITIZED=$(echo "$BRANCH_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//' | cut -c1-28)
STACK_NAME="y-agent-${SANITIZED}"
SUBDOMAIN="${SANITIZED}"

echo "=== Deleting Preview Deployment ==="
echo "Branch:    $BRANCH_NAME"
echo "Stack:     $STACK_NAME"
echo ""

# ============================================================================
# 1. Read stack outputs before deletion
# ============================================================================
echo "--- Reading stack outputs ---"
get_output() {
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
        --output text 2>/dev/null || echo ""
}

WEB_BUCKET_NAME=$(get_output "WebBucketName")
CF_DOMAIN=$(get_output "CloudFrontDomainName")

# ============================================================================
# 2. Empty S3 bucket
# ============================================================================
if [ -n "$WEB_BUCKET_NAME" ]; then
    echo "--- Emptying S3 bucket: $WEB_BUCKET_NAME ---"
    aws s3 rm "s3://$WEB_BUCKET_NAME" --recursive --region "$AWS_REGION" || true
else
    echo "No web bucket found, skipping S3 cleanup."
fi

# ============================================================================
# 3. Delete CloudFormation stack
# ============================================================================
echo "--- Deleting CloudFormation stack: $STACK_NAME ---"
aws cloudformation delete-stack \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION"

echo "Waiting for stack deletion..."
aws cloudformation wait stack-delete-complete \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION"
echo "Stack deleted."

# ============================================================================
# 4. Delete DNS record
# ============================================================================
if [ -n "$CF_DOMAIN" ]; then
    echo "--- Deleting DNS record ---"
    ./scripts/upsert-dns.sh "$SUBDOMAIN" "$CF_DOMAIN" DELETE
else
    echo "No CloudFront domain found, skipping DNS cleanup."
fi

echo ""
echo "=== Preview deleted ==="
echo ""
