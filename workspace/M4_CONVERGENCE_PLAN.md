# M4 Autonomous Survival Convergence Plan

## Current Gate

- Protocol: `m4-fixed-v1`
- Protocol SHA-256: `031d35021141e6b4dc34fa7151a6c9cdb8154454b6d9e8187d1dfb337523a2ce`
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
| G2 | One live preparation episode with machine-visible progress | in_progress |
| G3 | Machine-checkable shelter or approved natural safe-state verification | locked |
| G4 | Hostile, health, hunger, dusk, and night interrupt continuity | locked |
| G5 | First eligible survival-to-dawn episode | locked |
| G6 | Three independent fresh eligible episodes | locked |

G0 passed offline validation. The autonomous loop, planner, verifier, skill/action suppression paths, bridge transport, session evidence, and independent eligibility gate share `episode_deadline_monotonic`. In-flight planner and verifier returns cannot resume execution, deadline-bound bridge actions are single-shot, and missing or unordered monotonic event evidence is ineligible.

G1 passed offline validation. GoalGenerator and Curriculum preserve the fixed order of immediate threat, critical health, hunger/food, shelter preparation, night safety maintenance, and tool/resource progression. Shelter safety requires machine-state verification, and every `auto_goal` event carries source, reason, priority, and priority class.

## Current Hypothesis

The earliest blocker is the G2 live-preparation evidence path. The next change is limited to a full M4 preflight/runtime manifest and one fresh BM-011 preparation episode that measures autonomous goals, resource and crafting progress, shelter intent, time remaining, inventory/world deltas, and repeated no-progress behavior. It does not count as an eligible first-night success unless the complete BM-011 gate independently passes.

## Evidence Discipline

- One live episode per round.
- One root-cause hypothesis per round.
- At most one principal subsystem change per round.
- Every live result records unique episode, session, and level identities plus result/session hashes.
- Reset, time set, teleport, give, and gamemode operations are allowed only before `autonomous_start` and are forbidden in the active episode.
- Offline fixtures never count as live capability evidence.
- M4 completion requires BM-011 through BM-014 at 3/3 each. Work stops after M4 and does not enter M5.
