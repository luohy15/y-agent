#!/bin/bash

# List all preview deployment slots and their current git branch/commit
# Usage: ./scripts/list-previews.sh

AWS_REGION="${AWS_REGION:-us-east-1}"

STACKS=$(aws cloudformation list-stacks \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE \
    --region "$AWS_REGION" \
    --query "StackSummaries[?starts_with(StackName, 'y-agent-test')].StackName" \
    --output text)

if [ -z "$STACKS" ]; then
    echo "No preview slots found."
    exit 0
fi

printf "%-20s %-25s %-10s %s\n" "SLOT" "BRANCH" "COMMIT" "LAST UPDATED"
printf "%-20s %-25s %-10s %s\n" "----" "------" "------" "------------"

for STACK in $STACKS; do
    TAGS=$(aws cloudformation describe-stacks \
        --stack-name "$STACK" \
        --region "$AWS_REGION" \
        --query "Stacks[0].[Tags, LastUpdatedTime || CreationTime]" \
        --output json)

    BRANCH=$(echo "$TAGS" | jq -r '.[0][] | select(.Key=="GitBranch") | .Value // "-"')
    COMMIT=$(echo "$TAGS" | jq -r '.[0][] | select(.Key=="GitCommit") | .Value // "-"')
    UPDATED=$(echo "$TAGS" | jq -r '.[1]')

    printf "%-20s %-25s %-10s %s\n" "$STACK" "${BRANCH:--}" "${COMMIT:--}" "$UPDATED"
done
