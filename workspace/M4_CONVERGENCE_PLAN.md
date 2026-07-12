# M4 Autonomous Survival Convergence Plan

## Current Gate

- Protocol: `m4-fixed-v1`
- Protocol SHA-256: `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`
- Current target: BM-011 Survive the first night
- Eligible successes: 1/3
- M4 canonical status: `not_run`
- M1, M2, and M3 regression baseline: `repeat_verified`

BM-012, BM-013, and BM-014 remain locked until BM-011 reaches 3/3 eligible live successes.

## Scope

The protocol is independent from M1/M2 task semantics. It reuses the pinned Paper runtime, bridge, machine evidence shape, content hashing, and anti-replay controls. It does not inherit peaceful difficulty, prepared inventory, terminal fixtures, or scripted intermediate goals.

The first BM-011 baseline keeps learned executable skills off. Built-in primitive actions and the LLM planner remain available. `survive_first_night` cannot execute as the root strategy, and quarantined skills are forbidden.

## Gate Ladder

| Gate | Requirement | State |
|---|---|---|
| G0 | Fixed protocol, fresh episode, natural time, one absolute deadline, independent eligibility | passed_probe_16_death_rejection |
| G1 | Deterministic survival-goal priority cases | passed |
| G2 | One live preparation episode with machine-visible progress | passed_probe_6 |
| G3 | Machine-checkable shelter or approved natural safe-state verification | passed_offline_atomicity_recovery |
| G4 | Hostile, health, hunger, dusk, and night interrupt continuity | passed_offline |
| G5 | First eligible survival-to-dawn episode | passed_probe_15 |
| G6 | Three independent fresh eligible episodes | probe_17_authorized_1_of_3 |

G0 passes both sides of live validation. Probe 15 exercised the zero-transition path across 84 active observations and reached an independently eligible terminal state 492.703 seconds before the deadline. Probe 16 exercised the rejection path: six Mineflayer death/respawn transitions matched six Paper death messages, no terminal event was emitted after later health-20 respawns and a verified shelter, missing lifecycle evidence after bridge loss failed closed, and the independent gate also rejected a 0.031-second duration overrun plus the late Planner return without allowing a post-deadline action.

G1 passed offline validation. GoalGenerator and Curriculum preserve the fixed order of immediate threat, critical health, hunger/food, shelter preparation, night safety maintenance, and tool/resource progression. Shelter safety requires machine-state verification, and every `auto_goal` event carries source, reason, priority, and priority class.

G2 passed in Probe 6. The Agent gained `oak_log:1` and `dark_oak_sapling:1` before dusk at world time 9952 under the fixed live protocol, with all 32 real Planner calls schema-valid and the absolute deadline intact.

G3 passed offline validation. `m4-sealed-cell-shelter-verifier-v1` consumes a complete 36-coordinate Mineflayer snapshot and accepts only a solid floor, two passable interior cells, four two-block-high full-block wall columns, a full-block roof, no hostile inside, complete coordinate evidence, and all nine structural positions attributed to successful placements in the current episode. No natural safe-point strategy is approved in this baseline.

G4 passed strict offline integration. RuntimeSupervisor applies the fixed hostile, critical-health, hunger, dusk-shelter, and night-safety order; Observer preserves hostile IDs and positions for grounded attack or flee actions. A strict-M4 hostile is no longer treated as an immediate reachable threat when the current observation also contains a complete pinned shelter report proving the same player cell, a fully sealed entrance, blocked direct reachability, and no hostile inside. Agent records one trigger per actionable condition, suspends rather than fails a non-emergency root, keeps its task frontier active, allows the aligned survival goal to act, emits a matching recovery when the condition clears, and never holds two root goals concurrently.

## Current Hypothesis

Probe 7 confirms the M4 action-parameter-grounding fix in live execution. All 22 real Planner calls were schema-valid, every `dig` used canonical top-level coordinates and optional `block`, all nine `dig` actions passed ActionVerifier, and nine succeeded. The Agent accumulated 11 oak logs, so Probe 6's alias rejection did not recur.

The new earliest unrecovered transition is task-completion/readiness grounding. At session event index 366 the machine observation already contained `oak_log:9`. Planner call `llm-1ef73e3cdfab47e3` at index 376 nevertheless treated the fulfilled `Gather 6 oak logs` task as ready and emitted another `dig` rather than the dependent craft/build step. The next successful action raised inventory to 10 logs, and subsequent plans continued gathering. Across 21 actions there were 15 successes but zero crafting actions and zero placement actions; the shelter remained unverified.

The dusk interrupt itself behaved coherently: one `dusk_shelter_required` trigger suspended the resource goal, preserved its frontier, selected the aligned shelter goal, and escalated the same trigger to `night_shelter_required` without creating a competing root. The run ultimately consumed the remaining 58.14 seconds in a deadline-bound `move_to`, ended 0.016 seconds after the absolute deadline, and was independently rejected.

The task-completion/readiness hypothesis passed live in Probe 8. At cycle 9, one `m4_task_state_reconciliation` event completed seven duplicate gather nodes as soon as the machine observation reached `oak_log:6`; the next selected behavior entered crafting instead of gathering. Non-inventory criteria remained outside the reconciliation path.

The new earliest unrecovered transition is craft action-parameter grounding. Session event index 207 at monotonic 280930.390 attempted `craft` with `recipe=oak_planks` and `count=4`; ActionVerifier requires canonical `item`, so it rejected the action before execution. All 11 craft attempts repeated the same alias family, producing zero planks and no shelter placements. Later readiness-format warnings and the final deadline overrun do not displace this earlier transition.

Craft parameter grounding passed live in Probe 9. Planner output was normalized to canonical `item`, ActionVerifier accepted it, and one craft action converted four oak logs into 16 observed oak planks.

The new earliest unrecovered transition is shelter-phase progression. Immediately after the 16-plank observation and task reconciliation, Planner call `llm-05670ca498a34ebf` at session event index 302 expanded the shelter goal into additional logs, sticks, a crafting table, pickaxe, cobblestone, and furnace. Its first actions returned to gathering, even though the same plan declared the shelter build precondition as 16 oak planks and that machine state already held. No place action occurred, and the first shelter root exhausted eight cycles at event index 414.

Shelter-phase progression passed live in Probe 10. The autonomous chain gathered six oak logs, crafted 24 oak planks, activated one machine-grounded `build_shelter_cell`, placed the nine final structure blocks, removed the temporary scaffold, and obtained a 9/9 current-episode match from the unchanged G3 verifier. All 11 actions succeeded.

