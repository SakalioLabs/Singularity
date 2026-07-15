# PROGRESS.md -- Evidence-Backed Progress

## Convergence Result

M1, M2, and M3 are `repeat_verified`. M1 has 15 distinct state-grounded benchmark successes. M2 has 23 eligible current-protocol successes across BM-006..010, including 3/3 accepted pairs for both composite tasks. M3 has three distinct raw-log-verified later-session retrieval/outcome pairs plus an approved held-out transfer gate. M4 is `failing`: BM-011 is repeat_verified at 3/3, BM-012 has twenty-two failed live attempts and remains 0/3, and BM-013..014 remain unverified. See `workspace/evals/capability_evidence_current.json` for the canonical state.

## Current Assessment

Singularity has broad source coverage and a large passing offline test surface, but the full Minecraft Agent system is not complete. The authoritative capability report is `workspace/evals/capability_evidence_current.json`.

Official Paper 1.20.4 build 499 is hash-pinned and all counted runs use hash-verified protocol identities. M1 remains complete at 15/15, M2 contributes 23 eligible current-protocol successes, and M4 now contributes three independently eligible BM-011 episodes with unique session, episode, level, and session hashes. The overall system remains incomplete.

BM-012 remains 0/3 after twenty-two attempts. Probe 22 ran exactly once from frozen committed and pushed gate commit `fa7bb5c`. The Agent started 24 goals, completed 22 and failed two across 85 cycles; it executed 20/31 actions successfully and made 85 real Planner calls with 84 schema-valid responses and 289928 total tokens. It stopped at `max_goals_or_stopped` after 326.329 seconds, stayed inside the absolute deadline, passed 68/74 eligibility checks, and acquired no iron.

The readiness-recovery inventory-family intervention was not exercised. Probe 22 emitted zero `m4_readiness_recovery_completion_propagation`, zero `m4_readiness_recovery_stale_sibling_sweep`, and zero `m4_readiness_recovery_planner_context` events. No inventory-family recovery child, bound root, requirement fingerprint, inventory proof, root latency, idempotency count, or stale-sibling before/after count exists for this run. The Probe 21 exact-oak/root disconnect did not recur, there was no post-satisfaction `Currently have 0 oak_log` reasoning, and no duplicate oak-recovery chain appeared; those absences do not validate the unexercised branch.

Independent review overrides Runner event 593. Its `place_replan_rejected_reference_repeated` empty plan failed the coal goal, but event 775 later placed a crafting table and event 855 machine-crafted `wooden_pickaxe:1`.

The new earliest failure layer is `m4_readiness_recovery_failed_dependency_machine_state_disconnect`. Task `ac997fe4` (`Craft wooden pickaxe`) was created at event 230, activated at event 287, and failed on task deadline at event 548. Dependent task `4cbefa6a` (`Mine coal ore`) remained accepted and depended on that failed title. After event 855 created the wooden pickaxe, events 863-872 machine-completed ten equivalent accepted pickaxe tasks and reconciliation event 873 confirmed the inventory state, but `ac997fe4` remained failed and `4cbefa6a` remained blocked.

Event 1326 then began 21 readiness-recovery selections of the already satisfied `Craft wooden pickaxe` dependency. Every selection had empty child/root/fingerprint fields, and goals 4 through 24 completed generically in one cycle without releasing the coal task. No stone-pickaxe, iron approach, iron dig, pickup, or positive iron delta followed. Five task-deadline interrupts all recovered and are not the terminal blocker.

The required decision enum is recorded as `infrastructure_ineligible` because it has no inconclusive or intervention-not-exercised value. This is causal-test ineligibility, not a preflight failure: preflight, reset, fixed controls, protocol identity, runtime health, and deadline checks passed. The immutable source report is now accompanied by `workspace/evals/m4_probe22_derived_audit.json`, which marks that choice as a taxonomy limitation and adds the prospective value `intervention_not_exercised_new_blocker`. The annotation grants no capability upgrade.

The bounded `m4-failed-dependency-machine-state-reconciliation-v1` repair passes offline. A failed or blocked direct dependency is reconciled only from a structured, machine-verifiable inventory postcondition on the active frontier. Exact item matching is the default; family aggregation requires an explicit trusted internal contract. The reconciliation preserves the previous terminal status, original failure reason/result/transition, attempts, blockers, and observations while adding proof, observation identity, requirement fingerprint, state generation, timestamp, and a deterministic event ID.

