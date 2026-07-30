from __future__ import annotations

from datetime import datetime, timezone

from app.blocker_reducer import reduce_blockers
from app.models import ActionAuthorization, ActionCheckRequest, ActionCheckResponse
from app.storage import JsonStorage


HIGH_RISK_ACTIONS = {
    "submit_production_job",
    "stop_production_job",
    "publish_claim",
    "change_locked_protocol",
    "exclude_scientific_data",
    "increase_budget",
    "operate_instrument",
}
PERMISSIVE_AUDIT_DECISIONS = {"PASS", "PASS_WITH_CAVEATS"}
ALLOWED_ACTORS = {"claude_science"}
LOW_RISK_ACTIONS = {
    "run_unit_tests",
    "run_local_analysis",
    "read_results",
    "generate_report_draft",
}


class PolicyEngine:
    def __init__(self, storage: JsonStorage, project_ids: set[str] | None = None):
        self.storage = storage
        self.project_ids = project_ids

    def check(self, request: ActionCheckRequest) -> ActionCheckResponse:
        if self.project_ids is not None and request.project_id not in self.project_ids:
            return ActionCheckResponse(decision="DENY", reason_codes=["UNKNOWN_PROJECT"])
        if request.actor not in ALLOWED_ACTORS:
            return ActionCheckResponse(decision="DENY", reason_codes=["ACTOR_NOT_ALLOWED"])

        blocker_state = reduce_blockers(
            self.storage.event_log(),
            project_id=request.project_id,
            quarantined=self.storage.quarantined_event_hashes(request.project_id),
        )
        if blocker_state.fail_closed:
            return ActionCheckResponse(
                decision="DENY",
                reason_codes=["BLOCKER_STATE_INCONSISTENT"],
            )
        if request.action not in HIGH_RISK_ACTIONS:
            if request.action in LOW_RISK_ACTIONS:
                return ActionCheckResponse(decision="ALLOW", reason_codes=[])
            return ActionCheckResponse(decision="DENY", reason_codes=["UNKNOWN_ACTION"])

        reasons: list[str] = []
        matching_blockers = [
            finding_id
            for finding_id, event in blocker_state.active.items()
            if self._scope_matches(event.blocked_scopes, request.action)
        ]
        reasons.extend(
            f"ACTIVE_BLOCKER_{finding_id}" for finding_id in sorted(matching_blockers)
        )

        cycle = self.storage.final_cycle_for_commit(request.project_id, request.science_commit)
        if not cycle:
            reasons.append("NO_FINAL_AUDIT_FOR_COMMIT")
        else:
            if cycle.evidence_manifest_sha256.lower() != request.manifest_sha256.lower():
                reasons.append("MANIFEST_MISMATCH")
            decision = (cycle.audit_result or {}).get("decision")
            if decision not in PERMISSIVE_AUDIT_DECISIONS:
                reasons.append("AUDIT_DECISION_NOT_PERMISSIVE")

        authorization = self._matching_authorization(request)
        if not authorization:
            reasons.extend(
                [
                    "POLICY_APPROVAL_REQUIRED",
                    "BUDGET_APPROVAL_REQUIRED",
                    "PI_APPROVAL_REQUIRED",
                ]
            )
        else:
            if not authorization.policy_approved:
                reasons.append("POLICY_APPROVAL_REQUIRED")
            if not authorization.budget_approved:
                reasons.append("BUDGET_APPROVAL_REQUIRED")
            if not authorization.pi_approved:
                reasons.append("PI_APPROVAL_REQUIRED")

        if reasons:
            return ActionCheckResponse(
                decision="DENY",
                reason_codes=list(dict.fromkeys(reasons)),
            )
        return ActionCheckResponse(decision="ALLOW", reason_codes=[])

    def _matching_authorization(
        self,
        request: ActionCheckRequest,
    ) -> ActionAuthorization | None:
        now = datetime.now(timezone.utc)
        matches: list[ActionAuthorization] = []
        for authorization in self.storage.authorizations(request.project_id):
            try:
                expires_at = datetime.fromisoformat(authorization.expires_at)
            except ValueError:
                continue
            if expires_at.tzinfo is None or expires_at <= now:
                continue
            if (
                authorization.actor == request.actor
                and authorization.action == request.action
                and authorization.science_commit == request.science_commit.lower()
                and authorization.manifest_sha256 == request.manifest_sha256.lower()
            ):
                matches.append(authorization)
        return max(matches, key=lambda item: item.created_at) if matches else None

    @staticmethod
    def _scope_matches(scopes: list[str], action: str) -> bool:
        if not scopes or "*" in scopes or action in scopes:
            return True
        if "production" in scopes and action in {
            "submit_production_job",
            "stop_production_job",
            "operate_instrument",
        }:
            return True
        return False
