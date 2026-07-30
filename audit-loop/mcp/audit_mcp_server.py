#!/usr/bin/env python3
"""science-audit-loop MCP server (local stdio, hand-rolled JSON-RPC 2.0).

本地 stdio MCP server：让 "Claude Science" 在每次 session 结束时与本地科学审计
流水线交互 —— 查看审计状态、领取 pending review、提交 disposition、请求新的
审计 cycle、确认 escalation、通知 PI（人为介入通道）。

设计约束:
  * stdout 只承载协议 JSON 行；所有日志走 stderr。
  * 单条消息的异常不会杀死主循环。
  * 所有写操作原子化（tmp + os.replace）；所有读操作容忍文件缺失。
  * 本 server 从不修改 scienceRepo / auditRepo 的内容。

运行:
  <audit-loop>/.venv/bin/python audit_mcp_server.py [--config <config.yaml>]
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import itertools
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# --------------------------------------------------------------------------
# stdout discipline: keep a private handle to the real stdout for protocol
# frames, then point sys.stdout at stderr so that ANY stray print() from this
# module or from imported third-party code (fastapi/httpx/controller) can never
# corrupt the JSON-RPC stream.
# --------------------------------------------------------------------------
PROTOCOL_OUT = sys.stdout
sys.stdout = sys.stderr

SERVER_NAME = "science-audit-loop"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

# Paths are derived from this file's location so a clone runs anywhere.
# Override with --config or AUDIT_LOOP_CONFIG.
_LOOP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = str(_LOOP_ROOT / "orchestrator" / "config.yaml")
FALLBACK_PROJECTS_YAML = str(_LOOP_ROOT / "orchestrator" / "projects.yaml")

# Least privilege: this server submits dispositions on Claude Science's behalf and
# nothing else. It must not hold PI_APPROVAL_TOKEN — an executor able to authorize
# its own high-risk action would collapse the two-key rule — nor the action or read
# tokens it never uses. Endpoints whose token is absent answer 503, which is the
# intended posture rather than a misconfiguration.
SECRET_KEYS = (
    "CLAUDE_API_TOKEN",
)

DISPOSITION_VALUES = (
    "ACCEPT_AND_FIX",
    "ACCEPT_AND_STOP",
    "DISAGREE_WITH_EVIDENCE",
    "NEED_PI_DECISION",
    "DEFER_WITH_CAVEAT",
    "PASS_NO_ACTION",
)

SHA40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
CYCLE_ID_RE = re.compile(r"^CYCLE-[0-9]{6}$")

# audit_report.md is embedded verbatim; guard against pathological sizes.
MAX_EMBED_CHARS = 200_000

_EVENT_SEQ = itertools.count(1)


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    sys.stderr.write(f"[{stamp}] {SERVER_NAME}: {message}\n")
    sys.stderr.flush()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolError(Exception):
    """Tool-level failure -> reported as isError:true, never a protocol error."""


# --------------------------------------------------------------------------
# file helpers
# --------------------------------------------------------------------------
def read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, PermissionError):
        return None
    except OSError as exc:  # pragma: no cover - defensive
        log(f"read failed for {path}: {exc}")
        return None


def read_json_or_none(path: Path) -> Any | None:
    raw = read_text_or_none(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log(f"malformed JSON in {path}: {exc}")
        return None


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def append_log_line(path: Path, line: str) -> None:
    """Append one line with a single O_APPEND write (atomic for small writes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (line.rstrip("\n") + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)


@contextlib.contextmanager
def file_lock(lock_path: Path):
    """Exclusive flock on a sidecar lock file, for read-modify-write cycles."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def move_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def truncate_for_embed(text: str, label: str) -> str:
    if len(text) <= MAX_EMBED_CHARS:
        return text
    head = text[:MAX_EMBED_CHARS]
    return (
        f"{head}\n\n[...{label} truncated: {len(text)} chars total, "
        f"first {MAX_EMBED_CHARS} shown. Read the file directly for the rest.]"
    )


# --------------------------------------------------------------------------
# context / config
# --------------------------------------------------------------------------
class Context:
    """Loaded configuration plus lazily-built controller client."""

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path).expanduser()
        self.config: dict[str, Any] = {}
        self.config_error: str | None = None
        self._controller_client: Any = None
        self._load()

    def _load(self) -> None:
        try:
            import yaml
        except Exception as exc:  # pragma: no cover
            self.config_error = f"PyYAML unavailable: {exc}"
            return
        raw = read_text_or_none(self.config_path)
        if raw is None:
            self.config_error = f"config not found: {self.config_path}"
            return
        try:
            parsed = yaml.safe_load(raw)
        except Exception as exc:
            self.config_error = f"config is not valid YAML ({self.config_path}): {exc}"
            return
        if not isinstance(parsed, dict):
            self.config_error = f"config must be a YAML mapping: {self.config_path}"
            return
        self.config = parsed
        paths = parsed.get("paths")
        if not isinstance(paths, dict):
            self.config_error = f"config has no 'paths' mapping: {self.config_path}"
            return
        required = ("science_repo", "audit_repo", "controller_root", "state_dir", "venv_python")
        missing = [key for key in required if not paths.get(key)]
        if missing:
            self.config_error = f"config paths missing keys: {', '.join(missing)}"

    def require_config(self) -> None:
        if self.config_error:
            raise ToolError(
                f"configuration error — {self.config_error}. "
                "Fix orchestrator/config.yaml (or pass --config) and restart the MCP server."
            )

    # -- derived paths ----------------------------------------------------
    @property
    def _paths(self) -> dict[str, Any]:
        value = self.config.get("paths")
        return value if isinstance(value, dict) else {}

    @property
    def _project(self) -> dict[str, Any]:
        value = self.config.get("project")
        return value if isinstance(value, dict) else {}

    @property
    def science_repo(self) -> Path:
        return Path(str(self._paths.get("science_repo", "")))

    @property
    def audit_repo(self) -> Path:
        return Path(str(self._paths.get("audit_repo", "")))

    @property
    def controller_root(self) -> Path:
        return Path(str(self._paths.get("controller_root", "")))

    @property
    def state_dir(self) -> Path:
        return Path(str(self._paths.get("state_dir", "")))

    @property
    def venv_python(self) -> Path:
        return Path(str(self._paths.get("venv_python", sys.executable)))

    @property
    def secrets_env(self) -> Path:
        value = self._paths.get("secrets_env")
        if value:
            return Path(str(value))
        return self.state_dir / "secrets.env"

    @property
    def science_branch(self) -> str:
        return str(self._project.get("science_branch") or "main")

    @property
    def project_id(self) -> str:
        return str(self._project.get("project_id") or "")

    @property
    def audit_loop_root(self) -> Path:
        """config.yaml lives at <audit_loop_root>/orchestrator/config.yaml."""
        return self.config_path.resolve().parent.parent

    @property
    def projects_yaml(self) -> Path:
        candidate = self.config_path.resolve().parent / "projects.yaml"
        if candidate.exists():
            return candidate
        return Path(FALLBACK_PROJECTS_YAML)

    @property
    def spool_dir(self) -> Path:
        return self.state_dir / "spool"

    @property
    def pending_dir(self) -> Path:
        return self.state_dir / "pending_reviews"

    @property
    def recorded_dir(self) -> Path:
        return self.pending_dir / "recorded"

    @property
    def escalations_path(self) -> Path:
        return self.state_dir / "escalations.json"

    @property
    def controller_state_path(self) -> Path:
        return self.state_dir / "controller" / "state.json"

    @property
    def notifications_log(self) -> Path:
        return self.state_dir / "logs" / "notifications.log"

    def make_audit_request_script(self) -> Path:
        """orchestrator/make_audit_request.py, preferring the derived root."""
        derived = self.audit_loop_root / "orchestrator" / "make_audit_request.py"
        if derived.exists():
            return derived
        configured = self._paths.get("audit_loop_root")
        if configured:
            alternative = Path(str(configured)) / "orchestrator" / "make_audit_request.py"
            if alternative.exists():
                return alternative
        return derived

    # -- secrets ----------------------------------------------------------
    def load_secrets(self) -> dict[str, str]:
        raw = read_text_or_none(self.secrets_env)
        if raw is None:
            raise ToolError(
                f"secrets.env missing — run install.sh first (expected at {self.secrets_env})"
            )
        secrets: dict[str, str] = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                secrets[key] = value
        return secrets

    def secrets_status(self) -> tuple[bool, list[str]]:
        """(file_exists, missing_or_empty_keys) — never returns secret values."""
        try:
            secrets = self.load_secrets()
        except ToolError:
            return False, list(SECRET_KEYS)
        return True, [key for key in SECRET_KEYS if not secrets.get(key)]

    # -- controller -------------------------------------------------------
    def controller_client(self) -> Any:
        """Build the controller ASGI app in-process on first use (lazy)."""
        if self._controller_client is not None:
            return self._controller_client
        self.require_config()
        secrets = self.load_secrets()
        missing = [key for key in SECRET_KEYS if not secrets.get(key)]
        if "CLAUDE_API_TOKEN" in missing:
            raise ToolError(
                f"secrets.env has no CLAUDE_API_TOKEN — run install.sh first ({self.secrets_env})"
            )
        controller_root = self.controller_root
        if not (controller_root / "app" / "main.py").exists():
            raise ToolError(f"controller_root does not look like the controller: {controller_root}")

        os.environ["SCIENCE_REPO_PATH"] = str(self.science_repo)
        os.environ["AUDIT_REPO_PATH"] = str(self.audit_repo)
        os.environ["PROJECT_CONFIG_PATH"] = str(self.projects_yaml)
        os.environ["CONTROLLER_STATE_PATH"] = str(self.controller_state_path)
        for key in SECRET_KEYS:
            if secrets.get(key):
                os.environ[key] = secrets[key]
        self.controller_state_path.parent.mkdir(parents=True, exist_ok=True)

        root_str = str(controller_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        try:
            from app.main import create_app  # type: ignore[import-not-found]
            from fastapi.testclient import TestClient
        except Exception as exc:
            raise ToolError(f"cannot import the controller app: {type(exc).__name__}: {exc}") from exc
        try:
            application = create_app()
        except Exception as exc:
            raise ToolError(f"controller create_app() failed: {type(exc).__name__}: {exc}") from exc
        client = TestClient(application, raise_server_exceptions=False)
        self._controller_client = (client, secrets)
        log("controller app built in-process")
        return self._controller_client


# --------------------------------------------------------------------------
# spool events
# --------------------------------------------------------------------------
def emit_event(ctx: Context, event: dict[str, Any]) -> Path:
    spool = ctx.spool_dir
    spool.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    name = f"evt-{stamp}-{os.getpid()}-{next(_EVENT_SEQ)}.json"
    target = spool / name
    tmp = spool / f".{name}.tmp"  # dot prefix: never matches the evt-*.json glob
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(event, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)
    log(f"emitted spool event {name}: {event.get('type')}")
    return target


# --------------------------------------------------------------------------
# git helpers (read-only against the science repo)
# --------------------------------------------------------------------------
def run_git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# --------------------------------------------------------------------------
# state readers
# --------------------------------------------------------------------------
def load_controller_cycles(ctx: Context) -> list[dict[str, Any]]:
    state = read_json_or_none(ctx.controller_state_path)
    if not isinstance(state, dict):
        return []
    cycles = state.get("cycles")
    if not isinstance(cycles, dict):
        return []
    items = [value for value in cycles.values() if isinstance(value, dict)]
    return sorted(items, key=lambda item: str(item.get("cycle_id", "")))


def list_pending_reviews(ctx: Context) -> list[dict[str, Any]]:
    directory = ctx.pending_dir
    if not directory.is_dir():
        return []
    reviews: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        if not path.is_file():
            continue
        payload = read_json_or_none(path)
        if not isinstance(payload, dict):
            log(f"skipping unreadable pending review {path.name}")
            continue
        payload["_path"] = str(path)
        payload.setdefault("cycle_id", path.stem)
        reviews.append(payload)
    reviews.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("cycle_id"))))
    return reviews


def load_escalations(ctx: Context) -> dict[str, Any]:
    payload = read_json_or_none(ctx.escalations_path)
    if not isinstance(payload, dict) or not isinstance(payload.get("escalations"), list):
        return {"escalations": []}
    return payload


# --------------------------------------------------------------------------
# tool: audit_status
# --------------------------------------------------------------------------
def tool_audit_status(ctx: Context, _args: dict[str, Any]) -> str:
    ctx.require_config()
    lines: list[str] = []
    lines.append(f"AUDIT LOOP STATUS  ({utc_now_iso()})")
    lines.append(f"config: {ctx.config_path}")
    project_label = ctx.project_id or "(no project_id)"
    lines.append(f"project: {project_label}   science_branch: {ctx.science_branch}")

    head_note = "unavailable"
    if (ctx.science_repo / ".git").exists():
        result = run_git(ctx.science_repo, "rev-parse", "HEAD")
        if result.returncode == 0:
            head = result.stdout.strip()
            branch = run_git(ctx.science_repo, "rev-parse", "--abbrev-ref", "HEAD")
            head_note = f"{head[:12]} (branch {branch.stdout.strip() or '?'})"
        else:
            head_note = f"git error: {result.stderr.strip()[:120]}"
    lines.append(f"science repo: {ctx.science_repo}  HEAD={head_note}")
    lines.append("")

    cycles = load_controller_cycles(ctx)
    if not cycles:
        lines.append("Cycles: none (controller state empty or not yet created)")
    else:
        recent = cycles[-8:]
        lines.append(f"Cycles: {len(cycles)} total, showing most recent {len(recent)}")
        lines.append("  cycle_id      commit        status                 decision            disposition")
        for cycle in recent:
            cycle_id = str(cycle.get("cycle_id", "?"))
            commit = str(cycle.get("science_commit") or "")[:12] or "-"
            status = str(cycle.get("status") or "-")
            decision = "-"
            if status == "FINAL":
                result = cycle.get("audit_result")
                if isinstance(result, dict):
                    decision = str(result.get("decision") or "-")
            disposition = str(cycle.get("disposition_status") or "-")
            lines.append(
                f"  {cycle_id:<13} {commit:<13} {status:<22} {decision:<19} {disposition}"
            )
    lines.append("")

    pending = list_pending_reviews(ctx)
    if pending:
        ids = ", ".join(str(item.get("cycle_id")) for item in pending)
        lines.append(f"Pending reviews: {len(pending)}  [{ids}]")
        lines.append("  -> call get_pending_review to read the oldest one.")
    else:
        lines.append("Pending reviews: 0")

    escalations = load_escalations(ctx)["escalations"]
    open_items = [
        item
        for item in escalations
        if isinstance(item, dict) and str(item.get("status", "OPEN")).upper() == "OPEN"
    ]
    acknowledged = [
        item
        for item in escalations
        if isinstance(item, dict) and str(item.get("status", "")).upper() == "ACKNOWLEDGED"
    ]
    lines.append(
        f"Escalations: {len(open_items)} OPEN, {len(acknowledged)} ACKNOWLEDGED "
        f"({len(escalations)} total)"
    )
    for item in open_items:
        cycle_ids = item.get("cycle_ids")
        cycle_text = ",".join(str(value) for value in cycle_ids) if isinstance(cycle_ids, list) else "-"
        lines.append(
            f"  OPEN {item.get('escalation_id', '?')}  finding={item.get('finding_id', '?')}"
            f"  cycles={cycle_text}  opened_at={item.get('opened_at', '?')}"
        )
    lines.append("")

    secrets_present, missing_keys = ctx.secrets_status()
    if not secrets_present:
        secrets_note = f"MISSING ({ctx.secrets_env}) — run install.sh first"
    elif missing_keys:
        secrets_note = f"present but incomplete; unset keys: {', '.join(missing_keys)}"
    else:
        secrets_note = f"present, all {len(SECRET_KEYS)} keys set"
    lines.append("Initialization:")
    lines.append(f"  secrets.env:      {secrets_note}")
    lines.append(
        f"  state dir:        {'present' if ctx.state_dir.is_dir() else 'MISSING'}  ({ctx.state_dir})"
    )
    controller_state = read_json_or_none(ctx.controller_state_path)
    lines.append(
        "  controller state: "
        + (
            f"present ({len(cycles)} cycles)"
            if isinstance(controller_state, dict)
            else "not created yet (treated as empty)"
        )
    )
    queued = len(list(ctx.spool_dir.glob("evt-*.json"))) if ctx.spool_dir.is_dir() else 0
    lines.append(
        f"  spool:            {'present' if ctx.spool_dir.is_dir() else 'MISSING'}, "
        f"{queued} queued event(s)"
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# tool: get_pending_review
# --------------------------------------------------------------------------
HOW_TO_RESPOND = """===== HOW TO RESPOND / 如何回覆 =====
用 submit_disposition 提交一个 disposition 对象，规则如下：

1. findings 数组必须为上面 finding_ids 中的每一个 finding_id 各给出恰好一个
   disposition，不多不少，不重复。
2. disposition 只能取以下六个值之一：
     ACCEPT_AND_FIX          接受该 finding，并已提交修复 commit
     ACCEPT_AND_STOP         接受该 finding，停止相关工作，不提交修复
     DISAGREE_WITH_EVIDENCE  不同意，必须在 evidence 中给出可核验的证据
     NEED_PI_DECISION        需要 PI 裁决（配合 notify_pi 使用）
     DEFER_WITH_CAVEAT       暂缓处理，并在文档中带上明确的 caveat
     PASS_NO_ACTION          无需动作
3. fix_commit 仅在且必须在 disposition == ACCEPT_AND_FIX 时出现：它必须是一个
   全新 science commit 的完整 40 位 sha，且该 commit 必须以被审计的
   science_commit 为祖先（即先在 scienceRepo 提交修复，再引用其 sha）。
   任何其它 disposition 携带 fix_commit 都会被 controller 拒绝。
4. report_sha256 必须逐字回抄上面的 report_sha256，并且
   report_sha256_confirmed 必须为 true —— 这代表你确实读过这份报告。
5. cycle_id 与 audit_report_id 必须与上面完全一致。
6. 绝不能声称某个 finding 已经 closed。关闭只能由下一轮 re-audit 验证后由
   controller 完成；disposition 里不允许出现 closed 字段。

提交格式（submit_disposition 的 disposition 参数，原样转发给 controller）：

{
  "cycle_id": "<cycle_id>",
  "audit_report_id": "<audit_report_id>",
  "report_sha256_confirmed": true,
  "report_sha256": "<64-hex report_sha256>",
  "findings": [
    {"finding_id": "F-XXX", "disposition": "PASS_NO_ACTION", "evidence": "..."},
    {"finding_id": "F-YYY", "disposition": "ACCEPT_AND_FIX", "fix_commit": "<40-hex sha>"}
  ]
}

如果 controller 返回 valid:false，它会给出具体 errors 列表；请据此修正后重新提交。"""


def tool_get_pending_review(ctx: Context, args: dict[str, Any]) -> str:
    ctx.require_config()
    requested = args.get("cycle_id")
    if requested is not None and not isinstance(requested, str):
        raise ToolError("cycle_id must be a string like CYCLE-000007")

    pending = list_pending_reviews(ctx)
    if not pending:
        return (
            "No pending audit review. / 当前没有待处理的审计报告。\n"
            f"pending_reviews dir: {ctx.pending_dir}\n"
            "The orchestrator writes a pending review only after an audit cycle reaches FINAL. "
            "Use request_audit to start a new cycle, or audit_status for the overall picture."
        )

    if requested:
        matches = [item for item in pending if str(item.get("cycle_id")) == requested]
        if not matches:
            available = ", ".join(str(item.get("cycle_id")) for item in pending)
            raise ToolError(
                f"no pending review for {requested}. Pending cycle_ids: {available}"
            )
        review = matches[0]
    else:
        review = pending[0]

    finding_ids = review.get("finding_ids")
    finding_text = (
        ", ".join(str(value) for value in finding_ids)
        if isinstance(finding_ids, list) and finding_ids
        else "(none listed in the pending review file)"
    )

    lines: list[str] = []
    lines.append("===== PENDING AUDIT REVIEW / 待处理审计报告 =====")
    lines.append(f"cycle_id:        {review.get('cycle_id', '?')}")
    lines.append(f"audit_report_id: {review.get('audit_report_id', '?')}")
    lines.append(f"report_sha256:   {review.get('report_sha256', '?')}")
    lines.append(f"science_commit:  {review.get('science_commit', '?')}")
    lines.append(f"decision:        {review.get('decision', '?')}")
    lines.append(f"finding_ids:     {finding_text}")
    lines.append(f"created_at:      {review.get('created_at', '?')}")
    lines.append(f"report_path:     {review.get('report_path', '?')}")
    lines.append(f"result_path:     {review.get('result_path', '?')}")
    queue_ids = ", ".join(str(item.get("cycle_id")) for item in pending)
    lines.append(f"queue:           {len(pending)} pending (oldest first: {queue_ids})")
    lines.append("")

    report_path = review.get("report_path")
    report_text = read_text_or_none(Path(str(report_path))) if report_path else None
    lines.append("----- BEGIN audit_report.md -----")
    if report_text is None:
        lines.append(
            f"[audit_report.md unreadable or missing at {report_path!r} — "
            "do NOT submit a disposition based on a report you could not read]"
        )
    else:
        lines.append(truncate_for_embed(report_text, "audit_report.md").rstrip("\n"))
    lines.append("----- END audit_report.md -----")
    lines.append("")

    result_path = review.get("result_path")
    result_text = read_text_or_none(Path(str(result_path))) if result_path else None
    lines.append("----- BEGIN audit_result.json -----")
    if result_text is None:
        lines.append(f"[audit_result.json unreadable or missing at {result_path!r}]")
    else:
        lines.append(truncate_for_embed(result_text, "audit_result.json").rstrip("\n"))
    lines.append("----- END audit_result.json -----")
    lines.append("")
    lines.append(HOW_TO_RESPOND)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# tool: submit_disposition
# --------------------------------------------------------------------------
def tool_submit_disposition(ctx: Context, args: dict[str, Any]) -> str:
    ctx.require_config()
    disposition = args.get("disposition")
    if not isinstance(disposition, dict):
        raise ToolError(
            "argument 'disposition' must be a JSON object "
            "(cycle_id, audit_report_id, report_sha256_confirmed, report_sha256, findings)"
        )

    client, secrets = ctx.controller_client()
    token = secrets.get("CLAUDE_API_TOKEN", "")
    try:
        # The disposition is forwarded verbatim; this server never edits it.
        response = client.post(
            "/claude/dispositions",
            json=disposition,
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception as exc:
        raise ToolError(f"controller POST failed: {type(exc).__name__}: {exc}") from exc

    body_text = response.text
    try:
        payload = response.json()
    except Exception:
        payload = None

    if response.status_code != 200 or not isinstance(payload, dict):
        raise ToolError(
            f"controller returned HTTP {response.status_code} for /claude/dispositions:\n"
            f"{body_text[:4000]}"
        )

    errors = payload.get("errors")
    error_list = [str(item) for item in errors] if isinstance(errors, list) else []

    if payload.get("valid") is not True:
        detail = "\n".join(f"  - {item}" for item in error_list) or "  - (no errors returned)"
        raise ToolError(
            "controller REJECTED the disposition (valid=false). "
            "Errors verbatim from the controller:\n"
            f"{detail}\n"
            "Correct the disposition and call submit_disposition again. "
            "Nothing was recorded and no state was moved."
        )

    cycle_id = str(disposition.get("cycle_id") or "")
    lines = ["Disposition ACCEPTED by the controller (valid=true).", f"cycle_id: {cycle_id or '?'}"]
    if error_list:
        lines.append("controller warnings/errors list (non-blocking): " + "; ".join(error_list))
    else:
        lines.append("controller errors: [] (none)")

    # Move the pending review out of the queue.
    if CYCLE_ID_RE.match(cycle_id):
        source = ctx.pending_dir / f"{cycle_id}.json"
        if source.exists():
            try:
                move_atomic(source, ctx.recorded_dir / source.name)
                lines.append(f"pending review moved to: {ctx.recorded_dir / source.name}")
            except OSError as exc:
                lines.append(f"WARNING: could not move pending review {source}: {exc}")
        else:
            lines.append(f"note: no pending review file at {source} (already moved?)")
    else:
        lines.append(f"note: cycle_id {cycle_id!r} is not CYCLE-nnnnnn; pending queue untouched")

    # Emit the spool event so the orchestrator can advance the cycle.
    if CYCLE_ID_RE.match(cycle_id):
        try:
            path = emit_event(
                ctx, {"type": "disposition_recorded", "cycle_id": cycle_id, "source": "mcp"}
            )
            lines.append(f"spool event emitted: {path.name} (disposition_recorded)")
        except OSError as exc:
            lines.append(f"WARNING: could not emit disposition_recorded event: {exc}")
    lines.append(
        "The orchestrator will pick the event up; findings stay OPEN until a re-audit "
        "verifies the fixes."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# tool: request_audit
# --------------------------------------------------------------------------
def tool_request_audit(ctx: Context, args: dict[str, Any]) -> str:
    ctx.require_config()
    reason = args.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ToolError("argument 'reason' is required and must be a non-empty string")
    regenerate = args.get("regenerate_manifest", True)
    if not isinstance(regenerate, bool):
        raise ToolError("argument 'regenerate_manifest' must be a boolean")

    repo = ctx.science_repo
    if not (repo / ".git").exists():
        raise ToolError(f"science repo is not a git repository: {repo}")

    lines: list[str] = []
    if regenerate:
        script = ctx.make_audit_request_script()
        if not script.exists():
            raise ToolError(
                f"make_audit_request.py not found at {script} — either run install.sh / the "
                "orchestrator setup, or call request_audit with regenerate_manifest=false"
            )
        command = [
            str(ctx.venv_python),
            str(script),
            "--repo",
            str(repo),
            "--reason",
            reason,
        ]
        log(f"running: {' '.join(command)}")
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"make_audit_request.py timed out after {exc.timeout}s") from exc
        except OSError as exc:
            raise ToolError(f"cannot run make_audit_request.py: {exc}") from exc
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip() or "(empty stderr)"
            raise ToolError(
                f"make_audit_request.py exited {completed.returncode}:\n{stderr[:4000]}"
            )
        stdout_lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
        if not stdout_lines:
            raise ToolError("make_audit_request.py produced no stdout; expected the new HEAD sha")
        sha = stdout_lines[-1]
        lines.append(f"manifest regenerated via {script.name} (exit 0)")
        if completed.stderr and completed.stderr.strip():
            lines.append(f"script stderr (informational): {completed.stderr.strip()[:800]}")
    else:
        result = run_git(repo, "rev-parse", "HEAD")
        if result.returncode != 0:
            raise ToolError(f"git rev-parse HEAD failed: {result.stderr.strip()}")
        sha = result.stdout.strip()
        lines.append("manifest NOT regenerated (regenerate_manifest=false); using current HEAD")

    if not SHA40_RE.match(sha):
        raise ToolError(f"expected a full 40-character commit sha, got: {sha!r}")
    sha = sha.lower()

    branch = ctx.science_branch
    ref = f"refs/heads/{branch}"
    verify = run_git(repo, "rev-parse", "--verify", "--quiet", ref)
    if verify.returncode != 0:
        raise ToolError(f"branch {branch} does not exist in {repo} (missing {ref})")
    branch_head = verify.stdout.strip()
    ancestor = run_git(repo, "merge-base", "--is-ancestor", sha, ref)
    if ancestor.returncode != 0:
        raise ToolError(
            f"commit {sha} is not on branch {branch} (not an ancestor of {ref}, "
            f"whose head is {branch_head}). Only {branch} commits may be audited; "
            "push/merge the work onto that branch first."
        )
    on_branch = "branch head" if branch_head == sha else f"ancestor of {branch} head {branch_head[:12]}"

    event = {
        "type": "science_commit",
        "sha": sha,
        "source": "mcp",
        "reason": reason,
    }
    path = emit_event(ctx, event)

    lines.append(f"science_commit: {sha}")
    lines.append(f"branch check:   OK ({on_branch})")
    lines.append(f"spool event:    {path.name}")
    lines.append(f"reason:         {reason}")
    lines.append("audit queued; the orchestrator will pick it up.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# tool: acknowledge_escalation
# --------------------------------------------------------------------------
def tool_acknowledge_escalation(ctx: Context, args: dict[str, Any]) -> str:
    ctx.require_config()
    escalation_id = args.get("escalation_id")
    note = args.get("resolution_note")
    if not isinstance(escalation_id, str) or not escalation_id.strip():
        raise ToolError("argument 'escalation_id' is required and must be a non-empty string")
    if not isinstance(note, str) or not note.strip():
        raise ToolError("argument 'resolution_note' is required and must be a non-empty string")
    escalation_id = escalation_id.strip()

    lock_path = ctx.escalations_path.with_name(ctx.escalations_path.name + ".lock")
    with file_lock(lock_path):
        payload = load_escalations(ctx)
        items = payload["escalations"]
        target = None
        for item in items:
            if isinstance(item, dict) and str(item.get("escalation_id")) == escalation_id:
                target = item
                break
        if target is None:
            known = [
                str(item.get("escalation_id"))
                for item in items
                if isinstance(item, dict) and item.get("escalation_id")
            ]
            raise ToolError(
                f"unknown escalation_id: {escalation_id}. "
                + (f"Known ids: {', '.join(known)}" if known else "No escalations are recorded.")
            )
        status = str(target.get("status", "OPEN")).upper()
        if status == "ACKNOWLEDGED":
            raise ToolError(
                f"escalation {escalation_id} is already ACKNOWLEDGED "
                f"(at {target.get('acknowledged_at', 'unknown time')}): "
                f"{target.get('resolution_note', '')!r}"
            )
        stamp = utc_now_iso()
        target["status"] = "ACKNOWLEDGED"
        target["resolution_note"] = note
        target["acknowledged_at"] = stamp
        target["acknowledged_by"] = "mcp"
        atomic_write_json(ctx.escalations_path, payload)

    remaining = [
        item
        for item in load_escalations(ctx)["escalations"]
        if isinstance(item, dict) and str(item.get("status", "OPEN")).upper() == "OPEN"
    ]
    return "\n".join(
        [
            f"Escalation {escalation_id} -> ACKNOWLEDGED at {stamp}.",
            f"finding_id: {target.get('finding_id', '?')}",
            f"resolution_note: {note}",
            f"remaining OPEN escalations: {len(remaining)}",
            f"file: {ctx.escalations_path}",
        ]
    )


# --------------------------------------------------------------------------
# tool: notify_pi
# --------------------------------------------------------------------------
def applescript_quote(text: str) -> str:
    """Escape text for an AppleScript double-quoted string literal."""
    out: list[str] = []
    for char in text:
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 32:
            out.append(" ")
        else:
            out.append(char)
    return '"' + "".join(out) + '"'


def tool_notify_pi(ctx: Context, args: dict[str, Any]) -> str:
    ctx.require_config()
    subject = args.get("subject")
    body = args.get("body")
    if not isinstance(subject, str) or not subject.strip():
        raise ToolError("argument 'subject' is required and must be a non-empty string")
    if not isinstance(body, str) or not body.strip():
        raise ToolError("argument 'body' is required and must be a non-empty string")

    subject_short = subject.strip()[:200]
    body_short = body.strip()[:1000]

    script = (
        f"display notification {applescript_quote(body_short)} "
        f'with title "Audit Loop" '
        f"subtitle {applescript_quote(subject_short)}"
    )

    notify_status = "sent"
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            notify_status = (
                "osascript failed (non-fatal): "
                + ((completed.stderr or "").strip()[:300] or f"exit {completed.returncode}")
            )
            log(notify_status)
    except (OSError, subprocess.SubprocessError) as exc:
        notify_status = f"osascript unavailable (non-fatal): {type(exc).__name__}: {exc}"
        log(notify_status)

    stamp = utc_now_iso()
    flat_subject = " ".join(subject_short.split())
    flat_body = " ".join(body_short.split())
    line = f"{stamp}\tsource=mcp\tstatus={notify_status.split(' ')[0]}\tsubject={flat_subject}\tbody={flat_body}"
    try:
        append_log_line(ctx.notifications_log, line)
        log_note = f"appended to {ctx.notifications_log}"
    except OSError as exc:
        raise ToolError(f"could not append to {ctx.notifications_log}: {exc}") from exc

    return "\n".join(
        [
            "PI notified (人为介入通道).",
            f"subject: {flat_subject}",
            f"macOS notification: {notify_status}",
            f"log: {log_note}",
            f"log line: {line}",
        ]
    )


# --------------------------------------------------------------------------
# tool registry
# --------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "audit_status",
        "description": (
            "一次调用拿到审计闭环全貌 / One-call situational overview of the local audit loop: "
            "recent controller cycles (cycle_id, science_commit prefix, status, FINAL decision, "
            "disposition_status), pending review count and ids, OPEN escalations, and whether "
            "secrets.env plus the state directory are initialized. Call this first at the end of a "
            "session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "handler": tool_audit_status,
    },
    {
        "name": "get_pending_review",
        "description": (
            "领取一份待处理的 FINAL 审计报告 / Fetch a pending audit review: the header "
            "(cycle_id, audit_report_id, report_sha256, science_commit, decision, finding_ids), the "
            "FULL text of audit_report.md, the full audit_result.json, and the rules for replying. "
            "Defaults to the oldest pending review; pass cycle_id to select a specific one. Always "
            "read this before calling submit_disposition — report_sha256 must be echoed back."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cycle_id": {
                    "type": "string",
                    "pattern": "^CYCLE-[0-9]{6}$",
                    "description": "Optional. Specific cycle to fetch, e.g. CYCLE-000007. "
                    "Omit for the oldest pending review.",
                }
            },
            "additionalProperties": False,
        },
        "handler": tool_get_pending_review,
    },
    {
        "name": "submit_disposition",
        "description": (
            "提交对某个 audit cycle 全部 findings 的处置意见 / Submit the disposition for every "
            "finding of one FINAL audit cycle. The object is forwarded VERBATIM to the controller at "
            "POST /claude/dispositions; the controller is the only validator. Requirements: exactly "
            "one entry per finding_id of the cycle; disposition from {ACCEPT_AND_FIX, "
            "ACCEPT_AND_STOP, DISAGREE_WITH_EVIDENCE, NEED_PI_DECISION, DEFER_WITH_CAVEAT, "
            "PASS_NO_ACTION}; fix_commit required if and only if ACCEPT_AND_FIX, and it must be a "
            "full 40-hex sha of a NEW science commit descending from the audited commit; "
            "report_sha256 echoed exactly with report_sha256_confirmed=true; never claim a finding "
            "is closed. If the controller replies valid:false, its error list comes back verbatim — "
            "fix and resubmit."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["disposition"],
            "properties": {
                "disposition": {
                    "type": "object",
                    "description": "The claude_disposition object, passed through unchanged.",
                    "required": [
                        "cycle_id",
                        "audit_report_id",
                        "report_sha256_confirmed",
                        "report_sha256",
                        "findings",
                    ],
                    "properties": {
                        "cycle_id": {"type": "string", "pattern": "^CYCLE-[0-9]{6}$"},
                        "audit_report_id": {"type": "string", "minLength": 1},
                        "report_sha256_confirmed": {
                            "type": "boolean",
                            "description": "Must be true; asserts you read the report.",
                        },
                        "report_sha256": {
                            "type": "string",
                            "pattern": "^[a-fA-F0-9]{64}$",
                            "description": "Echo the report_sha256 from get_pending_review exactly.",
                        },
                        "findings": {
                            "type": "array",
                            "minItems": 1,
                            "description": "Exactly one entry per finding_id of the cycle.",
                            "items": {
                                "type": "object",
                                "required": ["finding_id", "disposition"],
                                "properties": {
                                    "finding_id": {
                                        "type": "string",
                                        "pattern": "^F-[A-Za-z0-9._-]+$",
                                    },
                                    "disposition": {
                                        "type": "string",
                                        "enum": list(DISPOSITION_VALUES),
                                    },
                                    "fix_commit": {
                                        "type": "string",
                                        "pattern": "^[a-fA-F0-9]{40}$",
                                        "description": "Only with ACCEPT_AND_FIX; a new science "
                                        "commit descending from the audited commit.",
                                    },
                                    "evidence": {"type": "string", "minLength": 1},
                                },
                            },
                        },
                    },
                }
            },
            "additionalProperties": False,
        },
        "handler": tool_submit_disposition,
    },
    {
        "name": "request_audit",
        "description": (
            "为 science repo 当前 HEAD 触发一次新的审计 cycle / Queue a new audit cycle for the "
            "science repo HEAD. With regenerate_manifest=true (default) it runs "
            "orchestrator/make_audit_request.py to refresh the evidence manifest and commit it, then "
            "uses the resulting HEAD sha; with false it audits the current HEAD as-is. The sha must "
            "be on the science branch. On success a science_commit event is spooled and the "
            "orchestrator takes over."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["reason"],
            "properties": {
                "reason": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Why this audit is requested; recorded in the spool event and "
                    "passed to make_audit_request.py.",
                },
                "regenerate_manifest": {
                    "type": "boolean",
                    "default": True,
                    "description": "Regenerate the evidence manifest before auditing (default true).",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_request_audit,
    },
    {
        "name": "acknowledge_escalation",
        "description": (
            "确认一条 escalation 并记录处理说明 / Mark an OPEN escalation as ACKNOWLEDGED with a "
            "resolution note and timestamp in state/escalations.json. Fails if the escalation_id is "
            "unknown or already acknowledged. Acknowledging records that a human decision was taken "
            "— it does not close the underlying finding."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["escalation_id", "resolution_note"],
            "properties": {
                "escalation_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Escalation id as shown by audit_status.",
                },
                "resolution_note": {
                    "type": "string",
                    "minLength": 1,
                    "description": "What was decided and why; stored verbatim.",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_acknowledge_escalation,
    },
    {
        "name": "notify_pi",
        "description": (
            "人为介入通道：向 PI 推送 macOS 通知并记录 / Human-in-the-loop channel: send a macOS "
            "notification titled \"Audit Loop\" to the PI and append the message to "
            "state/logs/notifications.log. Use for NEED_PI_DECISION findings, blocked audits, or "
            "anything requiring a human call. The log line is always written even if the desktop "
            "notification cannot be displayed."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["subject", "body"],
            "properties": {
                "subject": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Short subject (notification subtitle, <=200 chars kept).",
                },
                "body": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Message body (<=1000 chars kept).",
                },
            },
            "additionalProperties": False,
        },
        "handler": tool_notify_pi,
    },
]

TOOL_HANDLERS: dict[str, Callable[[Context, dict[str, Any]], str]] = {
    tool["name"]: tool["handler"] for tool in TOOLS
}


def public_tool_list() -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
        }
        for tool in TOOLS
    ]


# --------------------------------------------------------------------------
# JSON-RPC plumbing
# --------------------------------------------------------------------------
def send(message: dict[str, Any]) -> None:
    PROTOCOL_OUT.write(json.dumps(message, ensure_ascii=False) + "\n")
    PROTOCOL_OUT.flush()


def send_result(request_id: Any, result: dict[str, Any]) -> None:
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def send_error(request_id: Any, code: int, message: str, data: Any = None) -> None:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    send({"jsonrpc": "2.0", "id": request_id, "error": error})


def text_content(text: str, is_error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle_initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = requested if isinstance(requested, str) and requested else DEFAULT_PROTOCOL_VERSION
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def handle_tools_call(ctx: Context, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(name, str) or name not in TOOL_HANDLERS:
        known = ", ".join(sorted(TOOL_HANDLERS))
        return text_content(f"unknown tool: {name!r}. Available tools: {known}", is_error=True)
    if not isinstance(arguments, dict):
        return text_content(
            f"tool {name}: 'arguments' must be a JSON object, got {type(arguments).__name__}",
            is_error=True,
        )
    handler = TOOL_HANDLERS[name]
    log(f"tools/call {name} args={sorted(arguments)}")
    try:
        return text_content(handler(ctx, arguments), is_error=False)
    except ToolError as exc:
        log(f"tool {name} failed: {exc}")
        return text_content(f"{name} failed: {exc}", is_error=True)
    except Exception as exc:  # never let a tool bug become a protocol error
        log(f"tool {name} raised {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc(file=sys.stderr)
        return text_content(
            f"{name} failed with an internal error: {type(exc).__name__}: {exc}", is_error=True
        )


def handle_message(ctx: Context, message: dict[str, Any]) -> None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}

    is_notification = "id" not in message

    if not isinstance(method, str):
        if not is_notification:
            send_error(request_id, -32600, "invalid request: 'method' must be a string")
        return

    if is_notification:
        # notifications/initialized and every other notification: no response.
        log(f"notification ignored: {method}")
        return

    if method == "initialize":
        result = handle_initialize(params)
        send_result(request_id, result)
        log(f"initialize -> protocolVersion {result['protocolVersion']}")
        return
    if method == "ping":
        send_result(request_id, {})
        return
    if method == "tools/list":
        send_result(request_id, {"tools": public_tool_list()})
        return
    if method == "tools/call":
        send_result(request_id, handle_tools_call(ctx, params))
        return

    send_error(request_id, -32601, f"method not found: {method}")


def serve(ctx: Context) -> int:
    log(f"started (pid {os.getpid()}), config={ctx.config_path}")
    if ctx.config_error:
        log(f"WARNING: {ctx.config_error} — initialize/tools/list still work; tools will error")
    stdin = sys.stdin
    while True:
        try:
            line = stdin.readline()
        except KeyboardInterrupt:
            log("interrupted; exiting")
            return 0
        except Exception as exc:  # pragma: no cover
            log(f"stdin read failed: {type(exc).__name__}: {exc}")
            return 1
        if line == "":
            log("stdin closed; exiting")
            return 0
        stripped = line.strip()
        if not stripped:
            continue
        try:
            message = json.loads(stripped)
        except (json.JSONDecodeError, ValueError) as exc:
            log(f"parse error: {exc}")
            send_error(None, -32700, f"parse error: {exc}")
            continue
        if isinstance(message, list):
            # JSON-RPC batches are not part of the current MCP spec.
            send_error(None, -32600, "batch requests are not supported")
            continue
        if not isinstance(message, dict):
            send_error(None, -32600, "invalid request: expected a JSON object")
            continue
        try:
            handle_message(ctx, message)
        except Exception as exc:  # the loop must survive anything
            log(f"handler crashed: {type(exc).__name__}: {exc}")
            import traceback

            traceback.print_exc(file=sys.stderr)
            if "id" in message:
                send_error(
                    message.get("id"),
                    -32603,
                    f"internal error: {type(exc).__name__}: {exc}",
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_mcp_server.py",
        description="stdio MCP server for the local scientific audit loop",
    )
    parser.add_argument(
        "--config",
        default=os.getenv("AUDIT_LOOP_CONFIG", DEFAULT_CONFIG_PATH),
        help="path to orchestrator/config.yaml (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    ctx = Context(args.config)
    return serve(ctx)


if __name__ == "__main__":
    sys.exit(main())
