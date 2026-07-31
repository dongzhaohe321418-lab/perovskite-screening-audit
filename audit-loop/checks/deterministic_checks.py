#!/usr/bin/env python3
"""Tier-0 machine-truth verifier for a science repository.

CONTRACT
--------
This script is the deterministic, LLM-free floor of the audit pipeline. It reads a
science repository at one fixed commit and emits a ``check_report/v1`` JSON document.
Its output is authoritative: neither the auditing model nor the audited model may
dispute a result here. The only legitimate response to a FAIL is to change the
repository (or to change these checks by a reviewed edit to this file and its config,
which changes ``checks_sha256`` and is therefore visible).

NO SCIENTIFIC JUDGMENT
----------------------
Every check in this file is a PROCESS invariant: file existence, byte-level hash
identity, JSON well-formedness, history shape, link resolvability, banner presence,
config-declared pattern contradictions, config-declared agreement between a number
published in prose and the machine-readable artifact that same document cites, and the
exit status of the repository's own declared test entrypoint. Nothing here evaluates
whether a physical result is correct, well-chosen, converged-enough, or believable. Where domain vocabulary is needed (status
words, banner text, manifest key names), it lives in ``checks.yaml`` as data. Adding
domain knowledge to this file is a defect.

DETERMINISM
-----------
Given the same commit pair, the same config bytes and the same script bytes, the
``results`` array is byte-identical across runs and machines: every list is sorted,
and no timestamp or path of the audit host appears inside ``results``.

``checks_sha256`` is sha256 over ``b"checks_script:" + script_bytes + b"\\nconfig:" +
config_bytes`` -- it pins the exact verifier that produced a report, so a report can
never be re-attributed to a different version of these checks.

Exit status: 0 whenever the report was written (whatever the check outcomes), 2 only on
internal error.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator, Sequence

import yaml

SCHEMA = "check_report/v1"
MAX_VIOLATIONS = 50
HEX40 = re.compile(r"\A[0-9a-f]{40}\Z")
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


class InternalError(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    i, n, out = 0, len(pattern), []
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == n:
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[":
            j = pattern.find("]", i + 1)
            if j < 0:
                out.append(re.escape("["))
                i += 1
            else:
                body = pattern[i + 1 : j]
                body = "^" + body[1:] if body.startswith("!") else body
                out.append("[" + body + "]")
                i = j + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(r"\A" + "".join(out) + r"\Z")


class GlobSet:
    def __init__(self, patterns: Sequence[str]) -> None:
        self.patterns = list(patterns)
        self._rx = [glob_to_regex(p) for p in self.patterns]

    def __bool__(self) -> bool:
        return bool(self._rx)

    def matches(self, path: str) -> bool:
        return any(r.match(path) for r in self._rx)

    def select(self, paths: Iterable[str]) -> list[str]:
        return sorted(p for p in paths if self.matches(p))


def norm_repo_path(path: str) -> str | None:
    """Normalise a repo-relative path; None if it escapes the repo root."""
    cleaned = posix_normpath(path.replace("\\", "/"))
    if cleaned is None or cleaned in {"", "."}:
        return None
    return cleaned


def posix_normpath(path: str) -> str | None:
    parts: list[str] = []
    for seg in path.split("/"):
        if seg in {"", "."}:
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


@dataclass
class Blob:
    sha: str
    size: int


@dataclass
class Ctx:
    worktree: str
    git_dir: str
    audited_commit: str
    base_commit: str | None
    config: dict[str, Any]
    config_path: str
    _blobs: dict[str, Blob] | None = field(default=None, repr=False)
    _content: dict[str, bytes | None] = field(default_factory=dict, repr=False)
    _dirs: frozenset[str] | None = field(default=None, repr=False)

    # ---- git plumbing (bytes-first; text mode is never used for hashed content) ----

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        cp = subprocess.run(
            ["git", "--git-dir", self.git_dir, *args],
            capture_output=True,
            text=False,
        )
        if check and cp.returncode != 0:
            raise InternalError(
                f"git {' '.join(args[:3])} failed rc={cp.returncode}: "
                f"{cp.stderr.decode('utf-8', 'replace')[:400]}"
            )
        return cp

    def git_text(self, *args: str, check: bool = True) -> str:
        return self.git(*args, check=check).stdout.decode("utf-8", "surrogateescape")

    @property
    def blobs(self) -> dict[str, Blob]:
        if self._blobs is None:
            raw = self.git("ls-tree", "-r", "-l", "-z", self.audited_commit).stdout
            table: dict[str, Blob] = {}
            for record in raw.split(b"\x00"):
                if not record:
                    continue
                meta, _, path = record.partition(b"\t")
                fields = meta.split()
                if len(fields) < 4 or fields[1] != b"blob":
                    continue
                size = fields[3]
                table[path.decode("utf-8", "surrogateescape")] = Blob(
                    sha=fields[2].decode("ascii"),
                    size=int(size) if size.isdigit() else -1,
                )
            self._blobs = table
        return self._blobs

    @property
    def tracked(self) -> list[str]:
        return sorted(self.blobs)

    @property
    def tracked_dirs(self) -> frozenset[str]:
        if self._dirs is None:
            dirs: set[str] = set()
            for path in self.blobs:
                parts = path.split("/")[:-1]
                for i in range(len(parts)):
                    dirs.add("/".join(parts[: i + 1]))
            self._dirs = frozenset(dirs)
        return self._dirs

    def exists(self, path: str) -> bool:
        return path in self.blobs

    def dir_exists(self, path: str) -> bool:
        return path.rstrip("/") in self.tracked_dirs

    def git_show_bytes(self, path: str) -> bytes | None:
        """Raw bytes of ``path`` at the audited commit, or None if untracked.

        Raw bytes only: no text mode, no newline translation, no decoding. Hash
        comparisons in C-HASH-001 depend on this.
        """
        if path in self._content:
            return self._content[path]
        blob = self.blobs.get(path)
        if blob is None:
            self._content[path] = None
            return None
        cp = self.git("cat-file", "blob", blob.sha, check=False)
        data = cp.stdout if cp.returncode == 0 else None
        self._content[path] = data
        return data

    def git_show_text(self, path: str) -> str | None:
        raw = self.git_show_bytes(path)
        return None if raw is None else raw.decode("utf-8", "replace")

    # ---- config access ----

    def cfg(self, key: str, default: Any = None) -> Any:
        value = self.config.get(key, default)
        return default if value is None and default is not None else value

    def globs(self, key: str) -> GlobSet:
        return GlobSet(self.config.get(key) or [])

    def files_matching(self, key: str) -> list[str]:
        return self.globs(key).select(self.blobs)

    # ---- reproduce-command helpers ----

    def gd(self) -> str:
        return shlex.quote(self.git_dir)

    def show_cmd(self, path: str) -> str:
        return f"git --git-dir={self.gd()} cat-file blob {self.audited_commit}:{shlex.quote(path)}"

    def exists_probe(self, candidates: Sequence[str], note: str = "") -> str:
        args = " ".join(shlex.quote(c) for c in candidates)
        return (
            f"for p in {args}; do git --git-dir={self.gd()} cat-file -e "
            f"{self.audited_commit}:\"$p\" 2>/dev/null "
            f"&& echo \"exists: $p\" || echo \"missing: $p\"; done"
            + (f"  # {note}" if note else "")
        )


# --------------------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------------------

CheckFn = Callable[[Ctx], dict[str, Any]]


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    title: str
    cls: str
    fn: CheckFn


REGISTRY: list[CheckSpec] = []


def check(check_id: str, title: str, cls: str) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        REGISTRY.append(CheckSpec(check_id=check_id, title=title, cls=cls, fn=fn))
        return fn

    return register


def result(
    status: str,
    detail: str,
    reproduce: str = "",
    violations: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "detail": detail,
        "reproduce": reproduce,
        "violations": list(violations or []),
    }


def violation(path: str, message: str, expected: Any = "", actual: Any = "") -> dict[str, Any]:
    return {
        "path": path,
        "message": message,
        "expected": "" if expected is None else str(expected),
        "actual": "" if actual is None else str(actual),
    }


# --------------------------------------------------------------------------------------
# manifest entry extraction (shared by C-HASH-001 / C-HASH-002)
# --------------------------------------------------------------------------------------


@dataclass
class ManifestEntry:
    manifest: str
    pointer: str
    raw_path: str
    hash_hex: str | None
    hash_key: str | None
    hash_digits: int
    declared_size: int | None
    ambiguous: bool = False


def canonical_json_bytes(raw: bytes) -> bytes | None:
    """Canonical JSON form: sorted keys, compact separators, no trailing newline.

    Returns None when the payload is not JSON, so the caller can report the entry
    as unresolved rather than assert a mismatch it cannot substantiate.
    """
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _is_hex_hash(value: Any, digits: int) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{%d}" % digits, value))


def _path_like(value: str, path_like_rx: re.Pattern[str]) -> bool:
    return bool(path_like_rx.match(value))


def extract_manifest_entries(
    doc: Any, manifest: str, cfg: dict[str, Any]
) -> tuple[list[ManifestEntry], int]:
    """Pair path-like fields with hash fields, purely by config-declared key names.

    Three shapes are recognised, all config-driven:
      A. sibling fields    {"local_source": p, "sha256": h, "size_bytes": n}
      B. path-keyed scalar {"input_sha256": {"<path>": "<64hex>"}}
      C. path-keyed object {"<path>": {"sha256": "<64hex>", "size_bytes": n}}

    A hash that cannot be paired with a path is counted (returned as the second value)
    but never reported: an unpaired hash is not resolvable, so no claim is made.
    """
    path_keys = set(cfg.get("manifest_path_keys") or [])
    hash_keys = list(cfg.get("manifest_hash_keys") or [])
    size_keys = list(cfg.get("manifest_size_keys") or [])
    trunc: dict[str, int] = dict(cfg.get("manifest_truncated_hash_keys") or {})
    hash_suffix = cfg.get("manifest_hash_key_suffix") or "_sha256"
    size_suffix = cfg.get("manifest_size_key_suffix") or "_size_bytes"
    stem_suffixes = list(cfg.get("manifest_path_key_stem_suffixes") or [])
    map_keys = set(cfg.get("manifest_path_keyed_map_keys") or [])
    autodetect = bool(cfg.get("manifest_path_keyed_map_autodetect"))
    path_like_rx = re.compile(cfg.get("manifest_path_like_regex") or r"\A[\w./+-]+\.[A-Za-z0-9]{1,10}\Z")

    entries: list[ManifestEntry] = []
    unpaired = 0

    def stems(key: str) -> list[str]:
        out = [key]
        for suffix in stem_suffixes:
            if key.endswith(suffix) and len(key) > len(suffix):
                out.append(key[: -len(suffix)])
        return out

    def is_map_value(value: Any) -> bool:
        if _is_hex_hash(value, 64):
            return True
        if isinstance(value, dict):
            return any(k in value for k in hash_keys) or any(k in value for k in trunc)
        return False

    def map_value_hash(value: Any) -> tuple[str | None, str | None, int, int | None]:
        if _is_hex_hash(value, 64):
            return value, None, 64, None
        if isinstance(value, dict):
            for k in hash_keys:
                if _is_hex_hash(value.get(k), 64):
                    return value[k], k, 64, _first_int(value, size_keys)
            for k, digits in sorted(trunc.items()):
                if _is_hex_hash(value.get(k), digits):
                    return value[k], k, digits, _first_int(value, size_keys)
        return None, None, 64, None

    def _first_int(node: dict[str, Any], keys: Sequence[str]) -> int | None:
        for k in keys:
            v = node.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                return v
        return None

    def handle_object_map(node: dict[str, Any], pointer: str) -> None:
        for key, value in node.items():
            hash_hex, hash_key, digits, size = map_value_hash(value)
            if hash_hex is None:
                continue
            entries.append(
                ManifestEntry(
                    manifest=manifest,
                    pointer=f"{pointer}/{key}",
                    raw_path=key,
                    hash_hex=hash_hex,
                    hash_key=hash_key,
                    hash_digits=digits,
                    declared_size=size,
                )
            )

    def walk(node: Any, pointer: str) -> None:
        nonlocal unpaired
        if isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{pointer}/{i}")
            return
        if not isinstance(node, dict):
            return

        keys_are_paths = bool(node) and all(
            isinstance(k, str) and _path_like(k, path_like_rx) for k in node
        )
        values_are_hashes = bool(node) and all(is_map_value(v) for v in node.values())
        if autodetect and keys_are_paths and values_are_hashes:
            handle_object_map(node, pointer)
            return

        present_paths = [k for k in node if k in path_keys and isinstance(node[k], str)]
        generic_hash_keys = [k for k in hash_keys if _is_hex_hash(node.get(k), 64)]
        generic_trunc_keys = [k for k in trunc if _is_hex_hash(node.get(k), trunc[k])]
        claimed_hash_keys: set[str] = set()

        for pkey in sorted(present_paths):
            hash_hex: str | None = None
            hash_key: str | None = None
            digits = 64
            for stem in stems(pkey):
                candidate = f"{stem}{hash_suffix}"
                if _is_hex_hash(node.get(candidate), 64):
                    hash_hex, hash_key = node[candidate], candidate
                    break
            if hash_hex is None and len(present_paths) == 1:
                if generic_hash_keys:
                    hash_key = generic_hash_keys[0]
                    hash_hex = node[hash_key]
                elif generic_trunc_keys:
                    hash_key = sorted(generic_trunc_keys)[0]
                    hash_hex, digits = node[hash_key], trunc[hash_key]
            if hash_key is not None:
                claimed_hash_keys.add(hash_key)

            size: int | None = None
            for stem in stems(pkey):
                candidate = f"{stem}{size_suffix}"
                if isinstance(node.get(candidate), int) and not isinstance(node.get(candidate), bool):
                    size = node[candidate]
                    break
            if size is None and len(present_paths) == 1:
                size = _first_int(node, size_keys)

            entries.append(
                ManifestEntry(
                    manifest=manifest,
                    pointer=f"{pointer}/{pkey}",
                    raw_path=node[pkey],
                    hash_hex=hash_hex,
                    hash_key=hash_key,
                    hash_digits=digits,
                    declared_size=size,
                    ambiguous=hash_hex is None and len(present_paths) > 1,
                )
            )

        for key, value in node.items():
            if key in map_keys and isinstance(value, dict):
                handle_object_map(value, f"{pointer}/{key}")
                continue
            if isinstance(value, (dict, list)):
                walk(value, f"{pointer}/{key}")
                continue
            if key in claimed_hash_keys:
                continue
            if _is_hex_hash(value, 64) or (key in trunc and _is_hex_hash(value, trunc[key])):
                unpaired += 1

    walk(doc, "")
    return entries, unpaired


def resolve_entry_path(entry: ManifestEntry, ctx: Ctx) -> tuple[str | None, list[str]]:
    """Resolve a manifest path against the audited tree; returns (hit, candidates).

    An empty candidate list means the value was not repo-path-shaped at all (a URL, an
    absolute path, a citation string) and no claim is made about it.
    """
    raw = entry.raw_path.strip()
    if not raw or raw.startswith(("http://", "https://", "ssh://", "/", "~")) or "{{" in raw:
        return None, []
    if any(ch in raw for ch in "*?\n\t"):
        return None, []
    shape = re.compile(ctx.cfg("manifest_path_like_regex", r"\A[\w./+-]+\.[A-Za-z0-9]{1,10}\Z"))
    if not shape.match(raw):
        return None, []
    manifest_dir = os.path.dirname(entry.manifest)
    candidates: list[str] = []
    for candidate in (f"{manifest_dir}/{raw}" if manifest_dir else raw, raw):
        norm = norm_repo_path(candidate)
        if norm and norm not in candidates:
            candidates.append(norm)
    for candidate in candidates:
        if ctx.exists(candidate):
            return candidate, candidates
    return None, candidates


def load_manifest_entries(ctx: Ctx) -> tuple[list[ManifestEntry], int, list[str], list[str]]:
    manifests = ctx.files_matching("manifest_globs")
    entries: list[ManifestEntry] = []
    unpaired = 0
    unparsable: list[str] = []
    for manifest in manifests:
        raw = ctx.git_show_bytes(manifest)
        if raw is None:
            continue
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            unparsable.append(manifest)
            continue
        found, unpaired_here = extract_manifest_entries(doc, manifest, ctx.config)
        entries.extend(found)
        unpaired += unpaired_here
    return entries, unpaired, manifests, unparsable


# --------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------


@check("C-HASH-001", "Verify every declared manifest sha256 against the real blob", "HARD")
def c_hash_001(ctx: Ctx) -> dict[str, Any]:
    entries, unpaired, manifests, unparsable = load_manifest_entries(ctx)
    if not manifests:
        return result(
            "SKIP",
            "No tracked JSON file matched manifest_globs, so no declared hash was verifiable.",
            reproduce=f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit}",
        )

    violations: list[dict[str, Any]] = []
    hashed = 0
    unresolved = 0
    first_bad: str | None = None
    canonical_json_hash_keys = set(ctx.config.get("canonical_json_hash_keys") or [])
    for entry in entries:
        if entry.hash_hex is None:
            continue
        resolved, _ = resolve_entry_path(entry, ctx)
        if resolved is None:
            unresolved += 1
            continue
        raw = ctx.git_show_bytes(resolved)
        if raw is None:
            unresolved += 1
            continue
        hashed += 1
        if entry.hash_key in canonical_json_hash_keys:
            # Some hashes commit to a document's canonical JSON serialisation rather
            # than to its stored bytes, so byte-hashing them compares the wrong
            # object and fails a manifest that is in fact correct.
            canonical = canonical_json_bytes(raw)
            if canonical is None:
                unresolved += 1
                continue
            actual_full = hashlib.sha256(canonical).hexdigest()
        else:
            actual_full = hashlib.sha256(raw).hexdigest()
        actual = actual_full[: entry.hash_digits]
        if actual != entry.hash_hex:
            first_bad = first_bad or resolved
            violations.append(
                violation(
                    resolved,
                    f"declared {entry.hash_key or 'sha256'} in {entry.manifest} "
                    f"(at {entry.pointer or '/'}) does not match the blob at the audited commit",
                    expected=entry.hash_hex,
                    actual=actual,
                )
            )
        blob = ctx.blobs[resolved]
        if entry.declared_size is not None and entry.declared_size != blob.size:
            first_bad = first_bad or resolved
            violations.append(
                violation(
                    resolved,
                    f"declared size_bytes in {entry.manifest} (at {entry.pointer or '/'}) "
                    f"does not match the blob size at the audited commit",
                    expected=f"{entry.declared_size} bytes",
                    actual=f"{blob.size} bytes",
                )
            )

    detail = (
        f"Hashed {hashed} manifest-declared blob reference(s) from {len(manifests)} manifest "
        f"file(s) with hashlib.sha256 over raw bytes; {len(violations)} disagreement(s); "
        f"{unresolved} hash-bearing entr(ies) had no resolvable path (see C-HASH-002); "
        f"{unpaired} hash value(s) were not pairable with a path field and were not judged."
    )
    if unparsable:
        detail += f" {len(unparsable)} manifest(s) did not parse (see C-JSON-001)."
    repro = (
        f"{ctx.show_cmd(first_bad)} | shasum -a 256"
        if first_bad
        else f"{ctx.show_cmd(manifests[0])} | python3 -m json.tool | head -40"
    )
    return result("FAIL" if violations else "PASS", detail, repro, violations)


@check("C-HASH-002", "Verify every manifest-referenced path exists at the audited commit", "HARD")
def c_hash_002(ctx: Ctx) -> dict[str, Any]:
    entries, _, manifests, _ = load_manifest_entries(ctx)
    if not manifests:
        return result(
            "SKIP",
            "No tracked JSON file matched manifest_globs, so no manifest path was checkable.",
            reproduce=f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit}",
        )

    violations: list[dict[str, Any]] = []
    checked = 0
    skipped = 0
    seen: set[tuple[str, str]] = set()
    first_bad: tuple[list[str], str] | None = None
    for entry in entries:
        resolved, candidates = resolve_entry_path(entry, ctx)
        if not candidates:
            skipped += 1
            continue
        checked += 1
        if resolved is not None:
            continue
        if any(ctx.dir_exists(c) for c in candidates):
            continue
        key = (entry.manifest, entry.raw_path)
        if key in seen:
            continue
        seen.add(key)
        first_bad = first_bad or (candidates, f"named by {entry.manifest} at {entry.pointer or '/'}")
        violations.append(
            violation(
                candidates[0],
                f"{entry.manifest} (at {entry.pointer or '/'}) names a path that does not exist "
                f"at the audited commit; tried {', '.join(candidates)}",
                expected="a tracked file at the audited commit",
                actual="no such path in the tree",
            )
        )

    detail = (
        f"Resolved {checked} manifest path reference(s) from {len(manifests)} manifest file(s) "
        f"against git ls-tree at the audited commit; {len(violations)} unresolvable; "
        f"{skipped} non-repo-path value(s) (URL/absolute/templated) were not judged."
    )
    repro = (
        ctx.exists_probe(*first_bad)
        if first_bad
        else f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit} | wc -l"
    )
    return result("FAIL" if violations else "PASS", detail, repro, violations)


def _dup_key_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    counts = collections.Counter(key for key, _ in pairs)
    duplicates = sorted(key for key, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate object key(s): {', '.join(duplicates)}")
    return dict(pairs)


@check("C-JSON-001", "Parse every tracked JSON and reject duplicate object keys", "HARD")
def c_json_001(ctx: Ctx) -> dict[str, Any]:
    targets = ctx.files_matching("json_scan_globs")
    violations: list[dict[str, Any]] = []
    first_bad: str | None = None
    for path in targets:
        raw = ctx.git_show_bytes(path)
        if raw is None:
            continue
        try:
            json.loads(raw.decode("utf-8"), object_pairs_hook=_dup_key_hook)
        except UnicodeDecodeError as exc:
            first_bad = first_bad or path
            violations.append(
                violation(path, "file is not valid UTF-8", "decodable UTF-8 JSON", str(exc)[:200])
            )
        except ValueError as exc:
            first_bad = first_bad or path
            violations.append(
                violation(
                    path,
                    "JSON did not parse under a strict duplicate-key detector",
                    "parses with no duplicate object keys",
                    str(exc)[:200],
                )
            )
    detail = (
        f"Parsed {len(targets)} tracked JSON file(s) at the audited commit with a strict "
        f"object_pairs_hook duplicate-key detector; {len(violations)} rejected."
    )
    repro = (
        f"{ctx.show_cmd(first_bad)} | python3 -c "
        "'import collections,json,sys;"
        "json.load(sys.stdin, object_pairs_hook=lambda p: (lambda c: "
        '(_ for _ in ()).throw(ValueError("dup: %s" % [k for k,n in c.items() if n>1])) '
        "if any(n>1 for n in c.values()) else dict(p))(collections.Counter(k for k,_ in p)))'"
        if first_bad
        else f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit} | grep '\\.json$' | wc -l"
    )
    return result("FAIL" if violations else "PASS", detail, repro, violations)


@check("C-COMMIT-001", "Reject empty commits that carry a substantive message", "HARD")
def c_commit_001(ctx: Ctx) -> dict[str, Any]:
    window = int(ctx.cfg("history_window", 50) or 50)
    allowed = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in (ctx.config.get("allowed_empty_commit_patterns") or [])]

    if ctx.base_commit:
        rev_list_args = ["rev-list", "--parents", f"{ctx.base_commit}..{ctx.audited_commit}"]
        scope = f"{ctx.base_commit}..{ctx.audited_commit}"
    else:
        rev_list_args = ["rev-list", "--parents", f"-{window}", ctx.audited_commit]
        scope = f"the last {window} commit(s) of {ctx.audited_commit[:12]}"
    listing = ctx.git_text(*rev_list_args)

    rows = [line.split() for line in listing.splitlines() if line.strip()]
    violations: list[dict[str, Any]] = []
    merges = 0
    inspected = 0
    for row in rows:
        sha, parents = row[0], row[1:]
        if len(parents) > 1:
            merges += 1
            continue
        inspected += 1
        if parents:
            changed = ctx.git_text("diff", "--name-only", parents[0], sha)
        else:
            changed = ctx.git_text("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha)
        if [line for line in changed.splitlines() if line.strip()]:
            continue
        message = ctx.git_text("log", "-1", "--format=%B", sha).strip()
        subject = message.splitlines()[0] if message else ""
        if any(rx.search(message) for rx in allowed):
            continue
        violations.append(
            violation(
                sha,
                f"commit changes zero files but its message is substantive: {subject!r}",
                expected="either a non-empty diff or a message matching allowed_empty_commit_patterns",
                actual="0 files changed",
            )
        )

    detail = (
        f"Inspected {inspected} non-merge commit(s) in {scope} for a zero-file diff paired with a "
        f"substantive message; {len(violations)} found ({merges} merge commit(s) not judged)."
    )
    rev_list = f"git --git-dir={ctx.gd()} " + " ".join(rev_list_args[:1] + rev_list_args[2:])
    repro = (
        f"for c in $({rev_list}); do "
        f"[ -z \"$(git --git-dir={ctx.gd()} diff-tree --no-commit-id --name-only -r $c)\" ] "
        f"&& git --git-dir={ctx.gd()} log -1 --format='EMPTY %H %s' $c; done"
    )
    return result("FAIL" if violations else "PASS", detail, repro, violations)


MD_LINK_RX = re.compile(r"\[[^\]\n]*\]\(\s*<?([^)>\s]+)>?(?:\s+[\"'][^\"'\n]*[\"'])?\s*\)")
BACKTICK_RX = re.compile(r"`([^`\n]+)`")


def _link_candidates(text: str, extensions: Sequence[str], ignore: Sequence[re.Pattern[str]]) -> Iterator[tuple[int, str, str]]:
    exts = tuple(e.lower() for e in extensions)
    for lineno, line in enumerate(text.splitlines(), start=1):
        raw_targets = [("markdown link", m.group(1)) for m in MD_LINK_RX.finditer(line)]
        raw_targets += [("backticked path", m.group(1)) for m in BACKTICK_RX.finditer(line)]
        for kind, target in raw_targets:
            target = target.strip().strip("“”\"'")
            if not target or any(rx.search(target) for rx in ignore):
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target or any(ch in target for ch in " \t*?<>|$(){}[]"):
                continue
            basename = target.rsplit("/", 1)[-1].lower()
            matched = next((e for e in exts if basename.endswith(e)), None)
            if matched is None or len(basename) <= len(matched):
                continue
            yield lineno, kind, target


@check("C-LINK-001", "Resolve markdown links and backticked repo paths", "SOFT")
def c_link_001(ctx: Ctx) -> dict[str, Any]:
    targets = ctx.files_matching("link_scan_globs")
    extensions = list(ctx.config.get("link_extensions") or [])
    if not targets or not extensions:
        return result(
            "SKIP",
            "link_scan_globs matched no tracked file or link_extensions is empty.",
            reproduce=f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit}",
        )
    ignore = [re.compile(p) for p in (ctx.config.get("link_ignore_regexes") or [])]

    violations: list[dict[str, Any]] = []
    scanned = 0
    seen: set[tuple[str, str]] = set()
    first_bad: tuple[list[str], str] | None = None
    for path in targets:
        text = ctx.git_show_text(path)
        if text is None:
            continue
        parent = os.path.dirname(path)
        for lineno, kind, target in _link_candidates(text, extensions, ignore):
            scanned += 1
            candidates: list[str] = []
            for candidate in (f"{parent}/{target}" if parent else target, target):
                norm = norm_repo_path(candidate)
                if norm and norm not in candidates:
                    candidates.append(norm)
            if not candidates or any(ctx.exists(c) or ctx.dir_exists(c) for c in candidates):
                continue
            key = (path, target)
            if key in seen:
                continue
            seen.add(key)
            first_bad = first_bad or (candidates, f"{target!r} referenced from {path}:{lineno}")
            violations.append(
                violation(
                    path,
                    f"line {lineno}: {kind} {target!r} resolves to no file at the audited commit "
                    f"(tried {', '.join(candidates)})",
                    expected="a tracked path, relative to the document or to the repo root",
                    actual="neither resolution exists",
                )
            )

    detail = (
        f"Resolved {scanned} repo-path-shaped reference(s) in {len(targets)} scanned file(s) "
        f"against the audited tree, accepting document-relative or repo-root-relative; "
        f"{len(violations)} resolved to nothing."
    )
    repro = (
        ctx.exists_probe(*first_bad)
        if first_bad
        else f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit} | wc -l"
    )
    return result("FAIL" if violations else "PASS", detail, repro, violations)


@check("C-INJECT-001", "Detect audited content that instructs the auditor", "HARD")
def c_inject_001(ctx: Ctx) -> dict[str, Any]:
    """Audited content is DATA, never instructions.

    A tracked file that addresses the auditor and tells it to suppress,
    downgrade, or skip a finding is itself a process defect, whether or not the
    auditor complies. Detection is pure pattern matching over config-supplied
    regexes so no judgment is involved.
    """
    patterns = ctx.config.get("auditor_instruction_regexes") or []
    if not patterns:
        return result(
            "SKIP",
            "No auditor_instruction_regexes are configured.",
            reproduce=f"grep -n auditor_instruction_regexes {shlex.quote(ctx.config_path)}",
        )
    targets = ctx.files_matching("injection_scan_globs")
    if not targets:
        return result(
            "SKIP",
            "injection_scan_globs matched no tracked file at the audited commit.",
            reproduce=f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit}",
        )
    compiled = [(spec, re.compile(spec, re.IGNORECASE)) for spec in patterns]
    violations: list[dict[str, Any]] = []
    first_bad: str | None = None
    for path in sorted(targets):
        text = ctx.git_show_text(path)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for spec, rx in compiled:
                if rx.search(line):
                    first_bad = first_bad or path
                    violations.append(
                        violation(
                            path,
                            f"line {lineno} instructs the auditor",
                            expected="audited content states facts only",
                            actual=line.strip()[:200],
                        )
                    )
                    break
    if not violations:
        return result(
            "PASS",
            f"No auditor-directed instruction matched in {len(targets)} tracked files.",
        )
    return result(
        "FAIL",
        f"{len(violations)} line(s) in the audited tree attempt to direct the auditor; "
        "such content carries no authority and must be reported.",
        reproduce=(
            f"git --git-dir={ctx.gd()} show {ctx.audited_commit}:{first_bad} "
            "| grep -niE 'do not report|not a finding|pre-approved|overrides the audit'"
        ),
        violations=violations,
    )


# --------------------------------------------------------------------------------------
# tree safety (C-TREESAFE-001)
# --------------------------------------------------------------------------------------

SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"


@dataclass(frozen=True)
class TreeEntry:
    mode: str
    obj_type: str
    sha: str
    path: str


def tree_entries(ctx: Ctx) -> list[TreeEntry]:
    """Every entry of the audited tree paired with its git mode.

    ``ls-tree -r -z`` so paths arrive raw: never quoted, never escaped, so a path holding a
    newline or a quote cannot break the parse. The committed tree is the authority and the
    worktree is never stat'ed, so this reads correctly even when no checkout exists.
    """
    raw = ctx.git("ls-tree", "-r", "-z", ctx.audited_commit).stdout
    entries: list[TreeEntry] = []
    for record in raw.split(b"\x00"):
        if not record:
            continue
        meta, sep, path = record.partition(b"\t")
        if not sep:
            continue
        fields = meta.split()
        if len(fields) < 3:
            continue
        entries.append(
            TreeEntry(
                mode=fields[0].decode("ascii", "replace"),
                obj_type=fields[1].decode("ascii", "replace"),
                sha=fields[2].decode("ascii", "replace"),
                path=path.decode("utf-8", "surrogateescape"),
            )
        )
    return entries


def symlink_target_escapes(link_path: str, target: str) -> tuple[bool, str]:
    """Resolve a symlink target against the link's own directory.

    Returns ``(escapes, resolved)``. An absolute target escapes by construction; a relative
    one escapes when its normalised form walks above the repository root. Purely textual:
    the target is the committed blob's bytes, and nothing on the audit host is consulted.
    """
    if target.startswith("/"):
        return True, target
    parent = os.path.dirname(link_path)
    joined = f"{parent}/{target}" if parent else target
    resolved = posix_normpath(joined)
    if resolved is None:
        return True, joined
    return False, resolved or "."


def treesafe_reproduce(ctx: Ctx, path: str, read_target: bool) -> str:
    """Re-derive one entry's mode, and for a symlink the target blob, from the git dir."""
    quoted = shlex.quote(path)
    listing = f"git --git-dir={ctx.gd()} ls-tree -r {ctx.audited_commit} -- {quoted}"
    if not read_target:
        return listing
    return (
        f"{listing} ; git --git-dir={ctx.gd()} cat-file blob "
        f"{ctx.audited_commit}:{quoted} ; echo"
    )