The new earliest unrecovered transition is autonomous goal-budget lifecycle. After shelter verification, GoalGenerator correctly selected `Enter and maintain verified shelter through nightfall`, but GoalVerifier immediately completed that maintenance goal from the already-safe state. The same one-cycle goal was selected twice, consuming goal slots 3 and 4. `autonomous_end` event index 304 then terminated with `max_goals_or_stopped` at world time 11226 before night, despite 135.297 seconds remaining.

Maintenance-goal lifecycle passed live in Probe 11. `Remain in verified shelter until dawn` stayed active, emitted two bounded waits, and ended only when the absolute episode deadline fired; it did not allocate another goal or terminate on `max_goals`.

Probe 11 exposed runtime-harness limit drift, not a contradiction in the fixed protocol. Probe 12 confirms that fix live: the manifest used exactly 1200 seconds, 24 autonomous goals, and 40 cycles per goal, while the protocol retained its 320-cycle total cap and unchanged hash. The Agent gathered resources, crafted planks, built a 9/9 machine-verified shelter by world time 11282, and maintained it into night.

The new earliest unrecovered transition is `planner_transport_failure_goal_abandonment`. At session event index 506, Planner call `llm-24dd4cd454db4e1e` made its one allowed transport attempt for `Remain in verified shelter until dawn` and received `APIConnectionError -> ConnectError -> SSLEOFError`. The immediately preceding machine observation at index 502 still showed health 20, food 20, world time 14902, an online verified shelter, and one nearby hostile, with more than 900 seconds of episode budget remaining. The error plan became `empty_plan` at index 511, and the autonomous loop failed and discarded the active maintenance root instead of preserving it for a next-cycle transport recovery.

Later events are a secondary cascade, not the earliest blocker. GoalGenerator selected an immediate-threat flee goal, the Agent left its verified shelter, and shelter verification became false at world time 15362. Eleven rebuild attempts lacked a grounded neighbor, one later rebuild timed out and disconnected the Agent-side bridge, and all subsequent observations fell back to empty position/inventory and time zero. The exact-profile run then ended at the absolute deadline without a terminal machine verification.

The `planner_transport_failure_goal_lifecycle` patch remained bounded in Probe 13. There were no live transport exceptions and therefore zero `m4_planner_transport_recovery` events; the Probe 12 failure did not recur. Sixteen real model responses with `planning_actions_missing` were correctly handled by the pre-existing `m4_planner_output_recovery` branch, producing zero `empty_plan` events and demonstrating that transport and schema recovery remain separate.

The new earliest unrecovered transition is `verified_shelter_hostile_flee`. At session observation index 920, world time 21672, the Agent had health/food 20, was inside the pinned 9/9 sealed-cell shelter, and observed one skeleton 5.1 blocks away. The G3 report proved `direct_reachability=blocked`, a fully sealed entrance, and no hostile inside. Runtime interrupt event 933 nevertheless generated an outward `move_to` target, and action event 943 moved the Agent 7.894 blocks before reporting a tolerance miss. Observation 940 then showed shelter verification false at world time 22152. The dawn observation at event 1057 had health 19 and natural time 23092 but no verified shelter, so no terminal machine event could be emitted.

The Probe 14 hypothesis was `runtime_interrupt_safe_state_grounding`: a hostile outside a complete machine-verified sealed shelter must not trigger an emergency action that exits that safe state. The patch alters only strict-M4 hostile interrupt grounding for this proven-safe condition; hostile handling without a verified shelter, hostiles inside the cell, health/hunger interrupts, priority order, and the G3 contract remain unchanged.

The offline safe-state gate passes. Replaying Probe 13 observation event 920 through the patched RuntimeSupervisor selects `night_safety_maintenance`, emits no emergency action, and records that the previously generated outward `move_to` was suppressed. The full report is accepted only when the pinned verifier and contract pass, the report and observation floor to the same player cell, the report saw every actionable hostile, `direct_reachability=blocked`, and `hostiles_inside=[]`. Spoofed reports, stale player positions, reachable threats, hostiles in the player cell, and non-M4 profiles retain the original `hostile_nearby` behavior. Critical health still wins when the outside hostile is proven blocked.

Probe 14 produced a runner-reported eligible terminal state, but independent audit rejects it. Paper recorded `Singularity was slain by Zombie` at 00:34:41 and again at 00:35:04. The first death is corroborated by canonical observation event 1183 (`health=7.999998`, `oak_planks:32`, world time 15472) followed by event 1198 (`health=20`, planks gone, world time 15692); the second is corroborated by event 1224 (`health=8.000002`, `stick:1`) followed by event 1238 (`health=20`, empty inventory). The later 9/9 shelter, natural dawn, terminal event, and deadline pass cannot repair a death inside the active survival interval.

The fixed-code Probe 16 replication failed, leaving BM-011 at 1/3. Runner reported a later `empty_plan` at event 682 after one real Planner response contained an invalid control character, but independent causal ordering finds an earlier irreversible transition at action event 217 / monotonic 21178.031 / world time 10701. `build_shelter_cell` started with 16 oak planks at origin `(93,136,-36)`, placed two blocks, then returned `no grounded neighbor exists` while leaving those placements and reducing inventory to 14. Nine same-origin partial failures consumed or stranded enough material to reach nine planks, followed by fourteen same-goal material-threshold rejections before the malformed Planner output. No movement or alternate origin occurred inside that shelter root.

The current single hypothesis remains `bounded_shelter_partial_failure_atomicity`: a failed bounded shelter attempt must not leave partial final placements or consume the reserve needed for the next complete attempt, and the strict-M4 recovery path must select a grounded relocation before repeating the template. The offline backend/Agent gate now passes without changing the protocol, success threshold, or M1/M2 behavior. Exactly one fresh Probe 17 is authorized; BM-011 remains 1/3 until independent live evidence passes.

## G5 Preflight: Bounded Shelter Partial-Failure Atomicity

