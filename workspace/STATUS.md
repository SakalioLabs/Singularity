# STATUS.md | Last updated: 2026-07-19

## M1 Convergence Result

- M1 is `repeat_verified`.
- G0 through G5 are complete under the fixed `m1-fixed-v1` protocol.
- BM-001..005 each have three distinct verified live successes: `15/15` total.
- The M1 convergence freeze is lifted; M2-M7 retain their own current evidence statuses.
- Ordered gates, fixed protocol, and stop conditions are in `workspace/CONVERGENCE_PLAN.md`; failure-level evidence is in `workspace/evals/m1_failure_ledger.json`.

## M3 Bounded Skill-Learning Result

- M3 is `repeat_verified` under the canonical capability contract.
- Three distinct later-session skill retrieval/outcome pairs pass raw-log hash, protocol, GoalVerifier, and attribution checks.
- The gather-wood held-out transfer gate is approved with two disjoint live support sessions.
- The historical 37-session failing report remains retained evidence, but it is superseded for current M3 status by the newer bounded-loop evidence.

## Stone Pickaxe Skill Convergence

- Phases 0-118 retain the verified SP-001/SP-002 history, SP-003 definition, consumed authorizations, offline repairs, and immutable failures. Phase 117 live-confirms the local-table carry strategy but exposes rejection of an exact navigation target when the Planner includes matching y. Phase 118 normalizes only that exactly machine-bound shape in a process-local overlay while preserving the frozen Phase 116 runner and runtime. Earlier skill records and Probe 21/22/23 hashes remain protected.
- SP-001 Acquire Cobblestone is 3/3 and SP-002 Craft Stone Pickaxe is 3/3. SP-003 is not live-verified: twenty-one baseline authorizations are consumed, baseline remains 0/1, and candidates remain 0/3. Nineteen produced Agent episodes; two created no Agent episode before Bridge readiness.
- `learned:acquire_cobblestone@1.0.0` and `learned:craft_stone_pickaxe@1.0.0` remain immutable advisory history. Executable `learned:acquire_cobblestone@1.1.0` and `learned:craft_stone_pickaxe@1.0.1` are approved under separate fingerprint-bound runtime gates.
- SP-003 starts in a fresh seed-12345 survival world with exact empty inventory and requires the full `logs -> table -> wooden pickaxe -> three stone -> stone pickaxe` machine-verified chain. Phase 117 evidence is pushed at `271a188f` and retains the 13-file exact-y rejection failure. Phase 118 now passes offline: all five exact xyz cases normalize into the existing x/z center binding without retry, while all three wrong-y cases remain rejected. Audit `11100a3f...` binds the repair. The full chain is still not live-proven.
- Four separately authorized non-counting fixture-preparation sessions failed machine audit and remain retained. The fifth passed and sealed the 45-file fixture tree `996b2a1f989626e9c44ddca5c24f81ae55a5dca03b246f0d72723c46fd6a7636`. The first SP-001 episode exposed repeated equip; the second exposed pickup-candidate geometry; the third and fourth independently passed; the fifth failed closed before any action when its sole provider call ended in `SSLEOFError`; the sixth exposed a same-cell `GoalBlock` alias; the seventh reached the same zero-action provider TLS failure; the eighth independently passed and exercised the repair path.

## M2 Convergence Result