@check("C-TREESAFE-001", "Reject tracked symlinks and gitlinks in the audited tree", "HARD")
def c_treesafe_001(ctx: Ctx) -> dict[str, Any]:
    """A tracked link is a read path whose content the audited commit does not contain.

    The auditor reads the audited commit through a real ``git worktree`` checkout and may
    open any path inside it. A tracked symlink (git mode ``120000``) is materialised by
    that checkout, so what is read through it is not a committed blob: a target leaving the
    repository turns "read a file in the audited tree" into "read a file on the audit
    host", whose bytes may then be sent to an external model API. A gitlink (mode
    ``160000``) pins a submodule commit whose content is likewise not part of the audited
    tree. Both are supply-chain surface, not style.

    Mechanism only: the mode comes from the commit, never from the filesystem, and every
    exception is a path listed verbatim in ``treesafe_allowed_paths``.
    """
    allowed = {
        norm
        for norm in (norm_repo_path(str(p)) for p in (ctx.config.get("treesafe_allowed_paths") or []))
        if norm
    }
    reject_gitlinks = bool(ctx.cfg("treesafe_reject_gitlinks", True))

    entries = tree_entries(ctx)
    violations: list[dict[str, Any]] = []
    n_symlinks = n_escaping = n_gitlinks = n_allowlisted = 0
    expected_mode = (
        "a regular file (git mode 100644/100755), or an explicit treesafe_allowed_paths entry"
    )

    for entry in sorted(entries, key=lambda e: e.path):
        if entry.mode == GITLINK_MODE:
            n_gitlinks += 1
            if entry.path in allowed:
                n_allowlisted += 1
                continue
            if not reject_gitlinks:
                continue
            record = violation(
                entry.path,
                "tracked gitlink (git mode 160000): a submodule pins a commit of another "
                "repository, so the content this path yields in a checkout is not part of "
                "the audited tree and is covered by no check here",
                expected=expected_mode,
                actual=f"mode 160000 -> submodule commit {entry.sha}",
            )
            record["reproduce"] = treesafe_reproduce(ctx, entry.path, read_target=False)
            violations.append(record)
            continue
        if entry.mode != SYMLINK_MODE:
            continue

        n_symlinks += 1
        # The blob of a 120000 entry IS the link target: bytes, verbatim, no trailing newline.
        blob = ctx.git("cat-file", "blob", entry.sha, check=False)
        readable = blob.returncode == 0
        target = blob.stdout.decode("utf-8", "surrogateescape") if readable else ""
        escapes, resolved = symlink_target_escapes(entry.path, target) if readable else (False, "")
        if escapes:
            n_escaping += 1
        if entry.path in allowed:
            n_allowlisted += 1
            continue

        shown = target[:200] + ("..." if len(target) > 200 else "")
        if not readable:
            message = (
                "tracked symlink (git mode 120000) whose target blob could not be read, so "
                "what a checkout would materialise here cannot be established"
            )
            actual = f"mode 120000 -> blob {entry.sha} unreadable"
        elif escapes:
            message = (
                f"tracked symlink (git mode 120000) whose target {shown!r} leaves the "
                f"repository root: a git worktree checkout materialises it, so an auditor "
                f"reading this path reads a file on the audit host that is not a committed "
                f"blob of the audited tree. This is the dangerous class -- an exfiltration "
                f"and supply-chain path out of the audited commit"
            )
            actual = f"mode 120000 -> {shown!r} (escapes the repository root)"
        else:
            message = (
                f"tracked symlink (git mode 120000) resolving inside the repository to "
                f"{resolved!r}: its committed content is a link target, not a file blob, so "
                f"what is read through this path is decided by checkout behaviour rather "
                f"than by the audited tree"
            )
            actual = f"mode 120000 -> {shown!r} (resolves to {resolved})"
        record = violation(entry.path, message, expected=expected_mode, actual=actual)
        record["reproduce"] = treesafe_reproduce(ctx, entry.path, read_target=True)
        violations.append(record)

    detail = (
        f"Examined the git mode of {len(entries)} tracked tree entr(ies) at the audited "
        f"commit, read from git ls-tree and never from a checkout; {n_symlinks} symlink(s) "
        f"(mode 120000), {n_escaping} of them resolving outside the repository root, and "
        f"{n_gitlinks} gitlink(s) (mode 160000); {n_allowlisted} entr(ies) matched "
        f"treesafe_allowed_paths and were not reported; {len(violations)} violation(s)."
    )
    if not reject_gitlinks:
        detail += (
            " treesafe_reject_gitlinks is false, so gitlink(s) were counted but not reported."
        )
    census = (
        f"git --git-dir={ctx.gd()} ls-tree -r {ctx.audited_commit} "
        f"| awk '{{print $1}}' | sort | uniq -c"
    )
    return result("FAIL" if violations else "PASS", detail, census, violations)


