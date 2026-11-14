# Slice & Sip: demonstration runbook (branch `devops/demo-pipeline`)

## 0. Deployment boundary and status

This is a prepared implementation, **not a claim of a successful AWS deployment**.
The original user's new Terraform root has not been applied. `terraform fmt`,
`terraform validate` and `terraform plan` must run on the EC2 installation
because Terraform/provider binaries are unavailable in the artifact builder.

- AWS account: `597765856364`, region: `eu-west-1`.
- Existing EC2: `i-0eb789ac23be694c0`; `Bootcamp-Instance-Profile`.
- Existing ECR repos: `slice-sip-frontend` and `slice-sip-backend`.
  **Do not import or manage these in this new Terraform state.**
- Known task execution role: `arn:aws:iam::597765856364:role/ecsTaskExecutionRole`.
- Shared bootcamp VPC `vpc-04b6091923e283784` is referenced, not managed.
- Project AWS resources only appear *after* a successful triggered build.
- Host automation is a preinstalled, trusted copy under `/opt/slice-sip-demo`;
  Woodpecker builds from GitHub without giving build containers the EC2 role.

The six user-provided `arn:aws:iam::aws:policy/...` ARNs are **policies**, not
IAM role ARNs. The `Bootcamp-Instance-Profile` identity has the ECS/ELB/ECR/S3
permissions used here, based on supplied policies, but actual AWS constraints,
resource policies and service-linked roles still need live verification.

## 1. Local source preparation (Windows Git Bash)

1. Apply `apply_to_windows.sh` from the package only while on
   `devops/demo-pipeline`. It refuses dirty tracked work and doesn't touch Git
   history or untracked virtual environments. Review changes with `git status`
   and `git diff --check`.
2. `python -m pip install -r backend/requirements.txt pytest`
3. `PYTHONPATH=backend python -m pytest -q backend/tests ci/tests`
4. Optionally `docker compose -f docker-compose.dev.yml up --build` and test
   `/ready`, an order, and a support request (use fictional names).
5. Commit **only reviewed source**, not `terraform.tfvars`, state, tokens or
   generated local virtual environments.
6. Publishing this new branch itself counts as a Git event. For a rehearsed
   demo, keep the EC2 poller **unarmed**, publish the branch to make its CI
   configuration available, preflight the host, then **push another commit**
   during the presentation to trigger the first actual provisioning.
7. Verify the repository owner/collaborators permit pushing this branch.
   No GitHub token is needed on EC2 for pushes; EC2 only needs read access.

## 2. Pre-demo EC2: install trusted host controller (no app deployed)

Use a reviewed snapshot of this source branch. On EC2, take a trusted local
copy as `/opt/slice-sip-demo` (root-owned and not writable by Woodpecker
workflow containers or GitHub branch contributors). For example, after
reviewing the branch and fetching it in a separate temporary checkout:

```bash
# The following is illustrative; adapt the source directory to your reviewed
# checkout. Do not run it against an unreviewed Git commit as root.
sudo install -d -m 0755 /opt/slice-sip-demo
sudo cp -a /path/to/reviewed-slice-sip-source/. /opt/slice-sip-demo/
sudo chown -R root:root /opt/slice-sip-demo
sudo chmod -R go-w /opt/slice-sip-demo
```

The existing Git checkout at `/home/ssm-user/slice-sip-ci-source` must have an
`origin` that can READ the demo branch using `git ls-remote` as `ssm-user`:

```bash
sudo runuser -u ssm-user -- git -C /home/ssm-user/slice-sip-ci-source \
  ls-remote --exit-code origin refs/heads/devops/demo-pipeline
```

If this prompts for login or fails, configure an **approved read-only Git
credential** or access method. Do not paste PATs into chat or commands.

### Required host software and CI setup

- `terraform` v1.10+ and AWS provider 6.37+ (EC2 previously had Terraform 1.17).
- `aws` CLI v2, Python 3, Ansible available to systemd/root through PATH.
- Woodpecker 3.x server accessible on `127.0.0.1:8000`; repository active
  and pipeline manual triggers permitted for its token.
- Root-owned `0600` Woodpecker API token at
  `/etc/slice-sip-ci/woodpecker-api-token` (existing setup).
- Kaniko ECR registry secret `ecr_password` correctly refreshed and authorized
  for BOTH `manual` and `push` events and the pinned plugin image. The supplied
  `ci/refresh-ecr-woodpecker-secret.py` updates this event restriction.
