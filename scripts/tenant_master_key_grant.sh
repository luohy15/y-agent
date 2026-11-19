#!/bin/bash

# Sole owner of inline policy y-agent-tenant-master-key-read on y-agent-lambda-role.
# Not called by scripts/deploy.sh, create-role.sh, or CI. A stack update cannot
# create or delete this policy. Refuses unless --confirm-role-grant is passed.
#
# The grant is not environment isolation. All nine functions that use
# y-agent-lambda-role can call GetParameter once this exists. Runtime targeting
# (empty Y_AGENT_TENANT_MASTER_KEY_PARAMETER) only stops accidental resolution.
#
# GitHubDeployRole is implicitDeny for iam:PutRolePolicy. Do not add that
# permission. An administrator runs this script after a separate authorization.

set +x
set -e

if [[ " $* " != *" --confirm-role-grant "* ]]; then
    echo "Shared-role grant is not authorized. Refusing." >&2
    exit 1
fi

ROLE_NAME="${ROLE_NAME:-y-agent-lambda-role}"
AWS_PROFILE_OPTION=""
if [ -n "${AWS_PROFILE:-}" ]; then
    AWS_PROFILE_OPTION="--profile $AWS_PROFILE"
fi

ACCOUNT_ID=$(aws sts get-caller-identity $AWS_PROFILE_OPTION --query Account --output text)
SSM_KEY_ID="b7bc6286-09b1-4b4c-bb58-3b85d9e42746"
POLICY_DOCUMENT=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadTenantMasterKey",
      "Effect": "Allow",
      "Action": "ssm:GetParameter",
      "Resource": "arn:aws:ssm:us-east-1:${ACCOUNT_ID}:parameter/y-agent/tenant/master-key"
    },
    {
      "Sid": "DecryptTenantMasterKeyViaSsm",
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:us-east-1:${ACCOUNT_ID}:key/${SSM_KEY_ID}",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "ssm.us-east-1.amazonaws.com",
          "kms:EncryptionContext:PARAMETER_ARN": "arn:aws:ssm:us-east-1:${ACCOUNT_ID}:parameter/y-agent/tenant/master-key"
        }
      }
    }
  ]
}
EOF
)

aws iam put-role-policy $AWS_PROFILE_OPTION \
    --role-name "$ROLE_NAME" \
    --policy-name y-agent-tenant-master-key-read \
    --policy-document "$POLICY_DOCUMENT"

echo "Shared-role grant applied: y-agent-tenant-master-key-read"