@check("C-BANNER-001", "Require the superseded banner in superseded files", "HARD")
def c_banner_001(ctx: Ctx) -> dict[str, Any]:
    targets = ctx.files_matching("superseded_globs")
    pattern = ctx.config.get("superseded_banner_regex")
    if not pattern:
        return result(
            "SKIP",
            "No superseded_banner_regex is configured, so no banner was checkable.",
            reproduce=f"grep -n superseded_banner_regex {shlex.quote(ctx.config_path)}",
        )
    if not targets:
        return result(
            "SKIP",
            "superseded_globs matched no tracked file at the audited commit.",
            reproduce=f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit}",
        )
    window = int(ctx.cfg("banner_window_lines", 10) or 10)
    rx = re.compile(pattern, re.MULTILINE)

    violations: list[dict[str, Any]] = []
    first_bad: str | None = None
    for path in targets:
        text = ctx.git_show_text(path)
        if text is None:
            continue
        head = "\n".join(text.splitlines()[:window])
        if rx.search(head):
            continue
        first_bad = first_bad or path
        violations.append(
            violation(
                path,
                f"no superseded banner in the first {window} line(s)",
                expected=f"a line matching /{pattern}/",
                actual=(head.splitlines()[0][:120] if head.splitlines() else "<empty file>"),
            )
        )

    detail = (
        f"Searched the first {window} line(s) of {len(targets)} file(s) matching superseded_globs "
        f"for /{pattern}/; {len(violations)} lacked it."
    )
    repro = (
        f"{ctx.show_cmd(first_bad or targets[0])} | head -n {window} | grep -nE {shlex.quote(pattern)}"
    )
    return result("FAIL" if violations else "PASS", detail, repro, violations)


