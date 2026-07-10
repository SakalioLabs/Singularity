# Self-Learning Roadmap

Updated: 2026-07-10

The bounded, evidence-gated skill-learning scope passed final acceptance. This result does not imply unrestricted continuous self-evolution.

## Current Learning Stage

**Executable with active lifecycle enforcement.** Three skills completed candidate, advisory, paired-live promotion, later-session retrieval/use, and attribution. Two remain executable; wooden-pickaxe was subsequently quarantined by the verified failure lifecycle.

## Closed-Loop Gap

The requested first-batch loop has no open acceptance edge. The next research gap is correction after quarantine: a corrected wooden-pickaxe must be a new version and repeat all paired-live gates before runtime use.

## Stage Results

### Candidate

- Three distinct GoalVerifier-confirmed M1 sources per skill.
- Before/after action transitions, postconditions, verifier version, session/environment provenance, and source hashes retained.
- Normalized typed templates deduplicate repeated episodes.
- Candidates have zero Planner or runtime influence.
- Automatic goal-end extraction was additionally live verified in session `9735e9d6-f9d`; the episode produced one synonymous candidate, merged it into canonical candidate `ef2c7be4`, created zero new queue records, and retained three unique template fingerprints.

### Advisory

- All three skills passed a live shadow run with zero influence.
- All three passed an advisory run that injected only bounded action types and directly executed zero actions.
- All three passed an unsupported-family or unavailable-skill fallback run.
- Controlled evaluation required explicit one-skill authorization and did not grant normal runtime permission.

### Executable

- Every skill passed three fresh-world baseline/candidate pairs with fixed Planner, backend, verifier, protocol, seed, initial state, goal, and budget.
- Source logs were finalized before hashing and rechecked during paired evaluation.
- Completion rates were 1.0 for every baseline and candidate arm.
- Failed actions, verifier rejects, and no-progress loops did not regress.
- Promotion created `1.0.1` and retained `1.0.0` as history/rollback metadata.
- Later runtime sessions selected, executed, completed, and attributed each skill at confidence 1.0.

## Experiment Results

| Skill | Source sessions | Valid pairs | Baseline completion | Candidate completion | Environment steps | Later runtime | Current status |
|---|---:|---:|---:|---:|---:|---|---|
| `learned:gather_wood` | 3 | 3 | 1.0 | 1.0 | 12 -> 6, stable in 3/3 pairs | `b9e1bb0e-88b` | executable, held-out validated |
| `learned:craft_crafting_table` | 3 | 3 | 1.0 | 1.0 | 3 -> 3, no regression | `4b6f10e7-6fc` | executable |
| `learned:craft_wooden_pickaxe` | 3 | 3 | 1.0 | 1.0 | 3 -> 3, no regression | `1ec21c1f-fd9` | quarantined after later controlled failures |

## Held-Out Transfer

- Training: gather 3 oak logs in three paired candidate sessions.
- Validation: three independent paired worlds under the fixed M1 protocol.
- Held-out: gather 2 oak logs with a shifted fixture in disjoint sessions.
- Baseline session `0432d494-c7d`: completion 1.0, 3 environment steps.
- Runtime session `6da981d0-e7c`: completion 1.0, 2 environment steps, attribution 1.0.
- Training/held-out session overlap: 0.
- Transfer gate: approved.
- This is task-state/environment-split transfer on pinned seed `12345`, not a new-seed claim.

## Failure Lifecycle

The wooden-pickaxe skill completed its positive loop before the failure experiment.

| Experiment | Verifier-visible failure | Task recovered | Lifecycle result |
|---|---|---:|---|
| `wooden-pickaxe-fault-01` | craft item missing | yes | executable, failure 1 |
| `wooden-pickaxe-fault-02` | unavailable place item | yes | demoted to advisory, failure 2 |
| `wooden-pickaxe-fault-03` | unavailable equip item | yes | quarantined, failure 3 |
| `wooden-pickaxe-quarantine-fallback-01` | no injection; quarantined skill is ineligible | yes | no selection/execution, ordinary Planner fallback |

Fault profiles are allowlisted research controls, are logged as `controlled_failure_only`, and cannot count toward promotion.

## Capability Evidence

- M1: `repeat_verified`, 5/5 benchmark tasks.
- M3 continual learning: `repeat_verified`, 3/3 distinct executable-skill sessions.
- M3 transfer support: approved held-out gate.
- Full project status remains incomplete because unrelated M2/M4/M5/M6/M7 milestones are outside this work.

## Next Experiments

1. Propose a corrected wooden-pickaxe contract as a new version; do not mutate or reactivate `1.0.1`.
2. Add held-out initial-inventory splits for both crafting skills.
3. Add a new-seed gather split before making any seed-generalization claim.
4. Extend the DSL only when a live task requires a new bounded operation.
5. Keep one target skill per paired experiment and preserve all negative integrity evidence.
