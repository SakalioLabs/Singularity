# PROGRESS.md -- Evidence-Backed Progress

## Current Assessment

Singularity has broad source coverage and a large passing offline test surface, but the full Minecraft Agent system is not complete. The authoritative capability report is `workspace/evals/capability_evidence_current.json`.

Current report outcome:

- Readiness: `rejected`
- Claim audit: `approved`
- System status: `incomplete`
- Declared-complete phases audited: 1 (M0 only)
- Supported completion claims: 1 (M0 research baseline)
- Contradicted completion claims: 0 after status correction
- Unsupported completion claims: 0 after status correction
- Failing live phases: 4 (M1, M3, M5, M6)
- Repeat-verified runtime phases: 0

## Engineering Delivered

- Mineflayer bridge, structured observations, canonical action control, safety verification, and session logging.
- Rule and LLM planning, hierarchical tasks, readiness reporting, deterministic prerequisite recovery, reflection, and goal verification.
- Layered memory, task continuity, typed retrieval, promptware filtering, attribution gates, skill memory, skill lifecycle, and transfer gates.
- Autonomous curriculum, runtime interrupts, world-model/frontier reports, causal evidence, and controlled self-evolution reports.
- Vision analysis, optional screenshot plumbing, visual action grounding, and screenshot evidence validation.
- Multi-agent shared state, role execution, bridge preflight, schedule comparison, and single-agent baseline machinery.
- Evidence and ablation tooling for action verification/value, memory policy, plan cache, mixed initiative, coaching, visual review, and runtime profiles.
- Machine-checkable M3/M5/M6 live adapters with distinct-session deduplication and transfer/world-model/visual-action support gates.
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

## Evidence That Still Matters

- Latest tracked M1 benchmark file records BM-001..005 as failures with empty inventories.
- The new tracked critical-transition replay localizes all five historical M1 failures: four contain 100 actionless non-terminal plans each, while the only 200-action run first exhibits repeated no-progress navigation. These diagnoses have no manual critical-unit labels and do not upgrade M1 evidence.
- No tracked successful M2 benchmark suite is available.
- No three-run first-night survival evidence is available.
- Existing M3 traces show no memory reads or writes, no completed goals, and 2,601 unbounded context cycles.
- Existing M5 traces cover 22 moving sessions and pass the world-model feedback gate, but complete 0 of 27 goals.
- Existing M6 traces contain no verified screenshots and no live-source visual-action interventions.
- No live BM-701 multi-agent execution report is available.
- M3, M5, and M6 acceptance is machine-checkable; all 37 existing sessions were ingested and none qualifies.
- The bounded-memory and autonomous-event fixes apply only to future sessions. They do not upgrade or rewrite the historical evidence above.
- Execution-state lineage, capsule probes, and shadow-state invariants are offline-verified but have no live Minecraft ablation or restoration evidence. The gate now requires positive context reduction in eligible cases and can only authorize shadow revision selection after repeated evidence; it always emits `automatic_restore_allowed=false`.
- Frontier skill routing has no fresh Minecraft completion, interaction-step, token, or latency comparison. The old ranker remains available through `--no-skill-frontier-routing` for live fixed-control runs.
- Skill soft retirement has deterministic offline coverage but no live defect-injection calibration or paired no-skill Minecraft traces. No current skill is justified for runtime quarantine by tracked evidence.
- Workflow crystallization is offline-verified, but no existing Minecraft cache entry has the three-session live evidence required for deterministic execution. Existing schema-v1 gates are intentionally rejected.
- Episode early-abort mechanics are offline-verified only. Existing logs do not provide disjoint successful calibration/validation/test populations, so no live gate is approved and runtime remains off by default.
- Frontier-budget mechanics are offline-verified only. The three built-in prerequisite cases conserve an eight-round budget and target later synthetic resolutions better than uniform, but they provide only three interval observations and no connected paired Minecraft sessions. No advisory runtime gate is approved; default mode remains off and shadow mode cannot change planner context.

## Research Direction

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

1. Restore a healthy Minecraft server and bridge runtime.
2. Re-run M1 with pathfinder-backed truthful navigation and readiness recovery; compare empty plans, unreached navigation, dependent world actions, and no-progress transitions against the tracked critical-transition report.
3. Promote no capability until the ledger reports `repeat_verified`.
4. Re-run M3/M5 with the new bounded-memory and autonomous-event contracts, then collect three distinct qualifying sessions for each adapter; M6 still requires screenshot-backed visual interventions.
5. Continue research-driven improvements only with baseline/candidate traces and regression gates.
6. Collect fixed-control live lineage and shadow-restoration traces on at least three distinct candidate sessions, verifying `goal_frontier_capsule_v1` memory-read events and actual token/latency deltas; keep automatic restoration disabled even if shadow selection is approved.
7. Collect per-judge defect-injection controls and paired no-skill skill-contribution traces across at least three distinct live sessions before applying a runtime retirement overlay; preserve all skill files for audit and recovery.
8. Run schema-v2 hybrid workflow guidance on fresh M1/M2 traces, then regenerate runtime reports and permit deterministic reuse only for entries with three distinct exact matched successes and no regression.
9. Build disjoint fixed-control M1/M2 episode-abort splits, run `behavior_surface_v1` in shadow mode, and permit active termination only after validation and held-out test global-recall certificates pass with positive failed-episode savings.
10. Collect at least 12 distinct matched uniform/information frontier-budget sessions under one fixed task stream and seed protocol, then require exact allocation replay, non-regressing completion/verifier/action outcomes, positive prerequisite-resolution targeting, and a held-out interval-coverage certificate before advisory planner context.
