from __future__ import annotations

from app.blocker_reducer import reduce_blockers
from app.models import BlockerEvent


def test_blocker_reducer_derives_verified_closed_state():
    fix_commit = "a" * 40
    events = [
        BlockerEvent(
            event="FINDING_OPENED",
            finding_id="F-001",
            project_id="perovskite-screening",
            data={"blocking": True},
        ),
        BlockerEvent(
            event="FIX_COMMIT_SUBMITTED",
            finding_id="F-001",
            project_id="perovskite-screening",
            data={"fix_commit": fix_commit},
        ),
        BlockerEvent(
            event="REAUDIT_STARTED",
            finding_id="F-001",
            project_id="perovskite-screening",
            cycle_id="CYCLE-000002",
            data={"fix_commit": fix_commit},
        ),
        BlockerEvent(
            event="FINDING_VERIFIED_CLOSED",
            finding_id="F-001",
            project_id="perovskite-screening",
            cycle_id="CYCLE-000002",
            data={"verified_commit": fix_commit},
        ),
    ]

    state = reduce_blockers(events, "perovskite-screening")

    assert not state.fail_closed
    assert state.active == {}
    assert state.findings == {}


def test_nonblocking_finding_is_tracked_but_not_a_policy_blocker():
    event = BlockerEvent(
        event="FINDING_OPENED",
        finding_id="F-INFO",
        project_id="perovskite-screening",
        data={"blocking": False},
    )

    state = reduce_blockers([event], "perovskite-screening")

    assert "F-INFO" in state.findings
    assert "F-INFO" not in state.active


def test_blocker_reducer_fails_closed_on_inconsistent_state():
    state = reduce_blockers(
        [
            BlockerEvent(
                event="FINDING_VERIFIED_CLOSED",
                finding_id="F-404",
                project_id="perovskite-screening",
            )
        ],
        "perovskite-screening",
    )

    assert state.fail_closed