- The existing dockerized Woodpecker agent is already running on EC2.
- All deployment AWS CLI commands use **EC2 instance profile**, not static keys.

Verify server locally before arming:

```bash
aws sts get-caller-identity
aws ecs describe-clusters --clusters slice-sip-ecs --region eu-west-1
sudo python3 /opt/slice-sip-demo/ci/demo_poller.py
```

The first command must show the `Bootcamp-Instance-Profile` assumed role;
ECS cluster should initially be absent. Poller defaults to read-only mode.

## 3. State backend: explicit pre-demo bootstrap

**Only** the new `/opt/slice-sip-demo/infrastructure` root uses this S3
backend. Existing Windows ECR state stays separate.

Use an instructor-approved, globally unique S3 bucket name. You can create a
small project-specific state bucket before the presentation (this is CI
infrastructure, not app infrastructure). The script enforces S3 versioning,
SSE-S3 encryption and public-access blocking:

```bash
cd /opt/slice-sip-demo
sudo bash scripts/bootstrap-s3-state.sh APPROVED-GLOBALLY-UNIQUE-BUCKET --execute
sudo ls -l /etc/slice-sip-ci/state.hcl
```

Or use an existing **approved** bucket and configure
`/etc/slice-sip-ci/state.hcl` from `infrastructure/backend.s3.hcl.example`.
Don't reconfigure a shared bucket without permission. Keep the bucket after
`terraform destroy` (it contains state history and lock metadata).

Copy `infrastructure/terraform.tfvars.example` to the root-owned
`infrastructure/terraform.tfvars` on EC2 and verify the actual subnet IDs,
route tables, and AZs before first deployment. By default the task ENIs have
no public IP and need NAT for ECR, CloudWatch and Discord egress. If no
approved NAT route exists, choose approved **public** ECS subnets and set
`ecs_assign_public_ip=true` for a simple bootcamp demo; ingress remains
restricted to the ALB security group.

```bash
cd /opt/slice-sip-demo/infrastructure
sudo cp terraform.tfvars.example terraform.tfvars
sudo chmod 0600 terraform.tfvars
sudo terraform fmt -check -recursive  # If not formatted, use terraform fmt -recursive in reviewed working copy
sudo terraform init -reconfigure -input=false -backend-config=/etc/slice-sip-ci/state.hcl
sudo terraform validate
sudo terraform plan -input=false  # enable_application defaults false; NO apply yet
```

Expect an empty new project resource plan with `enable_application=false`
(data lookups may still occur); do NOT mix old legacy EC2/ECR states.

**Before the actual presentation** simulate/verify permission for:
`ecs:RegisterTaskDefinition`, `ecs:CreateService`, `ecs:UpdateService`,
`elasticloadbalancing:ModifyRule`, `logs:CreateLogGroup`,
`logs:DescribeLogGroups`, `ecr:DescribeImages`, and `iam:PassRole` on the
execution role. Existing policies generally cover these actions. Verify
`ecsTaskExecutionRole` itself can pull ECR images and publish CloudWatch logs.

## 4. Set up Git polling and safe arm gate

The poller needs the existing protected Woodpecker token and the EC2 clone.
It checks the head of **only** `devops/demo-pipeline`, then uses `POST
/api/repos/{repo_id}/pipelines` for a Woodpecker `manual` event. The
`.woodpecker/verify.yml` workflow accepts `manual` and `push` on this branch.

Install its service, then create the approval file **just before** the live
presentation. `--execute` without this root-owned gate refuses writes.

```bash
sudo install -m 0644 /opt/slice-sip-demo/ci/systemd/slice-sip-demo-poller.service \
  /etc/systemd/system/slice-sip-demo-poller.service
sudo systemctl daemon-reload
# Prepare first: don't start/arm the service yet.
sudo systemctl status woodpecker-server || true
```

First, after the demo branch is published but **before** the live presentation,
record its current SHA as a baseline. This does not run CI or deploy anything:

```bash
sudo python3 /opt/slice-sip-demo/ci/demo_poller.py --baseline-current
```

When ready to let the **next new push** deploy:

```bash
sudo install -d -m 0700 /etc/slice-sip-ci
printf 'ARM_SLICE_SIP_DEMO\n' | sudo tee /etc/slice-sip-ci/demo-armed >/dev/null
sudo chown root:root /etc/slice-sip-ci/demo-armed
sudo chmod 0600 /etc/slice-sip-ci/demo-armed
sudo systemctl start slice-sip-demo-poller
sudo journalctl -u slice-sip-demo-poller -f
```

