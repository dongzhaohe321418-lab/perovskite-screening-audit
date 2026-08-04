#!/bin/bash
# Drain one orchestrator pass. Safe to call on any interval: the pass takes an
# flock, so overlapping ticks exit immediately rather than double-dispatching,
# and the per-hour rate limit still bounds how many audits actually run.
cd /Users/ericdong/Desktop/perovskite-project/audit-loop
exec ./.venv/bin/python orchestrator/orchestrator.py process
