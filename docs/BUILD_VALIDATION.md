# Validation record for consolidated demo archive

- Source: user's Git archive from commit `df8cf5b` (`devops/stateless-demo`).
- The stateless FastAPI backend code and tests were already present.
- DB/RDS, SQS/DLQ and notification worker sources removed.
- Local Docker Compose no longer starts PostgreSQL or migrations.
- `.woodpecker/verify.yml` now allows `manual` and `push` events for `devops/demo-pipeline`.
- New dual ECS blue/green services, Terraform S3 backend with native locking,
  root-owned EC2 poller, trusted first-apply/Ansible release controller,
  and explicit restricted cleanup script included.
- Offline Python tests: **14 passed** in artifact-building environment.
- `python -m compileall` passed for backend and host CI Python sources.

**Not tested against live AWS:** `terraform init`, `fmt`, `validate`, `plan`,
actual Woodpecker manual trigger, Kaniko registry secret permission, ECR image
push, ECS task startup, ALB health, S3 backend permissions, or live
blue/green traffic switching. Use `DEMO_RUNBOOK.md` to verify these on EC2.
