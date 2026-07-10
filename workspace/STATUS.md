# STATUS.md | Last updated: 2026-07-10

## M1 Convergence Freeze

- Sole active capability gate: move M1 from `live_failing` to `repeat_verified`.
- Current gate: `G0_RUNTIME_AVAILABLE` is failing.
- Earliest blocker: no controlled Minecraft server on `localhost:25565`; port `3000` is an unrelated Windows service, not a Singularity bridge.
- M2-M7 feature work and research-driven runtime changes are frozen until all five M1 tasks have three distinct verified live successes.
- Ordered gates, fixed protocol, and stop conditions are in `workspace/CONVERGENCE_PLAN.md`; failure-level evidence is in `workspace/evals/m1_failure_ledger.json`.

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
| M1 | Minimum Viable Bot | **Live failing** | BM-001..005 each 0/3; 0/15 required live successes |
| M2 | LLM Task Planning | **Evidence pending** | BM-006..010: no tracked execution evidence |
| M3 | Skill Library & Memory | **Live failing** | 0/37 sessions qualify; no memory reads/writes and 2,601 unbounded context cycles |
| M4 | Autonomous Survival | **Evidence pending** | BM-011..014: no tracked execution evidence |
| M5 | Open-World Exploration | **Live failing** | 0/37 sessions qualify; world-model gate passes, but 0/27 goals completed |
| M6 | Vision & Multimodal | **Live failing** | 0/37 sessions qualify; no verified screenshots or live-source visual-action interventions |
| M7 | Multi-Agent Collaboration | **Evidence pending** | BM-701: no tracked live execution |

Source is present and relevant offline suites pass for M1-M7, but those facts do not change the live statuses above.

## Current Runtime Readiness

- Python, Java, Node.js, npm, and Mineflayer dependencies pass local preflight.
- `localhost:25565` is unavailable; no Minecraft server assets are present in the repository workspace.
- Port `3000` accepts TCP through `svchost.exe`, but fails the Singularity `health` protocol and now correctly fails the `bot_bridge` check.
- Raw current evidence is `logs/benchmarks/m1_preflight_20260710_142227.json`; preflight evidence is explicitly ineligible for live capability counts.
- `scripts/m1-runtime.ps1` provides a controlled one-task startup path on bridge port `30000`, creates a fresh level, records the server jar hash, restores server properties, and never accepts or edits the Minecraft EULA.
- The G1 harness is implemented and offline-tested: canonical reset state, BM-004's five-cobblestone threshold, per-task limits, deterministic runtime isolation, transition evidence, and immutable sessions are enforced. G1 remains live-unverified behind G0.

## Latest Verified Engineering Changes

- Made bridge preflight protocol-aware so an unrelated TCP listener cannot pass as Singularity; bot readiness and requested username/version/MC-port identity remain separate checks.
- Added timestampable JSON preflight evidence marked as non-capability evidence, plus a controlled M1 runtime launcher that never signs the EULA or stops unknown processes.
- Added one shared fixed M1 protocol for tasks, reset fixtures, versions, runtime identities, limits, and exact dependency versions; Node and Python reject protocol drift.
- Added allowlisted reset commands with observed postcondition checks for inventory, spawn, fixture, mode, difficulty, time, weather, health, and food.
- Forced RuleBasedPlanner and isolated memory persistence/context, skills, vision, plan cache, self-evolution, frontier budgets, episode abort, LLM critics, and action candidate selection for M1.
- Hardened action evidence: navigation requires strict tolerance, unreached movement defers dependent actions, dig waits for a bounded pickup observation, and dig/craft require real pre/post block and inventory deltas.
- Hardened capability counting against copied sessions, repeated episodes/log hashes, mixed Paper jar hashes, nested reset records, and unsupported success text.
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

1. Provision Paper 1.20.4 at `mc-server/server.jar`, read and accept the EULA manually, configure seed/offline mode/port, and operator-enable `Singularity`.
2. Run `powershell -ExecutionPolicy Bypass -File scripts/m1-runtime.ps1 -RunBenchmark -TaskId BM-001`.
3. Localize BM-001's first unrecovered live transition and change only that layer.
4. Progress BM-002..005 in dependency order, never overwriting evidence.
5. Collect 15 distinct successes under one Paper jar hash and regenerate capability evidence; only `repeat_verified` reopens later milestones.