- Scope: strict-M4 `build_shelter_cell`, Agent recovery state, and shelter-phase Planner grounding only; the fixed protocol, G3 success verifier, goal order, deadline, and M1/M2 behavior are unchanged
- Mutation-free rejection: the bridge simulates all nine final placements and the temporary roof scaffold before equip, dig, or place; Probe 16's origin now returns zero placements with unchanged material inventory
- Unexpected failure: any block placed by the bounded action is removed in reverse order, material recovery is observed for up to two seconds, and residual blocks or missing inventory fail the atomicity check closed
- Atomicity scope: final placements and the selected material inventory; existing terrain clearing remains separately reported and is not claimed as a whole-world transaction
- Relocation: after an atomic failure, the bridge deterministically scans a maximum Chebyshev radius of six and vertical offset of two for a standable origin whose complete template preflight passes
- Agent boundary: relocation origin, centered movement target, radius, and offsets are validated before `m4_shelter_atomicity_recovery` is scheduled; malformed or out-of-bounds machine output clears the pending recovery
- Planner recovery: while a validated relocation is pending, the next shelter plan is exactly one canonical `move_to`; a failed move retains the recovery and a successful move clears it before template retry
- Offline tests: `tests/test_bot_server_m4_protocol.js` has 8/8 M4 cases and `tests/test_m4_shelter.py` has 18/18 cases, including exact Probe 16 geometry, rollback success/failure, bounded-output rejection, and relocation-before-retry
- Regression: 685 Python tests and 35 internal PASS cases across all six fixed Node suites pass; syntax compilation and `git diff --check` also pass
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`; reset and validation contract hashes remain unchanged
- Live authorization: exactly one fresh Probe 17 under the exact fixed profile is unlocked; no other live episode is authorized in this round

## G0 Offline Evidence: Active-Episode Death Continuity

- Probe 14 runner claim: `completed=true`, `terminal_survival_verified`, and `eligible=true`
- Independent rejection: Paper server stdout contains two `Singularity was slain by Zombie` messages at 00:34:41 and 00:35:04; diagnostic log SHA-256 is `9cbe6e2533298e1c989fb8bedb713df2498bccbf7682185aec47322e26351a4d`
- Canonical corroboration: observation transitions 1183 to 1198 and 1224 to 1238 reset health to 20 while dropping held inventory during active night
- Bridge source: `m4-player-lifecycle-verifier-v1` consumes Mineflayer `death` and `spawn` events and exposes cumulative totals plus episode-relative death, respawn, spawn, pending-respawn, and uninterrupted fields
- Reset binding: the M4 reset establishes one episode/level/protocol-bound baseline only after an initial Mineflayer spawn and rejects nonzero episode deltas; historical pre-reset deaths do not contaminate the fresh interval
- Canonical propagation: every strict-M4 observation carries a fresh lifecycle snapshot, while `m4_player_lifecycle` records the baseline and each deduplicated transition with validation status
- Terminal fail-closed behavior: Agent obtains a fresh lifecycle snapshot and emits `terminal_survival_verification` only for a valid zero-death, zero-respawn, uninterrupted interval
- Independent eligibility: all observation and lifecycle-event counters must be valid, baseline-consistent, monotonic, and zero; terminal observation, terminal event, and result lifecycle signatures must match
- Probe 14 fixture: a death followed by respawn, restored health 20, online bot, verified shelter, and dawn terminal claim is independently rejected; missing, rolled-back, event-only, and malformed evidence also fail closed
- Anti-spoof result: a final positive health value, online bot, verified shelter, or later respawn cannot erase an earlier active-episode death
- Protocol boundary: strict M4 only; M1/M2 fixed task semantics and evidence remain unchanged
- Offline regression: 685 Python tests and all six fixed Node suites pass; M4 bridge reset also rejects a missing initial-spawn baseline
- Protocol integrity: current SHA-256 `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`, reset contract `0df412101c5c01bf89b32e26d2d9beead7f9b64d10ba5de714caab51b1b63e52`, validation contract `bd2e7466d18d72927c7ca84a11736597a05eab5adf4b788627fe9377542d1e02`
- Live validation: Probe 15 passed the uninterrupted path; Probe 16 recorded six valid death/respawn transitions matching Paper, blocked terminalization after later respawns and shelter verification, and rejected the subsequent missing lifecycle snapshot
- Live authorization: the shelter atomicity gate now passes offline; exactly one fresh Probe 17 is authorized

## G5 Preflight: Verified Shelter Hostile Safe-State Grounding

- Scope: strict-M4 RuntimeSupervisor hostile evaluation and Agent audit logging only; GoalGenerator, G3 verifier contract, Planner, ActionVerifier, M1/M2 behavior, and protocol data are unchanged
- Trigger: complete pinned G3 shelter report, report and current observation in the same integral player cell, fully sealed entrance, `complete_local_collision_enclosure`, `direct_reachability=blocked`, empty `hostiles_inside`, and a report hostile count covering every actionable nearby hostile
- Grounding: suppress only the `hostile_nearby` decision for the proven blocked outside threat and continue evaluating health, hunger, night maintenance, deadlines, and return-to-base under their existing priorities
- Night behavior: an aligned `Remain in verified shelter until dawn` root stays active with `night_safety_maintenance`; no outward runtime emergency action executes and no competing hostile root is opened
- Audit: `m4_hostile_safe_state_grounding` records the hostile identity/cell, observed and verified player cells, verifier ID, contract hash, blocked reachability, suppressed action, selected surviving interrupt, and a deduplicated fingerprint
- Fail-closed exclusions: spoofed or incomplete reports, stale player cells, missing hostile coordinates, report count mismatch, reachable threats, hostiles inside the player cell, and non-M4 profiles
- Probe 13 replay: archived observation event 920 now returns `night_safety_maintenance`, `emergency_action=null`, hostile ID 1789, player cell `(107,140,-29)`, and `outward_move_suppressed=true`
- Offline tests: `tests/test_runtime_supervisor.py`; 15/15 cases pass, including exact Probe 13 reproduction and Agent no-action integration
- Regression: 679 Python tests and all six fixed Node suites pass; Python compilation and repository checks remain required before commit
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Live result: Probe 14 reached and preserved a verified shelter through dawn, but no hostile was within the verified safe state; `m4_hostile_safe_state_grounding` count was zero, so the prior failure did not recur and the new branch was not exercised live
- Next live authorization: superseded by the passing bounded-shelter atomicity gate above; exactly one Probe 17 is authorized

## G5 Preflight: Planner Transport Next-Cycle Recovery

- Scope: strict-M4 autonomous goal lifecycle only; Planner transport policy, protocol hash, goal priority, shelter verifier, and action execution are unchanged
- Trigger: `status=error`, no actions, `real_llm_call=false`, `schema_valid=false`, exact `single-attempt` evidence, one failed attempt, and an allowlisted connection/timeout exception chain
- Probe 12 coverage: `APIConnectionError -> ConnectError -> SSLEOFError`
- Recovery: emit `m4_planner_transport_recovery`, preserve the current goal, and retry planning from a fresh observation in the next autonomous cycle
- Retry boundary: same-call retry count remains zero; each failed call consumes one normal cycle and remains bounded by 40 per goal, 320 total, and the absolute episode deadline
- Fail-closed exclusions: authentication failures, real-response schema/JSON errors, non-transport exceptions, missing evidence, and all deadline errors
- Existing recovery: `planning_actions_missing` continues to use `m4_planner_output_recovery` and is unchanged
- Evidence fields: goal, cycle, Planner call ID, error type/chain, transport policy, goal-preserved flag, resume policy, deadline, and remaining budget
- Offline tests: `tests/test_m4_deadline.py`
- Regression: 675 Python tests, all six fixed Node suites, Python compilation, and `git diff --check` passed
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Live result: Probe 13 had zero transport errors, zero transport recoveries, and zero empty plans; the prior failure did not recur, while a later verified-shelter hostile flee became the new earliest blocker
- Next live authorization: satisfied by the strict-M4 hostile safe-state preflight above; exactly one Probe 14 is unlocked

## G5 Preflight: Exact Runtime Harness and Terminalization

- Scope: M4 runtime harness and terminal evidence only; the protocol, goal priority, bounded shelter action, maintenance cadence, and G3 verifier are unchanged
- Exact BM-011 profile: 1200-second episode timeout, 24 autonomous goals, 40 cycles per goal, and 320 total cycles
- Harness enforcement: PowerShell and Python defaults are protocol-derived; either runner rejects any runtime-limit mismatch before episode execution
- Eligibility enforcement: `manifest_runtime_limits` requires exact protocol equality rather than accepting a shortened preparation envelope
- Terminal event: `terminal_survival_verification` requires an `until dawn` maintenance goal, finite dawn-boundary machine time, positive finite health, an online bot bridge, and a complete pinned shelter report
- Result binding: `completed=true` and `termination_reason=terminal_survival_verified` are produced only from the Agent terminal event path
- Fail-closed behavior: missing/non-finite time, missing health, disconnection, or an incomplete/spoofed shelter report cannot terminalize the episode
- Offline tests: `tests/test_m4_protocol.py` and `tests/test_m4_shelter.py`
- Regression: 674 Python tests, all six fixed Node suites, PowerShell syntax parsing, Python compilation, and `git diff --check` passed
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Live result: Probe 12 used the exact profile; the harness fix passed, but BM-011 remained ineligible because an earlier Planner transport error abandoned the active dawn-maintenance goal
- Next live authorization: unlocked by the strict-M4 next-cycle Planner transport preflight above

## G5 Preflight: Maintenance Goal Lifecycle

- Scope: M4 verified-shelter maintenance only; max goals, max cycles, total cycles, deadline, priority order, and G3 verifier are unchanged
- Dusk boundary: `Enter and maintain verified shelter through nightfall` requires verified shelter and world time in `[12000, 23000)`
- Dawn boundary: `Remain in verified shelter until dawn` requires verified shelter and world time at or after 23000, or after natural wrap below 1000
- Pending behavior: one `wait` action capped at 15000 ms, then a fresh machine observation and runtime interrupt evaluation
- Root semantics: the current maintenance root remains active; pending safety is not logged as goal completion and does not allocate another goal slot
- Fail-closed behavior: missing/non-finite time or lost shelter verification cannot satisfy a boundary
- Evidence: `m4_maintenance_phase_grounding` records boundary, current world time, boundary state, and wait duration
- Offline tests: `tests/test_m4_shelter.py`
- Regression: 672 Python tests and all six fixed Node suites passed
- Protocol integrity: max goals remains 24, max cycles per goal remains 40, and protocol SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Historical live authorization: consumed by Probe 11; current authorization is governed by the reopened G0 gate above

## G5 Preflight: Bounded Shelter Action

- Scope: M4 shelter construction only; autonomous goal priority, task reconciliation, M1/M2 contracts, and the fixed G3 verifier are unchanged
- Action: `build_shelter_cell` with current machine `player_cell` origin and an allowlisted inventory material
- Final structure: four two-block-high wall columns plus one center roof, exactly nine current-episode structural placements
- Temporary support: one bounded roof scaffold is placed and removed inside the same action; minimum starting inventory is 10 blocks
- Grounding: Planner replaces unrelated shelter-plan expansion only after a trusted machine snapshot and material threshold; evidence is `m4_shelter_phase_grounding`
- Verification: ActionVerifier rejects stale origins, untrusted verifier reports, already-verified shelters, unsupported materials, and insufficient inventory
- Backend evidence: every final target has before/after state; cleared and temporary positions are reported separately
- Agent evidence: nine final positions enter `_m4_episode_block_delta` and must still pass `m4-sealed-cell-shelter-verifier-v1`
- Offline tests: `tests/test_m4_shelter.py` and `tests/test_bot_server_m4_protocol.js`
- Regression: 670 Python tests and all six fixed Node suites passed
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Historical live authorization: consumed by Probe 10; current authorization is governed by the reopened G0 gate above

## G5 Preflight: Craft Parameter Grounding

- Scope: M4 Planner output only; ActionVerifier, task reconciliation, M1/M2 contracts, and protocol hash are unchanged
- Canonical `craft`: nonempty `item`, with optional positive integer `count`
- Accepted normalization: `recipe` to `item` only when values are nonconflicting
- Rejected drift: unknown keys, missing/invalid item, `item`/`recipe` conflicts, booleans, fractions, zero, and negative counts
- Evidence: `m4_action_parameter_grounding` now reports `craft_action_count`, original parameter hash, alias list, and canonical parameters
- Prompt grounding: M4 fixed output contract now states `item` and forbids `recipe`
- Offline tests: `tests/test_m4_deadline.py`
- Regression: 667 Python tests and all six fixed Node suites passed
- Historical live authorization: consumed by Probe 9; current authorization is governed by the reopened G0 gate above

## G5 Preflight: Task Completion Readiness

- Scope: M4 autonomous loop and task lifecycle only; Planner schema, ActionVerifier, M1/M2 contracts, and protocol hash are unchanged
- Trigger: current machine observation satisfies every item/count in a task's pure `inventory` success criteria
- Transition: accepted or active task becomes completed with reason `machine_state_success_criteria_satisfied`
- Dependency effect: dependent craft/build tasks become schedulable before the next Planner context is assembled
- Evidence: `m4_task_state_reconciliation` records cycle, root goal, task ID/title, and machine-checkable criteria
- Fail-closed boundary: criteria containing flags, structure, action, result, position, observed names, or mixed keys are not auto-completed
- Protocol boundary: reconciliation is disabled unless `planner_protocol=m4-fixed-v1`
- Offline tests: `tests/test_memory_task_system.py`
- Regression: 665 Python tests and all six fixed Node suites passed
- Historical live authorization: consumed by Probe 8; current authorization is governed by the reopened G0 gate above

## G5 Preflight: Action Parameter Grounding

- Scope: M4 Planner output only; ActionVerifier, M1/M2 contracts, protocol hash, and provider controls are unchanged
- Canonical `dig`: finite top-level `x`, `y`, and `z`, with optional top-level `block` and positive `timeout_ms`
- Accepted normalization: `position.{x,y,z}` to top-level coordinates and `block_name` to `block` only when values are complete and nonconflicting
- Rejected drift: unknown keys such as `target`, incomplete/non-finite coordinates, top-level/nested coordinate conflicts, and `block`/`block_name` conflicts
- Evidence: `m4_action_parameter_grounding` is embedded in plan schema validation and accepted plan events
- Prompt grounding: the M4 fixed output contract now states the canonical shape and forbids aliases
- Offline tests: `tests/test_m4_deadline.py`
- Regression: 663 Python tests and 30 Node tests passed
- Protocol integrity: `m4-fixed-v1` SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Historical live authorization: consumed by Probe 7; current authorization is governed by the reopened G0 gate above

## G4 Offline Evidence

- Required cases: hostile, critical health, hunger, dusk shelter, and night safety maintenance
- Priority: hostile threat, critical health, hunger, unverified night shelter, verified night maintenance, dusk shelter, task deadline, and return-to-base
- Grounded actions: weapon equip followed by entity-ID attack, vector flee when unarmed, and verified inventory item use for health or hunger
- Pause semantics: a non-emergency autonomous root ends with `status=suspended` and `auto_goal_interrupted`, not `auto_goal_failed`
- Frontier semantics: proposed, accepted, active, waiting, and blocked tasks are preserved; trigger and recovery evidence carry the same paused task ID and trigger ID
- Takeover semantics: the matching GoalGenerator survival goal runs without recursively interrupting itself
- Recovery semantics: condition clearance emits exactly one `runtime_interrupt_recovery` with `resume_preserved_frontier`
- Hysteresis: repeated same-state checks emit maintenance under one trigger; dusk-to-night emits escalation under that trigger rather than another root transition
- Root exclusivity: strict integration observed only zero or one open root between every `goal_start` and `goal_end`
- Offline tests: `tests/test_runtime_supervisor.py`
- Live evidence: Probe 15 exercised one successful dusk-shelter trigger/recovery chain. Probe 16 exercised five hostile triggers and five emergency flee actions, but six deaths followed while shelter remained unverified, so the hostile case is a failed live observation rather than accepted G4 evidence. The verified-shelter outside-hostile safe-state branch remains unexercised live.

## G3 Offline Evidence

- Verifier: `m4-sealed-cell-shelter-verifier-v1`
- Contract SHA-256: `5660b2ea4cbfb8e09c3919db714006961e1eeb9ee7b7c8d8dfec8a3217c4479f`
- Strategy: `sealed_cell_v1`; one standable interior cell, four two-block-high sealed wall columns, and one full-block roof
- Machine input: exact 3x3x4 Mineflayer snapshot, 36 unique block coordinates, player position/cell, collision state, and nearby hostile positions
- Provenance: all eight wall blocks and the roof must match successful observed placement deltas from the current episode; pre-existing structures and partial attribution fail
- Path-risk rule: complete local collision enclosure plus overhead cover and no hostile in the interior cell; an unproven aperture fails closed
- Entrance evidence: all four boundary columns carry lower/upper coordinates and are recorded as fully sealed; exit requires a later controlled removal
- Natural alternatives: none approved in this baseline
- Runtime wiring: Agent records observed `place`, `dig`, and bounded-template deltas, attaches the report to every strict-M4 observation, logs only state changes, and sends a compact decision to Planner
- Acceptance wiring: GoalGenerator and GoalVerifier require the pinned verifier ID, contract hash, all checks, empty issues, 9/9 placement attribution, and sealed coordinate evidence
- Offline tests: `tests/test_m4_shelter.py` and `tests/test_bot_server_m4_protocol.js`
- Live evidence: Probe 15 built and preserved the complete sealed cell through eligible dawn. Probe 16's first shelter root produced nine partial `no grounded neighbor` failures and exhausted its complete-build reserve; a later emergency root eventually passed 9/9 at world time 20301, but only after six deaths, and the shelter was lost after dawn before a bridge timeout.

## G2 Live Evidence

### Probe 16: Replication Failed; Partial Shelter Failures Consumed the Build Reserve

- Episode: `m4_episode_20260713_015708_c2d96dd3`
- Session: `aae8c680-4f8`
- Preflight: passed with a fresh level and lifecycle baseline under unchanged protocol `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`
- G2: false because the completed evidence was deadline-ineligible; pre-dusk progress itself gained `oak_log:1` by world time 9861
- BM-011 eligible: false; accepted eligible successes remain 1/3
- Independent earliest blocker: action event 217 at monotonic 21178.031 / world time 10701; `build_shelter_cell` placed two blocks, failed on an ungrounded third position, left the partial structure, and changed inventory from 16 to 14 oak planks
- Shelter failure cascade: nine same-origin `no grounded neighbor` failures reduced the reserve to nine planks, then the same shelter root emitted fourteen material-threshold rejections without a relocation action; across the episode bounded shelter was 1/36 successful
- Runner-reported later transition: event 682 at monotonic 21379.171 ended the original shelter root with `empty_plan` after real call `llm-cab685fd8d7142d9` returned an invalid control character; it occurred after 23 shelter failures and does not displace the earlier material-loss transition
- Planner controls: 203 calls, 201 real, 200 schema-valid; one early connection error recovered next-cycle, one malformed real response, one deadline-bound final timeout, zero provider-control violations, and 537061 total tokens
- Hostile/death chain: five hostile triggers and five emergency flee actions preceded six Mineflayer death/respawn transitions; Paper independently recorded six matching deaths between 02:03:09 and 02:05:40
- Lifecycle gate: baseline plus six valid 1/1 through 6/6 transition events were canonical; a later missing snapshot after bridge loss emitted an invalid fail-closed lifecycle event, no terminal event was produced, and eligibility rejected all death/respawn and continuity checks
- Late shelter: one 9/9 bounded shelter finally passed at event 1487 / world time 20301 after all six deaths, then was lost after dawn at world time 23341; it cannot restore eligibility
- Goals: 15 total; 4 completed, 5 failed, and 6 interrupted
- Actions: 108 attempted and 29 successful; `build_shelter_cell` 1/36, `move_to` 9/53, `dig` 9/9, `craft` 2/2, `look_at` 1/1, and `wait` 7/7
- Deadline: Agent ended at 22299.750 and evidence ended at 22299.765 against deadline 22299.734; one Planner call/error plan returned 0.016 seconds late, no action executed after the deadline, and independent duration/no-post-deadline checks rejected the episode
- Skill attribution: skills remained off; selected/executed/quarantined counts were all zero
- Next hypothesis: `bounded_shelter_partial_failure_atomicity`; the subsequent offline gate passes and authorizes exactly one Probe 17, while this live result remains ineligible
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_015708_c2d96dd3/`

