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
| G3 | Machine-checkable shelter or approved natural safe-state verification | ready |
| G4 | Hostile, health, hunger, dusk, and night interrupt continuity | locked |
| G5 | First eligible survival-to-dawn episode | locked |
| G6 | Three independent fresh eligible episodes | locked |

G0 passed offline validation. The autonomous loop, planner, verifier, skill/action suppression paths, bridge transport, session evidence, and independent eligibility gate share `episode_deadline_monotonic`. In-flight planner and verifier returns cannot resume execution, deadline-bound bridge actions are single-shot, and missing or unordered monotonic event evidence is ineligible.

G1 passed offline validation. GoalGenerator and Curriculum preserve the fixed order of immediate threat, critical health, hunger/food, shelter preparation, night safety maintenance, and tool/resource progression. Shelter safety requires machine-state verification, and every `auto_goal` event carries source, reason, priority, and priority class.

## Current Hypothesis

The M4 planning-status empty-plan hypothesis is confirmed and closed by the sixth G2 probe. All 32 real Planner calls were schema-valid, every plan passed the M4 plan-envelope check, no `empty_plan` occurred, and the next-cycle `planning_actions_missing` recovery path was not needed. The episode acquired `oak_log:1` and `dark_oak_sapling:1` before dusk at world time 9952, so G2 passed for the first time and G3 is unlocked.

The earliest unrecovered runtime transition is now session event index 138 at monotonic 256257.687. For cycle 6 of `Gather 6 oak logs for tools and shelter`, Planner call `llm-7f64b5bbb62f4bc8` returned a schema-valid planning envelope whose `dig` action used alias parameters `block_name` plus nested `position`. The canonical primitive requires top-level `x`, `y`, and `z`, with optional `block`, so ActionVerifier rejected the action without execution. Inventory remained `oak_log:1` and `dark_oak_sapling:1` while world time advanced from 9932 to 9952.

Later evidence does not displace this first transition. Seventeen alias-style `dig` actions were rejected in total; the first earlier rejection recovered through a valid `move_to` and `dig`, but all 16 rejections from event 138 onward were unrecovered. Twenty failed actions were reflection-suppressed with zero legacy reflection writes, and 11 unique task-deadline interrupts received 11 matching recoveries while terminalizing 96 unique expired tasks. The retained runtime hypothesis is `planner_action_parameter_grounding`, but gate order now requires offline G3 shelter-verifier work first. No further live episode or action-grounding patch is authorized until that verifier gate is ready.

## G2 Live Evidence

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
