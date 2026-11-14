"""Offline safety checks for demo branch and health-gated traffic switching."""
from __future__ import annotations
import importlib.util
from pathlib import Path
from unittest.mock import patch

DIR = Path(__file__).resolve().parents[1]

def load(name: str):
    spec = importlib.util.spec_from_file_location(name, DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

blue_green = load("roleless_blue_green")
poller = load("demo_poller")
release = load("demo_release")

BLUE = "arn:aws:elasticloadbalancing:eu-west-1:597765856364:targetgroup/slice-sip-blue/123"
GREEN = "arn:aws:elasticloadbalancing:eu-west-1:597765856364:targetgroup/slice-sip-green/456"

def rule(a, b):
    return {"Actions": [{"Type": "forward", "ForwardConfig": {"TargetGroups": [
        {"TargetGroupArn": BLUE, "Weight": a},
        {"TargetGroupArn": GREEN, "Weight": b}]}}]}

def test_identifies_blue_and_green():
    assert blue_green.groups_from_rule(rule(100, 0), BLUE, GREEN) == "blue"
    assert blue_green.groups_from_rule(rule(0, 100), BLUE, GREEN) == "green"

def test_refuses_partial_switch():
    import pytest
    with pytest.raises(blue_green.DeploymentError):
        blue_green.groups_from_rule(rule(50, 50), BLUE, GREEN)

def test_refuses_rogue_target_group():
    import pytest
    with pytest.raises(blue_green.DeploymentError):
        blue_green.groups_from_rule(rule(100, 0), BLUE, GREEN + "x")

def test_poller_only_matches_approved_branch_and_commit():
    good = {"branch": poller.BRANCH, "commit": "a" * 40, "event": "manual", "number": 8, "status": "success"}
    other = {**good, "branch": "main", "number": 11}
    fork = {**good, "number": 10, "from_fork": True}
    assert poller.pipeline_for_sha([good, other, fork], "a" * 40) is good
    assert poller.pipeline_for_sha([good], "b" * 40) is None

def test_poller_prefers_latest_matching_build():
    base = {"branch": poller.BRANCH, "commit": "b" * 40, "event": "manual", "number": 3, "status": "failure"}
    new = {**base, "number": 4, "status": "success"}
    assert poller.pipeline_for_sha([base, new], "b" * 40) is new

def test_provision_preview_does_not_write():
    with patch.object(release, "cmd", side_effect=AssertionError("should not execute")):
        release.release("c" * 40 + "-12", execute=False)

def test_switch_preview_does_not_update_aws():
    tag = "d" * 40 + "-12"
    active = {"taskDefinition": "some-task", "desiredCount": 1}
    def fake_call(svc, operation, *args):
        if (svc, operation) == ("elbv2", "describe-target-groups"):
            return {"TargetGroups": [{"TargetGroupArn": BLUE if any("blue" in x for x in args) else GREEN}]}
        if (svc, operation) == ("elbv2", "describe-rules"):
            return {"Rules": [rule(100, 0)]}
        if (svc, operation) == ("ecs", "describe-task-definition"):
            return {"taskDefinition": {"containerDefinitions": [{"name": "frontend", "image": "old"}, {"name": "backend", "image": "old"}]}}
        raise AssertionError((svc, operation, args))
    with patch.object(blue_green, "call", side_effect=fake_call), patch.object(blue_green, "tf_output", return_value="ignored"), patch.object(blue_green, "service", return_value=active), patch.object(blue_green, "get_images", return_value={"frontend": "new-frontend", "backend": "new-backend"}):
        assert blue_green.run(tag, preview=True) == "preview"
