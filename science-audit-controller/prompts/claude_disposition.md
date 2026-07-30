# Claude Science Disposition Template

Read the full audit report and audit result JSON supplied by the Controller. Return the exact hash in `report_sha256` and set `report_sha256_confirmed` to true only after confirming it.

Return one disposition per finding. Allowed dispositions are `ACCEPT_AND_FIX`, `ACCEPT_AND_STOP`, `DISAGREE_WITH_EVIDENCE`, `NEED_PI_DECISION`, `DEFER_WITH_CAVEAT`, and `PASS_NO_ACTION`.

Never respond “all fixed” without per-finding dispositions. Never mark a finding as closed. If claiming a fix, provide a new full Science Commit SHA.