### Probe 15: First Independently Eligible BM-011 Success

- Episode: `m4_episode_20260713_012907_b900a160`
- Session: `bdf58b2b-51a`
- Preflight: passed under protocol `378689bc96d28580b2debcccb12efb4f955de38dd031e681ace529d4f75d157d`; lifecycle baseline established after the initial Mineflayer spawn with 0/0 episode death/respawn counts
- G2: passed; pre-dusk inventory gained `oak_log:2` and `dark_oak_sapling:1` by world time 9821
- BM-011 eligible: true; accepted eligible successes are now 1/3
- Lifecycle continuity: 84 active observations, one canonical baseline event, maximum death/respawn counts 0/0, no baseline drift, uninterrupted terminal state, and zero Paper death messages
- Planner controls: 42/42 real calls were schema-valid, zero reasoning bytes, maximum latency 10.750 seconds, and zero output or transport recoveries
- Goals: four roots; resource gathering was suspended by dusk, then shelter build, nightfall maintenance, and dawn maintenance completed with no failed root
- Interrupt: one `dusk_shelter_required` trigger at session index 137 and matching recovery at index 342; the paused frontier remained active and no concurrent root appeared
- Actions: 41 attempted and 40 successful; `move_to` 6/7, `dig` 4/4, `craft` 1/1, `build_shelter_cell` 1/1, and `wait` 28/28
- Shelter: pinned G3 verification passed at session index 317 / world time 11801 with all 9/9 placements and remained valid through terminal world time 23281
- Terminal: event index 849 passed with health/food 20, bot online, verified shelter, matching lifecycle signatures, and natural dawn
- Deadline: Agent ended at 20125.703 and canonical evidence ended at 20125.750 against deadline 20618.453, leaving 492.703 seconds; no post-deadline execution
- Skill attribution: skills remained off; selected/executed/quarantined counts were all zero
- First unrecovered transition: none
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_012907_b900a160/`

### Probe 14: Runner Eligible False Positive; Two Zombie Deaths Reopen G0

- Episode: `m4_episode_20260713_002858_94ea560e`
- Session: `2f005489-d89`
- Preflight: passed; manifest limits were exactly `1200/24/40`
- G2: passed; pre-dusk machine progress gained `oak_log:2`
- BM-011 accepted eligible: false; eligible successes remain 0/3 despite runner `eligible=true`
- Death continuity: Paper recorded zombie deaths at 00:34:41 and 00:35:04; canonical health/inventory reset transitions corroborate both, but no death event reached the session or eligibility gate
- First irreversible transition: after hostile interrupt event 1145, the aligned flee root's first real plan emitted `build_shelter_cell`; action event 1179 was rejected as a stale origin while the zombie closed to 1.1 blocks and health fell to about 8, followed by the first death before the next `move_to` executed
- Planner recovery: 80 calls, 78 real schema-valid responses, two single-attempt `APIConnectionError -> ConnectError -> ConnectError -> SSLEOFError` failures, and two matching `m4_planner_transport_recovery` events preserving the same goal; zero empty/output recoveries
- Actions: 78 attempted, 32 successful; all 10 digs and 12 waits succeeded, 4/5 crafts succeeded, and 1/43 bounded shelter builds succeeded
- Shelter: the emergency shelter root recovered after both deaths, passed the pinned G3 verifier with 9/9 placements at world time 17832, and remained verified through terminal world time 23172
- Safe-state retest: no hostile entered the verified-shelter threat window; zero `m4_hostile_safe_state_grounding` events, so the Probe 13 branch was not exercised live
- Terminal snapshot: machine event passed at world time 23172 with health/food 20, bot online, verified shelter, and `dark_oak_planks:3`; it is insufficient because uninterrupted survival was false
- Deadline: Agent ended at 16511.000 and evidence at 16511.046 against deadline 17010.046, leaving 499.000 seconds; no post-deadline execution
- Skill attribution: skills remained off; selected/executed/quarantined counts were all zero
- Evidence: `logs/benchmarks/m4/m4_episode_20260713_002858_94ea560e/`

### Probe 13: Natural Dawn Observed; Hostile Interrupt Exited Verified Shelter

- Episode: `m4_episode_20260712_234515_7644ff79`
- Session: `56274454-2cf`
- Preflight: passed; manifest limits were exactly `1200/24/40`
- G2: passed; pre-dusk machine progress gained `oak_log:2`
- BM-011 eligible: false; eligible successes remain 0/3
- Eligibility narrowed to three issues: missing `terminal_survival_verification`, missing matching terminal machine verification, and `completed=false`
- Planner controls: 98/98 real calls, 82 schema-valid plans, 16 `planning_actions_missing` recoveries, zero transport errors, zero `m4_planner_transport_recovery`, zero empty plans, and no provider-control violations
- Shelter: one bounded action eventually succeeded after eight recovered terrain/origin failures; G3 passed with 9/9 episode placements at world time 12592
- Maintenance: the same `Remain in verified shelter until dawn` root stayed active for 22 cycles and 21 successful waits before the hostile interrupt
- Earliest blocker: observation event 920 / interrupt event 933 / action event 943; a skeleton 5.1 blocks outside a fully sealed, direct-reachability-blocked shelter caused an outward `move_to`
- Safety delta: the emergency action moved 7.894 blocks, changed shelter verification from true to false, and suspended the dawn root at world time 22152
- Dawn: natural dawn was observed at event 1057, world time 23092, health 19, bot online, but shelter verification remained false and no terminal event was emitted
- Episode end: 24 goals consumed the exact goal budget at world time 5392 with 187.156 seconds of Agent budget remaining; 18 goals completed, 6 were interrupted, and none were reported failed
- Actions: 65 attempted, 49 successful; all 21 waits, 14 digs, and two crafts succeeded
- Deadline: eligible; no post-deadline action, plan, or Planner call
- Skill attribution: skills remained off; selected/executed/quarantined counts were all zero
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_234515_7644ff79/`

