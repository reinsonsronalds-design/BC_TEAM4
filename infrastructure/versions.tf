terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.37"
    }
  }
  # A separate, PRE-EXISTING versioned bucket is bootstrapped once on EC2.
  # Configuration supplied only through /etc/slice-sip-ci/state.hcl.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = { Project = "SliceAndSip", Environment = "bootcamp", ManagedBy = "Terraform" }
  }
}
locals {
  enable_https       = trimspace(var.app_certificate_arn) != ""
  app_log_group_name = "/ecs/${var.project_name}/app"
  discord_channels   = toset(["orders", "invoices", "support"])
}