The scheduler no longer returns a terminal failed task title directly. An unmet requirement can create only one active bounded recovery child per fingerprint, with a new task ID, parent/root provenance, and a three-attempt budget. Existing root-completion binding is reused after successful reconciliation, and full reconciliation runs after every M4 post-action machine observation. Probe 22 consumed its sole authorization at `autonomous_start` monotonic 78162.171 (`2026-07-14T11:53:37.544782Z`). No Probe 23, live retry, or second episode ran; next authorization is false, BM-012 remains 0/3, M4 remains `failing`, and BM-013/BM-014 remain locked.

Validation passes across seven new gate cases, 106 Memory/TaskSystem definitions, 47 M4 deadline definitions, all 751 definitions in 37 non-live Python scripts, six fixed Node suites with 52 internal assertions, Python compilation, Node syntax, 1065 JSON files, GoalVerifier, capability consistency, credential scan, and repository checks. M1, M2, and M3 remain `repeat_verified`.

Current report outcome:

- Readiness: `rejected`
- Claim audit: `approved`
- System status: `incomplete`
- Declared-complete phases audited: 4 (M0, M1, M2, M3)
- Supported completion claims: 4 (M0, M1, M2, M3)
- Contradicted completion claims: 0 after status correction
- Unsupported completion claims: 0 after status correction
- Partial live phases: 0
- Failing live phases: 3 (M4, M5, M6)
- Repeat-verified runtime phases: 3 (M1, M2, M3)

## Canonical Capability State

| Phase | Canonical status |
|---|---|
| M0 | `source_verified` |
| M1 | `repeat_verified` |
| M2 | `repeat_verified` |
| M3 | `repeat_verified` |
| M4 | `failing` |
| M5 | `failing` |
| M6 | `failing` |
| M7 | `not_run` |

## M2 Convergence Progress

