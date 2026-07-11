# M4 Autonomous Survival Convergence Plan

## Current Gate

- Protocol: `m4-fixed-v1`
- Protocol SHA-256: `a44723f6bd86110a1a5d0ead3378850cd906f9d272c27f3f7fed5fa87db7d1ce`
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
| G0 | Fixed protocol, fresh episode, natural time, one absolute deadline, independent eligibility | in_progress |
| G1 | Deterministic survival-goal priority cases | pending |
| G2 | One live preparation episode with machine-visible progress | locked |
| G3 | Machine-checkable shelter or approved natural safe-state verification | locked |
| G4 | Hostile, health, hunger, dusk, and night interrupt continuity | locked |
| G5 | First eligible survival-to-dawn episode | locked |
| G6 | Three independent fresh eligible episodes | locked |

G0 currently has a pinned protocol and passing offline anti-forgery/deadline eligibility tests. It remains in progress until the autonomous loop, planner, action controller, and post-run evidence gate share `episode_deadline_monotonic`.

## First Hypothesis

The earliest blocker is deadline ownership: `run_goal` has M2 goal-level checks, but `run_autonomous` has no episode-level monotonic deadline and does not bind Planner/action budgets to one absolute value. The next change is limited to deadline propagation and suppression. No live BM-011 episode may run before its deterministic tests pass.

## Evidence Discipline

- One live episode per round.
- One root-cause hypothesis per round.
- At most one principal subsystem change per round.
- Every live result records unique episode, session, and level identities plus result/session hashes.
- Reset, time set, teleport, give, and gamemode operations are allowed only before `autonomous_start` and are forbidden in the active episode.
- Offline fixtures never count as live capability evidence.
- M4 completion requires BM-011 through BM-014 at 3/3 each. Work stops after M4 and does not enter M5.