- `m2-fixed-v1` now pins BM-006..010 fixtures, Paper and dependency identities, the LLM request contract, planner/action/verifier/skill profiles, reset and validation hashes, limits, and machine-checkable terminal criteria.
- A real Paper BM-010 empty-execution smoke proved that reset and terminal observations work and that planner text or an unchanged world cannot pass the shelter verifier.
- A separate real Paper template smoke placed exactly 55 cobblestone blocks in survival, left the two-block entrance and interior clear, covered the roof, moved the player inside, and passed the independent shelter verifier.
- Both smoke artifacts explicitly set `counts_toward_live_observed=false` and `counts_toward_repeat_verified=false`; they validate the harness, not M2 planning capability.
- The fixed LLM contract now records the OpenAI-compatible endpoint `https://opencode.ai/zen/go/v1`, dialogue model `deepseek-v4-flash`, temperature 0, 4096 maximum tokens, and JSON-object response format. The credential is available outside the repository and is absent from all evidence artifacts.
- The first BM-006 live baseline produced a valid three-node Root Plan but all three dig attempts used noncanonical parameter aliases. The retained failure motivated an exact typed dig contract without relaxing the ActionVerifier.
- The next BM-006 baseline eliminated those alias rejects: two real digs succeeded, one craft produced four dark-oak planks, and two dependent task paths completed. It still failed with no crafting table; after the recovered craft, the `craft_planks` task remained `active` instead of becoming `completed`.
- M2 action feedback now binds the pre-action task before observing consumptive post-state, and the exact one-log-to-four-planks regression passes offline. One live rerun stopped at a transient Root Plan connection error before any action, so it cannot validate that fix.
- The following live rerun completed two grounded digs but never attempted craft: continuation planning saw the benchmark's required dig action without any successful-action history and redundantly dug a second log. This repeated behavior is now the earliest execution blocker.
- `m2-successful-action-summary-v1` now injects at most eight typed successful actions from the current goal into continuation/replan calls and records the same bounded summary in planner-call evidence. In the next live run, the planner observed `dig:1`, advanced directly to planks, then observed `dig:1, craft:1` and selected crafting table without another dig.
- That run completed the original `craft_planks active -> completed` transition and reached four dark-oak planks, but took 317.71 seconds under a fixed 240-second goal limit. Planner calls returned at elapsed 245.11 and 319.89 seconds and the Agent still executed their actions.
- `m2-hard-total-deadline-v1` now binds every planner call to remaining goal time minus a fixed 30-second action window, disables provider retries, suppresses plans/actions after the deadline, and makes goal duration plus post-deadline event checks independently eligibility-critical. A boundary regression proves a late planner response executes zero actions.
- The first post-fix live baseline recorded request budgets of 209.921, 185.750, and 164.078 seconds with zero retries, ended at goal elapsed 93.797 seconds, and recorded zero deadline events and zero post-deadline actions. Its first dig succeeded, but the next plan used `craft.parameters.recipe`; ActionVerifier correctly rejected the missing `item` parameter.
- The strict planner schema now requires `craft.item` plus an optional positive integer `count`, rejects the `recipe` alias before execution, and persisted result artifacts now include `goal_elapsed_s` and `max_duration_s`. Four unchanged reruns then failed at the root request with provider `Connection error` before any action, while a non-counting 90-second full-prompt probe succeeded in 32.875 seconds.
- A cooldown rerun validated the craft contract live: dig produced one dark-oak log, `craft(item=dark_oak_planks,count=4)` succeeded, `craft_planks` completed, and continuation selected `craft(item=crafting_table)`. ActionVerifier then rejected the four dark-oak planks because its recipe required exact `oak_planks:4`, before a later connection error.
- `m2-machine-verifier-v2` now pins `minecraft-planks-tag-v1` and accepts the Minecraft 1.20.4 plank family, including mixed plank stacks, only when satisfying recipe ingredients. Terminal inventory targets remain exact.
- A later HTTP 200 consumed all 4096 completion tokens in default thinking mode and returned no visible content. The fixed request now disables thinking, requires `finish_reason=stop` and zero reasoning bytes, and produced valid full Root Plans in 5-9 seconds with roughly 440-460 completion tokens.
- Repeated continuation failures were typed as `APIConnectionError -> RemoteProtocolError`. The failed `Connection: close` hypothesis was removed. `m2-bounded-transport-retry-v1` instead keeps SDK retries at zero, permits one evidence-recorded transport-only retry after rebuilding the client, and recomputes the remaining deadline budget before retrying.
- The next live run completed dig, dark-oak plank craft, and crafting-table craft in 39.328 seconds, but GoalVerifier rejected its hardcoded `oak_log` source check. BM-006 now pins the Minecraft 1.20.4 log/stem source family while retaining required block-removal and pickup proof; the prior live trace passes only as a non-counting replay.
- The fresh controlled baseline then passed end to end in 26.23 seconds: one valid Root Plan, three successful actions, three complete task paths, exact `crafting_table:+1`, machine GoalVerifier achievement, zero deadline events, and protocol-eligible immutable session `4bb9d423-4ec` under the prior protocol revision.
- Its matching candidate completed the task but selected no skill. Two `skill_deferred` events proved that the learned contract treated `oak_planks` as exact while the world held four `dark_oak_planks`; the pairing gate retained the comparable run but rejected it as ineligible.
- `m2-bounded-skills-v2` now applies the pinned plank family to learned-skill preconditions and contract readiness as well as recipe verification. Quantity-short and non-plank controls remain rejected offline.
- Three new fixed-protocol BM-006 baseline/candidate pairs passed in independent worlds. Every baseline kept skills off; every candidate selected `learned:craft_crafting_table@1.0.1` and contributed one successful verified craft action with attribution confidence 1.0. The canonical gate accepts all three pairs.
- BM-007 converged with three eligible skill-off/skill-on pairs. The accepted pairs are `bm007-priority-one-r1`, `bm007-move-once-r1`, and `bm007-backoff-r3`; every candidate selected and successfully executed `learned:craft_wooden_pickaxe@1.0.2`.
- Retained BM-007 failures exposed saturated nearby-block context, repeated movement, transient crafting inventory, and two framework-owned attribution errors. Nearby-block diversity, stable crafting confirmation with bounded cooldown, and local skill-postcondition attribution now have regression coverage. The original failures, the 1.0.2 quarantine event, both attribution corrections, and its approved-gate restoration remain in lifecycle history; historical 1.0.1 remains quarantined.
- BM-008 passed three independent coal-mining runs. BM-009 passed three two-action stick-to-torch chains after the prompt stopped inventing a crafting table. BM-010 passed three independent 55-block shelter builds with exact wall, entrance, roof, episode-delta, player-inside, and dependent task-state proof.
- M2 is `repeat_verified`: BM-006..010 all meet the three-run gate, BM-006 and BM-007 each have 3/3 eligible pairs, the pairing gate is approved, and sessions `591bf0aa-d7e` and `3b49bf83-84e` provide eligible recovery evidence.