- Phase 2 protocol construction is complete: `m2-fixed-v1` covers BM-006..010 with the pinned compatible endpoint and `deepseek-v4-flash`, structured root/continuation/replan calls, dependency-bearing subtasks, independent world-state verification, and strict evidence eligibility.
- Phase 3 live convergence is complete: BM-006 and BM-007 each have three eligible baseline/candidate pairs, BM-008..010 each have three independent eligible successes, and the canonical recovery gate accepts two sessions.
- A real Paper BM-010 empty-execution smoke passed reset/observation checks and was correctly rejected by the terminal verifier. A second real Paper smoke executed the bounded template, placed 55 blocks, and passed the exact 5x5 shelter verifier.
- Those smoke reports are deliberately non-capability evidence. They establish harness readiness but contain no LLM Root Plan and do not count toward M2.
- A real API preflight returned valid JSON plus complete token usage, and two controlled BM-006 baselines reached the live planner. The first exposed three noncanonical dig parameter shapes; the typed dig contract then removed that failure in the next run.
- The latest run advanced from 0 actions accepted beyond navigation to two successful digs, four dark-oak planks, one valid Root Plan, and two complete task paths. It still produced no crafting table and remains ineligible.
- M2 action feedback now captures the pre-action task before a consumptive post-state can invalidate its input precondition; the exact one-log-to-four-planks lifecycle regression passes offline. A live rerun hit a transient Root Plan connection error before exercising the path.
- A subsequent live rerun produced a valid Root Plan and two successful grounded digs, but no craft. The continuation prompt exposed `required_action_types` without exposing the already successful dig, so the planner redundantly dug a second log before a malformed third response ended the run.
- Added `m2-successful-action-summary-v1`: at most eight successful current-goal actions, typed targets/positions/inventory deltas, and a 1600-character hard bound are injected separately from memory and copied into planner-call evidence.
- The next live run proved the intervention: after one dig, continuation selected plank craft; after that craft, continuation selected crafting table and explicitly recognized that required dig/craft action types were already satisfied. No redundant dig occurred, and `craft_planks` completed.
- The run lasted 317.71 seconds despite BM-006's fixed 240-second limit. In-flight planner requests crossed the deadline, and actions were still executed at elapsed 245.14 and 319.92 seconds.
- Added `m2-hard-total-deadline-v1`: planner requests receive only remaining goal time minus a 30-second action window, use zero provider retries, and are rejected if they return after that window. Agent checks suppress late plans/actions, and both the session validator and canonical log adapter reject an exceeded duration, a deadline event, or an action timestamp after the fixed limit.
- The first post-fix live run proved the request metadata path with decreasing 209.921/185.750/164.078-second budgets, zero retries, a 93.797-second goal duration, and no post-deadline action. It exposed a new earlier action-contract gap when the model emitted `craft.recipe` instead of the verifier-required `craft.item`.
- Added an exact `craft.item` schema with optional positive integer `count`, rejecting `recipe` before execution, and added auditable `goal_elapsed_s/max_duration_s` result fields. Four unchanged live reruns then encountered provider `Connection error` on the Root Plan before any action; a separate non-counting full-prompt probe succeeded in 32.875 seconds.
- A cooldown rerun validated the new craft contract in Minecraft: one log became four dark-oak planks, the `craft_planks` task completed, and continuation selected a crafting table. The next action was rejected because the old verifier treated recipe `oak_planks:4` as an exact item requirement.
- Added `m2-machine-verifier-v2` with pinned `minecraft-planks-tag-v1` ingredient semantics. Any supported Minecraft 1.20.4 plank combination can satisfy a plank recipe ingredient, while terminal item criteria remain exact.
- Default thinking mode later exhausted all 4096 output tokens with no visible content. M2 now fixes `thinking=disabled`, requires a stopped visible response with zero reasoning bytes, and uses `m2-bounded-transport-retry-v1`: zero SDK retries plus at most one typed `APIConnectionError` retry after client reset and deadline recomputation.
- A 39.328-second live run then produced the requested crafting table but exposed an exact-`oak_log` machine-verifier defect. BM-006 now pins ten accepted log/stem source blocks while preserving block-removal and pickup requirements; the same prior trace passes only as non-counting replay evidence.
- The next controlled baseline was the first eligible M2 success under its protocol revision: 26.23 seconds benchmark duration, 19.891 seconds goal duration, three successful actions, three complete task paths, `crafting_table:+1`, GoalVerifier achieved, and zero deadline issues in session `4bb9d423-4ec`.
- Its matching candidate also completed BM-006 but selected no skill. The retained trace reported `inventory:oak_planks>=4` twice despite four dark-oak planks, so the pairing gate correctly marked the comparable pair ineligible.
- `m2-bounded-skills-v2` extends the already pinned `minecraft-planks-tag-v1` policy to learned-skill preconditions and contract readiness. Offline tests accept dark-oak and mixed plank stacks at a total of four, while rejecting three planks and non-plank inventory.
- Three fresh BM-006 pairs then passed under protocol SHA-256 `deeff43e51b03ba435db03c7f8760b0279d8d45190dd5bca69cd0c24c75100bb`. All six arms passed; all three candidates selected and successfully executed `learned:craft_crafting_table@1.0.1`; no arm recorded an action failure.
- The canonical BM-006 gate is 3/3 eligible pairs and `repeat_verified`.
- BM-007 converged at 3/3 eligible pairs. Stable crafting confirmation now rejects Mineflayer inventory ghosts, waits through a bounded cooldown before retrying, and records each attempt. Local skill success is attributed from verified skill postconditions rather than unrelated suffixes of the broader goal. Historical failures, quarantine, attribution corrections, and the approved-gate restoration of 1.0.2 remain auditable.
- BM-008 completed three independent `equip → move_to → dig` coal runs. One malformed root response remains retained as a failed run; a later accepted run also provides recovery evidence.
- BM-009 completed three independent two-craft runs after task guidance made the no-table torch recipe and fixed initial resource budget explicit. The prior 36-action table/place detour remains retained failure evidence.
- BM-010 completed three independent bounded builds. Each placed 55 episode-delta blocks, preserved the two-block entrance and clear interior, covered 25/25 roof positions, moved the player inside, and emitted complete dependent task-state paths. Earlier schema and state-path failures remain retained.
- The canonical M2 state is now `repeat_verified` with no missing evidence and an approved composite pairing/recovery gate. M4-M7 were not started.

## Engineering Delivered

