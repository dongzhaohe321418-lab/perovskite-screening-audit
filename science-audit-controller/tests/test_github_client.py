from __future__ import annotations

import subprocess

from app.github_client import GitHubClient


def git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_local_git_mode_compares_initial_push_against_empty_tree(tmp_path):
    repo = tmp_path / "audit-repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "projects").mkdir()
    artifact = repo / "projects" / "artifact.txt"
    artifact.write_text("audit artifact\n", encoding="utf-8")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Controller Test",
        "-c",
        "user.email=controller@example.invalid",
        "commit",
        "-m",
        "initial audit",
    )
    head = git(repo, "rev-parse", "HEAD")
    client = GitHubClient(audit_repo_path=str(repo))

    changed = client.list_changed_files("audit", "0" * 40, head)

    assert changed == ["projects/artifact.txt"]
    assert client.is_ancestor("audit", "0" * 40, head)
    assert client.commit_exists("audit", head)