## M4 Convergence Result

- M4 is `failing`; BM-011 remains repeat-verified, but BM-012 remains 0/3 after twenty-three failed live attempts and the phase is not complete until BM-011 through BM-014 each reach 3/3.
- BM-011 is `repeat_verified` with three independently eligible fresh `m4-fixed-v1` survival-to-dawn episodes.
- Every accepted BM-011 run has a unique episode, session, level, and session hash; all pass machine shelter, zero-death lifecycle, natural-time, absolute-deadline, and independent eligibility checks.
- BM-012 is 0/3 after twenty-three failed live attempts. Probe 23 ran once from pushed gate `f528ea17`; the failed-dependency reconciliation branch was not exercised because no failed pickaxe task was a direct dependency on the active frontier. The next earliest layer is `m4_ready_task_failed_root_machine_state_disconnect`: a failed torch root remained bound after machine state contained four torches. Probe 23 reached the deadline, passed 66/74 checks, acquired no iron, and is classified `intervention_not_exercised`. Its authorization is consumed, next authorization is false, and BM-013/BM-014 remain locked.

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
| M0 | Research Baseline | **Complete (`source_verified`)** | Research deliverables present |
| M1 | Minimum Viable Bot | **Complete (`repeat_verified`)** | BM-001..005 each 3/3; 15/15 distinct eligible live successes |
| M2 | LLM Task Planning | **Complete (`repeat_verified`)** | BM-006/BM-007: 3/3 eligible pairs each; BM-008..010: 3/3 each; recovery gate approved |
| M3 | Skill Library & Memory | **Complete (`repeat_verified`)** | 3/3 raw-log-verified runtime sessions plus approved held-out transfer support |
| M4 | Autonomous Survival | **Failing (`failing`)** | BM-011 repeat_verified 3/3; BM-012 twenty-three failed attempts, 0/3; BM-013..014 not_run |
| M5 | Open-World Exploration | **Failing (`failing`)** | World-model gate passes, but 0/27 historical goals completed |
| M6 | Vision & Multimodal | **Failing (`failing`)** | No verified screenshots or live-source visual-action interventions |
| M7 | Multi-Agent Collaboration | **Pending (`not_run`)** | BM-701: no tracked live execution |

Source is present and relevant offline suites pass for M1-M7, but those facts do not change the live statuses above.

## Current Runtime Readiness

- Python, Java, Node.js, npm, and Mineflayer dependencies pass local preflight.
- Pinned Paper 1.20.4 build 499 is present in the ignored runtime directory and its SHA-256 is verified.
- Paper generated `server.properties` and `eula.txt`; the user authorized EULA acceptance, and the fixed server settings plus offline `Singularity` operator passed live preflight.
- `mc-server/eula.txt` is currently `eula=true`; runtime scripts only verify this state and do not alter the agreement.
- Port `3000` accepts TCP through `svchost.exe`, but fails the Singularity `health` protocol and now correctly fails the `bot_bridge` check.
- Immutable result, preflight, manifest, and session evidence covers 76 per-run live benchmark results; 15 eligible successes count toward M1 and 23 current-protocol successes toward M2.
- `scripts/m1-runtime.ps1` provides a controlled one-task startup path on bridge port `30000`, creates a fresh level, records the server jar hash, restores server properties, and never accepts or edits the Minecraft EULA.
- `scripts/m2-runtime.ps1` provides the equivalent fresh-world M2 path, enforces `m2-fixed-v1`, records immutable preflight/manifest/result artifacts, and supports non-counting harness/template smoke modes.
- The M2 API endpoint and fixed non-thinking dialogue request pass full-prompt calls with bounded transport evidence. BM-006 and BM-007 each have three accepted skill-off/skill-on pairs under the current protocol; BM-008..010 each have three accepted default-arm runs.
- The G1 harness is live-verified: canonical reset state, BM-004's five-cobblestone threshold, per-task limits, deterministic runtime isolation, transition evidence, and immutable sessions are enforced.