- Mineflayer bridge, structured observations, canonical action control, safety verification, and session logging.
- Rule and LLM planning, hierarchical tasks, readiness reporting, deterministic prerequisite recovery, reflection, and goal verification.
- Layered memory, task continuity, typed retrieval, promptware filtering, attribution gates, skill memory, skill lifecycle, and transfer gates.
- Autonomous curriculum, runtime interrupts, world-model/frontier reports, causal evidence, and controlled self-evolution reports.
- Vision analysis, optional screenshot plumbing, visual action grounding, and screenshot evidence validation.
- Multi-agent shared state, role execution, bridge preflight, schedule comparison, and single-agent baseline machinery.
- Evidence and ablation tooling for action verification/value, memory policy, plan cache, mixed initiative, coaching, visual review, and runtime profiles.
- Machine-checkable M3/M5/M6 live adapters with distinct-session deduplication and transfer/world-model/visual-action support gates.
- Portable canonical evidence inventory with content hashes, session identities, protocol hashes, evidence kinds, and counting eligibility for every consumed report and source log.
- Added `m2-fixed-v1`, strict `m2-root-plan-v1` validation, real-call metadata and token accounting, root-task lifecycle evidence, failure-triggered replanning, independent terminal observations, and canonical M2 session/pair deduplication.
- Added the bounded `build_shelter_5x5` Mineflayer action and verifier: exact construction zone, allowlisted material, episode block delta, wall/roof/entrance/interior geometry, inventory consumption, and protected-area occupancy are checked from live observations.
- Rule and LLM planning cycles now retrieve typed memory through strict per-read and per-decision character budgets, emit a schema-v2 contract, and exclude non-planning causal reads from bounded-context evidence. Rule selection remains world-state-driven and reports that memory has not yet influenced its action choice.
- Autonomous runs now emit observations, plans, selected goals, and terminal subgoal outcomes as non-nested machine-checkable events; queued tasks no longer silently replace the goal whose plan is being executed.
- Task continuity now uses schema-v2 execution-state records with session, branch, parent/root checkpoint, depth, validation, and revision provenance. Planner context follows one active root-to-current path and labels failed/proposed branches as hints; revision commands remain review-only and cannot restore world state.
- Added a MemGym-style fixed-control lineage ablation plus a verifier-backed shadow-restoration report and gate. Built-in lineage fixtures reduce failed-branch contamination from 2 to 0 with 2/3 review-ready cases; they remain synthetic and cannot approve the gate.
- Player observations and action snapshots now preserve dimension, hunger, saturation, oxygen, XP, game mode, and selected slot so future shadow comparisons can reject hidden state rollback rather than comparing inventory and position alone.
- Replaced planner-facing rich task-continuity injection with a budgeted Goal Frontier Capsule while retaining the full durable ledger. Built-in cases preserve all identity/frontier/continuation probes, keep failed checkpoint IDs out of the capsule, and reduce fair flat-baseline context by 103, 74, and 86 characters respectively (87.7 average). Bounded-context replay now cross-checks the declared budget, observed characters, and sanitized trace while allowing a valid empty capsule before the first checkpoint; these remain offline fixture results, not a live token-cost claim.
- Added `frontier_transition_skill_router_v1`, which reranks governed skills against readiness tasks, assigned skills, missing preconditions, target state, task family, and Bayesian-smoothed use outcomes. Its 600-character planner projection logs only skill names, task IDs, scores, coverage, and reason codes. Fixed-control built-ins improve expected top-1 routing from 0/3 to 3/3 with full frontier coverage and zero regressions; this is synthetic offline evidence only.
- Added a verifier-calibrated soft-retirement pipeline. It measures false-pass bias per judge with injected defects, compares each learned skill to a fixed-control no-skill baseline, requires live provenance and distinct sessions, and applies approved results only as a task-family runtime overlay. Built-ins cannot be quarantined, synthetic fixtures are runtime-ineligible, skill files are never mutated, and every gate hard-codes `automatic_delete_allowed=false`.
- Upgraded AgenticCache reuse with Progressive Crystallization and EvoSOP lifecycle constraints. Schema-v2 cache reports can grant only hybrid planner guidance from offline traces; runtime reports aggregate exact executable-workflow matches, independent sessions, goal outcomes, action failures, and verifier rejects per entry. Three matched successes across three complete live sessions are required by default for deterministic reuse, while regressions demote only the affected entry.
- Added a hosted-API-compatible recall-controlled episode viability cascade. `behavior_surface_v1` scores only typed action/verifier/progress events, calibrates exact binomial survival bounds per round, searches budgets on a separate validation split, certifies global success recall on held-out test data, and binds `shadow`/`active` runtime use to planner, action backend, verifier, task stream, and seed identities. The implementation explicitly makes no hidden-activation or token-savings claim.
- Added `frontier_information_budget_v1` with an exact uniform control, fixed integer planner-round ledger, deterministic soft allocation, exploration floor, typed prerequisite/verifier/novelty/risk signals, and BAGEN-style remaining-round intervals. Active episode-abort savings can become bounded recovery credit but never extend the ledger. `frontier-rollout-budget-report` accepts offline fixtures for shadow review yet permits planner-facing advice only from distinct paired uniform/information JSONL sessions whose allocations replay exactly, outcomes do not regress, interval coverage has an exact one-sided certificate, and any recovered rounds link to an approved abort gate. Automatic retry, branch execution, and budget extension are structurally impossible.
- Added AgentRx/AgentTether-style critical-transition diagnosis. `minecraft_transition_unit_v1` normalizes both action cycles and actionless planner responses; deterministic constraints feed a temporal/plan/target/artifact/error dependency graph and `first_unrecovered_constraint_v1`. Five synthetic failures match 5/5 critical units and categories versus 3/5 for a recency baseline. Repair candidates are typed and review-only, with no planner, retry, intervention, memory-promotion, or skill-mutation authority.
- Fixed Mineflayer navigation truthfulness: `move_to` now uses pathfinder and succeeds only inside target tolerance, absent/null Y values preserve horizontal goals, action/socket timeout budgets align without replay, and unreached partial navigation defers the remaining plan suffix before any dependent world action.
- Added `m1-fixed-v1` as the shared Node/Python source of truth for BM-001..005, including canonical fixtures, BM-004's five-cobblestone threshold, cycle/time limits, runtime identities, and exact Mineflayer dependency versions.
- Added a reset-capable controlled runner that creates one fresh level per task, verifies all reset postconditions, forces the minimal RuleBasedPlanner profile, records the exact Paper jar hash, and refuses multi-task M1 acceptance runs in one episode.
- Pinned and provisioned official Paper 1.20.4 build 499, verified its published SHA-256, generated EULA/config files without accepting the EULA, and prepared the localhost-only fixed server configuration.
- Added state-grounded M1 transition validation. Dig must remove an observed source block and increase the target inventory; craft must increase the requested item; copied sessions, repeated episodes/hashes, nested reset payloads, and mixed server jars are ineligible.
- Added a bounded post-dig pickup window and closer grounded resource approach so the post-action observation can prove pickup instead of racing the item entity.
- Completed M1 live convergence: exact oak targeting, per-species 32-block tree visibility, measured navigation recovery, grounded drop collection, deterministic stone search, Minecraft-data drop mapping, target-specific pickup waits, and non-replayed dig commands now support 15/15 eligible successes.

