# No Terraform-managed webhook values or secret metadata. Supply existing
# Secrets Manager ARNs through the protected EC2-only tfvars if enabled.
# The Fargate EXECUTION role must have secretsmanager:GetSecretValue.
