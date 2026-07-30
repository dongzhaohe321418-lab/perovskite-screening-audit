from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.models import (
    ActionAuthorization,
    BlockerEvent,
    BlockerEventQuarantine,
    BlockerEventRecord,
    Cycle,
    CycleStatus,
    DispositionStatus,
    blocker_event_sha256,
    utc_now,
)


class ImmutableCycleError(RuntimeError):
    pass


class DuplicateDispositionError(RuntimeError):
    pass


class AuditHeadConflict(RuntimeError):
    pass


class JsonStorage:
    """Atomic JSON storage suitable for a single host with multiple workers."""

    FINAL_FIELDS = {
        "audit_repo_commit",
        "audit_report_sha256",
        "audit_report_id",
        "audit_result",
        "parent_report_sha256",
    }

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("CONTROLLER_STATE_PATH", "./data/state.json"))
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self._thread_lock = threading.RLock()
        self.delivery_lease_seconds = int(os.getenv("DELIVERY_LEASE_SECONDS", "300"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.touch(exist_ok=True)
        with self._locked_state() as state:
            self._normalize_state(state)

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "deliveries": {},
            "cycles": {},
            "idempotency": {},
            "next_cycle_number": 1,
            "codex_tasks": {},
            "claude_tasks": {},
            "event_log": [],
            "dispositions": {},
            "authorizations": [],
            "quarantined_events": [],
            "audit_heads": {},
        }

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        with self.path.open("r", encoding="utf-8") as fh:
            state = json.load(fh)
        if not isinstance(state, dict):
            raise RuntimeError("controller state must be a JSON object")
        return state

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.path)

    def _normalize_state(self, state: dict[str, Any]) -> None:
        changed = False
        defaults = self._default_state()
        for key, value in defaults.items():
            if key not in state:
                state[key] = value
                changed = True
        for delivery_id in state.pop("delivery_ids", []):
            state["deliveries"].setdefault(
                delivery_id,
                {"status": "COMPLETED", "attempts": 1, "completed_at": utc_now()},
            )
            changed = True
        if changed or not self.path.exists():
            self._write_unlocked(state)

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        with self._thread_lock:
            with self.lock_path.open("r+") as lock_fh:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
                try:
                    state = self._read_unlocked()
                    yield state
                finally:
                    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    def claim_delivery(self, delivery_id: str) -> str:
        """Atomically claim a delivery, returning CLAIMED, PROCESSING, or COMPLETED."""

        with self._locked_state() as state:
            now = datetime.now(timezone.utc)
            existing = state["deliveries"].get(delivery_id)
            if existing and existing.get("status") == "COMPLETED":
                return "COMPLETED"
            if existing and existing.get("status") == "PROCESSING":
                started_at = datetime.fromisoformat(existing["started_at"])
                if now - started_at < timedelta(seconds=self.delivery_lease_seconds):
                    return "PROCESSING"
            attempts = int((existing or {}).get("attempts", 0)) + 1
            state["deliveries"][delivery_id] = {
                "status": "PROCESSING",
                "attempts": attempts,
                "started_at": now.isoformat(),
            }
            self._write_unlocked(state)
            return "CLAIMED"

    def complete_delivery(self, delivery_id: str, response: dict[str, Any]) -> None:
        with self._locked_state() as state:
            delivery = state["deliveries"].get(delivery_id)
            if not delivery or delivery.get("status") != "PROCESSING":
                raise RuntimeError(f"delivery is not processing: {delivery_id}")
            delivery.update({"status": "COMPLETED", "completed_at": utc_now(), "response": response})
            self._write_unlocked(state)

    def fail_delivery(self, delivery_id: str, error: str) -> None:
        with self._locked_state() as state:
            delivery = state["deliveries"].get(delivery_id)
            if not delivery:
                return
            delivery.update({"status": "FAILED", "failed_at": utc_now(), "error": error[:1000]})
            self._write_unlocked(state)

    def delivery(self, delivery_id: str) -> dict[str, Any] | None:
        with self._locked_state() as state:
            value = state["deliveries"].get(delivery_id)
            return dict(value) if value else None

    def create_or_get_cycle(self, payload: dict[str, Any]) -> tuple[Cycle, bool]:
        with self._locked_state() as state:
            key = payload["idempotency_key"]
            existing_id = state["idempotency"].get(key)
            if existing_id:
                return Cycle(**state["cycles"][existing_id]), False

            number = state["next_cycle_number"]
            cycle_id = f"CYCLE-{number:06d}"
            state["next_cycle_number"] = number + 1
            cycle = Cycle(cycle_id=cycle_id, **payload)
            state["cycles"][cycle_id] = cycle.model_dump(mode="json")
            state["idempotency"][key] = cycle_id
            self._write_unlocked(state)
            return cycle, True

    def update_cycle(self, cycle_id: str, **updates: Any) -> Cycle:
        with self._locked_state() as state:
            if cycle_id not in state["cycles"]:
                raise KeyError(f"unknown cycle: {cycle_id}")
            current = state["cycles"][cycle_id]
            if current.get("status") == CycleStatus.FINAL.value:
                protected = self.FINAL_FIELDS.intersection(updates)
                status = updates.get("status")
                if protected or (status is not None and status not in {CycleStatus.FINAL, CycleStatus.FINAL.value}):
                    raise ImmutableCycleError(f"cycle {cycle_id} has immutable FINAL audit state")
            current.update(updates)
            current["updated_at"] = utc_now()
            state["cycles"][cycle_id] = Cycle(**current).model_dump(mode="json")
            self._write_unlocked(state)
            return Cycle(**state["cycles"][cycle_id])

    def mark_audit_invalid(self, cycle_id: str) -> Cycle:
        cycle = self.get_cycle(cycle_id)
        if not cycle:
            raise KeyError(f"unknown cycle: {cycle_id}")
        if cycle.status == CycleStatus.FINAL:
            raise ImmutableCycleError(f"cycle {cycle_id} has immutable FINAL audit state")
        return self.update_cycle(cycle_id, status=CycleStatus.AUDIT_OUTPUT_INVALID)

    def finalize_cycle(
        self,
        cycle_id: str,
        *,
        audit_repo_commit: str,
        audit_report_sha256: str,
        audit_report_id: str,
        audit_result: dict[str, Any],
        events: list[BlockerEvent] | None = None,
        expected_audit_head: str,
    ) -> tuple[Cycle, bool]:
        with self._locked_state() as state:
            if cycle_id not in state["cycles"]:
                raise KeyError(f"unknown cycle: {cycle_id}")
            current = state["cycles"][cycle_id]
            previous = [
                Cycle(**value)
                for value in state["cycles"].values()
                if value.get("project_id") == current["project_id"]
                and value.get("status") == CycleStatus.FINAL.value
                and value.get("cycle_id") != cycle_id
            ]
            previous.sort(key=lambda item: item.cycle_id)
            proposed = {
                "audit_repo_commit": audit_repo_commit,
                "audit_report_sha256": audit_report_sha256,
                "audit_report_id": audit_report_id,
                "audit_result": audit_result,
                "parent_report_sha256": previous[-1].audit_report_sha256 if previous else None,
            }
            if current.get("status") == CycleStatus.FINAL.value:
                if all(current.get(key) == value for key, value in proposed.items()):
                    return Cycle(**current), False
                raise ImmutableCycleError(f"cycle {cycle_id} has immutable FINAL audit state")
            if current.get("status") not in {
                CycleStatus.CODEX_TASK_CREATED.value,
                CycleStatus.AUDIT_OUTPUT_INVALID.value,
            }:
                raise RuntimeError(
                    f"cycle {cycle_id} is not eligible for audit finalization from "
                    f"{current.get('status')}"
                )
            if not current.get("audit_request"):
                raise RuntimeError(f"cycle {cycle_id} has no validated audit request")
            trusted_head = state["audit_heads"].get(current["project_id"])
            if trusted_head != expected_audit_head:
                raise AuditHeadConflict(
                    f"audit head advanced from {expected_audit_head} to {trusted_head}"
                )
            current.update(proposed)
            current["status"] = CycleStatus.FINAL.value
            current["updated_at"] = utc_now()
            state["cycles"][cycle_id] = Cycle(**current).model_dump(mode="json")
            self._append_events_unlocked(state, events or [])
            state["audit_heads"][current["project_id"]] = audit_repo_commit
            self._write_unlocked(state)
            return Cycle(**state["cycles"][cycle_id]), True

    def ensure_audit_head(self, project_id: str, initial_head: str) -> str:
        with self._locked_state() as state:
            existing = state["audit_heads"].get(project_id)
            if existing is not None:
                return existing
            state["audit_heads"][project_id] = initial_head
            self._write_unlocked(state)
            return initial_head

    def audit_head(self, project_id: str) -> str | None:
        with self._locked_state() as state:
            return state["audit_heads"].get(project_id)

    def get_cycle(self, cycle_id: str) -> Cycle | None:
        with self._locked_state() as state:
            data = state["cycles"].get(cycle_id)
            return Cycle(**data) if data else None

    def list_cycles(self, project_id: str | None = None) -> list[Cycle]:
        with self._locked_state() as state:
            cycles = [Cycle(**item) for item in state["cycles"].values()]
        if project_id:
            cycles = [cycle for cycle in cycles if cycle.project_id == project_id]
        return sorted(cycles, key=lambda item: item.cycle_id)

    def final_cycle_for_commit(self, project_id: str, science_commit: str) -> Cycle | None:
        matches = [
            cycle
            for cycle in self.list_cycles(project_id)
            if cycle.science_commit == science_commit and cycle.status == CycleStatus.FINAL
        ]
        return matches[-1] if matches else None

    def open_cycle_for_commit(self, project_id: str, science_commit: str) -> Cycle | None:
        """The still-auditable cycle at a commit, if any.

        A fix commit usually already has its own cycle by the time the
        disposition naming it is submitted, because the push that created the
        commit triggered one. That cycle is the re-audit for the finding.
        """
        matches = [
            cycle
            for cycle in self.list_cycles(project_id)
            if cycle.science_commit == science_commit
            and cycle.status in {CycleStatus.CREATED, CycleStatus.CODEX_TASK_CREATED,
                                 CycleStatus.AUDIT_OUTPUT_INVALID}
        ]
        return matches[-1] if matches else None

    def store_codex_task(self, cycle_id: str, prompt: str) -> None:
        with self._locked_state() as state:
            state["codex_tasks"].setdefault(
                cycle_id,
                {"prompt": prompt, "created_at": utc_now()},
            )
            self._write_unlocked(state)

    def store_claude_task(self, cycle_id: str, prompt: str) -> None:
        with self._locked_state() as state:
            state["claude_tasks"].setdefault(
                cycle_id,
                {"prompt": prompt, "created_at": utc_now()},
            )
            state["cycles"][cycle_id]["disposition_status"] = DispositionStatus.TASK_CREATED.value
            state["cycles"][cycle_id]["updated_at"] = utc_now()
            self._write_unlocked(state)

    def append_event(self, event: BlockerEvent) -> None:
        self.append_events([event])

    def append_events(self, events: list[BlockerEvent]) -> None:
        with self._locked_state() as state:
            self._append_events_unlocked(state, events)
            self._write_unlocked(state)

    @staticmethod
    def _append_events_unlocked(state: dict[str, Any], events: list[BlockerEvent]) -> None:
        for event in events:
            payload = event.model_dump(mode="json")
            identity = {
                key: payload.get(key)
                for key in ("event", "finding_id", "project_id", "cycle_id", "blocked_scopes", "data")
            }
            if any(
                all(existing.get(key) == value for key, value in identity.items())
                for existing in state["event_log"]
            ):
                continue
            state["event_log"].append(payload)

    def event_log(self) -> list[BlockerEvent]:
        with self._locked_state() as state:
            return [BlockerEvent(**item) for item in state["event_log"]]

    def event_records(self, project_id: str | None = None) -> list[BlockerEventRecord]:
        """Every appended event with its canonical hash and append-order index.

        A project filter keeps events that carry no project_id, because those
        are exactly the events that fail the project's fold and whose hashes an
        operator therefore needs to read.
        """

        records = [
            BlockerEventRecord(
                index=index,
                event_sha256=blocker_event_sha256(event),
                event=event,
            )
            for index, event in enumerate(self.event_log())
        ]
        if project_id:
            records = [
                record
                for record in records
                if record.event.project_id in {None, project_id}
            ]
        return records

    def record_disposition(
        self,
        cycle_id: str,
        disposition: dict[str, Any],
        events: list[BlockerEvent],
    ) -> None:
        with self._locked_state() as state:
            if cycle_id in state["dispositions"]:
                raise DuplicateDispositionError(f"disposition already recorded for {cycle_id}")
            state["dispositions"][cycle_id] = disposition
            cycle = state["cycles"][cycle_id]
            cycle["disposition_status"] = DispositionStatus.RECORDED.value
            cycle["updated_at"] = utc_now()
            self._append_events_unlocked(state, events)
            self._write_unlocked(state)

    def mark_disposition_invalid(self, cycle_id: str) -> None:
        with self._locked_state() as state:
            cycle = state["cycles"][cycle_id]
            if cycle.get("disposition_status") != DispositionStatus.RECORDED.value:
                cycle["disposition_status"] = DispositionStatus.INVALID.value
                cycle["updated_at"] = utc_now()
                self._write_unlocked(state)

    def get_disposition(self, cycle_id: str) -> dict[str, Any] | None:
        with self._locked_state() as state:
            value = state["dispositions"].get(cycle_id)
            return dict(value) if value else None

    def add_authorization(self, authorization: ActionAuthorization) -> None:
        with self._locked_state() as state:
            if any(
                item["authorization_id"] == authorization.authorization_id
                for item in state["authorizations"]
            ):
                raise ValueError(f"duplicate authorization_id: {authorization.authorization_id}")
            state["authorizations"].append(authorization.model_dump(mode="json"))
            self._write_unlocked(state)

    def authorizations(self, project_id: str | None = None) -> list[ActionAuthorization]:
        with self._locked_state() as state:
            items = [ActionAuthorization(**item) for item in state["authorizations"]]
        if project_id:
            items = [item for item in items if item.project_id == project_id]
        return items

    def add_quarantine(self, quarantine: BlockerEventQuarantine) -> bool:
        """Append a quarantine record, returning whether it was new.

        Quarantine is append-only and never removes an event from event_log.
        Re-quarantining the same hash for the same project is a no-op.
        """

        with self._locked_state() as state:
            if any(
                item["project_id"] == quarantine.project_id
                and item["event_sha256"] == quarantine.event_sha256
                for item in state["quarantined_events"]
            ):
                return False
            state["quarantined_events"].append(quarantine.model_dump(mode="json"))
            self._write_unlocked(state)
            return True

    def quarantines(self, project_id: str | None = None) -> list[BlockerEventQuarantine]:
        with self._locked_state() as state:
            items = [BlockerEventQuarantine(**item) for item in state["quarantined_events"]]
        if project_id:
            items = [item for item in items if item.project_id == project_id]
        return items

    def quarantined_event_hashes(self, project_id: str | None = None) -> frozenset[str]:
        return frozenset(item.event_sha256 for item in self.quarantines(project_id))