@check("C-STATE-001", "Detect config-declared cross-document status contradictions", "HARD")
def c_state_001(ctx: Ctx) -> dict[str, Any]:
    conflicts = ctx.config.get("status_conflicts") or []
    if not conflicts:
        return result(
            "SKIP",
            "No status_conflicts are configured, so no contradiction pattern was evaluated.",
            reproduce=f"grep -n status_conflicts {shlex.quote(ctx.config_path)}",
        )

    def hits(patterns: Sequence[str], paths: Sequence[str]) -> list[tuple[str, int, str, str]]:
        compiled = [(p, re.compile(p)) for p in patterns]
        found: list[tuple[str, int, str, str]] = []
        for path in paths:
            text = ctx.git_show_text(path)
            if text is None:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                for pattern, rx in compiled:
                    if rx.search(line):
                        found.append((path, lineno, line.strip()[:240], pattern))
                        break
        return sorted(found)

    violations: list[dict[str, Any]] = []
    evaluated = 0
    first_pair: tuple[tuple[str, int, str, str], tuple[str, int, str, str]] | None = None
    for conflict in conflicts:
        cid = str(conflict.get("id") or "<unnamed>")
        description = str(conflict.get("description") or "")
        scope = GlobSet(conflict.get("scope_globs") or []).select(ctx.blobs)
        asserts = list(conflict.get("asserts") or [])
        denies = list(conflict.get("denies") or [])
        if not scope or not asserts or not denies:
            continue
        evaluated += 1
        a_hits = hits(asserts, scope)
        d_hits = hits(denies, scope)
        if not a_hits or not d_hits:
            continue
        pair = next(
            ((a, d) for a in a_hits for d in d_hits if (a[0], a[1]) != (d[0], d[1])),
            None,
        )
        if pair is None:
            continue
        a, d = pair
        first_pair = first_pair or pair
        extra = ""
        if len(a_hits) > 1 or len(d_hits) > 1:
            extra = f" ({len(a_hits)} asserting and {len(d_hits)} denying line(s) in scope)"
        violations.append(
            violation(
                a[0],
                f"{cid}: {description} -- {a[0]}:{a[1]} asserts /{a[3]}/ ({a[2]!r}) while "
                f"{d[0]}:{d[1]} denies it via /{d[3]}/ ({d[2]!r}){extra}",
                expected=f"no file in scope matches both an asserts and a denies pattern of {cid}",
                actual=f"assert at {a[0]}:{a[1]}; deny at {d[0]}:{d[1]}",
            )
        )

    detail = (
        f"Evaluated {evaluated} configured status_conflict pattern set(s) over their declared "
        f"scopes at the audited commit; {len(violations)} produced a co-occurring assert/deny pair."
    )
    if first_pair is not None:
        a, d = first_pair
        repro = (
            f"{ctx.show_cmd(a[0])} | sed -n {a[1]}p ; "
            f"{ctx.show_cmd(d[0])} | sed -n {d[1]}p"
        )
    else:
        probe = conflicts[0]
        repro = (
            f"git --git-dir={ctx.gd()} grep -nE {shlex.quote((probe.get('asserts') or [''])[0])} "
            f"{ctx.audited_commit} -- {' '.join(shlex.quote(g) for g in (probe.get('scope_globs') or ['.']))}"
        )
    return result("FAIL" if violations else "PASS", detail, repro, violations)


