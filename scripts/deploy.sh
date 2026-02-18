#!/bin/bash

# Manual AWS SAM deployment script for y-agent (API + Worker + Admin)
# Usage: ./scripts/deploy.sh [branch-name]
#   If branch-name is provided, deploys a preview stack y-agent-{sanitized-branch}

AWS_PROFILE=${AWS_PROFILE:-default}
AWS_REGION=${AWS_REGION:-us-east-1}
BRANCH_NAME="${1:-}"

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

set -e

# ============================================================================
# Branch name sanitization
# ============================================================================
if [ -n "$BRANCH_NAME" ]; then
    SANITIZED=$(echo "$BRANCH_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//' | sed 's/-$//' | cut -c1-28)
    STACK_NAME="y-agent-${SANITIZED}"
    echo "Preview deployment: branch=$BRANCH_NAME sanitized=$SANITIZED stack=$STACK_NAME"
else
    STACK_NAME=""
    echo "Starting deployment of y-agent (main)..."
fi

# ============================================================================
# Export dependencies as requirements.txt for SAM
# ============================================================================
if command -v uv &> /dev/null; then
    echo "Exporting dependencies with uv..."
    cd api && uv export --format=requirements-txt --no-hashes | grep -v "^-e \." > requirements.txt && cd ..
    cd admin && uv export --format=requirements-txt --no-hashes | grep -v "^-e \." > requirements.txt && cd ..
    cd worker && uv export --format=requirements-txt --no-hashes | grep -v "^-e \." > requirements.txt && cd ..
else
    echo "Error: uv is required for deployment but not found in PATH"
    echo "Please install uv: https://github.com/astral-sh/uv"
    exit 1
fi

# ============================================================================
# SAM Build
# ============================================================================
echo "Building SAM application..."
sam build --build-dir ~/.cache/y-agent/.aws-sam --cached

# ============================================================================
# Parameter Override Setup
# ============================================================================
add_param() {
    local param_name="$1"
    local env_var="$2"
    if [ -n "${!env_var}" ]; then
        if [ -n "$PARAM_OVERRIDES" ]; then
            PARAM_OVERRIDES="$PARAM_OVERRIDES $param_name=${!env_var}"
        else
            PARAM_OVERRIDES="$param_name=${!env_var}"
        fi
    fi
}

echo "Deploying SAM application..."
PARAM_OVERRIDES=""

add_param "DatabaseUrl" "DATABASE_URL"
add_param "JwtSecretKey" "JWT_SECRET_KEY"
add_param "DomainName" "DOMAIN_NAME"
add_param "CertificateArn" "CERTIFICATE_ARN"
add_param "GoogleClientId" "GOOGLE_CLIENT_ID"

# ============================================================================
# SAM Deploy
# ============================================================================
if [ -n "$STACK_NAME" ]; then
    # Branch preview deployment — bypass samconfig.toml
    LAMBDA_ROLE_NAME="${LAMBDA_ROLE_NAME:-y-agent-lambda-role}"
    add_param "BranchName" "SANITIZED"
    add_param "LambdaRoleName" "LAMBDA_ROLE_NAME"

    # Tag with git info for slot tracking
    GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
    GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    echo "Deploying preview stack: $STACK_NAME"
    sam deploy \
        --stack-name "$STACK_NAME" \
        --template-file ~/.cache/y-agent/.aws-sam/template.yaml \
        --resolve-s3 \
        --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
        --region "$AWS_REGION" \
        --no-confirm-changeset \
        --no-fail-on-empty-changeset \
        --parameter-overrides $PARAM_OVERRIDES \
        --tags "GitBranch=$GIT_BRANCH GitCommit=$GIT_COMMIT"

    # Print stack outputs for downstream scripts
    echo ""
    echo "=== Stack Outputs ==="
    aws cloudformation describe-stacks \
        --stack-name "$STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs" \
        --output table
else
    # Main stack deployment — use samconfig.toml
    if [ -f "samconfig.toml" ]; then
        echo "Using existing configuration..."
        if [ -n "$PARAM_OVERRIDES" ]; then
            sam deploy --profile $AWS_PROFILE --template-file ~/.cache/y-agent/.aws-sam/template.yaml --parameter-overrides $PARAM_OVERRIDES
        else
            sam deploy --profile $AWS_PROFILE --template-file ~/.cache/y-agent/.aws-sam/template.yaml
        fi
    else
        echo "Running guided deployment (first time)..."
        sam deploy --guided --profile $AWS_PROFILE
    fi
fi

echo ""
echo "Deployment complete!"
echo ""
