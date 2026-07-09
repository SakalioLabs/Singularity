# STATUS.md | Last updated: 2026-07-10

## Evidence Policy

Capability status is derived from `workspace/evals/capability_evidence_current.json`.

- `source present`: implementation files exist; this is not runtime evidence.
- `offline passing`: deterministic/unit tests pass; this is not Minecraft capability evidence.
- `live observed`: every required benchmark has at least one successful in-world execution.
- `repeat verified`: every required benchmark has at least three distinct successful executions.
- M1-M7 completion claims require `repeat verified` evidence. M0 is a research deliverable and can be source-verified.

## Phase Evidence

| Phase | Name | Status | Progress |
|-------|------|--------|----------|
| M0 | Research Baseline | **Complete (source verified)** | Research deliverables present |
| M1 | Minimum Viable Bot | **Live failing** | BM-001..005: 0/5 successful in latest tracked run |
| M2 | LLM Task Planning | **Evidence pending** | BM-006..010: no tracked execution evidence |
| M3 | Skill Library & Memory | **Live failing** | 0/37 sessions qualify; no memory reads/writes and 2,601 unbounded context cycles |
| M4 | Autonomous Survival | **Evidence pending** | BM-011..014: no tracked execution evidence |
| M5 | Open-World Exploration | **Live failing** | 0/37 sessions qualify; world-model gate passes, but 0/27 goals completed |
| M6 | Vision & Multimodal | **Live failing** | 0/37 sessions qualify; no verified screenshots or live-source visual-action interventions |
| M7 | Multi-Agent Collaboration | **Evidence pending** | BM-701: no tracked live execution |

Source is present and relevant offline suites pass for M1-M7, but those facts do not change the live statuses above.

## Current Runtime Readiness

- Python, Node.js, npm, and Mineflayer dependencies pass local preflight.
- `localhost:25565` is unavailable; no Minecraft server assets are present in the repository workspace.
- Port `3000` is reachable, but the existing bridge returns an empty `health` response.
- Ports `3001` and `3002` required for the current M7 role plan are not running.

## Latest Verified Engineering Changes

- Added task-readiness recovery that turns inventory blockers into concrete prerequisite goals.
- Preserved critical health, nearby-hostile, and night-survival goals ahead of scheduled work.
- Added knowledge-backed tool checks and grounded-coordinate checks to generic mining fallback.
- Added `capability-evidence-report` to reject unsupported M0-M7 completion claims from benchmark and runtime evidence.
- Added machine-checkable M3/M5/M6 adapters with distinct-session counting and independent mechanism gates.
- Generated tracked M3/M5/M6 evidence from all 37 existing sessions instead of treating missing reports as missing runs.
- Added strict typed planning-memory budgets for both rule and LLM planning, including separator-aware packet accounting and explicit rejection when the runtime contract is disabled.
- Added machine-checkable autonomous observation/plan/subgoal events and prevented queued tasks from silently retargeting an already generated plan.
- Added schema-v2 task execution-state lineage with active-path retrieval, failed-branch isolation, terminal `compress` checkpoints, validation evidence, and review-only revision proposals.

## Next Acceptance Work

1. Provision a Minecraft 1.20.4 test server after explicit EULA acceptance and restart the bridge.
2. Re-run BM-001..005, diagnose failures, and collect three successful runs per task.
3. Run BM-006..010 only after M1 is live-observed.
4. Re-run M3/M5 with the new bounded-memory and autonomous subgoal events; re-run M6 after screenshot capture and visual-action interventions are available.
5. Start distinct M7 role bridges and run BM-701 against the single-agent baseline.
6. Keep task-continuity restoration disabled until a memory-isolated ablation and world-state reachability verifier approve it.