The baseline prevents the pre-published branch head from triggering at startup.
Only a **new** Git commit proceeds to the first provisioning pipeline. It polls every 60 seconds and only
releases after the corresponding Woodpecker pipeline succeeds and both ECR
images have the matching immutable tag.

## 5. Presentation sequence

- On GitHub: push a simple, reviewed commit to `devops/demo-pipeline`.
- Watch Woodpecker tests and Kaniko image uploads, then host journal.
- The EC2 host deployer creates CloudWatch log group and runs Terraform
  plan → guarded apply in NEW S3 state. It initializes the blue service with
  `desired_count=1`, green `0` and ALB rule blue 100% / green 0%.
- Confirm ALB URL with `sudo terraform output -raw app_url` from the installed
  infrastructure directory. Test `/ready`, an example order and a support
  request (fictional input only). If Discord injection isn't enabled, the
  responses report `not_configured`; this is expected.
- Edit a visible string in root `index.html` and push again. Woodpecker
  publishes new tags. Ansible updates the inactive service, checks ALB
  target health, switches weights and scales down the previous service.
  **The EC2 instance itself never hosts the application containers.**
- View `/ecs/slice-sip/app` logs and both CloudWatch alarms.
- If a pipeline/deployment fails, the poller blocks that commit rather than
  blindly retrying the live AWS mutation. Inspect before a fresh commit.

This design is genuine **dual-service blue/green**, but not ECS-native
`deployment_configuration.strategy="BLUE_GREEN"`. ECS service revisions use
rolling behavior within each color. The ALB rule switch is executed by the
EC2/Ansible deployment controller, using permissions already on EC2.

## 6. Discord secret limitation

`Bootcamp-Instance-Profile` allows Secrets Manager operations. That does
**not** extend to Fargate. The existing `ecsTaskExecutionRole` needs
`secretsmanager:GetSecretValue` on three existing, populated webhook secrets
and `kms:Decrypt` only if using a customer-managed KMS key. These grants
must already exist or be authorized by the lab; don't expose webhook URLs
through plaintext ECS environment variables, Terraform state or GitHub.

If already authorized, set `enable_discord_webhooks=true` and the three
`discord_webhook_secret_arns` in protected EC2 `terraform.tfvars` **before
initial deployment**. Never put webhook values there. All three secrets must
contain URLs. Otherwise leave false, and demonstrate application routing,
CI/CD and CloudWatch; notifications will be reported `not_configured`.

Also verify Fargate outbound HTTPS access to discord.com, and don't submit
real customer information in the HTTP demo.

## 7. Explicit project-only cleanup

**Stop the poller first**, so it cannot redeploy after teardown:

```bash
sudo systemctl stop slice-sip-demo-poller
sudo rm -f /etc/slice-sip-ci/demo-armed
sudo python3 /opt/slice-sip-demo/ci/demo_release.py \
  --destroy --confirm DESTROY_ONLY_SLICE_SIP_DEMO
```

This runs a Terraform destroy against **only** the new S3 state root. It
cannot destroy instructor-managed EC2, the shared VPC, subnets, or ECR repos
because those are not managed resources in this state. It does not remove
S3 state bucket or CloudWatch log group; current EC2 IAM policies lack
`logs:DeleteLogGroup` so don't claim zero AWS artifacts after teardown.

## 8. Safety, costs, and known prerequisites

- ALB hourly/LCU charges plus Fargate vCPU/memory charges begin on first
  deployment; both colors may run briefly during blue/green.
- Confirm the bootcamp subnets belong to approved distinct AZs with correct
  IGW/NAT routes and Fargate-to-ECR/Logs/Discord connectivity.
- `awslogs` CloudWatch log group is deliberately not Terraform-managed due
  missing log group tag/delete IAM actions; after teardown it persists.
- Existing ECR repositories and versions persist; separate legacy Windows
  Terraform state remains responsible for those repos.
- The S3 state backend is created/pre-approved *before* the live demo; actual
  application infrastructure is created only after the first CI push.
- Existing Woodpecker OAuth and repository activation still need to be
  usable for API-triggered manual builds without an inbound webhook.
- Terraform AWS provider operations, ECS role passing, and live ALB rules
  have **not** been run from this output archive. AWS live validation is
  required, especially before an assessed presentation.
- Any future changes to privileged host Terraform or deployment scripts
  require review and reinstalling the root-owned copy. A repo contributor
  must not be able to change AWS-privileged host code just by pushing Git.
