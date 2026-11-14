# Slice & Sip demonstration infrastructure

No application resources exist until the **first successful CI publish**.
The EC2 host runs Terraform in a new S3-backed state root. ECR repositories,
EC2 instance, bootcamp networking, and task execution IAM role are DATA/input
resources owned elsewhere and are never deleted by this state.

* 2 ECS Fargate services: blue (initially 1), green (initially 0).
* ALB listener rule sends traffic to current color; EC2 Ansible handoff swaps
  traffic after the new color passes ALB target health. This is **not**
  ECS-native `BLUE_GREEN`, so no ECS infrastructure role is required.
* `awslogs` log group is created once by the EC2 host (existing `logs:CreateLogGroup`
  permission), not Terraform (no `logs:TagResource`/`DeleteLogGroup`).
* No RDS, SQS, EventBridge notifications, database, or application task role.
* Discord webhook URL injection is OPTIONAL; the separate task execution role
  must read secret values before enabling it.
* Terraform `backend "s3" {}` gets config from the private
  `/etc/slice-sip-ci/state.hcl`; versioning and native `use_lockfile = true`.

Never use the old Windows ECR Terraform state here. Never apply the infrastructure
on the developer workstation. See `docs/DEMO_RUNBOOK.md` for checks and gates.
