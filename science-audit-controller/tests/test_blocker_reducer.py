from __future__ import annotations

from app.blocker_reducer import reduce_blockers
from app.models import BlockerEvent, blocker_event_sha256


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


def test_fail_closed_error_names_the_canonical_event_hash():
    poison = BlockerEvent(
        event="FINDING_VERIFIED_CLOSED",
        finding_id="F-404",
        project_id="perovskite-screening",
    )

    state = reduce_blockers([poison], "perovskite-screening")

    assert state.errors == [
        f"close without open finding for F-404 (event_sha256={blocker_event_sha256(poison)})"
    ]


def test_quarantined_event_is_skipped_and_cannot_fail_closed():
    opened = BlockerEvent(
        event="FINDING_OPENED",
        finding_id="F-001",
        project_id="perovskite-screening",
        data={"blocking": True},
    )
    poison = BlockerEvent(
        event="FINDING_VERIFIED_CLOSED",
        finding_id="F-404",
        project_id="perovskite-screening",
    )
    events = [opened, poison]

    unquarantined = reduce_blockers(events, "perovskite-screening")
    repaired = reduce_blockers(
        events,
        "perovskite-screening",
        quarantined={blocker_event_sha256(poison)},
    )

    assert unquarantined.fail_closed
    assert not repaired.fail_closed
    assert repaired.errors == []
    assert "F-001" in repaired.active


def test_quarantine_can_remove_an_event_that_carries_no_project_id():
    poison = BlockerEvent(event="FINDING_OPENED", finding_id="F-001")

    unquarantined = reduce_blockers([poison], "perovskite-screening")
    repaired = reduce_blockers(
        [poison],
        "perovskite-screening",
        quarantined=frozenset({blocker_event_sha256(poison)}),
    )

    assert unquarantined.fail_closed
    assert not repaired.fail_closed
    assert repaired.findings == {}
