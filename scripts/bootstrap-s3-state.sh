#!/usr/bin/env bash
# Create a versioned private S3 bucket for THIS NEW Terraform state only.
set -euo pipefail
if [[ $# -ne 2 || "$2" != '--execute' ]]; then
  echo 'Usage: sudo bash scripts/bootstrap-s3-state.sh globally-unique-bucket-name --execute' >&2
  exit 2
fi
if [[ $(id -u) -ne 0 ]]; then echo 'Run with sudo on EC2' >&2; exit 2; fi
bucket=$1
if [[ ! $bucket =~ ^[a-z0-9][a-z0-9.-]{5,61}[a-z0-9]$ ]]; then echo 'Invalid S3 bucket name' >&2; exit 2; fi
if aws s3api head-bucket --bucket "$bucket" --region eu-west-1 >/dev/null 2>&1; then
  echo "Using accessible existing bucket $bucket WITHOUT modifying its configuration"
  status=$(aws s3api get-bucket-versioning --bucket "$bucket" --query Status --output text)
  if [[ "$status" != Enabled ]]; then
    echo 'Existing bucket has no versioning; use approved bucket or request admin review' >&2
    exit 2
  fi
  # These are read-only checks. We cannot silently change an existing shared bucket.
  aws s3api get-bucket-encryption --bucket "$bucket" >/dev/null
  aws s3api get-public-access-block --bucket "$bucket" >/dev/null
else
  echo "Creating new project-specific bucket $bucket (verify instructor approval first)"
  aws s3api create-bucket --bucket "$bucket" --region eu-west-1 \
    --create-bucket-configuration LocationConstraint=eu-west-1
  aws s3api put-bucket-versioning --bucket "$bucket" --versioning-configuration Status=Enabled
  aws s3api put-public-access-block --bucket "$bucket" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  aws s3api put-bucket-encryption --bucket "$bucket" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
fi
install -d -m 0700 /etc/slice-sip-ci
umask 077
printf 'bucket = "%s"\nkey = "slice-sip/demo-fargate/terraform.tfstate"\nregion = "eu-west-1"\nencrypt = true\nuse_lockfile = true\n' "$bucket" > /etc/slice-sip-ci/state.hcl
chmod 0600 /etc/slice-sip-ci/state.hcl
echo 'Native S3 locking configured for separate Slice & Sip demo state. No Terraform apply performed.'