# --------------------------------------------------------------------------------------
# numeric assertions (C-NUM-001)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NumericAssertion:
    """One config-declared agreement between a document and the artifact it cites."""

    aid: str
    doc: str
    pattern: str
    source: str
    pointer: str
    tolerance: float
    occurrence: str
    rx: re.Pattern[str]


# Typography only: a Unicode MINUS SIGN (U+2212) in a captured number is read as ASCII "-",
# and non-breaking / thin spaces are dropped. Those are rendering differences, not value
# differences: no other character is ever rewritten and no rounding is ever applied.
NUM_TRANSLATE = {0x2212: "-", 0x00A0: None, 0x2009: None, 0x202F: None}

# Both one-liners are pasted inside single quotes by the reproduce builder, so they must
# contain no single quote of their own; the pattern / pointer arrive as argv, never inlined.
NUM_DOC_EXTRACT_PY = (
    "import re,sys;rx=re.compile(sys.argv[1]);"
    "print([(i,m.group(1)) for i,l in enumerate(sys.stdin.read().splitlines(),1) "
    "for m in rx.finditer(l)])"
)
NUM_POINTER_PY = (
    "import functools,json,sys;print(functools.reduce("
    "lambda n,s: n[int(s)] if isinstance(n,list) else n[s], "
    'sys.argv[1].split("."), json.load(sys.stdin)))'
)