### Probe 12: Exact Runtime Profile Passed; Planner Transport Error Abandoned Dawn Root

- Episode: `m4_episode_20260712_230251_393445f7`
- Session: `90c6c4f5-6bb`
- Preflight: passed; manifest limits were exactly `1200/24/40`
- G2: failed only because the completed evidence crossed the absolute deadline; pre-dusk machine progress gained `oak_log:2` by world time 9862
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 231 calls, 229 real schema-valid calls, zero provider-control violations, and two transport failures; maximum successful-call latency was 13.093 seconds
- Shelter and maintenance: one bounded shelter action passed with 9/9 current-episode placements at world time 11282; the same verified shelter remained valid through world time 14902
- First unrecovered transition: Planner call event 506 / empty-plan event 511, call ID `llm-24dd4cd454db4e1e`, cycle 23 of `Remain in verified shelter until dawn`; one `APIConnectionError` caused `termination_reason=empty_plan` with more than 900 seconds remaining
- State at failure: health 20, food 20, `oak_planks:19`, `oak_log:1`, world time 14902, machine shelter verified, and one nearby hostile
- Secondary cascade: the next immediate-threat goal fled the verified cell; shelter verification was lost at time 15362, 11 rebuilds lacked grounded support, one rebuild timed out, and the Agent-side bridge disconnected
- Actions: 76 attempted, 25 successful; one craft, one successful bounded shelter build, eight successful waits, and 51 later failures
- Deadline: Agent ended 0.016 seconds late and manifest evidence 0.031 seconds late; one returned Planner error plan was recorded after the deadline, with no post-deadline action
- Terminal evidence: no `terminal_survival_verification`; terminal bot connection false, and zero-valued fallback observations failed natural-time progression and machine-terminal checks
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_230251_393445f7/`

### Probe 11: Maintenance Root Persisted; Shortened Harness Drift Exposed

- Episode: `m4_episode_20260712_224016_31e10f7d`
- Session: `a9cf79b4-53c`
- Preflight: passed
- G2: failed because terminal evidence crossed the deadline; pre-dusk inventory gained `oak_log:2`
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 21/21 real calls schema-valid, zero reasoning bytes, maximum latency 16.953 seconds
- Maintenance retest: one dawn-maintenance root remained active, two `m4_maintenance_phase_grounding` waits executed, and no replacement goal slot was allocated
- Shelter: bounded action succeeded with 9/9 placements; post-cleanup machine shelter verification remained true
- Terminal state: health 20, food 20, connected, world time 13943, night observed, next dawn not observed
- Runtime-profile finding: world time advanced about 4943 ticks under the nonconforming `240/4/8` harness; the fixed protocol already allows `1200/24/40`, so this run does not prove a protocol temporal-horizon failure
- Deadline: ineligible; Agent reached 9529.859 exactly and manifest evidence ended 0.062 seconds later; no new post-deadline action was started
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_224016_31e10f7d/`

