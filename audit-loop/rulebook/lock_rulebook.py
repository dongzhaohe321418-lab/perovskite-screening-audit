#!/usr/bin/env python3
"""Lock AUDIT_RULEBOOK.md into rulebook.lock.json.

The rulebook is the only source of rule IDs an auditor may cite, so it has to be
enumerable and pinned. This script parses the markdown, validates its structure
hard, and writes a machine-readable lock file containing the rulebook version,
the sha256 of the rulebook's raw bytes, and the sorted rule list.

Usage
-----
    python3 lock_rulebook.py              # regenerate rulebook.lock.json
    python3 lock_rulebook.py --check      # CI: exit 1 if the lock is stale

Exit codes
----------
    0   success (lock written, or --check found the lock current)
    1   --check only: the lock file is missing, unreadable, or stale
    2   structural violation in the rulebook; nothing was written

Standard library only, Python 3.12.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

RULEBOOK_NAME = "AUDIT_RULEBOOK.md"
LOCK_NAME = "rulebook.lock.json"

# Adding a family to the rulebook requires adding its prefix here in the same
# change (see "Amending this rulebook" in AUDIT_RULEBOOK.md).
KNOWN_FAMILIES: tuple[str, ...] = ("EVD", "STA", "COR", "CMP", "GRD", "NAV", "PRO")

VALID_CLASSES: tuple[str, ...] = ("HARD", "SOFT")

REQUIRED_FIELDS: tuple[str, ...] = (
    "class",
    "deterministic_check",
    "applies_to",
    "invariant",
    "how_to_audit",
    "evidence_required",
    "not_in_scope",
)

RULE_ID_RE = re.compile(r"^R-[A-Z]{3}-[0-9]{3}$")
CHECK_ID_RE = re.compile(r"^C-[A-Z]{2,8}-[0-9]{3}$")
SEMVER_RE = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
VERSION_RE = re.compile(r"rulebook_version\**\s*:?\**\s*([0-9][0-9A-Za-z.+\-]*)")

FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
# Accepts `- **key:** value` and `- **key**: value`.
FIELD_RE = re.compile(r"^-\s+\*\*(?P<key>[^*]+?)\*\*\s*:?\s*(?P<val>.*)$")
TITLE_SEPARATORS = (" — ", " – ", " -- ", " - ")


class StructuralError(Exception):
    """A violation that must prevent the rulebook from being locked at all."""


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #


def normalise_key(raw: str) -> str:
    """`**how to audit:**` -> `how_to_audit`."""
    key = raw.strip().strip("*`_").strip()
    key = key.rstrip(":").strip()
    return re.sub(r"[\s\-]+", "_", key).lower()


def clean_scalar(raw: str) -> str:
    """First whitespace-delimited token of a field value, markup stripped.

    Tolerates a trailing parenthetical comment such as the template's
    ``C-HASH-001        (or `none`)``.
    """
    value = raw.strip()
    if not value:
        return ""
    token = value.split()[0]
    return token.strip("`*_,;.").strip()


def parse_version(lines: list[str]) -> str:
    """First rulebook_version declaration in the file, validated as semver."""
    for lineno, line in enumerate(lines, start=1):
        match = VERSION_RE.search(line)
        if not match:
            continue
        version = match.group(1)
        if not SEMVER_RE.match(version):
            raise StructuralError(
                f"line {lineno}: rulebook_version {version!r} is not valid semver "
                "(expected MAJOR.MINOR.PATCH)"
            )
        return version
    raise StructuralError(
        "no rulebook_version declaration found; the rulebook must declare "
        "**rulebook_version:** <semver> near the top"
    )


def split_heading(text: str) -> tuple[str, str]:
    """`R-EVD-001 — Title` -> ('R-EVD-001', 'Title')."""
    for separator in TITLE_SEPARATORS:
        if separator in text:
            head, _, tail = text.partition(separator)
            return head.strip(), tail.strip()
    return text.strip(), ""


def parse_sections(lines: list[str]) -> list[dict[str, object]]:
    """Collect every level-3 section, skipping fenced code blocks.

    Fenced blocks are skipped so the field-block template inside the rulebook is
    not mistaken for a rule. The template deliberately carries an invalid family
    prefix, so if this skipping ever regresses the locker fails loudly rather
    than silently duplicating a real rule.
    """
    sections: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    in_fence = False

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")

        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if level == 3:
                current = {
                    "lineno": lineno,
                    "heading": heading.group(2).strip(),
                    "fields": {},
                    "order": [],
                }
                sections.append(current)
            else:
                current = None  # any other heading level closes a rule section
            continue

        if current is None:
            continue

        field = FIELD_RE.match(line)
        if field:
            key = normalise_key(field.group("key"))
            fields = current["fields"]
            assert isinstance(fields, dict)
            if key in fields:
                raise StructuralError(
                    f"line {lineno}: duplicate field '{key}' in section "
                    f"'{current['heading']}'"
                )
            fields[key] = field.group("val").strip()
            order = current["order"]
            assert isinstance(order, list)
            order.append(key)
            current["_last_key"] = key
        elif line.strip() and current.get("_last_key"):
            # continuation of a multi-paragraph field value
            fields = current["fields"]
            assert isinstance(fields, dict)
            last = current["_last_key"]
            assert isinstance(last, str)
            fields[last] = f"{fields[last]} {line.strip()}".strip()

    if in_fence:
        raise StructuralError("unclosed fenced code block in the rulebook")

    return sections


def parse_rules(lines: list[str]) -> list[dict[str, str]]:
    """Extract and hard-validate every rule in the rulebook."""
    rules: list[dict[str, str]] = []
    seen_ids: dict[str, int] = {}
    seen_checks: dict[str, str] = {}

    for section in parse_sections(lines):
        heading = section["heading"]
        assert isinstance(heading, str)
        fields = section["fields"]
        assert isinstance(fields, dict)
        lineno = section["lineno"]

        rule_id, title = split_heading(heading)
        looks_like_rule = rule_id.startswith("R-")

        if not looks_like_rule:
            # Prose subsections are fine, but a field block in one means a rule
            # heading was mistyped and would otherwise be silently dropped.
            if "class" in fields:
                raise StructuralError(
                    f"line {lineno}: section '{heading}' carries a **class:** field "
                    "but its heading is not a rule ID; a mistyped rule heading "
                    "would be silently skipped"
                )
            continue

        if not RULE_ID_RE.match(rule_id):
            raise StructuralError(
                f"line {lineno}: rule id {rule_id!r} does not match "
                r"^R-[A-Z]{3}-[0-9]{3}$"
            )

        family = rule_id[2:5]
        if family not in KNOWN_FAMILIES:
            raise StructuralError(
                f"line {lineno}: rule {rule_id} declares unknown family {family!r}; "
                f"known families are {', '.join(KNOWN_FAMILIES)} (add new families to "
                "KNOWN_FAMILIES and to the family table in the same change)"
            )

        if rule_id in seen_ids:
            raise StructuralError(
                f"line {lineno}: duplicate rule id {rule_id} "
                f"(first declared at line {seen_ids[rule_id]})"
            )
        seen_ids[rule_id] = int(lineno)  # type: ignore[arg-type]

        if not title:
            raise StructuralError(
                f"line {lineno}: rule {rule_id} has no title; expected "
                f"'### {rule_id} — <short imperative title>'"
            )

        missing = [name for name in REQUIRED_FIELDS if name not in fields]
        if missing:
            raise StructuralError(
                f"line {lineno}: rule {rule_id} is missing required field(s): "
                f"{', '.join(missing)}"
            )
        empty = [name for name in REQUIRED_FIELDS if not fields[name].strip()]
        if empty:
            raise StructuralError(
                f"line {lineno}: rule {rule_id} has empty required field(s): "
                f"{', '.join(empty)}"
            )

        rule_class = clean_scalar(fields["class"]).upper()
        if rule_class not in VALID_CLASSES:
            raise StructuralError(
                f"line {lineno}: rule {rule_id} declares class "
                f"{fields['class']!r}; expected one of {', '.join(VALID_CLASSES)}"
            )

        check = clean_scalar(fields["deterministic_check"])
        if check != "none" and not CHECK_ID_RE.match(check):
            raise StructuralError(
                f"line {lineno}: rule {rule_id} declares deterministic_check "
                f"{check!r}; expected 'none' or an id matching "
                r"^C-[A-Z]{2,8}-[0-9]{3}$"
            )
        if rule_class == "SOFT" and check != "none":
            raise StructuralError(
                f"line {lineno}: rule {rule_id} is SOFT but binds deterministic "
                f"check {check}; if a script can decide it, the rule is HARD"
            )
        if check != "none":
            if check in seen_checks:
                raise StructuralError(
                    f"line {lineno}: deterministic check {check} is claimed by both "
                    f"{seen_checks[check]} and {rule_id}; one check per rule"
                )
            seen_checks[check] = rule_id

        rules.append(
            {
                "rule_id": rule_id,
                "class": rule_class,
                "deterministic_check": check,
                "title": title,
            }
        )

    if not rules:
        raise StructuralError("the rulebook declares no rules")

    rules.sort(key=lambda rule: rule["rule_id"])
    return rules


def build_lock(rulebook_path: Path) -> dict[str, object]:
    try:
        raw = rulebook_path.read_bytes()
    except OSError as exc:
        raise StructuralError(f"cannot read {rulebook_path}: {exc}") from exc

    text = raw.decode("utf-8")
    lines = text.splitlines()

    return {
        "rulebook_version": parse_version(lines),
        "rulebook_sha256": hashlib.sha256(raw).hexdigest(),
        "generated_from": rulebook_path.name,
        "rule_count": 0,  # replaced below; key order is part of the contract
        "rules": parse_rules(lines),
    }


def serialise(lock: dict[str, object]) -> str:
    rules = lock["rules"]
    assert isinstance(rules, list)
    lock["rule_count"] = len(rules)
    return json.dumps(lock, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def summarise(lock: dict[str, object]) -> str:
    rules = lock["rules"]
    assert isinstance(rules, list)
    families: dict[str, list[dict[str, str]]] = {}
    for rule in rules:
        families.setdefault(rule["rule_id"][2:5], []).append(rule)

    lines = []
    for family in KNOWN_FAMILIES:
        members = families.get(family, [])
        if not members:
            continue
        hard = sum(1 for rule in members if rule["class"] == "HARD")
        soft = len(members) - hard
        checks = sum(1 for rule in members if rule["deterministic_check"] != "none")
        lines.append(
            f"  R-{family}-*  {len(members):>2} rules "
            f"({hard} HARD, {soft} SOFT, {checks} with a Tier-0 check)"
        )
    hard_total = sum(1 for rule in rules if rule["class"] == "HARD")
    lines.append(
        f"  total     {len(rules):>2} rules "
        f"({hard_total} HARD, {len(rules) - hard_total} SOFT)"
    )
    return "\n".join(lines)


def describe_staleness(expected: dict[str, object], actual: object) -> list[str]:
    if not isinstance(actual, dict):
        return ["lock file does not contain a JSON object"]

    reasons: list[str] = []
    for key in ("rulebook_version", "rulebook_sha256", "generated_from", "rule_count"):
        if actual.get(key) != expected[key]:
            reasons.append(f"{key}: lock has {actual.get(key)!r}, rulebook gives {expected[key]!r}")

    expected_rules = expected["rules"]
    assert isinstance(expected_rules, list)
    actual_rules = actual.get("rules")
    if not isinstance(actual_rules, list):
        reasons.append("rules: missing or not a list in the lock file")
        return reasons

    expected_by_id = {rule["rule_id"]: rule for rule in expected_rules}
    actual_by_id = {
        rule.get("rule_id"): rule for rule in actual_rules if isinstance(rule, dict)
    }
    for rule_id in sorted(set(expected_by_id) - set(actual_by_id)):
        reasons.append(f"rules: {rule_id} present in the rulebook, absent from the lock")
    for rule_id in sorted(set(actual_by_id) - set(expected_by_id)):
        reasons.append(f"rules: {rule_id} present in the lock, absent from the rulebook")
    for rule_id in sorted(set(expected_by_id) & set(actual_by_id)):
        if expected_by_id[rule_id] != actual_by_id[rule_id]:
            reasons.append(
                f"rules: {rule_id} differs "
                f"(lock {actual_by_id[rule_id]!r} vs rulebook {expected_by_id[rule_id]!r})"
            )

    if not reasons:
        reasons.append("serialised form differs (formatting drift); regenerate the lock")
    return reasons


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Parse AUDIT_RULEBOOK.md and write or verify rulebook.lock.json."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the lock file is current; exit 1 if it is stale (for CI)",
    )
    parser.add_argument(
        "--rulebook",
        type=Path,
        default=here / RULEBOOK_NAME,
        help=f"path to the rulebook markdown (default: ./{RULEBOOK_NAME})",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=here / LOCK_NAME,
        help=f"path to the lock file (default: ./{LOCK_NAME})",
    )
    args = parser.parse_args(argv)

    try:
        lock = build_lock(args.rulebook)
        payload = serialise(lock)
    except StructuralError as exc:
        print(f"ERROR: malformed rulebook: {exc}", file=sys.stderr)
        print("The rulebook was NOT locked.", file=sys.stderr)
        return 2

    if args.check:
        if not args.lock.exists():
            print(f"STALE: {args.lock} does not exist; run lock_rulebook.py", file=sys.stderr)
            return 1
        try:
            existing_text = args.lock.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"STALE: cannot read {args.lock}: {exc}", file=sys.stderr)
            return 1
        if existing_text == payload:
            print(
                f"OK: {args.lock.name} is current "
                f"(rulebook_version {lock['rulebook_version']}, "
                f"{lock['rule_count']} rules, sha256 {lock['rulebook_sha256'][:12]}…)"
            )
            return 0
        try:
            existing = json.loads(existing_text)
        except json.JSONDecodeError as exc:
            print(f"STALE: {args.lock} is not valid JSON: {exc}", file=sys.stderr)
            return 1
        print(f"STALE: {args.lock.name} does not match {args.rulebook.name}:", file=sys.stderr)
        for reason in describe_staleness(lock, existing):
            print(f"  - {reason}", file=sys.stderr)
        print("Run: python3 lock_rulebook.py", file=sys.stderr)
        return 1

    args.lock.write_text(payload, encoding="utf-8")
    print(f"Wrote {args.lock}")
    print(f"  rulebook_version : {lock['rulebook_version']}")
    print(f"  rulebook_sha256  : {lock['rulebook_sha256']}")
    print(f"  rule_count       : {lock['rule_count']}")
    print(summarise(lock))
    return 0


if __name__ == "__main__":
    sys.exit(main())
