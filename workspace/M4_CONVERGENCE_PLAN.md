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
| G5 | First eligible survival-to-dawn episode | diagnose_probe_7_task_readiness_grounding |
| G6 | Three independent fresh eligible episodes | locked |

G0 passed offline validation. The autonomous loop, planner, verifier, skill/action suppression paths, bridge transport, session evidence, and independent eligibility gate share `episode_deadline_monotonic`. In-flight planner and verifier returns cannot resume execution, deadline-bound bridge actions are single-shot, and missing or unordered monotonic event evidence is ineligible.

G1 passed offline validation. GoalGenerator and Curriculum preserve the fixed order of immediate threat, critical health, hunger/food, shelter preparation, night safety maintenance, and tool/resource progression. Shelter safety requires machine-state verification, and every `auto_goal` event carries source, reason, priority, and priority class.

G2 passed in Probe 6. The Agent gained `oak_log:1` and `dark_oak_sapling:1` before dusk at world time 9952 under the fixed live protocol, with all 32 real Planner calls schema-valid and the absolute deadline intact.

G3 passed offline validation. `m4-sealed-cell-shelter-verifier-v1` consumes a complete 36-coordinate Mineflayer snapshot and accepts only a solid floor, two passable interior cells, four two-block-high full-block wall columns, a full-block roof, no hostile inside, complete coordinate evidence, and all nine structural positions attributed to successful placements in the current episode. No natural safe-point strategy is approved in this baseline.

G4 passed strict offline integration. RuntimeSupervisor applies the fixed hostile, critical-health, hunger, dusk-shelter, and night-safety order; Observer preserves hostile IDs and positions for grounded attack or flee actions. Agent records one trigger per condition, suspends rather than fails a non-emergency root, keeps its task frontier active, allows the aligned survival goal to act, emits a matching recovery when the condition clears, and never holds two root goals concurrently.

## Current Hypothesis

Probe 7 confirms the M4 action-parameter-grounding fix in live execution. All 22 real Planner calls were schema-valid, every `dig` used canonical top-level coordinates and optional `block`, all nine `dig` actions passed ActionVerifier, and nine succeeded. The Agent accumulated 11 oak logs, so Probe 6's alias rejection did not recur.

The new earliest unrecovered transition is task-completion/readiness grounding. At session event index 366 the machine observation already contained `oak_log:9`. Planner call `llm-1ef73e3cdfab47e3` at index 376 nevertheless treated the fulfilled `Gather 6 oak logs` task as ready and emitted another `dig` rather than the dependent craft/build step. The next successful action raised inventory to 10 logs, and subsequent plans continued gathering. Across 21 actions there were 15 successes but zero crafting actions and zero placement actions; the shelter remained unverified.

The dusk interrupt itself behaved coherently: one `dusk_shelter_required` trigger suspended the resource goal, preserved its frontier, selected the aligned shelter goal, and escalated the same trigger to `night_shelter_required` without creating a competing root. The run ultimately consumed the remaining 58.14 seconds in a deadline-bound `move_to`, ended 0.016 seconds after the absolute deadline, and was independently rejected. The next round may change only the task-completion/readiness subsystem and must pass offline tests before another single live episode.

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