## Evidence That Still Matters

- M1 has 15 eligible live successes: BM-001..005 each 3/3. Every counted session has verified reset, action transition, terminal criteria, and an achieved Goal Verifier event.
- The retained runtime blocker and eight convergence failures remain ineligible historical evidence; they are not rewritten or counted as successes.
- The capability report independently deduplicates session IDs, episode IDs, logs, hashes, and Paper jars and now reports M1 as `repeat_verified`.
- The new tracked critical-transition replay localizes all five historical M1 failures: four contain 100 actionless non-terminal plans each, while the only 200-action run first exhibits repeated no-progress navigation. These diagnoses have no manual critical-unit labels and do not upgrade M1 evidence.
- M2 has 23 eligible current-protocol successes: BM-006 has six across three accepted pairs, BM-007 has eight including three accepted pairs, and BM-008..010 each have three. The retained BM-010 harness/template smokes remain explicitly excluded from capability counting.
- No three-run first-night survival evidence is available.
- M3 now has three eligible later-session skill retrieval/outcome cases at attribution confidence 1.0 and an approved held-out gather transfer gate; all source logs pass content-hash and fixed-protocol checks.
- Existing M5 traces cover 22 moving sessions and pass the world-model feedback gate, but complete 0 of 27 goals.
- Existing M6 traces contain no verified screenshots and no live-source visual-action interventions.
- No live BM-701 multi-agent execution report is available.
- The older 37-session M3 report remains retained negative history; it no longer overrides the newer bounded-loop evidence accepted by the canonical report. M5 and M6 remain failing.
- The bounded-memory and autonomous-event fixes apply only to future sessions. They do not upgrade or rewrite the historical evidence above.
- Execution-state lineage, capsule probes, and shadow-state invariants are offline-verified but have no live Minecraft ablation or restoration evidence. The gate now requires positive context reduction in eligible cases and can only authorize shadow revision selection after repeated evidence; it always emits `automatic_restore_allowed=false`.
- Frontier skill routing has no fresh Minecraft completion, interaction-step, token, or latency comparison. The old ranker remains available through `--no-skill-frontier-routing` for live fixed-control runs.
- Skill soft retirement has deterministic offline coverage but no live defect-injection calibration or paired no-skill Minecraft traces. No current skill is justified for runtime quarantine by tracked evidence.
- Workflow crystallization is offline-verified, but no existing Minecraft cache entry has the three-session live evidence required for deterministic execution. Existing schema-v1 gates are intentionally rejected.
- Episode early-abort mechanics are offline-verified only. Existing logs do not provide disjoint successful calibration/validation/test populations, so no live gate is approved and runtime remains off by default.
- Frontier-budget mechanics are offline-verified only. The three built-in prerequisite cases conserve an eight-round budget and target later synthetic resolutions better than uniform, but they provide only three interval observations and no connected paired Minecraft sessions. No advisory runtime gate is approved; default mode remains off and shadow mode cannot change planner context.

