#!/bin/bash

# Manual AWS SAM deployment script for y-agent (API + Worker + Admin)
AWS_PROFILE=${AWS_PROFILE:-default}
AWS_REGION=${AWS_REGION:-us-east-1}

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

set -e

echo "Starting deployment of y-agent..."

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
sam build

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
if [ -f "samconfig.toml" ]; then
    echo "Using existing configuration..."
    if [ -n "$PARAM_OVERRIDES" ]; then
        sam deploy --profile $AWS_PROFILE --parameter-overrides $PARAM_OVERRIDES
    else
        sam deploy --profile $AWS_PROFILE
    fi
else
    echo "Running guided deployment (first time)..."
    sam deploy --guided --profile $AWS_PROFILE
fi

echo ""
echo "Deployment complete!"
echo ""
