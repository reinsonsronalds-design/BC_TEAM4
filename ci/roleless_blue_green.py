#!/usr/bin/env python3
"""EC2-role blue/green using two ECS services and an ALB listener rule.

No ECS infrastructure IAM role. Never switches production traffic before the
inactive service reports a healthy ALB target. No AWS keys, no webhook secrets.
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

SHA_TAG = re.compile(r"^[0-9a-f]{40}-[1-9][0-9]*$")
PROJECT = "slice-sip"
REGION = "eu-west-1"


class DeploymentError(Exception):
    pass


def call(*args: str, json_result: bool = True) -> dict:
    result = subprocess.run(["aws", *args, "--region", REGION, "--output", "json", "--no-cli-pager"],
                            capture_output=True, text=True, timeout=90, check=False)
    if result.returncode:
        # Cloud errors must not print secrets from inputs.
        raise DeploymentError(f"AWS {args[0]} {args[1]} failed: {result.stderr.strip()[-260:]}")
    return json.loads(result.stdout) if json_result and result.stdout.strip() else {}


def tf_output(key: str) -> str:
    result = subprocess.run(["terraform", "output", "-raw", key], capture_output=True,
                            text=True, check=False, timeout=30, cwd=os.environ.get("SLICE_SIP_TF_DIR", "/opt/slice-sip-demo/infrastructure"))
    if result.returncode or not result.stdout.strip() or result.stdout.strip() == "Not deployed":
        raise DeploymentError(f"Terraform output {key} unavailable: initialize separate S3 state first")
    return result.stdout.strip()


def groups_from_rule(rule: dict, blue_arn: str, green_arn: str) -> str:
    actions = rule.get("Actions", [])
    if len(actions) != 1 or actions[0].get("Type") != "forward":
        raise DeploymentError("Production ALB rule has unexpected actions")
    weights = {g["TargetGroupArn"]: g.get("Weight", 0)
               for g in actions[0].get("ForwardConfig", {}).get("TargetGroups", [])}
    if blue_arn == green_arn or set(weights) != {blue_arn, green_arn}:
        raise DeploymentError("ALB rule is not owned by the Slice & Sip two-target-group deployment")
    if weights[blue_arn] == 100 and weights[green_arn] == 0:
        return "blue"
    if weights[green_arn] == 100 and weights[blue_arn] == 0:
        return "green"
    raise DeploymentError("Ambiguous production traffic weights; manual investigation required")


def modify_rule(rule_arn: str, active_arn: str, inactive_arn: str) -> None:
    payload = [{"Type": "forward", "ForwardConfig": {"TargetGroups": [
        {"TargetGroupArn": active_arn, "Weight": 100},
        {"TargetGroupArn": inactive_arn, "Weight": 0}]}}]
    fd, name = tempfile.mkstemp(prefix=".slice-sip-rule-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        os.chmod(name, 0o600)
        call("elbv2", "modify-rule", "--rule-arn", rule_arn, "--actions", f"file://{name}")
    finally:
        Path(name).unlink(missing_ok=True)


def service(region_name: str) -> dict:
    data = call("ecs", "describe-services", "--cluster", f"{PROJECT}-ecs", "--services", region_name)
    items = [s for s in data.get("services", []) if s.get("serviceName") == region_name and s.get("status") == "ACTIVE"]
    if len(items) != 1:
        raise DeploymentError(f"ECS service {region_name} unavailable")
    return items[0]


def get_images(tag: str) -> dict[str, str]:
    images: dict[str, str] = {}
    for part in ("frontend", "backend"):
        repo = f"{PROJECT}-{part}"
        details = call("ecr", "describe-repositories", "--repository-names", repo)["repositories"]
        if len(details) != 1:
            raise DeploymentError(f"ECR repository {repo} not unique")
        result = call("ecr", "describe-images", "--repository-name", repo, "--image-ids", f"imageTag={tag}")
        if len(result.get("imageDetails", [])) != 1:
            raise DeploymentError(f"ECR image {repo}:{tag} not available")
        images[part] = f"{details[0]['repositoryUri']}:{tag}"
    return images


def healthy_target(tg_arn: str) -> bool:
    result = call("elbv2", "describe-target-health", "--target-group-arn", tg_arn)
    statuses = [item.get("TargetHealth", {}).get("State") for item in result.get("TargetHealthDescriptions", [])]
    return any(s == "healthy" for s in statuses)


def wait_for_health(service_name: str, tg_arn: str, timeout: int = 600) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = service(service_name)
        if (s.get("desiredCount") == 1 and s.get("runningCount") == 1
                and s.get("pendingCount") == 0 and healthy_target(tg_arn)):
            return
        time.sleep(10)
    raise DeploymentError(f"Inactive {service_name} never became healthy; production unchanged")


def register_task_images(existing_task: str, images: dict[str, str]) -> str:
    current = call("ecs", "describe-task-definition", "--task-definition", existing_task)["taskDefinition"]
    safe_keys = ("family", "taskRoleArn", "executionRoleArn", "networkMode", "containerDefinitions",
                 "volumes", "requiresCompatibilities", "cpu", "memory", "runtimePlatform", "ephemeralStorage")
    body = {key: current[key] for key in safe_keys if key in current}
    container_names = {x.get("name") for x in body["containerDefinitions"]}
    if not set(images).issubset(container_names):
        raise DeploymentError("Unexpected ECS container configuration")
    for container in body["containerDefinitions"]:
        if container["name"] in images:
            container["image"] = images[container["name"]]
    fd, name = tempfile.mkstemp(prefix=".slice-sip-task-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(body, stream)
        os.chmod(name, 0o600)
        response = call("ecs", "register-task-definition", "--cli-input-json", f"file://{name}")
        return response["taskDefinition"]["taskDefinitionArn"]
    finally:
        Path(name).unlink(missing_ok=True)


def run(tag: str, preview: bool = True, bake_seconds: int = 30) -> str:
    if not SHA_TAG.fullmatch(tag):
        raise DeploymentError("Expected 40-character SHA plus -pipeline-number")
    blue = tf_output("blue_service_name")
    green = tf_output("green_service_name")
    listener_rule = tf_output("production_listener_rule_arn")
    groups = {}
    for color in ("blue", "green"):
        data = call("elbv2", "describe-target-groups", "--names", f"{PROJECT}-{color}")
        groups[color] = data["TargetGroups"][0]["TargetGroupArn"]
    rule = call("elbv2", "describe-rules", "--rule-arns", listener_rule)["Rules"][0]
    active_color = groups_from_rule(rule, groups["blue"], groups["green"])
    inactive_color = "green" if active_color == "blue" else "blue"
    active_service = blue if active_color == "blue" else green
    inactive_service = green if inactive_color == "green" else blue
    active = service(active_service)
    current = call("ecs", "describe-task-definition", "--task-definition", active["taskDefinition"])["taskDefinition"]
    current_tags = {x.get("name"): x.get("image", "") for x in current.get("containerDefinitions", [])}
    images = get_images(tag)
    print(f"ACTIVE={active_color} TARGET={inactive_color} TAG={tag}")
    if all(current_tags.get(name) == value for name, value in images.items()):
        print("ALREADY LIVE: both production images match the requested tag")
        return "unchanged"
    if preview:
        print("PREVIEW: would update inactive service, verify ALB health, switch rule, bake, then scale down old service")
        return "preview"
    if active.get("desiredCount") != 1 or not healthy_target(groups[active_color]):
        raise DeploymentError("Current production service is not healthy; refusing update")
    new_task = register_task_images(active["taskDefinition"], images)
    call("ecs", "update-service", "--cluster", f"{PROJECT}-ecs", "--service", inactive_service,
         "--task-definition", new_task, "--desired-count", "1")
    wait_for_health(inactive_service, groups[inactive_color])
    # Last read before traffic switch; fail closed if another actor modified rule.
    rule_now = call("elbv2", "describe-rules", "--rule-arns", listener_rule)["Rules"][0]
    if groups_from_rule(rule_now, groups["blue"], groups["green"]) != active_color:
        raise DeploymentError("Listener rule changed during build; refusing traffic switch")
    modify_rule(listener_rule, groups[inactive_color], groups[active_color])
    print(f"SWITCHED: production traffic -> {inactive_color}")
    try:
        deadline = time.monotonic() + bake_seconds
        while time.monotonic() < deadline:
            if not healthy_target(groups[inactive_color]):
                raise DeploymentError("New target became unhealthy during bake")
            time.sleep(min(5, max(0.01, deadline - time.monotonic())))
    except DeploymentError:
        modify_rule(listener_rule, groups[active_color], groups[inactive_color])
        raise
    call("ecs", "update-service", "--cluster", f"{PROJECT}-ecs", "--service", active_service,
         "--desired-count", "0")
    print(f"SUCCESS: {inactive_color} serves production, {active_color} scaled down")
    return "deployed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--deploy", action="store_true", help="Real AWS modifications; otherwise preview")
    ap.add_argument("--bake-seconds", type=int, default=30)
    args = ap.parse_args()
    if args.bake_seconds < 0 or args.bake_seconds > 300:
        ap.error("bake seconds must be 0-300")
    try:
        run(args.tag, not args.deploy, args.bake_seconds)
        return 0
    except (DeploymentError, subprocess.TimeoutExpired, OSError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
