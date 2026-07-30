from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx


class GitHubClient:
    """Read fixed Git objects from local clones or the GitHub REST API."""

    def __init__(
        self,
        science_repo_path: str | None = None,
        audit_repo_path: str | None = None,
        science_repo: str | None = None,
        audit_repo: str | None = None,
        token: str | None = None,
        api_url: str | None = None,
    ):
        self.repo_paths = {
            "science": science_repo_path or os.getenv("SCIENCE_REPO_PATH"),
            "audit": audit_repo_path or os.getenv("AUDIT_REPO_PATH"),
        }
        self.repo_full_names = {
            "science": science_repo or os.getenv("SCIENCE_REPO_FULL_NAME"),
            "audit": audit_repo or os.getenv("AUDIT_REPO_FULL_NAME"),
        }
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.api_url = (api_url or os.getenv("GITHUB_API_URL") or "https://api.github.com").rstrip("/")

    @staticmethod
    def verify_signature(secret: str | None, raw_body: bytes, signature_header: str | None) -> bool:
        if not secret or not signature_header or not signature_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    @staticmethod
    def changed_files_from_push(payload: dict[str, Any]) -> list[str]:
        """Extract advisory payload paths. Security decisions must not use this list."""

        files: set[str] = set()
        for commit in payload.get("commits", []):
            for key in ("added", "modified", "removed"):
                files.update(commit.get(key, []))
        return sorted(files)

    def get_file_at_commit(self, repo_kind: str, commit_sha: str, path: str) -> str:
        repo_path = self.repo_paths.get(repo_kind)
        if repo_path:
            return self._git_show(Path(repo_path), commit_sha, path)

        repo = self._repo_name(repo_kind)
        encoded_path = quote(path, safe="/")
        data = self._request_json(
            "GET",
            f"/repos/{quote(repo, safe='/')}/contents/{encoded_path}",
            params={"ref": commit_sha},
            not_found_message=f"{path} does not exist at {commit_sha}",
        )
        content = data.get("content")
        if data.get("encoding") != "base64" or not isinstance(content, str):
            raise RuntimeError(f"GitHub did not return inline base64 content for {path}")
        return base64.b64decode(content).decode("utf-8")

    def get_json_at_commit(self, repo_kind: str, commit_sha: str, path: str) -> dict[str, Any]:
        return json.loads(self.get_file_at_commit(repo_kind, commit_sha, path))

    def list_changed_files(self, repo_kind: str, before_sha: str | None, after_sha: str) -> list[str]:
        repo_path = self.repo_paths.get(repo_kind)
        if repo_path:
            return self._local_changed_files(Path(repo_path), before_sha, after_sha)

        after_tree = self._remote_tree(repo_kind, after_sha)
        before_tree = {} if self._is_zero_sha(before_sha) else self._remote_tree(repo_kind, before_sha or "")
        paths = set(before_tree) | set(after_tree)
        return sorted(path for path in paths if before_tree.get(path) != after_tree.get(path))

    def is_ancestor(self, repo_kind: str, base_sha: str | None, head_sha: str) -> bool:
        if self._is_zero_sha(base_sha):
            return True
        repo_path = self.repo_paths.get(repo_kind)
        if repo_path:
            result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", base_sha or "", head_sha],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        repo = self._repo_name(repo_kind)
        try:
            data = self._request_json(
                "GET",
                (
                    f"/repos/{quote(repo, safe='/')}/compare/"
                    f"{quote(base_sha or '', safe='')}...{quote(head_sha, safe='')}"
                ),
                not_found_message=f"{base_sha} is not an ancestor of {head_sha}",
            )
        except FileNotFoundError:
            return False
        return data.get("status") in {"ahead", "identical"}

    def commit_exists(self, repo_kind: str, commit_sha: str) -> bool:
        repo_path = self.repo_paths.get(repo_kind)
        if repo_path:
            result = subprocess.run(
                ["git", "cat-file", "-e", f"{commit_sha}^{{commit}}"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        repo = self._repo_name(repo_kind)
        try:
            self._request_json(
                "GET",
                f"/repos/{quote(repo, safe='/')}/commits/{quote(commit_sha, safe='')}",
                not_found_message=f"commit does not exist: {commit_sha}",
            )
            return True
        except FileNotFoundError:
            return False

    def _remote_tree(self, repo_kind: str, commit_sha: str) -> dict[str, tuple[str, str | None]]:
        if not commit_sha:
            raise RuntimeError("a fixed commit SHA is required for tree comparison")
        repo = self._repo_name(repo_kind)
        data = self._request_json(
            "GET",
            f"/repos/{quote(repo, safe='/')}/git/trees/{quote(commit_sha, safe='')}",
            params={"recursive": "1"},
            not_found_message=f"commit tree does not exist: {commit_sha}",
        )
        if data.get("truncated") is True:
            raise RuntimeError(f"GitHub returned a truncated tree for {repo}@{commit_sha}")
        return {
            item["path"]: (item.get("type", ""), item.get("sha"))
            for item in data.get("tree", [])
            if item.get("type") != "tree" and isinstance(item.get("path"), str)
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        not_found_message: str,
    ) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "science-audit-controller",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = httpx.request(
            method,
            self.api_url + path,
            headers=headers,
            params=params,
            timeout=20.0,
        )
        if response.status_code == 404:
            raise FileNotFoundError(not_found_message)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"unexpected GitHub response for {path}")
        return data

    def _repo_name(self, repo_kind: str) -> str:
        repo = self.repo_full_names.get(repo_kind)
        if not repo or "/" not in repo:
            raise RuntimeError(
                f"{repo_kind} repository is not configured; set its local path or full GitHub owner/name"
            )
        return repo

    @staticmethod
    def _local_changed_files(repo_path: Path, before_sha: str | None, after_sha: str) -> list[str]:
        if GitHubClient._is_zero_sha(before_sha):
            empty_tree = subprocess.run(
                ["git", "mktree"],
                cwd=repo_path,
                input="",
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            command = ["git", "diff", "--name-only", empty_tree, after_sha]
        else:
            command = ["git", "diff", "--name-only", before_sha or "", after_sha]
        result = subprocess.run(
            command,
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return sorted({line for line in result.stdout.splitlines() if line})

    @staticmethod
    def _is_zero_sha(value: str | None) -> bool:
        return not value or set(value) == {"0"}

    @staticmethod
    def _git_show(repo_path: Path, commit_sha: str, path: str) -> str:
        # Bytes-faithful read: text=True would apply newline translation, so the
        # recorded artifact hashes would not attest to the committed blob.
        result = subprocess.run(
            ["git", "show", f"{commit_sha}:{path}"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8")
