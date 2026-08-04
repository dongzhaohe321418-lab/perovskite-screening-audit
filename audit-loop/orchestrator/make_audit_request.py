#!/usr/bin/env python3
"""Regenerate .audit/{audit_request,evidence_manifest}.json at the science repo HEAD.

Run on behalf of Claude Science (the sole executor, constitution §1.1) by the
audit MCP server's request_audit tool. Commits ONLY the .audit pathspec, so any
unrelated dirty state in the working tree is never swept into the commit.

Format contract: identical to the science-audit-controller bootstrap —
- evidence stream: every tracked path outside .audit, sorted bytewise, as
  '<file_sha256><two spaces><path><LF>'; tree_sha256 = SHA-256 of that stream.
- evidence_manifest_sha256 in audit_request.json = SHA-256 of the manifest's
  canonical JSON (sorted keys, compact separators, no trailing newline), which
  is exactly what CycleManager._validate_audit_request recomputes.

Prints the new HEAD commit sha as the last stdout line (MCP contract).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ID = "perovskite-screening"


def sh(args: list[str], cwd: Path, binary: bool = False) -> bytes | str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--reason", default="claude-science session-end audit request")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo)

    branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    if branch != args.branch:
        print(f"refusing: HEAD is on {branch!r}, expected {args.branch!r}", file=sys.stderr)
        return 2

    head = sh(["git", "rev-parse", "HEAD"], repo).strip()
    raw = sh(["git", "ls-files", "-z", "--", ":!.audit/**"], repo, binary=True)
    paths = sorted(p for p in raw.split(b"\x00") if p)

    stream = bytearray()
    total_bytes = 0
    for path in paths:
        blob = subprocess.run(
            ["git", "cat-file", "blob", b"HEAD:" + path],
            cwd=repo, check=True, capture_output=True,
        ).stdout
        total_bytes += len(blob)
        stream += hashlib.sha256(blob).hexdigest().encode() + b"  " + path + b"\n"
    tree_sha256 = hashlib.sha256(bytes(stream)).hexdigest()

    manifest = {
        "algorithm": "sha256sum-list-v1",
        "canonical_stream": (
            "For every tracked path outside .audit, sort paths bytewise and append "
            "'<file_sha256><two spaces><path><LF>'; SHA-256 the resulting byte stream."
        ),
        "evidence_parent_commit": head,
        "excluded_paths": [".audit/**"],
        "file_count": len(paths),
        "project_id": PROJECT_ID,
        "recompute_command": (
            "git ls-files -z -- ':!.audit/**' | xargs -0 shasum -a 256 | shasum -a 256"
        ),
        "scope_roots": sorted({p.decode().split("/")[0] + ("/" if b"/" in p else "")
                               for p in paths}),
        "total_bytes": total_bytes,
        "tree_sha256": tree_sha256,
    }
    manifest_canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_sha = hashlib.sha256(manifest_canonical).hexdigest()

    request = {
        "audit_scope": (
            "Independent audit of all tracked scientific code, data and input manifests, "
            "computed results, reports, XRD analysis, and scientific claims at the fixed "
            "Science Commit. Verify provenance, reproducibility, internal consistency, "
            "decision gates, and high-risk production or publication claims."
        ),
        "evidence_manifest_path": ".audit/evidence_manifest.json",
        "evidence_manifest_sha256": manifest_sha,
        "notes": f"Requested via audit-mcp: {args.reason}",
        "project_id": PROJECT_ID,
        "requested_by": "claude-science-via-audit-mcp",
    }

    if args.dry_run:
        print(json.dumps({"manifest": manifest, "request": request}, indent=2))
        print(head)
        return 0

    audit_dir = repo / ".audit"
    audit_dir.mkdir(exist_ok=True)
    # Write the manifest in CANONICAL byte form (sorted keys, compact separators, no
    # trailing newline) so the file's raw-byte SHA-256 EQUALS the canonical-JSON digest
    # recorded in audit_request.json -- one hash convention, no ambiguity (audit F-018).
    (audit_dir / "evidence_manifest.json").write_bytes(manifest_canonical)
    (audit_dir / "audit_request.json").write_text(
        json.dumps(request, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    status = sh(["git", "status", "--porcelain", "--", ".audit"], repo).strip()
    if not status:
        print("no .audit changes; HEAD unchanged", file=sys.stderr)
        print(head)
        return 0
    sh(["git", "add", "--", ".audit"], repo)
    subprocess.run(
        ["git", "-c", "user.name=Claude Science (audit-mcp)",
         "-c", "user.email=claude-science@local",
         "commit", "-m", f"Audit request: {args.reason}", "--", ".audit"],
        cwd=repo, check=True, capture_output=True,
    )
    new_head = sh(["git", "rev-parse", "HEAD"], repo).strip()

    # ---- POST-COMMIT VERIFICATION (audit F-027) -------------------------------------
    # The digest above is taken at `head`, then .audit is committed on top -- so the
    # COMMITTED manifest describes its own parent tree, not the commit that carries it.
    # For the non-.audit evidence tree those are identical (the commit touches .audit
    # only), and that is what makes the binding valid. But if anything outside .audit
    # differs, the manifest does not identify the tree the gate binds to. Verify against
    # the committed objects rather than assume, and refuse to leave a bad binding behind.
    ls = subprocess.run(["git", "ls-tree", "-r", "-z", "--name-only", new_head],
                        cwd=repo, capture_output=True, check=True).stdout
    committed = sorted(q for q in ls.split(b"\0") if q and not q.startswith(b".audit/"))
    vstream = b""
    for q in committed:
        blob = subprocess.run(["git", "show", f"{new_head}:{q.decode()}"],
                              cwd=repo, capture_output=True, check=True).stdout
        vstream += hashlib.sha256(blob).hexdigest().encode() + b"  " + q + b"\n"
    verified = hashlib.sha256(vstream).hexdigest()
    if verified != tree_sha256:
        print(f"FATAL: committed manifest tree_sha256 {tree_sha256[:12]} does not describe the "
              f"tree at {new_head[:12]} (recomputed {verified[:12]}). The evidence binding would "
              f"be invalid -- audit F-027. Files outside .audit changed between digest and "
              f"commit; re-run so the digest is taken from a clean tree.", file=sys.stderr)
        return 3
    print(f"manifest verified against committed tree {new_head[:12]}: {verified[:12]}",
          file=sys.stderr)
    print(new_head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
