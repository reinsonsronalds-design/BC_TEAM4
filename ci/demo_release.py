#!/usr/bin/env python3
"""Trusted EC2 host action: bootstrap Terraform once, then Ansible blue/green.

The installed code is root-owned and pinned before the presentation. Build
source code on GitHub is *never* run with the EC2 instance profile credentials.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
TF = ROOT / "infrastructure"
PLAYBOOK = ROOT / "ansible/ecs-deploy.yml"
BACKEND_CONFIG = Path("/etc/slice-sip-ci/state.hcl")
TAG = re.compile(r"^[0-9a-f]{40}-[1-9][0-9]*$")

class ReleaseError(Exception):
    pass

def cmd(args: list[str], *, cwd: Path = ROOT, timeout: int = 1200, capture: bool = False) -> str:
    print("RUN:", args[0], args[1] if len(args) > 1 else "", flush=True)
    result = subprocess.run(args, cwd=cwd, check=False, timeout=timeout,
                            text=True, stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if result.returncode:
        reason = result.stderr[-400:] if capture and result.stderr else "Inspect command output"
        raise ReleaseError(f"{args[0]} failed ({result.returncode}): {reason}")
    return result.stdout if capture else ""

def setup_terraform() -> None:
    if not BACKEND_CONFIG.is_file():
        raise ReleaseError("S3 backend config /etc/slice-sip-ci/state.hcl is missing")
    cmd(["terraform", "init", "-reconfigure", "-input=false", f"-backend-config={BACKEND_CONFIG}"], cwd=TF)

def check_images(tag: str) -> None:
    for part in ("frontend", "backend"):
        cmd(["aws", "ecr", "describe-images", "--region", "eu-west-1",
             "--repository-name", f"slice-sip-{part}", "--image-ids", f"imageTag={tag}",
             "--query", "imageDetails[0].imageDigest", "--output", "text"], capture=True)

def ensure_log_group() -> None:
    name = "/ecs/slice-sip/app"
    result = cmd(["aws", "logs", "describe-log-groups", "--region", "eu-west-1",
                  "--log-group-name-prefix", name, "--query", "logGroups[].logGroupName",
                  "--output", "json"], capture=True)
    if name not in json.loads(result):
        cmd(["aws", "logs", "create-log-group", "--region", "eu-west-1", "--log-group-name", name])
        print(f"Created CloudWatch log group {name} (not Terraform-managed)")

def state_resources() -> list[str]:
    # A never-applied S3 backend has no state object yet. Terraform versions may
    # return a non-zero exit in this case; it is a valid first-build condition.
    result = subprocess.run(["terraform", "state", "list"], cwd=TF,
                            capture_output=True, text=True, check=False, timeout=60)
    if result.returncode:
        if "No state file was found" in result.stderr or "No state file was found" in result.stdout:
            return []
        raise ReleaseError(f"Cannot inspect separate Terraform state: {result.stderr[-250:]}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def provision(tag: str) -> None:
    print("FIRST DEPLOY: create project infrastructure through separate S3 state")
    ensure_log_group()
    plan_fd, plan_file = tempfile.mkstemp(prefix="slice-sip-plan-", suffix=".tfplan")
    os.close(plan_fd)
    os.chmod(plan_file, 0o600)
    try:
        args = ["-input=false", "-var=enable_application=true", f"-var=image_tag={tag}"]
        cmd(["terraform", "plan", *args, f"-out={plan_file}"], cwd=TF)
        data = json.loads(cmd(["terraform", "show", "-json", plan_file], cwd=TF, capture=True))
        changes = [c for c in data.get("resource_changes", []) if c.get("mode") == "managed"]
        # First creation is allowlist-controlled. Never automatically destroy or mutate
        # an unexpected existing AWS resource in a demo bootstrap.
        for change in changes:
            actions = change.get("change", {}).get("actions", [])
            if any(action not in {"no-op", "create"} for action in actions):
                raise ReleaseError(f"Unsafe initial Terraform action {change.get('address')}: {actions}")
        if not changes:
            raise ReleaseError("Initial Terraform plan has no resources to provision")
        cmd(["terraform", "apply", "-input=false", "-auto-approve", plan_file], cwd=TF, timeout=1800)
    finally:
        Path(plan_file).unlink(missing_ok=True)
    # Confirm service health (including ALB target) before calling first run success.
    from roleless_blue_green import call, healthy_target, wait_for_health
    tg = call("elbv2", "describe-target-groups", "--names", "slice-sip-blue")["TargetGroups"][0]["TargetGroupArn"]
    wait_for_health("slice-sip-blue", tg, timeout=600)
    print("FIRST DEPLOY SUCCESS: blue Fargate service healthy behind ALB")

def release(tag: str, execute: bool) -> None:
    if not TAG.fullmatch(tag):
        raise ReleaseError("Image tag must be <full-sha>-<woodpecker-pipeline-number>")
    if not execute:
        print(f"PREVIEW: would verify ECR images for {tag}, initialize S3 state, bootstrap if absent, or Ansible blue/green update")
        return
    check_images(tag)
    setup_terraform()
    existing = state_resources()
    # Reject any existing state that doesn't belong to this lab before applying.
    legacy = [v for v in existing if v.startswith(("aws_ecr_repository.", "aws_db_instance.", "aws_sqs_queue."))]
    if legacy:
        raise ReleaseError("Unexpected legacy state resources detected; refusing deployment")
    if "aws_ecs_service.blue[0]" not in existing or "aws_ecs_service.green[0]" not in existing:
        if existing:
            raise ReleaseError("Partial Terraform state needs a manual reviewed plan before retrying")
        provision(tag)
    else:
        cmd(["ansible-playbook", "-i", "localhost,", "-c", "local", str(PLAYBOOK),
             "-e", f"image_tag={tag}", "-e", "deploy_enabled=true"], timeout=1200)

def cleanup(confirmation: str) -> None:
    if confirmation != "DESTROY_ONLY_SLICE_SIP_DEMO":
        raise ReleaseError("Explicit project-only destroy confirmation missing")
    setup_terraform()
    existing = state_resources()
    if not any(name.startswith("aws_ecs_service.") for name in existing):
        raise ReleaseError("No Slice & Sip application services found in this separate state")
    if any(name.startswith("aws_ecr_repository.") or name.startswith("aws_instance.") for name in existing):
        raise ReleaseError("Refusing cleanup of state containing shared infrastructure")
    cmd(["terraform", "destroy", "-input=false", "-auto-approve", "-var=enable_application=true",
         "-var=image_tag=" + "0"*40 + "-1"], cwd=TF, timeout=1800)
    print("CLEANUP: Terraform-managed resources destroyed; separate existing ECR/EC2/VPC/S3/log group remain")

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", help="Full commit SHA + Woodpecker pipeline number")
    ap.add_argument("--execute", action="store_true", help="Allow project AWS changes")
    ap.add_argument("--destroy", action="store_true", help="Project-only destroy after demo")
    ap.add_argument("--confirm", default="")
    args = ap.parse_args()
    try:
        if args.destroy:
            cleanup(args.confirm)
        elif args.tag:
            release(args.tag, args.execute)
        else:
            ap.error("--tag or --destroy is required")
        return 0
    except (ReleaseError, ValueError, OSError, subprocess.TimeoutExpired, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
