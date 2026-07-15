#!/bin/bash

# Manual AWS SAM deployment script for y-agent (API + Worker + Admin)
# Usage: ./scripts/deploy.sh

AWS_PROFILE=${AWS_PROFILE:-default}

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

set -e

echo "Starting deployment of y-agent (main)..."

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
add_param "SubnetIds" "SUBNET_IDS"
add_param "LambdaSecurityGroupId" "LAMBDA_SECURITY_GROUP_ID"
add_param "TelegramBotToken" "TELEGRAM_BOT_TOKEN"
add_param "TelegramWebhookSecret" "TELEGRAM_WEBHOOK_SECRET"
add_param "OxylabsUsername" "OXYLABS_USERNAME"
add_param "OxylabsPassword" "OXYLABS_PASSWORD"
add_param "AlphaVantageApiKey" "ALPHAVANTAGE_API_KEY"

# ============================================================================
# SAM Deploy
# ============================================================================
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

echo ""
echo "Deployment complete!"
echo ""
