# Critical Transition Diagnosis

## Purpose

`minecraft_execution_dependency_graph_v1` diagnoses a failed Minecraft run at the level of behavioral transitions rather than raw log lines or the final error. It combines two research ideas:

- AgentRx treats agent correctness as guarded, step-indexed execution constraints with auditable evidence and asks for the first unrecoverable failure;
- AgentTether represents Observation-Belief-Action-Feedback cycles as Transition Units and follows temporal plus information-flow dependencies backward from a terminal symptom.

Singularity implements a deterministic Minecraft adaptation. It does not reproduce AgentRx's constraint-synthesis judge, AgentTether's learned HGT/Isolation Forest detectors, or either benchmark result.

## Transition Units

`minecraft_transition_unit_v1` gives every behavioral decision a stable identity. An action unit records:

- the preceding observation index and next feedback index;
- a plan identity, action position inside the plan, and a hash of any planner reasoning rather than raw chain-of-thought;
- omitted versus deliberately deferred plan-suffix counts, so a guarded navigation yield is not mislabeled as executor drift;
- canonical action family, argument keys, target signature, verifier status, and result status;
- compact before/after position, health, and inventory state;
- confirmed navigation/effect signals, typed violations, and recovery state.

Plans with no actions are also units. This follows AgentTether's allowance for an LLM response as the action in a unit and prevents zero-action terminal failures from disappearing from diagnosis.

## Execution Constraints

The first contract set is deterministic and auditable:

- supported action and required-argument schema;
- action-verifier rejection and bypass detection;
- backend/action failure signatures;
- `move_to` success only when observed position is within the target tolerance;
- re-observation before a world-changing action that depends on navigation;
- grounded and state-confirmed dig/craft effects when the trace exposes enough evidence;
- repeated identical failures or no-progress transitions;
- non-complete planner responses that expose no executable transition, plus plans whose declared actions never appear in execution logs.

Every violation carries a fixed category, severity, evidence fields, and a hashed recovery key. Free-form planner reasoning and raw error text are not copied into reports.

## Dependency Graph

Units receive directed edges for:

- temporal order;
- action order inside one plan;
- shared target;
- shared Minecraft artifact or inventory flow;
- repeated normalized error signature.

The localizer excludes violations that a later matching transition demonstrably repairs. It then scores remaining violations with direct severity, graph connectivity, and persistence, keeps the high-confidence frontier, and selects its earliest unit. This is `first_unrecovered_constraint_v1`, not a learned anomaly detector.

## Repair Memory Boundary

Each diagnosis can emit one `typed_repair_memory_candidate_v1` entry with a directive code such as:

- `verify_navigation_reached_before_dependent_action`;
- `produce_executable_or_prerequisite_recovery_action`;
- `verify_tool_feedback_against_world_state`;
- `stop_repeating_identical_failed_transition`.

Candidates are always `state=unresolved` and require evidence grounding, cooldown, and minimal intervention. Every report hard-codes planner guidance, automatic retry, runtime intervention, memory promotion, and skill mutation to false. Manual localization labels plus separate repair-outcome comparisons are still required before designing any runtime gate.

Manual JSON/JSONL labels use `session_id` or `case_id`, `critical_unit_ordinal` (or `critical_event_index`), `category`, and a non-authoritative `reviewer_id`. Reviewers can request `--include-graphs` when the compact evidence packet is insufficient. Labels affect agreement metrics only; they cannot promote a report.

## Navigation Contract Repair

Historical logs exposed a concrete bridge defect: `move_to` returned success after a fixed three-second loop even when the bot remained far from the target, and the wood planner immediately issued a dependent dig.

The bridge now uses its loaded Mineflayer pathfinder. X/Z-only requests use `GoalNearXZ`; explicit Y requests use `GoalNear`. Python omits an absent Y value instead of serializing it as `null`, while JavaScript also rejects null/blank coordinates defensively. Tolerance and timeout controls are forwarded end to end, the single-shot socket response budget includes the action timeout plus grace, and a transport timeout reconnects without replaying a potentially non-idempotent action. Completion is successful only when the final position is inside tolerance.

The rule planner emits only `move_to` for a distant tree and waits for the next observation cycle before digging. A duration-bounded `walk_to` may report useful partial motion, but the action controller marks an unreached result `requires_replan`; both goal-directed and autonomous actor loops then discard the remaining plan suffix after recording fresh state. The Transition Unit normalizer records that suffix as deliberately deferred rather than as an execution omission.

## Current Evidence

Five synthetic failed controls and one successful control provide fixed expected labels. The localizer matches 5/5 critical units and 5/5 categories; a final-violation recency baseline matches 3/5. These are synthetic results only.

`workspace/evals/critical_transition_m1_2026-07-10.json` replays the five tracked M1 failures. It normalizes all 200 action events, adds 400 planner-response units, and localizes all five failed boundaries: four begin with an empty non-terminal plan and one with repeated no-progress navigation. No manual critical-unit labels exist, so the report remains review-only and cannot support a runtime claim.