### Probe 10: Bounded Shelter Passed; Goal Budget Ended Before Night

- Episode: `m4_episode_20260712_222631_806bb698`
- Session: `4e5911f8-7d3`
- Preflight: passed
- G2: passed; pre-dusk inventory gained `oak_log:3` by world time 9866
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 13/13 real calls schema-valid, zero reasoning bytes, maximum latency 7.281 seconds
- Shelter retest: six oak logs gathered, 24 planks crafted, one bounded action succeeded, temporary scaffold removed, and G3 verifier passed with 9/9 episode placements
- Actions: 11 attempted and 11 successful; one craft and one bounded shelter action
- First unrecovered transition: two one-cycle verified-shelter maintenance goals consumed goal slots 3 and 4, then event index 304 ended the autonomous loop before night
- Terminal state: health 20, food 20, connected, machine shelter verified, world time 11226; night and next dawn were not observed
- Deadline: eligible; Agent ended with 135.297 seconds and manifest evidence with 135.266 seconds remaining, with no post-deadline execution
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_222631_806bb698/`

### Probe 9: Craft Grounding Passed; Shelter Phase Did Not Start

- Episode: `m4_episode_20260712_061341_1b7218cd`
- Session: `79e7ed21-129`
- Preflight: passed
- G2: failed; pre-dusk inventory gained only `oak_sapling:2`, while the first oak log arrived after dusk
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 26/26 real calls schema-valid; one final deadline-bound call timed out, zero reasoning bytes, maximum successful-call latency 9.641 seconds
- Craft-grounding retest: one canonical craft succeeded and produced `oak_planks:16`; no recipe-alias rejection recurred
- Actions: 27 attempted, 19 successful, one successful craft, zero place actions
- First unrecovered transition: after observing 16 planks, Planner call `llm-05670ca498a34ebf` expanded into unrelated tool/furnace work and returned to gathering rather than starting the already-unblocked shelter build
- Interrupt audit: one dusk shelter trigger preserved the frontier and escalated under the same trigger at night, with no competing root
- Deadline: ineligible; the final Planner call timed out at 281785.500, 0.016 seconds after the absolute deadline, and no later action executed
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_061341_1b7218cd/`

