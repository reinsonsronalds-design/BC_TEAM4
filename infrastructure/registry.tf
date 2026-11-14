# Reuse existing Slice & Sip ECR repositories.
# Managed by the original Terraform state.

data "aws_ecr_repository" "frontend" {
  name = "${var.project_name}-frontend"
}

data "aws_ecr_repository" "backend" {
  name = "${var.project_name}-backend"
}
