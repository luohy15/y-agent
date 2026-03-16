#!/bin/bash

# Load environment variables from .env if it exists
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
fi

set -e

STACK_NAME=${STACK_NAME:-"y-agent"}
ROLE_NAME="${STACK_NAME}-lambda-role"

AWS_PROFILE_OPTION=""
if [ ! -z "$AWS_PROFILE" ]; then
    AWS_PROFILE_OPTION="--profile $AWS_PROFILE"
    echo "Using AWS profile: $AWS_PROFILE"
fi

echo "Managing Lambda execution role: $ROLE_NAME"
echo ""

# Trust policy document
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}'

# Create role (continue if it already exists)
echo "Creating role..."
aws iam create-role $AWS_PROFILE_OPTION \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --no-cli-pager 2>/dev/null || echo "Role already exists, continuing..."

# Attach policies
POLICIES=(
    "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
    "arn:aws:iam::aws:policy/AmazonSQSFullAccess"
    "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
    "arn:aws:iam::aws:policy/AWSLambda_FullAccess"
    "arn:aws:iam::aws:policy/AmazonEC2FullAccess"
)

for POLICY_ARN in "${POLICIES[@]}"; do
    POLICY_NAME=$(echo "$POLICY_ARN" | awk -F'/' '{print $NF}')
    echo "Attaching $POLICY_NAME..."
    aws iam attach-role-policy $AWS_PROFILE_OPTION \
        --role-name "$ROLE_NAME" \
        --policy-arn "$POLICY_ARN"
done

echo ""
echo "Done! Role: $ROLE_NAME"
echo ""
echo "Policies attached:"
echo "- AWSLambdaBasicExecutionRole (CloudWatch Logs)"
echo "- AWSLambdaVPCAccessExecutionRole (VPC/RDS access)"
echo "- AmazonSQSFullAccess"
echo "- AmazonDynamoDBFullAccess"
echo "- AWSLambda_FullAccess"
echo "- AmazonEC2FullAccess"