### Probe 8: Task Reconciliation Passed; Craft Parameters Rejected

- Episode: `m4_episode_20260712_060223_239f1dde`
- Session: `dd883cea-eb9`
- Preflight: passed
- G2: report returned false because terminal evidence was deadline-ineligible; pre-dusk machine progress was present (`oak_log:3`, `oak_sapling:1` at world time 9943)
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 30/30 real schema-valid calls, zero reasoning bytes, maximum latency 10.295 seconds
- Task-reconciliation retest: one event completed seven fulfilled gather tasks at `oak_log:6`, and the next behavior advanced to craft
- Actions: 30 attempted, 17 successful; 11 craft attempts, zero successful crafts, zero shelter placements
- First unrecovered transition: event index 207 attempted `craft` with `recipe=oak_planks` instead of canonical `item=oak_planks`; ActionVerifier rejected it at monotonic 280930.390
- Interrupt audit: one dusk shelter trigger preserved the frontier and escalated under the same trigger at night, with no competing root
- Deadline: ineligible; Agent reached the absolute deadline and manifest evidence ended 0.015 seconds later; the deadline-bound final move was not replayed or reconnected
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_060223_239f1dde/`

### Probe 7: Action Grounding Passed; Task Readiness Did Not Converge

- Episode: `m4_episode_20260712_054638_ac6ac8de`
- Session: `b2f136c9-aa7`
- Preflight: passed
- G2: report returned false because terminal evidence was deadline-ineligible; pre-dusk machine progress itself was present (`oak_log:2`, `dark_oak_sapling:1` at world time 9889)
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 22/22 real schema-valid calls, zero reasoning bytes, maximum latency 6.280 seconds
- Action-grounding retest: 9/9 canonical `dig` actions passed ActionVerifier and succeeded; inventory reached `oak_log:11`
- Actions: 21 attempted, 15 successful, zero craft actions, zero place actions
- First unrecovered transition: with `oak_log:9` already observed at event index 366, Planner call `llm-1ef73e3cdfab47e3` at event index 376 continued the fulfilled `Gather 6 oak logs` task instead of advancing to craft/build
- Interrupt audit: one dusk shelter trigger suspended the resource goal and preserved its frontier; the same trigger escalated at night with no duplicate root, but no recovery occurred before termination
- Deadline: ineligible; the final deadline-bound `move_to` returned at 280160.234, 0.016 seconds after the absolute deadline, with no replay or reconnect
- Evidence: `logs/benchmarks/m4/m4_episode_20260712_054638_ac6ac8de/`

### Probe 6: M4 Plan Envelope Recovery and G2 Passed

- Episode: `m4_episode_20260711_231148_fb3a1544`
- Session: `e79d7321-799`
- Preflight: passed
- G2: passed; G3 shelter-verifier work is unlocked
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 32/32 real schema-valid Planner calls, zero reasoning bytes, maximum latency 10.546 seconds
- Plan-envelope retest: all 32 plans passed, zero `empty_plan` events, and zero `m4_planner_output_recovery` events; the prior failure did not recur
- Autonomous goals: 4; resource progression switched to dusk and night shelter priority
- Actions: 22 attempted and 2 successful; pre-dusk inventory gained `oak_log:1` and `dark_oak_sapling:1` by world time 9952
- First unrecovered transition: event index 138 rejected an alias-style `dig` using `block_name` plus nested `position`; canonical `dig` requires top-level coordinates and optional `block`
- Grounding audit: 17 alias-style `dig` rejections in total; an earlier rejection recovered, but the 16 rejections from event 138 onward did not, and no later action succeeded
- Reflection audit: 20 `failure_reflection_suppressed` events and zero legacy `failure_reflection` writes
- Interrupt audit: 11 unique deadline triggers, 11 matching recoveries, 96 unique expired tasks terminalized, no repeated trigger task, and 11 actions followed the first recovery
- Deadline: eligible; Agent ended at 256451.531 and manifest evidence ended at 256451.578, leaving 7.281 seconds before the absolute deadline with no post-deadline execution
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_231148_fb3a1544/`

