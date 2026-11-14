#!/usr/bin/env python3
"""Rotate a restricted Woodpecker ECR registry secret via localhost API.

Runs on the trusted EC2 host using its IAM instance profile. Never prints tokens.
This file contains NO credentials; the Woodpecker API token is root-only on disk.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

WOODPECKER_API = "http://127.0.0.1:8000/api"
REPOSITORY = "reinsonsronalds-design/BC_TEAM4"
API_TOKEN_FILE = Path("/etc/slice-sip-ci/woodpecker-api-token")
ECR_REGION = "eu-west-1"
SECRET_NAME = "ecr_password"
PLUGIN_IMAGE = "woodpeckerci/plugin-kaniko@sha256:54d5a5869ddb652372979b7714b706826fda33d48ea94c9d54d673be16ab5645"


def request(method: str, path: str, api_token: str, payload: dict | None = None):
    headers = {"Authorization": "Bearer " + api_token, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        WOODPECKER_API + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = response.read()
            return response.status, (json.loads(data) if data else None)
    except urllib.error.HTTPError as exc:
        # Do not show server response body: it might include credentials.
        if exc.code == 404:
            return 404, None
        raise RuntimeError(f"Woodpecker API {method} {path}: HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RuntimeError("Cannot reach Woodpecker API on EC2 localhost:8000") from None


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--check", action="store_true", help="Check access only; do not write secret")
    parsed = args.parse_args()

    if os.geteuid() != 0:
        raise RuntimeError("Run as root, through the approved systemd service or sudo")
    if not API_TOKEN_FILE.is_file():
        raise RuntimeError("Root-only Woodpecker API token file is missing")
    stat = API_TOKEN_FILE.stat()
    if stat.st_uid != 0 or stat.st_mode & 0o077:
        raise RuntimeError("Woodpecker token must be root-owned and mode 0600")
    api_token = API_TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not api_token or "\n" in api_token:
        raise RuntimeError("Woodpecker API token is empty or malformed")

    rc, repos = request("GET", "/user/repos?all=true", api_token)
    if rc != 200 or not isinstance(repos, list):
        raise RuntimeError("Cannot list Woodpecker repositories with supplied token")
    candidates = [r for r in repos if r.get("full_name", "").lower() == REPOSITORY.lower()]
    if len(candidates) != 1:
        raise RuntimeError("BC_TEAM4 is unavailable to this Woodpecker account")
    repo_id = candidates[0]["id"]

    # Check EC2 role ability without printing the 12-hour ECR password.
    process = subprocess.run(
        ["aws", "ecr", "get-login-password", "--region", ECR_REGION],
        capture_output=True, text=True, timeout=60, check=False
    )
    if process.returncode != 0 or not process.stdout.strip():
        raise RuntimeError("EC2 instance profile failed to obtain an ECR login password")
    password = process.stdout.strip()

    if parsed.check:
        print("Preflight OK: Woodpecker repository found and ECR IAM authentication works")
        return

    secret = {
        "name": SECRET_NAME,
        "value": password,
        "events": ["push", "manual"],
        "images": [PLUGIN_IMAGE],
    }
    rc, _ = request("GET", f"/repos/{repo_id}/secrets/{SECRET_NAME}", api_token)
    if rc == 404:
        method, path = "POST", f"/repos/{repo_id}/secrets"
    elif rc == 200:
        method, path = "PATCH", f"/repos/{repo_id}/secrets/{SECRET_NAME}"
    else:
        raise RuntimeError(f"Unexpected secret lookup status: HTTP {rc}")
    result, _ = request(method, path, api_token, secret)
    if result not in (200, 201, 204):
        raise RuntimeError(f"Woodpecker secret update failed: HTTP {result}")
    print("Woodpecker ECR registry secret refreshed; restricted to push/manual + pinned Kaniko plugin")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
