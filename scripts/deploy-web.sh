#!/bin/bash

# Deploy static files to S3 bucket
AWS_PROFILE=${AWS_PROFILE:-}
PROFILE_FLAG=""
if [ -n "$AWS_PROFILE" ]; then
    PROFILE_FLAG="--profile $AWS_PROFILE"
fi

# Load environment variables from .env if it exists (don't override existing vars)
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    while IFS= read -r line; do
        key="${line%%=*}"
        value="${line#*=}"
        if [ -n "$key" ] && [ -z "${!key}" ]; then
            export "$key=$value"
        fi
    done < <(grep -v '^#' .env | grep -v '^$')
fi

# Build the web app
echo "Building web app..."
cd web
npm ci
VITE_GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID npm run build
cd ..

STATIC_DIR="web/dist"

if [ ! -d "$STATIC_DIR" ]; then
    echo "Error: Build failed - '$STATIC_DIR' not found"
    exit 1
fi

echo "Deploying static files to S3 bucket: $WEB_BUCKET_NAME"

# Sync files to S3
aws s3 sync "$STATIC_DIR" "s3://$WEB_BUCKET_NAME" \
    $PROFILE_FLAG \
    --delete \
    --cache-control "public, max-age=3600"

echo "Static files deployed successfully!"

# Invalidate CloudFront cache if distribution ID is provided
if [ -n "$CLOUDFRONT_DISTRIBUTION_ID" ]; then
    echo "Invalidating CloudFront cache..."
    aws cloudfront create-invalidation \
        $PROFILE_FLAG \
        --distribution-id $CLOUDFRONT_DISTRIBUTION_ID \
        --paths "/*" \
        --no-cli-pager
    echo "CloudFront cache invalidation started"
else
    echo "CLOUDFRONT_DISTRIBUTION_ID not set - skipping cache invalidation"
fi
