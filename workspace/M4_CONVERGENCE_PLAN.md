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
| G2 | One live preparation episode with machine-visible progress | failed_probe_3 |
| G3 | Machine-checkable shelter or approved natural safe-state verification | locked |
| G4 | Hostile, health, hunger, dusk, and night interrupt continuity | locked |
| G5 | First eligible survival-to-dawn episode | locked |
| G6 | Three independent fresh eligible episodes | locked |

G0 passed offline validation. The autonomous loop, planner, verifier, skill/action suppression paths, bridge transport, session evidence, and independent eligibility gate share `episode_deadline_monotonic`. In-flight planner and verifier returns cannot resume execution, deadline-bound bridge actions are single-shot, and missing or unordered monotonic event evidence is ineligible.

G1 passed offline validation. GoalGenerator and Curriculum preserve the fixed order of immediate threat, critical health, hunger/food, shelter preparation, night safety maintenance, and tool/resource progression. Shelter safety requires machine-state verification, and every `auto_goal` event carries source, reason, priority, and priority class.

## Current Hypothesis

The bridge action-budget hypothesis is confirmed and closed by the third G2 probe. All 6 actions succeeded, including an oak-log `dig` that retained `timeout_ms=60000`, completed in 4.046 seconds, removed the observed target, and produced `oak_log:1`. The bridge remained connected. All 26 real schema-valid Planner calls also retained the pinned provider controls, emitted zero reasoning bytes, and completed within 12.781 seconds.

The preparation report surfaces the first goal's eventual `max_cycles` outcome, but the session contains an earlier unrecovered runtime transition. At monotonic 239869.781, active task `af7fad99` (`Find and move to oak logs`) emitted `task_deadline_elapsed` with `seconds_left=-1.8`. `_handle_runtime_interrupt` recorded the interrupt but did not terminate, pause, replace, or otherwise recover the expired task. `TaskSystem.get_next_task()` therefore selected the same active task before later actions, producing 21 identical interrupts through cycle 26 across resource, dusk-shelter, and night-shelter goals. No action followed the first interrupt.

The single current hypothesis is that an expired-task interrupt lacks a one-shot task lifecycle transition, creating permanent actor preemption. The next change is limited to deterministic expired-task recovery in the runtime interrupt/task lifecycle path, with focused offline tests before one fresh G2 episode in a later round. Planner wording, shelter construction, and other task scheduling behavior remain secondary observations and are not changed in this round.

## G2 Live Evidence

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