### Probe 5: M4 Failure Reflection Suppressed

- Episode: `m4_episode_20260711_220626_c1555273`
- Session: `df0ff546-6c2`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 22/22 real schema-valid Planner calls out of 23 total calls, zero reasoning bytes, maximum latency 24.625 seconds
- Autonomous goals: 4; resource progression switched to dusk and night shelter priority
- Actions: 28 attempted and 22 successful; pre-dusk inventory gained `dark_oak_log:3`, terminal inventory reached `dark_oak_log:10`, and all required G2 recording fields were present
- Reflection retest: 6 `failure_reflection_suppressed` events and zero legacy `failure_reflection` writes; immediate replanning remained active
- First unrecovered transition: event index 160 emitted `empty_plan` for the explicit oak-log goal while `status=planning`; Planner prose treated six dark-oak logs as completion, but no actions or machine goal verification followed and the goal was abandoned
- Interrupt audit: 7 unique deadline triggers, 7 matching recoveries, 29 unique expired tasks terminalized, no repeated trigger task, and 5 action events followed the first recovery
- Deadline: ineligible; Agent ended at the absolute deadline and manifest evidence ended 0.094 seconds later, with one Planner call and error plan recorded at the boundary but no subsequent action
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_220626_c1555273/`

### Probe 4: Expired Task Lifecycle Recovery

- Episode: `m4_episode_20260711_213951_5e37c97d`
- Session: `c3e63af5-76d`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed for 17/17 real schema-valid Planner calls, zero reasoning bytes, maximum latency 10.608 seconds
- Autonomous goals: 4; resource progression switched to emergency shelter priority at night
- Actions: 19 attempted and 15 successful; terminal inventory gained `oak_log:4` and `dark_oak_log:4`, but pre-dusk inventory delta remained empty
- Interrupt retest: 7 unique deadline triggers, 7 recoveries, 28 expired tasks terminalized, no repeated trigger task, and actions resumed after the first recovery
- First unrecovered transition: a failed move at world time 9494 entered an unbounded, unlogged failure-reflection LLM call for 29.985 seconds; the next observation was after dusk at world time 10094
- Deadline: ineligible; Agent ended 0.016 seconds and manifest evidence ended 0.078 seconds after the absolute deadline, with one late Planner call and plan but no post-deadline action
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_213951_5e37c97d/`

### Probe 3: Bridge Action Budget Bound

- Episode: `m4_episode_20260711_183833_d5ef78a8`
- Session: `15173437-4b6`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed; 26/26 real schema-valid calls, zero reasoning bytes, maximum latency 12.781 seconds
- Autonomous goals: 4; priority moved from resource progression to dusk/night shelter preparation
- Actions: 6 attempted and 6 successful; pre-dusk inventory gained `oak_log:1` and `oak_sapling:1`
- Bridge retest: oak-log `dig` completed in 4.046 seconds with a 60-second transport bound; the bridge stayed connected
- First unrecovered transition: expired active task `af7fad99` interrupted action execution at monotonic 239869.781, then repeated 21 times without a task state transition
- Deadline: ineligible; manifest evidence ended 0.094 seconds after the absolute deadline, with no post-deadline action, plan, or Planner call
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_183833_d5ef78a8/`

### Probe 2: Provider Controls Pinned

- Episode: `m4_episode_20260711_180909_9129569c`
- Session: `e2c566f5-1b7`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: passed; 32/32 real schema-valid calls, zero reasoning bytes, maximum latency 10.391 seconds
- Autonomous goals: 4, all generated from `wood_reserve_below_target`
- Actions: 12 attempted, 4 successful; no qualifying pre-dusk inventory or block delta
- First unrecovered transition: `dig(103,140,-30)` timed out after 15.015 seconds and disconnected the Python bridge
- Deadline: eligible; Agent ended 10.234 seconds before the absolute deadline with no post-deadline execution
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_180909_9129569c/`

### Probe 1: Unpinned Provider Thinking

- Episode: `m4_episode_20260711_170144_4ce51e64`
- Session: `441d17a2-bde`
- Preflight: passed
- G2: failed
- BM-011 eligible: false; eligible successes remain 0/3
- Autonomous goals: 2, both generated from `wood_reserve_below_target`
- Actions: 1 attempted, 0 successful
- Machine-visible inventory/block progress: none
- First unrecovered transition: `pre_dusk_planning_window_exhausted`
- Evidence: `logs/benchmarks/m4/m4_episode_20260711_170144_4ce51e64/`

## Evidence Discipline

- One live episode per round.
- One root-cause hypothesis per round.
- At most one principal subsystem change per round.
- Every live result records unique episode, session, and level identities plus result/session hashes.
- Reset, time set, teleport, give, and gamemode operations are allowed only before `autonomous_start` and are forbidden in the active episode.
- Offline fixtures never count as live capability evidence.
- M4 completion requires BM-011 through BM-014 at 3/3 each. Work stops after M4 and does not enter M5.
