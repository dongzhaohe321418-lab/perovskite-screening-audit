from __future__ import annotations

from dataclasses import dataclass, field

from app.models import BlockerEvent


@dataclass
class BlockerState:
    findings: dict[str, BlockerEvent] = field(default_factory=dict)
    active: dict[str, BlockerEvent] = field(default_factory=dict)
    fix_commits: dict[str, str] = field(default_factory=dict)
    reaudit_cycles: dict[str, str] = field(default_factory=dict)
    fail_closed: bool = False
    errors: list[str] = field(default_factory=list)


def reduce_blockers(events: list[BlockerEvent], project_id: str | None = None) -> BlockerState:
    state = BlockerState()
    for event in events:
        if project_id and not event.project_id:
            _error(state, f"blocker event lacks project_id for {event.finding_id}")
            continue
        if project_id and event.project_id and event.project_id != project_id:
            continue
        finding_id = event.finding_id
        if event.event == "FINDING_OPENED":
            if finding_id in state.findings:
                _error(state, f"duplicate open event for {finding_id}")
                continue
            state.findings[finding_id] = event
            if event.data.get("blocking", True):
                state.active[finding_id] = event
        elif event.event == "DISPOSITION_RECORDED":
            if finding_id not in state.findings:
                _error(state, f"DISPOSITION_RECORDED without open finding for {finding_id}")
        elif event.event == "FIX_COMMIT_SUBMITTED":
            if finding_id not in state.findings:
                _error(state, f"FIX_COMMIT_SUBMITTED without open finding for {finding_id}")
                continue
            fix_commit = event.data.get("fix_commit")
            if not isinstance(fix_commit, str) or len(fix_commit) != 40:
                _error(state, f"invalid fix commit for {finding_id}")
                continue
            state.fix_commits[finding_id] = fix_commit
        elif event.event == "REAUDIT_STARTED":
            if finding_id not in state.findings:
                _error(state, f"REAUDIT_STARTED without open finding for {finding_id}")
                continue
            fix_commit = event.data.get("fix_commit")
            if state.fix_commits.get(finding_id) != fix_commit:
                _error(state, f"REAUDIT_STARTED does not match submitted fix for {finding_id}")
                continue
            if not event.cycle_id:
                _error(state, f"REAUDIT_STARTED lacks cycle_id for {finding_id}")
                continue
            state.reaudit_cycles[finding_id] = event.cycle_id
        elif event.event == "FINDING_VERIFIED_CLOSED":
            if finding_id not in state.findings:
                _error(state, f"close without open finding for {finding_id}")
                continue
            if state.reaudit_cycles.get(finding_id) != event.cycle_id:
                _error(state, f"close lacks matching re-audit for {finding_id}")
                continue
            if state.fix_commits.get(finding_id) != event.data.get("verified_commit"):
                _error(state, f"close commit does not match submitted fix for {finding_id}")
                continue
            state.findings.pop(finding_id)
            state.active.pop(finding_id, None)
            state.fix_commits.pop(finding_id, None)
            state.reaudit_cycles.pop(finding_id, None)
        else:
            _error(state, f"unknown blocker event: {event.event}")
    return state


def _error(state: BlockerState, message: str) -> None:
    state.fail_closed = True
    state.errors.append(message)