def parse_numeric_assertion(raw: Any, seen_ids: set[str]) -> tuple[NumericAssertion | None, str]:
    """Validate one configured entry; returns (entry, reason-it-was-rejected)."""
    if not isinstance(raw, dict):
        return None, f"entry is {type(raw).__name__}, not a mapping"
    aid = str(raw.get("id") or "").strip()
    if not aid:
        return None, "no id"
    if aid in seen_ids:
        return None, f"id {aid!r} is already used by an earlier entry"
    doc = norm_repo_path(str(raw.get("doc") or ""))
    source = norm_repo_path(str(raw.get("source") or ""))
    if not doc or not source:
        return None, f"{aid}: doc and source must both be repo-relative paths inside the repo"
    pattern = raw.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return None, f"{aid}: pattern must be a non-empty string"
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return None, f"{aid}: pattern does not compile ({exc})"
    if rx.groups != 1:
        return None, f"{aid}: pattern must have exactly one capture group, it has {rx.groups}"
    pointer = str(raw.get("pointer") or "").strip()
    if not pointer or any(seg == "" for seg in pointer.split(".")):
        return None, f"{aid}: pointer must be a non-empty dot path"
    tolerance = raw.get("tolerance", 0)
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
        return None, f"{aid}: tolerance must be a number >= 0, got {tolerance!r}"
    occurrence = str(raw.get("occurrence") or "all")
    if occurrence not in {"all", "first"}:
        return None, f"{aid}: occurrence must be 'all' or 'first', got {occurrence!r}"
    return (
        NumericAssertion(
            aid=aid,
            doc=doc,
            pattern=pattern,
            source=source,
            pointer=pointer,
            tolerance=float(tolerance),
            occurrence=occurrence,
            rx=rx,
        ),
        "",
    )


def resolve_json_pointer(doc: Any, pointer: str) -> tuple[bool, Any]:
    """Walk a dot path; an integer segment indexes a list. Returns (resolved, value)."""
    node = doc
    for segment in pointer.split("."):
        if isinstance(node, list):
            if not re.fullmatch(r"-?[0-9]+", segment):
                return False, None
            index = int(segment)
            if not -len(node) <= index < len(node):
                return False, None
            node = node[index]
            continue
        if isinstance(node, dict) and segment in node:
            node = node[segment]
            continue
        return False, None
    return True, node


def num_as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.translate(NUM_TRANSLATE).strip())
        except ValueError:
            return None
    return None


def num_literal(value: Any) -> str:
    return json.dumps(value) if isinstance(value, (int, float)) else str(value)


def num_violation(
    path: str, message: str, expected: Any, actual: Any, reproduce: str
) -> dict[str, Any]:
    """A violation plus its own reproduce command (this check reports per-assertion)."""
    record = violation(path, message, expected, actual)
    record["reproduce"] = reproduce
    return record


def num_reproduce(ctx: Ctx, entry: NumericAssertion) -> str:
    """Re-derive both sides: every doc match with its line number, and the pointer value."""
    show = f"git --git-dir={ctx.gd()} show {ctx.audited_commit}"
    return (
        f"{show}:{shlex.quote(entry.doc)} | python3 -c {shlex.quote(NUM_DOC_EXTRACT_PY)} "
        f"{shlex.quote(entry.pattern)} ; "
        f"{show}:{shlex.quote(entry.source)} | python3 -c {shlex.quote(NUM_POINTER_PY)} "
        f"{shlex.quote(entry.pointer)}"
    )


def num_exists_reproduce(ctx: Ctx, entry: NumericAssertion) -> str:
    paths = " ".join(shlex.quote(p) for p in (entry.doc, entry.source))
    return (
        f"for p in {paths}; do git --git-dir={ctx.gd()} show {ctx.audited_commit}:\"$p\" "
        f">/dev/null 2>&1 && echo \"exists: $p\" || echo \"missing: $p\"; done"
    )


