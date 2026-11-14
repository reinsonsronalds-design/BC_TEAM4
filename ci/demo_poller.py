#!/usr/bin/env python3
"""Root-owned EC2 poller: Git HEAD -> Woodpecker manual run -> verified ECR -> deploy.

No GitHub webhook/NGROK required. Never executes freshly pulled repository
scripts with IAM access. The pinned /opt/slice-sip-demo code is installed
and reviewed before the presentation. Requires an explicit root-only arm file.
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
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BRANCH = "devops/demo-pipeline"
REPOSITORY = "reinsonsronalds-design/BC_TEAM4"
SOURCE = "/home/ssm-user/slice-sip-ci-source"
API_BASE = "http://127.0.0.1:8000/api"
TOKEN = Path("/etc/slice-sip-ci/woodpecker-api-token")
ARM = Path("/etc/slice-sip-ci/demo-armed")
STATE = Path("/var/lib/slice-sip-ci/demo-state.json")
LOCK = Path("/var/lib/slice-sip-ci/demo-poller.lock")
SHA = re.compile(r"^[0-9a-f]{40}$")

class PollError(Exception):
    pass

def protected_text(path: Path) -> str:
    data = path.stat()
    if data.st_uid != 0 or data.st_mode & 0o077 or not path.is_file():
        raise PollError(f"Expected root-owned, private file: {path}")
    return path.read_text(encoding="utf-8").strip()

def api(method: str, endpoint: str, token: str, payload: dict | None = None):
    if not endpoint.startswith("/") or endpoint.startswith("//"):
        raise PollError("Invalid Woodpecker API path")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    req = Request(API_BASE + endpoint, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as res:
            return json.load(res)
    except HTTPError as exc:
        raise PollError(f"Woodpecker API HTTP {exc.code} on {method} request") from None
    except (URLError, ValueError, TimeoutError) as exc:
        raise PollError("Woodpecker API not reachable or returned invalid JSON") from exc

def git_head() -> str:
    result = subprocess.run(["runuser", "-u", "ssm-user", "--", "git", "-C", SOURCE,
                             "ls-remote", "--exit-code", "origin", f"refs/heads/{BRANCH}"],
                            capture_output=True, text=True, timeout=45, check=False,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        raise PollError("Git remote HEAD unavailable; check EC2 clone access and demo branch")
    parts = result.stdout.strip().split()
    if len(parts) != 2 or parts[1] != f"refs/heads/{BRANCH}" or not SHA.fullmatch(parts[0]):
        raise PollError("Unexpected Git remote response")
    return parts[0]

def repo_id(token: str) -> int:
    info = api("GET", f"/repos/lookup/{quote(REPOSITORY, safe='/')}", token)
    if not isinstance(info, dict) or info.get("full_name", "").lower() != REPOSITORY.lower():
        raise PollError("Woodpecker repository does not match approved repo")
    result = info.get("id")
    if type(result) is not int or result <= 0:
        raise PollError("Woodpecker repository ID is invalid")
    return result

def pipelines(token: str, rid: int) -> list[dict]:
    q = urlencode({"branch": BRANCH, "page": 1, "perPage": 50})
    records = api("GET", f"/repos/{rid}/pipelines?{q}", token)
    if not isinstance(records, list):
        raise PollError("Invalid Woodpecker pipeline listing")
    return records

def pipeline_for_sha(records: list[dict], sha: str) -> dict | None:
    matches = [p for p in records if isinstance(p, dict) and p.get("commit") == sha
               and p.get("branch") == BRANCH and p.get("event") in ("manual", "push")
               and type(p.get("number")) is int and p["number"] > 0
               and p.get("from_fork") is not True]
    return max(matches, key=lambda p: p["number"]) if matches else None

def load_state() -> dict:
    if not STATE.exists():
        return {"deployed_sha": None, "failed_sha": None}
    return json.loads(protected_text(STATE))

def save_state(data: dict) -> None:
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE.parent, 0o700)
    fd, filename = tempfile.mkstemp(prefix=".demo-state-", dir=STATE.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(filename, STATE)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)

def tick(dry_run: bool = True) -> str:
    sha = git_head()
    if not dry_run and protected_text(ARM) != "ARM_SLICE_SIP_DEMO":
        raise PollError("Demo is not armed; no writes will occur")
    state = load_state()
    if state.get("ignored_sha") == sha:
        return f"NOOP: {sha[:12]} recorded as pre-demo baseline (not deployed)"
    if state.get("deployed_sha") == sha:
        return f"NOOP: {sha[:12]} already deployed"
    if state.get("failed_sha") == sha:
        return f"BLOCKED: {sha[:12]} previously failed; review manually before retriggering"
    token = protected_text(TOKEN)
    rid = repo_id(token)
    record = pipeline_for_sha(pipelines(token, rid), sha)
    if record is None:
        if dry_run:
            return f"PREVIEW: would trigger Woodpecker manual pipeline on {BRANCH} ({sha[:12]})"
        response = api("POST", f"/repos/{rid}/pipelines", token,
                       {"branch": BRANCH, "message": "Slice & Sip demo Git poller"})
        if not isinstance(response, dict) or response.get("commit") != sha:
            raise PollError("Triggered pipeline does not match polled commit (race); refuse deployment")
        return f"TRIGGERED: Woodpecker pipeline #{response.get('number')} for {sha[:12]}"
    status = record.get("status")
    number = record["number"]
    if status != "success":
        if status in ("failure", "error", "killed", "declined"):
            if not dry_run:
                state["failed_sha"] = sha
                save_state(state)
            return f"FAILED: Woodpecker pipeline #{number} status={status}; AWS unchanged"
        return f"WAITING: Woodpecker pipeline #{number} status={status}"
    tag = f"{sha}-{number}"
    if dry_run:
        return f"PREVIEW: pipeline #{number} successful; would deploy ECR images {tag}"
    # Record attempt before AWS writes to avoid automatic concurrent retries.
    state["failed_sha"] = sha
    save_state(state)
    command = ["python3", "/opt/slice-sip-demo/ci/demo_release.py", "--tag", tag, "--execute"]
    result = subprocess.run(command, text=True, check=False, timeout=3000)
    if result.returncode:
        return f"DEPLOY FAILED: {tag} (needs human review; previous ALB targets retained where possible)"
    state["deployed_sha"] = sha
    state["failed_sha"] = None
    save_state(state)
    return f"DEPLOYED: {tag}"

def main() -> int:
    import fcntl  # Linux-only runtime locking
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watch", action="store_true", help="Poll every 60 seconds until stopped")
    ap.add_argument("--execute", action="store_true", help="Enable writes if protected arm file exists")
    ap.add_argument("--baseline-current", action="store_true", help="Mark current remote commit as pre-demo baseline without building it")
    args = ap.parse_args()
    if os.geteuid() != 0:
        print("ERROR: poller requires root to read existing protected Woodpecker token", file=sys.stderr)
        return 2
    LOCK.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.baseline_current:
            sha = git_head()
            state = load_state()
            state["ignored_sha"] = sha
            save_state(state)
            print(f"BASELINE: {sha[:12]} will be ignored until a NEW Git push (no CI or AWS changes)")
            return 0
        while True:
            try:
                print(tick(dry_run=not args.execute), flush=True)
            except (PollError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
                print(f"POLL ERROR: {exc}", file=sys.stderr, flush=True)
                if not args.watch:
                    return 2
            if not args.watch:
                return 0
            time.sleep(60)

if __name__ == "__main__":
    sys.exit(main())