## Frozen Research Backlog

The material below is retained as historical context and is not active work while the M1 convergence freeze is in force.

- MineExplorer: hidden prerequisite graphs and rule-based milestones should define progress rather than final-text claims.
- MineNPC-Task: task attempts should be scored against explicit dependencies, bounded knowledge, and machine-checkable validators.
- AgenticSTS: every planner decision should use bounded typed retrieval instead of accumulating raw transcripts.
- WorldLines: memory should preserve visibility, state revisions, and action-native evidence under partial observability.
- SelfMem: memory-policy variants should be optimized offline from retrieval cost and downstream outcomes, then promoted only through existing gates.
- MAGE execution-state memory: active task paths, completed checkpoints, failed branches, and revision boundaries should be represented separately before automatic rollback is enabled.
- MemGym: execution-state memory must be evaluated with the planner and action backend held fixed so memory gains are not confounded with reasoning or tool improvements.
- Goal-Oriented Graphs: planner-facing memory should preserve the active goal-to-prerequisite frontier rather than return disconnected relevant checkpoints.
- OpenClaw and Hermes compression: keep the complete durable record outside the prompt, budget only the injected projection, and verify recall/artifact/continuation/decision retention with probes before promotion.
- OpenClaw and Hermes: durable memory, procedural skills, maintenance passes, and workspace separation are useful only when action authority and promotion gates remain explicit.
- SkillReranker: match skills to decomposed execution-state intervals and unresolved prerequisites rather than the root goal alone.
- Gold-standard lightweight game agents: hold a strong deterministic yardstick fixed and report negative results and regressions instead of grading an agent against itself.
- Blind Curator and SkillCenter: scale skill libraries only with provenance, verifier-visible failures, and false-pass-calibrated soft retirement; never delete skills from an LLM judge score alone.
- Progressive Crystallization and EvoSOP: treat exploration as workflow discovery, keep offline procedures hybrid, promote entries individually after repeated live verification, and demote regressions without erasing evidence.
- Recall-Controlled Early Abort: use exact sample-complexity-aware certificates and shadow deployment before behavior-changing termination; behavior-only Minecraft signals must not inherit hidden-state probe claims.
- IGRPO: when retries or branch rollouts become available, allocate a fixed planner-round budget toward frontier nodes that reduce verifier uncertainty or reveal prerequisites, and compare against uniform allocation before online suppression.
- BAGEN: treat planner rounds as an active progressive ledger, report conservative remaining-cost intervals, and measure optimistic misses separately from task completion.
- AgentTether: localize retry value along prerequisite/dependency paths, carry fixed versus unresolved state across attempts, and use cooldown/minimal-intervention guards rather than blind retry.
- AgentRx and TrajAudit: audit guarded execution constraints, identify the first unrecovered transition, and keep full traces outside a compact dependency-linked evidence packet until manual labels establish localization quality.

## Immediate Sequence

1. Preserve and audit the immutable M1/M3 evidence sets and wooden-pickaxe quarantine history.
2. Keep independently promoted wooden-pickaxe `1.0.2` executable and historical `1.0.1` quarantined.
3. Keep the M2 protocol, paired evidence, retained failures, and recovery sessions immutable unless a tracked change requires full revalidation.
4. Leave M4-M7 unopened in this workstream; M4 is the next acceptance gate when a new convergence cycle is explicitly started.