@check("C-NUM-001", "Verify config-declared numbers in prose against the artifact they cite", "HARD")
def c_num_001(ctx: Ctx) -> dict[str, Any]:
    """Assert that two committed files agree on a number, nothing more.

    Each ``numeric_assertions`` entry names a document, a regex with exactly one capture
    group over that document, a JSON artifact and a dot path into it. The captured number
    must equal the pointed-at number within an absolute tolerance. This is a pure
    consistency assertion between two files at one commit: it never judges whether either
    number is scientifically right, only whether the repository contradicts itself. A
    silently-dead assertion (pattern matching nothing) is itself reported, so an assertion
    cannot stop working unnoticed.
    """
    raw_entries = ctx.config.get("numeric_assertions") or []
    config_probe = f"grep -n numeric_assertions {shlex.quote(ctx.config_path)}"
    if not isinstance(raw_entries, list) or not raw_entries:
        return result(
            "SKIP",
            "numeric_assertions is absent or empty in the config, so no published number was "
            "cross-checked against the artifact its document cites.",
            reproduce=config_probe,
        )

    violations: list[dict[str, Any]] = []
    evaluated = 0
    compared = 0
    first_repro = ""
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_entries):
        entry, reason = parse_numeric_assertion(raw, seen_ids)
        if entry is None:
            violations.append(
                num_violation(
                    f"<numeric_assertions[{index}]>",
                    "assertion entry is malformed",
                    expected="id, doc, pattern (one capture group), source, pointer",
                    actual=reason,
                    reproduce=config_probe,
                )
            )
            continue
        seen_ids.add(entry.aid)
        evaluated += 1
        repro = num_reproduce(ctx, entry)

        doc_text = ctx.git_show_text(entry.doc)
        source_raw = ctx.git_show_bytes(entry.source)
        missing = [
            path
            for path, present in ((entry.doc, doc_text is not None), (entry.source, source_raw is not None))
            if not present
        ]
        if missing:
            exists_repro = num_exists_reproduce(ctx, entry)
            first_repro = first_repro or exists_repro
            violations.append(
                num_violation(
                    entry.doc,
                    f"{entry.aid}: declared source/doc missing",
                    expected=f"both {entry.doc} and {entry.source} tracked at the audited commit",
                    actual=f"not at the audited commit: {', '.join(missing)}",
                    reproduce=exists_repro,
                )
            )
            continue
        assert doc_text is not None and source_raw is not None

        try:
            source_doc = json.loads(source_raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            first_repro = first_repro or repro
            violations.append(
                num_violation(
                    entry.source,
                    f"{entry.aid}: declared source did not parse as JSON",
                    expected="a JSON document (see C-JSON-001)",
                    actual=str(exc)[:200],
                    reproduce=repro,
                )
            )
            continue

        resolved, node = resolve_json_pointer(source_doc, entry.pointer)
        expected_value = num_as_float(node) if resolved else None
        if expected_value is None:
            first_repro = first_repro or repro
            violations.append(
                num_violation(
                    entry.source,
                    f"{entry.aid}: pointer does not resolve",
                    expected=f"a number at {entry.pointer} in {entry.source}",
                    actual=(
                        f"resolved to {type(node).__name__} {num_literal(node)[:80]}, not a number"
                        if resolved
                        else "no such key or index"
                    ),
                    reproduce=repro,
                )
            )
            continue

        matches = [
            (lineno, match.group(1))
            for lineno, line in enumerate(doc_text.splitlines(), start=1)
            for match in entry.rx.finditer(line)
        ]
        if not matches:
            first_repro = first_repro or repro
            violations.append(
                num_violation(
                    entry.doc,
                    f"{entry.aid}: assertion pattern matched nothing",
                    expected=f"at least one match of /{entry.pattern}/ in {entry.doc}",
                    actual="zero matches, so the assertion no longer checks anything",
                    reproduce=repro,
                )
            )
            continue
        if entry.occurrence == "first":
            matches = matches[:1]

        for lineno, captured in matches:
            compared += 1
            actual_value = num_as_float(captured)
            if actual_value is None:
                first_repro = first_repro or repro
                violations.append(
                    num_violation(
                        entry.doc,
                        f"{entry.aid}: line {lineno} capture is not a number",
                        expected=f"the capture group of /{entry.pattern}/ to be numeric",
                        actual=captured[:120],
                        reproduce=repro,
                    )
                )
                continue
            if abs(actual_value - expected_value) <= entry.tolerance:
                continue
            first_repro = first_repro or repro
            violations.append(
                num_violation(
                    entry.doc,
                    f"{entry.aid}: line {lineno} states a number that disagrees with "
                    f"{entry.source} at {entry.pointer} (absolute tolerance "
                    f"{num_literal(entry.tolerance)})",
                    expected=num_literal(node),
                    actual=captured,
                    reproduce=repro,
                )
            )

    detail = (
        f"Compared {compared} number(s) captured from prose by {evaluated} configured "
        f"numeric_assertion(s) against the JSON pointer each document cites, both read at the "
        f"audited commit; {len(violations)} disagreement(s). Agreement between two committed "
        f"files only: no number is judged for scientific correctness."
    )
    if not violations and evaluated:
        first_entry, _ = parse_numeric_assertion(raw_entries[0], set())
        first_repro = num_reproduce(ctx, first_entry) if first_entry else config_probe
    return result("FAIL" if violations else "PASS", detail, first_repro or config_probe, violations)


@check("C-SCOPE-001", "Report changed paths outside the declared audit scope", "SOFT")
def c_scope_001(ctx: Ctx) -> dict[str, Any]:
    request_path = ctx.config.get("audit_request_path")
    scope_field = ctx.cfg("audit_scope_field", "audit_scope")
    if not request_path:
        return result(
            "SKIP",
            "No audit_request_path is configured, so no declared scope could be read.",
            reproduce=f"grep -n audit_request_path {shlex.quote(ctx.config_path)}",
        )
    if not ctx.base_commit:
        return result(
            "SKIP",
            "base_commit is NONE, so there is no diff range in which to locate out-of-scope paths.",
            reproduce=f"git --git-dir={ctx.gd()} log -1 --format=%H {ctx.audited_commit}",
        )
    raw = ctx.git_show_bytes(request_path)
    if raw is None:
        return result(
            "SKIP",
            f"{request_path} does not exist at the audited commit, so no scope is declared.",
            reproduce=f"git --git-dir={ctx.gd()} ls-tree -r --name-only {ctx.audited_commit} | grep -F -- {shlex.quote(request_path)}",
        )
    try:
        request = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return result(
            "SKIP",
            f"{request_path} did not parse as JSON ({str(exc)[:120]}), so no scope is declared.",
            reproduce=f"{ctx.show_cmd(request_path)} | python3 -m json.tool",
        )
    declared = request.get(scope_field) if isinstance(request, dict) else None
    patterns: list[str] = []
    if isinstance(declared, list):
        patterns = [str(p) for p in declared if isinstance(p, str)]
    elif isinstance(declared, dict):
        patterns = [str(p) for p in (declared.get("include_globs") or []) if isinstance(p, str)]
    if not patterns:
        kind = type(declared).__name__ if declared is not None else "absent"
        return result(
            "SKIP",
            f"{request_path}.{scope_field} is {kind}, not a list of path patterns, so no "
            f"machine-checkable scope is declared.",
            reproduce=f"{ctx.show_cmd(request_path)} | python3 -m json.tool",
        )

    scope = GlobSet(patterns)
    changed = sorted(
        {
            line
            for line in ctx.git_text("diff", "--name-only", ctx.base_commit, ctx.audited_commit).splitlines()
            if line.strip()
        }
    )
    violations = [
        violation(
            path,
            "path changed in the audited range but matches no declared audit_scope pattern",
            expected=f"a path matching one of: {', '.join(patterns)}",
            actual="outside the declared scope",
        )
        for path in changed
        if not scope.matches(path)
    ]
    detail = (
        f"Compared {len(changed)} path(s) changed in {ctx.base_commit[:12]}..{ctx.audited_commit[:12]} "
        f"against {len(patterns)} declared audit_scope pattern(s); {len(violations)} fell outside."
    )
    repro = f"git --git-dir={ctx.gd()} diff --name-only {ctx.base_commit} {ctx.audited_commit}"
    return result("FAIL" if violations else "PASS", detail, repro, violations)


@check("C-TEST-001", "Run the repository's declared test entrypoint in a pristine clone", "HARD")
def c_test_001(ctx: Ctx) -> dict[str, Any]:
    command = ctx.config.get("test_command")
    if command is None:
        return result(
            "SKIP",
            "test_command is null in the config, so the repository declares no test entrypoint to run.",
            reproduce=f"grep -n test_command {shlex.quote(ctx.config_path)}",
        )
    argv = shlex.split(command) if isinstance(command, str) else [str(a) for a in command]
    if not argv:
        return result(
            "SKIP",
            "test_command is empty, so there is no entrypoint to run.",
            reproduce=f"grep -n test_command {shlex.quote(ctx.config_path)}",
        )
    interpreter = ctx.config.get("test_python")
    if interpreter and argv[0] in {"python", "python3"}:
        argv[0] = str(interpreter)
    printable = " ".join(shlex.quote(a) for a in argv)
    clone_repro = (
        f"d=$(mktemp -d) && git clone --quiet --no-checkout --no-hardlinks {ctx.gd()} \"$d/repo\" "
        f"&& git -C \"$d/repo\" checkout --quiet --detach {ctx.audited_commit} "
        f"&& (cd \"$d/repo\" && {printable}); echo rc=$?"
    )
    if not ctx.config.get("test_command_enabled"):
        return result(
            "SKIP",
            f"test_command_enabled is false, so {printable!r} was not executed "
            f"(no test result is claimed either way).",
            reproduce=clone_repro,
        )

    timeout = int(ctx.cfg("test_timeout_seconds", 900) or 900)
    tmp = tempfile.mkdtemp(prefix="tier0-test-")
    clone = os.path.join(tmp, "repo")
    try:
        for step in (
            ["git", "clone", "--quiet", "--no-checkout", "--no-hardlinks", ctx.git_dir, clone],
            ["git", "-C", clone, "checkout", "--quiet", "--detach", ctx.audited_commit],
        ):
            cp = subprocess.run(step, capture_output=True, text=False)
            if cp.returncode != 0:
                return result(
                    "ERROR",
                    "Could not build a pristine clone at the audited commit, so the declared "
                    "test entrypoint was not run.",
                    clone_repro,
                    [
                        violation(
                            "<clone>",
                            " ".join(step[:3]) + " failed",
                            expected="rc=0",
                            actual=cp.stderr.decode("utf-8", "replace")[:400],
                        )
                    ],
                )
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in (ctx.config.get("test_env") or {}).items()})
        try:
            run = subprocess.run(
                argv,
                cwd=clone,
                capture_output=True,
                text=False,
                timeout=timeout,
                env=env,
            )
            rc: int | None = run.returncode
            output = (run.stdout + run.stderr).decode("utf-8", "replace")
        except subprocess.TimeoutExpired as exc:
            rc = None
            captured = (exc.stdout or b"") + (exc.stderr or b"")
            output = captured.decode("utf-8", "replace")
        except OSError as exc:
            return result(
                "ERROR",
                f"The declared test entrypoint {printable!r} could not be executed.",
                clone_repro,
                [violation("<test_command>", "exec failed", expected="an executable command", actual=str(exc)[:300])],
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tail = "\n".join(output.splitlines()[-40:])
    if rc == 0:
        return result(
            "PASS",
            f"Ran {printable!r} in a pristine clone at the audited commit; exit code 0. "
            f"Last output line: {(tail.splitlines() or [''])[-1][:200]!r}",
            clone_repro,
        )
    status_word = f"exit code {rc}" if rc is not None else f"timed out after {timeout}s"
    return result(
        "FAIL",
        f"Ran {printable!r} in a pristine clone at the audited commit; {status_word}.",
        clone_repro,
        [
            violation(
                "<test_command>",
                f"{printable} exited non-zero in a pristine clone ({status_word}); "
                f"last 40 output line(s) follow",
                expected="exit code 0",
                actual=tail[-4000:],
            )
        ],
    )


# --------------------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------------------


def run_checks(ctx: Ctx) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for spec in sorted(REGISTRY, key=lambda s: s.check_id):
        try:
            outcome = spec.fn(ctx)
        except Exception as exc:  # one broken check must never end the run
            outcome = result(
                "ERROR",
                f"The check raised {type(exc).__name__}: {str(exc)[:400]}",
                reproduce=(
                    f"python3 {shlex.quote(os.path.abspath(__file__))} "
                    f"--science-worktree {shlex.quote(ctx.worktree)} "
                    f"--science-git-dir {ctx.gd()} "
                    f"--audited-commit {ctx.audited_commit} "
                    f"--base-commit {ctx.base_commit or 'NONE'} "
                    f"--config {shlex.quote(ctx.config_path)} --out /tmp/check_report.json"
                ),
                violations=[
                    violation("<check>", f"{type(exc).__name__}: {str(exc)[:400]}", "a completed check", "exception")
                ],
            )
        violations = sorted(
            outcome.get("violations") or [],
            key=lambda v: (str(v.get("path", "")), str(v.get("message", ""))),
        )
        record: dict[str, Any] = {
            "check_id": spec.check_id,
            "title": spec.title,
            "class": spec.cls,
            "status": outcome["status"],
            "detail": outcome["detail"],
            "violations": violations[:MAX_VIOLATIONS],
            "reproduce": outcome.get("reproduce") or "",
        }
        if len(violations) > MAX_VIOLATIONS:
            record["violations_truncated"] = len(violations) - MAX_VIOLATIONS
        results.append(record)
    return results


def summarise(results: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(results), "pass": 0, "fail": 0, "skip": 0, "error": 0, "hard_fail": 0}
    for record in results:
        counts[record["status"].lower()] = counts.get(record["status"].lower(), 0) + 1
        if record["class"] == "HARD" and record["status"] in {"FAIL", "ERROR"}:
            counts["hard_fail"] += 1
    return counts


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tier-0 deterministic verifier for a science repository."
    )
    parser.add_argument("--science-worktree", required=True)
    parser.add_argument("--science-git-dir", required=True)
    parser.add_argument("--audited-commit", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def normalise_commit(value: str, label: str, allow_none: bool) -> str | None:
    text = value.strip()
    if allow_none and text.upper() in {"NONE", ""}:
        return None
    if not HEX40.match(text.lower()):
        raise InternalError(f"--{label} must be a 40-character lowercase hex sha, got {value!r}")
    return text.lower()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    started = utcnow()

    script_path = os.path.abspath(__file__)
    with open(script_path, "rb") as handle:
        script_bytes = handle.read()
    with open(args.config, "rb") as handle:
        config_bytes = handle.read()
    # Pins verifier identity: the exact script bytes plus the exact config bytes.
    checks_sha256 = hashlib.sha256(
        b"checks_script:" + script_bytes + b"\nconfig:" + config_bytes
    ).hexdigest()

    config = yaml.safe_load(config_bytes.decode("utf-8")) or {}
    if not isinstance(config, dict):
        raise InternalError("config root must be a mapping")

    audited = normalise_commit(args.audited_commit, "audited-commit", allow_none=False)
    base = normalise_commit(args.base_commit, "base-commit", allow_none=True)
    assert audited is not None

    git_dir = os.path.abspath(args.science_git_dir)
    worktree = os.path.abspath(args.science_worktree)
    if not os.path.exists(git_dir):
        raise InternalError(f"--science-git-dir does not exist: {git_dir}")
    if not os.path.isdir(worktree):
        raise InternalError(f"--science-worktree is not a directory: {worktree}")

    ctx = Ctx(
        worktree=worktree,
        git_dir=git_dir,
        audited_commit=audited,
        base_commit=base,
        config=config,
        config_path=os.path.abspath(args.config),
    )
    for sha, label in ((audited, "audited-commit"), (base, "base-commit")):
        if sha is None:
            continue
        if ctx.git("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode != 0:
            raise InternalError(f"--{label} {sha} is not a commit in {git_dir}")

    results = run_checks(ctx)
    report = {
        "schema": SCHEMA,
        "audited_commit": audited,
        "base_commit": base,
        "checks_sha256": checks_sha256,
        "started_at": started,
        "completed_at": utcnow(),
        "summary": summarise(results),
        "results": results,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=False, ensure_ascii=False)
        handle.write("\n")

    s = report["summary"]
    failed = ",".join(r["check_id"] for r in results if r["status"] in {"FAIL", "ERROR"}) or "none"
    print(
        f"check_report/v1 {audited[:12]} base={base[:12] if base else 'NONE'} "
        f"total={s['total']} pass={s['pass']} fail={s['fail']} skip={s['skip']} "
        f"error={s['error']} hard_fail={s['hard_fail']} not_passing={failed} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except InternalError as exc:
        print(f"internal error: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 - internal error contract is exit 2
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
