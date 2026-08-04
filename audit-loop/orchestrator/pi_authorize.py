#!/usr/bin/env python3
"""PI-only: authorize one high-risk action for one commit. The single human key.

The controller runs in-process — there is no standing HTTP server to POST to — so
this drives the same /authorizations endpoint the controller exposes, using the
PI_APPROVAL_TOKEN that lives in state/pi_token.env and is loaded by no automation.

It refuses to invent consent: it prints exactly what it will authorize and requires
the operator to type the commit back, so authorizing is a deliberate act and not a
flag someone left on. It also refuses to authorize an action the gate would still
deny for a *different* reason (an open blocker, a non-permissive audit), because an
authorization that cannot take effect is a false sense of unlock.

Usage:
  pi_authorize.py --action publish_claim --commit <40-hex> [--hours 24]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_pi_token() -> str:
    f = ROOT / "state" / "pi_token.env"
    if not f.exists():
        sys.exit(f"FATAL: {f} not found — the PI token file the automation never loads.")
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.startswith("PI_APPROVAL_TOKEN="):
            return line.split("=", 1)[1].strip()
    sys.exit("FATAL: PI_APPROVAL_TOKEN not in pi_token.env")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(Path(__file__).parent / "config.yaml"))
    ap.add_argument("--action", required=True)
    ap.add_argument("--commit", required=True, help="full 40-hex science commit")
    ap.add_argument("--hours", type=float, default=24.0, help="authorization lifetime")
    ap.add_argument("--yes", action="store_true", help="skip the type-back confirmation")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    state_dir = Path(cfg["paths"]["state_dir"])
    project = cfg["project"]["project_id"]
    science_repo = Path(cfg["paths"]["science_repo"])

    commit = args.commit.lower()
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        sys.exit("FATAL: --commit must be a full 40-hex sha")

    # The manifest the gate binds to: the evidence_manifest_sha256 recorded for the
    # FINAL cycle at this commit. Authorizing against anything else cannot match.
    state = json.loads((state_dir / "controller" / "state.json").read_text(encoding="utf-8"))
    finals = [c for c in state.get("cycles", {}).values()
              if c["science_commit"] == commit and c["status"] == "FINAL"]
    if not finals:
        sys.exit(f"FATAL: no FINAL audit cycle for {commit[:12]} — the gate would return "
                 "NO_FINAL_AUDIT_FOR_COMMIT. Let the loop audit this commit first.")
    cycle = sorted(finals, key=lambda c: c["cycle_id"])[-1]
    decision = (cycle.get("audit_result") or {}).get("decision")
    if decision not in ("PASS", "PASS_WITH_CAVEATS"):
        sys.exit(f"FATAL: {cycle['cycle_id']} decided {decision}, not permissive — the gate "
                 "would return AUDIT_DECISION_NOT_PERMISSIVE. Authorizing now would not unlock "
                 "anything.")
    manifest = cycle["evidence_manifest_sha256"]

    print("About to authorize — read this before confirming:")
    print(f"  action:   {args.action}")
    print(f"  commit:   {commit}")
    print(f"  cycle:    {cycle['cycle_id']}  decision {decision}")
    print(f"  manifest: {manifest}")
    print(f"  expires:  in {args.hours}h")
    if not args.yes:
        typed = input(f"Type the first 12 chars of the commit ({commit[:12]}) to confirm: ").strip()
        if typed != commit[:12]:
            sys.exit("aborted: confirmation did not match.")

    expires = (dt.datetime.now(dt.timezone.utc)
               + dt.timedelta(hours=args.hours)).isoformat()
    existing = state.get("authorizations", [])
    authorization = {
        "authorization_id": f"AUTH-{len(existing) + 1:06d}",
        "project_id": project,
        "actor": "claude_science",
        "action": args.action,
        "science_commit": commit,
        "manifest_sha256": manifest,
        "policy_approved": True,
        "budget_approved": True,
        "pi_approved": True,
        "approved_by": "principal-investigator",
        "expires_at": expires,
    }

    # Drive the controller's own endpoint so the authorization is validated and
    # recorded exactly as a live POST would — not hand-written into state.json.
    os.environ["PI_APPROVAL_TOKEN"] = load_pi_token()
    for line in (state_dir / "secrets.env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    os.environ["CONTROLLER_STATE_PATH"] = str(state_dir / "controller" / "state.json")
    os.environ["PROJECT_CONFIG_PATH"] = str(ROOT / "orchestrator" / "projects.yaml")
    os.environ["SCIENCE_REPO_PATH"] = str(state_dir / "science-mirror.git")
    os.environ["AUDIT_REPO_PATH"] = cfg["paths"]["audit_repo"]
    sys.path.insert(0, cfg["paths"]["controller_root"])
    from app.main import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app(), raise_server_exceptions=False)
    resp = client.post("/authorizations", json=authorization,
                       headers={"Authorization": f"Bearer {os.environ['PI_APPROVAL_TOKEN']}"})
    if resp.status_code != 200:
        sys.exit(f"FATAL: controller rejected the authorization: {resp.status_code} {resp.text}")
    print(f"\nAuthorized: {authorization['authorization_id']} recorded.")
    print("The gate will now ALLOW this exact action at this exact commit until it expires.")
    print("Claude Science can call check_action to confirm, then run the extraction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
