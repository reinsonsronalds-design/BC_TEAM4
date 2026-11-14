# Slice & Sip — DevOps Bootcamp CI/CD Demo

**Current build: stateless application + EC2-hosted Woodpecker + Terraform/Ansible + AWS ECS Fargate.**

Start with the existing bootcamp EC2 and its CI control plane, but **no
Slice & Sip ECS cluster, ALB, services, queues or database**. An approved,
versioned S3 bucket for Terraform state and the two legacy ECR repositories
can exist before the demonstration. The EC2 host contains trusted automation
scripts, but no application containers are running there.

## Presentation

1. Push to `devops/demo-pipeline` on GitHub.
2. EC2 Git poller detects a new commit without an inbound webhook or ngrok.
3. It asks the locally running Woodpecker API to run the repository pipeline.
4. Woodpecker tests FastAPI and publishes immutable frontend/backend image
   tags `<full-git-sha>-<pipeline-number>` with Kaniko to the existing ECR repos.
5. EC2 host validates the successful Woodpecker run and both ECR images; only
   then Terraform provisions the app on ECS Fargate. Ansible is used for
   subsequent releases.
6. Change a visible HTML string and push again. Woodpecker publishes two new
   images; Ansible updates the inactive Fargate service, waits for ALB `/ready`
   healthy status, moves 100% production traffic, observes a short bake period,
   and scales down the old Fargate service.
7. An explicit, restricted `terraform destroy` deletes **project-owned** AWS
   resources, not the bootcamp EC2, shared VPC/subnets, S3 state bucket or ECR.

## Deliberately simpler than the older architecture

- **No database** (no RDS, SQL migration, or persisted orders).
- **No SQS/DLQ/EventBridge notification routing/notification worker**.
- **No additional IAM roles created or modified**. EC2 uses its existing
  `Bootcamp-Instance-Profile` and the *existing* `ecsTaskExecutionRole`.
- **Blue/green with two ECS services and a weighted ALB rule**, controlled by
  the EC2 instance profile's existing `ecs:*` and `elasticloadbalancing:*`
  permissions. This is not the newer ECS-native blue/green strategy.
- **CloudWatch** logs and two alarms; no log-retention policy.
- **S3** state with native locking, no DynamoDB.
- Direct Discord HTTPS webhooks from FastAPI are **optional**. ECS can only
  inject their Secrets Manager values if the **separate execution role** can
  read them. The broad EC2 SecretsManager permission does not imply this.

**Important:** With webhook injection disabled, orders and support requests
still work and return `not_configured`/`demo_only`, but no Discord message is
sent. Do not present Discord as verified until tested end-to-end.

## Important files

- `.woodpecker/verify.yml`: tests and Kaniko builds for manual/push events
  on `devops/demo-pipeline`.
- `ci/demo_poller.py`: localhost Woodpecker API trigger, Git polling and
  once-per-commit deployment gate.
- `ci/demo_release.py`: first-build Terraform bootstrap, later Ansible handoff,
  explicitly confirmed cleanup.
- `ci/roleless_blue_green.py`, `ansible/ecs-deploy.yml`: safe blue/green deploy.
- `infrastructure/`: new **separate S3 state root**; existing ECR is data-only.
- `scripts/bootstrap-s3-state.sh`: pre-demo, explicit state-bucket creation.
- `docs/DEMO_RUNBOOK.md`: setup, checks, permissions, demo, recovery, cleanup.
- `backend/app.py`: two stateless API endpoints plus `/health` and `/ready`.
- `docker-compose.dev.yml`: local NGINX/FastAPI demo, without PostgreSQL.

Older `docs/PHASE*.md`, `ci/*release*` notes and old optional Ansible EC2
bootstrap playbooks are **historical** and do not describe this deployment.
Use the new demo runbook, not the old phase instructions.

## Quick local checks

```bash
python -m pip install -r backend/requirements.txt pytest
PYTHONPATH=backend python -m pytest -q backend/tests ci/tests
# Optional locally if Docker is available:
docker compose -f docker-compose.dev.yml up --build
# Browser: http://localhost:8080 ; readiness: http://localhost:8080/ready
```

## Read before using AWS

Read [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md). **Do not run
`terraform apply` or arm the poller before its preflight gates are satisfied.**
This build was tested offline only; live AWS resources and network routes
must be verified in the bootcamp environment before presenting.
