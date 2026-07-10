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
- Added fixed-control task-lineage ablation, critical-player-state shadow validation, and a live-evidence gate that can authorize only shadow revision selection. Built-in fixtures remain review-only and `automatic_restore_allowed` is always false.
- Added a Goal Frontier Capsule for planner-facing task continuity. It preserves active leaf/path identifiers, goal prerequisites, missing preconditions, and continuation actions under a declared character budget; runtime logs identify the capsule profile without recording raw memory text.
- Added task-frontier skill routing with a legacy baseline switch, governance filtering, prerequisite/target-state scoring, bounded reason-coded planner context, and a 3-case fixed-control ablation. The built-in 3/3 result remains offline-only.
- Added Blind-Curator-style skill retirement audits: per-judge defect-injection calibration, fixed-control no-skill contribution reports, and a live-evidence gate. Approved candidates become task-family-scoped in-memory exclusions only; built-ins remain usable, skill files are untouched, and automatic deletion is prohibited.
- Upgraded plan caching to `progressive_workflow_crystallization_v1`: offline transitions are bounded hybrid planner hints, while direct deterministic reuse requires entry-scoped matched success across three distinct live sessions by default. Action, goal, or verifier regressions demote only the affected entry to agentic execution.
- Added `behavior_surface_v1` recall-controlled episode viability. It uses exact per-round Clopper-Pearson calibration, disjoint calibration/validation/test splits, held-out global-recall certificates, and fixed runtime provenance. It is off by default and has no approved live Minecraft gate.
- Added `frontier_information_budget_v1` and a uniform fixed-control baseline. Curriculum/task-frontier branches now receive a conserved integer planner-round slate with explicit remaining-round intervals; paired raw session logs, exact allocation replay, outcome non-regression, and an interval-coverage certificate are required before advisory planner context. Built-ins remain shadow-only, and automatic retry, branch execution, and budget extension are forbidden.
- Added `critical-transition-report` with action and planner-response Transition Units, guarded Minecraft execution constraints, temporal/plan/artifact/target/error dependencies, first-unrecovered localization, compact evidence packets, and review-only typed Repair Memory candidates. Synthetic localization is 5/5; historical M1 diagnoses remain unlabeled and cannot affect runtime.
- Replaced the bridge's fixed-duration false-success `move_to` with Mineflayer pathfinder goals plus final-distance verification. Missing Y values remain horizontal, pathfinder controls are forwarded, and unreached partial navigation forces replanning before the actor can execute a dependent plan suffix.

## Next Acceptance Work

1. Provision a Minecraft 1.20.4 test server after explicit EULA acceptance and restart the bridge.
2. Re-run BM-001..005, verify every successful `move_to` has `reached=true`, confirm no dependent world action follows an unreached navigation result, compare critical-transition diagnoses, and collect three successful runs per task.
3. Run BM-006..010 only after M1 is live-observed.
4. Re-run M3/M5 with the new bounded-memory and autonomous subgoal events; re-run M6 after screenshot capture and visual-action interventions are available.
5. Start distinct M7 role bridges and run BM-701 against the single-agent baseline.
6. Run lineage ablation and shadow restoration reports on fresh fixed-control M1/M3/M5 sessions; verify capsule profile, probe retention, token/latency savings, and three distinct candidate sessions before shadow selection review, while keeping automatic restoration disabled.
7. Compare frontier skill routing against `--no-skill-frontier-routing` on fresh M1/M2 task streams, measuring task completion, environment steps, verifier rejects, token cost, and latency before treating the synthetic top-1 gain as operational evidence.
8. Collect live defect-injection calibration and paired no-skill contribution traces across at least three distinct candidate sessions before loading any `--skill-retirement-gate`; the built-in fixtures remain runtime-ineligible.
9. Run hybrid plan-cache guidance on fresh M1/M2 sessions, collect three exact matched successes per candidate entry, and compare planner calls, token cost, actions, completion, and verifier outcomes before any deterministic promotion.
10. Collect disjoint fixed-control M1/M2 calibration, validation, and test trajectories; run episode viability in shadow mode first, and keep active abort disabled until held-out recall is certified and failed-episode planner-round savings are positive.
11. Run matched uniform and information frontier-budget shadow sessions on the same M1/M2 task stream. Collect at least 12 successful candidate interval observations across distinct paired sessions before generating an advisory gate; keep branch execution and retries manual even after approval.
12. Manually label critical units and categories on fresh baseline/candidate M1 failures, compare exact/within-one/category accuracy plus repair outcomes, and keep Repair Memory outside planner context until a separate gate exists.
