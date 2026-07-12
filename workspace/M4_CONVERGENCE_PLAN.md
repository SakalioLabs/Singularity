# M4 Autonomous Survival Convergence Plan

## Current Gate

- Protocol: `m4-fixed-v1`
- Protocol SHA-256: `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Current target: BM-011 Survive the first night
- Eligible successes: 0/3
- M4 canonical status: `not_run`
- M1, M2, and M3 regression baseline: `repeat_verified`

BM-012, BM-013, and BM-014 remain locked until BM-011 reaches 3/3 eligible live successes.

## Scope

The protocol is independent from M1/M2 task semantics. It reuses the pinned Paper runtime, bridge, machine evidence shape, content hashing, and anti-replay controls. It does not inherit peaceful difficulty, prepared inventory, terminal fixtures, or scripted intermediate goals.

The first BM-011 baseline keeps learned executable skills off. Built-in primitive actions and the LLM planner remain available. `survive_first_night` cannot execute as the root strategy, and quarantined skills are forbidden.

## Gate Ladder

| Gate | Requirement | State |
|---|---|---|
| G0 | Fixed protocol, fresh episode, natural time, one absolute deadline, independent eligibility | passed |
| G1 | Deterministic survival-goal priority cases | passed |
| G2 | One live preparation episode with machine-visible progress | passed_probe_6 |
| G3 | Machine-checkable shelter or approved natural safe-state verification | passed_offline |
| G4 | Hostile, health, hunger, dusk, and night interrupt continuity | passed_offline |
| G5 | First eligible survival-to-dawn episode | diagnose_probe_11_protocol_temporal_horizon |
| G6 | Three independent fresh eligible episodes | locked |

G0 passed offline validation. The autonomous loop, planner, verifier, skill/action suppression paths, bridge transport, session evidence, and independent eligibility gate share `episode_deadline_monotonic`. In-flight planner and verifier returns cannot resume execution, deadline-bound bridge actions are single-shot, and missing or unordered monotonic event evidence is ineligible.

G1 passed offline validation. GoalGenerator and Curriculum preserve the fixed order of immediate threat, critical health, hunger/food, shelter preparation, night safety maintenance, and tool/resource progression. Shelter safety requires machine-state verification, and every `auto_goal` event carries source, reason, priority, and priority class.

G2 passed in Probe 6. The Agent gained `oak_log:1` and `dark_oak_sapling:1` before dusk at world time 9952 under the fixed live protocol, with all 32 real Planner calls schema-valid and the absolute deadline intact.

G3 passed offline validation. `m4-sealed-cell-shelter-verifier-v1` consumes a complete 36-coordinate Mineflayer snapshot and accepts only a solid floor, two passable interior cells, four two-block-high full-block wall columns, a full-block roof, no hostile inside, complete coordinate evidence, and all nine structural positions attributed to successful placements in the current episode. No natural safe-point strategy is approved in this baseline.

G4 passed strict offline integration. RuntimeSupervisor applies the fixed hostile, critical-health, hunger, dusk-shelter, and night-safety order; Observer preserves hostile IDs and positions for grounded attack or flee actions. Agent records one trigger per condition, suspends rather than fails a non-emergency root, keeps its task frontier active, allows the aligned survival goal to act, emits a matching recovery when the condition clears, and never holds two root goals concurrently.

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

The new earliest unrecovered transition is the fixed protocol temporal horizon. The episode began from the pinned natural time near 9000 and ended at world time 13943 after the full 240 seconds. BM-011 requires a night observation followed by the next dawn boundary at 23000 or natural wrap below 1000. The observed 4943-tick advance is approximately 20.6 ticks/second; reaching 23000 from 9000 requires about 680 seconds before setup margin. Therefore the current 240-second deadline cannot produce eligible natural-dawn evidence even with perfect shelter and survival. The next round must revise only the fixed M4 temporal horizon and matching bounded maintenance cadence, without time commands, tick acceleration, or eligibility relaxation.

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
- Protocol integrity: max goals remains 4, max cycles per goal remains 8, and protocol SHA-256 remains `a3ff6b9d39fa4955b4c52739f9059ae5969b82c74c4d33d751c79aa7f3b7f202`
- Live authorization: one fresh G5 BM-011 episode; stop after evidence generation and diagnose its first unrecovered transition

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
- Live authorization: one fresh G5 BM-011 episode; stop after evidence generation and diagnose its first unrecovered transition

## G5 Preflight: Craft Parameter Grounding

- Scope: M4 Planner output only; ActionVerifier, task reconciliation, M1/M2 contracts, and protocol hash are unchanged
- Canonical `craft`: nonempty `item`, with optional positive integer `count`
- Accepted normalization: `recipe` to `item` only when values are nonconflicting
- Rejected drift: unknown keys, missing/invalid item, `item`/`recipe` conflicts, booleans, fractions, zero, and negative counts
- Evidence: `m4_action_parameter_grounding` now reports `craft_action_count`, original parameter hash, alias list, and canonical parameters
- Prompt grounding: M4 fixed output contract now states `item` and forbids `recipe`
- Offline tests: `tests/test_m4_deadline.py`
- Regression: 667 Python tests and all six fixed Node suites passed
- Live authorization: one fresh G5 BM-011 episode; stop after evidence generation and diagnose its first unrecovered transition

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
- Live authorization: one fresh G5 BM-011 episode; stop after evidence generation and diagnose its first unrecovered transition

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
- Live authorization: one fresh G5 BM-011 episode; stop after evidence generation and diagnose its first unrecovered transition

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
- Live evidence: none; prior Probe 6 task-deadline events remain non-G4 observations and do not count toward this gate

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
- Live evidence: none; G3 is an offline deterministic gate and does not count toward BM-011

## G2 Live Evidence

### Probe 11: Maintenance Root Persisted; 240 Seconds Cannot Reach Dawn

- Episode: `m4_episode_20260712_224016_31e10f7d`
- Session: `a9cf79b4-53c`
- Preflight: passed
- G2: failed because terminal evidence crossed the deadline; pre-dusk inventory gained `oak_log:2`
- BM-011 eligible: false; eligible successes remain 0/3
- Planner controls: 21/21 real calls schema-valid, zero reasoning bytes, maximum latency 16.953 seconds
- Maintenance retest: one dawn-maintenance root remained active, two `m4_maintenance_phase_grounding` waits executed, and no replacement goal slot was allocated
- Shelter: bounded action succeeded with 9/9 placements; post-cleanup machine shelter verification remained true
- Terminal state: health 20, food 20, connected, world time 13943, night observed, next dawn not observed
- Temporal proof: world time advanced about 4943 ticks in 240 seconds; natural progression from pinned 9000 to dawn 23000 requires about 680 seconds before margin
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
