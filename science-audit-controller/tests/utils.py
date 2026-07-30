from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.github_client import GitHubClient


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "perovskite-screening"


class FakeGitHub(GitHubClient):
    def __init__(self):
        self.files: dict[tuple[str, str, str], str] = {}
        self.diffs: dict[tuple[str, str | None, str], list[str]] = {}
        self.existing_commits: set[str] = set()
        self.list_failures_remaining = 0
        self.file_failures_remaining = 0
        self.ancestor_results: dict[tuple[str, str | None, str], bool] = {}

    def get_file_at_commit(self, repo_kind: str, commit_sha: str, path: str) -> str:
        if self.file_failures_remaining:
            self.file_failures_remaining -= 1
            raise RuntimeError("temporary GitHub content failure")
        key = (repo_kind, commit_sha, path)
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    def list_changed_files(self, repo_kind: str, before_sha: str | None, after_sha: str) -> list[str]:
        if self.list_failures_remaining:
            self.list_failures_remaining -= 1
            raise RuntimeError("temporary GitHub failure")
        return list(self.diffs.get((repo_kind, before_sha, after_sha), []))

    def commit_exists(self, repo_kind: str, commit_sha: str) -> bool:
        return commit_sha in self.existing_commits or any(
            kind == repo_kind and sha == commit_sha
            for kind, sha, _ in self.files
        )

    def is_ancestor(self, repo_kind: str, base_sha: str | None, head_sha: str) -> bool:
        return self.ancestor_results.get((repo_kind, base_sha, head_sha), True)

    def set_diff(
        self,
        repo_kind: str,
        before_sha: str | None,
        after_sha: str,
        paths: list[str],
    ) -> None:
        self.diffs[(repo_kind, before_sha, after_sha)] = paths


def policy_bundle() -> dict[str, Any]:
    """A well-formed policy bundle: the receipt must always name its own policy."""
    return {
        "constitution_sha256": "a" * 64,
        "rulebook_version": "1.0.0",
        "rulebook_sha256": "b" * 64,
        "checks_sha256": "c" * 64,
    }


def valid_audit_request() -> dict[str, Any]:
    return {
        "project_id": PROJECT_ID,
        "audit_scope": "MVP audit",
        "evidence_manifest_sha256": "a" * 64,
    }


def audit_artifacts(
    fake: FakeGitHub,
    commit: str,
    cycle,
    decision: str,
    findings: list[dict[str, Any]],
    *,
    verified_closed_findings: list[dict[str, Any]] | None = None,
) -> list[str]:
    prefix = f"projects/{cycle.project_id}/cycles/{cycle.cycle_id}/"
    audit_result = {
        "cycle_id": cycle.cycle_id,
        "audited_commit": cycle.science_commit,
        "decision": decision,
        "findings": findings,
        "verified_closed_findings": verified_closed_findings or [],
    }
    contents = {
        "audit_report.md": f"# Audit Report\n\nDecision: {decision}\n",
        "audit_result.json": json.dumps(audit_result, sort_keys=True),
        "codex_run_metadata.json": json.dumps(
            {
                "cycle_id": cycle.cycle_id,
                "audited_commit": cycle.science_commit,
                "runner": "fake-codex",
                "model": "fake-model",
                "started_at": "2026-07-30T00:00:00+00:00",
                "completed_at": "2026-07-30T00:01:00+00:00",
                "policy_bundle": policy_bundle(),
            },
            sort_keys=True,
        ),
    }
    contents["report_manifest.json"] = json.dumps(
        {
            "cycle_id": cycle.cycle_id,
            "files": {
                name: {"sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
                for name, content in contents.items()
            },
        },
        sort_keys=True,
    )
    paths = []
    for name, content in contents.items():
        path = prefix + name
        fake.files[("audit", commit, path)] = content
        paths.append(path)
    return paths