## Latest Verified Engineering Changes

- Made bridge preflight protocol-aware so an unrelated TCP listener cannot pass as Singularity; bot readiness and requested username/version/MC-port identity remain separate checks.
- Added timestampable JSON preflight evidence marked as non-capability evidence, plus a controlled M1 runtime launcher that never signs the EULA or stops unknown processes.
- Added one shared fixed M1 protocol for tasks, reset fixtures, versions, runtime identities, limits, and exact dependency versions; Node and Python reject protocol drift.
- Pinned the server to official Paper 1.20.4 build 499 and its published SHA-256; the launcher, bridge, runner, and capability gate reject any other jar.
- Provisioned and bootstrapped the ignored local Paper runtime without accepting the EULA, then fixed server properties and the deterministic offline operator identity.
- Added allowlisted reset commands with observed postcondition checks for inventory, spawn, fixture, mode, difficulty, time, weather, health, and food.
- Forced RuleBasedPlanner and isolated memory persistence/context, skills, vision, plan cache, self-evolution, frontier budgets, episode abort, LLM critics, and action candidate selection for M1.
- Hardened action evidence: navigation requires strict tolerance, unreached movement defers dependent actions, dig waits for a bounded pickup observation, and dig/craft require real pre/post block and inventory deltas.
- Hardened capability counting against copied sessions, repeated episodes/log hashes, mixed Paper jar hashes, nested reset records, and unsupported success text.
- Added task-readiness recovery that turns inventory blockers into concrete prerequisite goals.
- Preserved critical health, nearby-hostile, and night-survival goals ahead of scheduled work.
- Added knowledge-backed tool checks and grounded-coordinate checks to generic mining fallback.
- Added `capability-evidence-report` to reject unsupported M0-M7 completion claims from benchmark and runtime evidence.
- Added machine-checkable M3/M5/M6 adapters with distinct-session counting and independent mechanism gates.
- Canonicalized M1/M3 evidence into repository-relative paths with per-file SHA-256, session, protocol, evidence-kind, and eligibility records; M3 source logs are now revalidated instead of trusted by path alone.
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
- Added a bounded authoritative crafting-table inventory refresh and isolated SP-002 post-action machine completion. Three independent revalidations each made exactly one stone pickaxe from the sealed fixture in one backend attempt, passed all machine and evidence gates, and complete the SP-002 3/3 extraction gate without changing capability or M4 status.
- Added task-specific SP-002 executable-promotion tooling with exact report reconstruction, pre-write tamper rejection, append-only versioning, rollback binding, and idempotency coverage. This phase does not modify the skill library or grant runtime authority.
- Applied the approved SP-002 promotion offline: retained craft 1.0.0 as advisory history, appended executable 1.0.1 with rollback metadata, created its approved crafting-family runtime gate, and verified gate-controlled runtime selection plus byte-stable reexecution.

## Next Acceptance Work

1. Preserve the immutable M1 and M3 evidence and the quarantined wooden-pickaxe `1.0.1` history.
2. Preserve executable wooden-pickaxe `1.0.2` as the independently gated repair; never restore executable authority to quarantined `1.0.1`.
3. Keep the completed M2 evidence set immutable and rerun the canonical audit after any planner, bridge, verifier, or skill-lifecycle change.
4. Treat M4 as the next unopened acceptance gate; no M4-M7 execution was started during M2 convergence.

## Stone-Pickaxe Workstream

- Current gate: SP-001 and SP-002 are independently 3/3 with executable `learned:acquire_cobblestone@1.1.0` and `learned:craft_stone_pickaxe@1.0.1`. SP-003 remains baseline 0/1 and candidates 0/3 after twenty-one consumed baseline authorizations; no live authorization exists.
- Phase 117's exact 13-file failure preserves five exact-target y rejections, three wrong-y rejections, two late successful x/z-only moves, and the 300-second deadline boundary at evidence commit `271a188f`. The consumed authorization cannot be reused.
- Phase 118's SP-003-only normalization repair passes offline at full Python 1042/1042 and preserves every frozen Phase 116/runtime identity. The next transaction is its commit and push. Only afterward may a fresh parent-bound one-use baseline authorization be created; candidate execution remains locked until a baseline completes the full chain.
- Capability impact: none. M4 remains failing; this workstream does not authorize full BM-012, Probe 24, or iron mining.
