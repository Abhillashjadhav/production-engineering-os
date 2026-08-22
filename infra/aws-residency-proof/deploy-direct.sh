#!/usr/bin/env bash
set -euo pipefail

readonly REGION="ap-south-1"
readonly REPOSITORY="Abhillashjadhav/production-engineering-os"
readonly GITHUB_ENVIRONMENT="india-residency"
readonly ROLE_NAME="ProductionEngineeringOsResidencyRole"

account_id="$(aws sts get-caller-identity --query Account --output text)"
readonly account_id
readonly bucket="peos-residency-${account_id}-${REGION}"
readonly provider_arn="arn:aws:iam::${account_id}:oidc-provider/token.actions.githubusercontent.com"

if ! aws s3api head-bucket --bucket "${bucket}" --region "${REGION}" >/dev/null 2>&1; then
  aws s3api create-bucket \
    --bucket "${bucket}" \
    --region "${REGION}" \
    --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
fi

aws s3api put-public-access-block \
  --bucket "${bucket}" \
  --region "${REGION}" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-encryption \
  --bucket "${bucket}" \
  --region "${REGION}" \
  --server-side-encryption-configuration \
  'Rules=[{ApplyServerSideEncryptionByDefault={SSEAlgorithm=AES256}}]'

aws s3api put-bucket-ownership-controls \
  --bucket "${bucket}" \
  --region "${REGION}" \
  --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'

aws s3api put-bucket-lifecycle-configuration \
  --bucket "${bucket}" \
  --region "${REGION}" \
  --lifecycle-configuration \
  '{"Rules":[{"ID":"DeleteAbandonedSyntheticProbes","Status":"Enabled","Filter":{"Prefix":"residency-probes/"},"Expiration":{"Days":1}}]}'

aws s3api put-bucket-tagging \
  --bucket "${bucket}" \
  --region "${REGION}" \
  --tagging 'TagSet=[{Key=purpose,Value=production-engineering-os-residency-proof},{Key=residency,Value=IN}]'

if ! aws iam get-open-id-connect-provider \
  --open-id-connect-provider-arn "${provider_arn}" >/dev/null 2>&1; then
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com >/dev/null
fi

trust_file="$(mktemp)"
policy_file="$(mktemp)"
trap 'rm -f "${trust_file}" "${policy_file}"' EXIT

cat >"${trust_file}" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "${provider_arn}"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {"StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub": "repo:${REPOSITORY}:environment:${GITHUB_ENVIRONMENT}"
    }}
  }]
}
EOF

if aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  aws iam update-assume-role-policy \
    --role-name "${ROLE_NAME}" \
    --policy-document "file://${trust_file}"
else
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "file://${trust_file}" >/dev/null
fi

cat >"${policy_file}" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAuthenticatedBucketRegion",
      "Effect": "Allow",
      "Action": "s3:GetBucketLocation",
      "Resource": "arn:aws:s3:::${bucket}"
    },
    {
      "Sid": "ProbeSyntheticPrefix",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::${bucket}/residency-probes/*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name ExactResidencyProbe \
  --policy-document "file://${policy_file}"

role_arn="$(aws iam get-role --role-name "${ROLE_NAME}" --query Role.Arn --output text)"

printf '\nDeployment complete. Add these GitHub environment variables to %s:\n' "${GITHUB_ENVIRONMENT}"
printf 'AWS_RESIDENCY_BUCKET=%s\n' "${bucket}"
printf 'AWS_RESIDENCY_ROLE_ARN=%s\n' "${role_arn}"
