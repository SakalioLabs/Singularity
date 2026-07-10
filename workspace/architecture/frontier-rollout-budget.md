# Fixed-Budget Frontier Rollout Control

## Purpose

`frontier_information_budget_v1` turns curriculum candidates and task-readiness nodes into a conserved planner-round slate. It addresses a gap between three existing mechanisms:

- curriculum scores rank goals but do not allocate a matched compute budget;
- task readiness identifies blocked prerequisites but selects only one task;
- recall-controlled episode abort can save planner rounds but previously had no destination ledger.

The controller is inspired by IGRPO's soft information-weighted expansion, BAGEN's progressive remaining-budget intervals, MineExplorer's hidden-prerequisite failures, and AgentTether's dependency-aware failure localization. It is an inference-time deterministic controller, not a reproduction of any paper's training algorithm.

## Branch Contract

Each branch has a stable identifier and typed fields:

- source and category;
- ready, eligible, selected, and safety-reserved flags;
- prerequisite-closure count;
- verifier-reject and no-progress counts;
- novelty and frontier-gap counts;
- risk, attempts, failures, and unresolved dependency counts;
- lower/upper estimated planner rounds.

Free-form planner reasoning does not affect allocation. Curriculum titles remain available transiently for planner context, while evidence traces store branch identifiers and typed signals.

## Allocation

Both policies receive exactly the same integer pool:

- `uniform_frontier_budget_v1` is the fixed-control baseline;
- `frontier_information_budget_v1` applies a softmax-like weight over transparent branch scores and converts expected shares to integers with deterministic largest-remainder rounding;
- an exploration floor gives each eligible branch a round when the pool can afford it;
- blocked and urgent safety-reserved branches receive no exploratory rollout rounds. Immediate safety remains the runtime supervisor's responsibility;
- every report records total, consumed, available, recovered, allocated, and unallocated rounds and verifies conservation.

Recovered rounds are a subpool of the original ledger. They never increase the total. An active recall-qualified episode abort may create a recovery credit equal to the unused goal rounds; a later frontier allocation can consume only the selected branch's allocated share.

## Budget Intervals

`frontier_budget_interval_v1` emits a lower/upper remaining-round estimate or an infeasibility alert. The current estimator is deterministic and heuristic. Every raw allocation therefore records `interval_calibrated=false`.

Promotion uses successful candidate outcomes from independent paired sessions:

1. compare actual rounds against the pre-execution interval;
2. compute interval coverage and optimistic misses;
3. compute an exact one-sided Clopper-Pearson coverage lower bound;
4. require the lower bound to meet the configured target before planner-facing use.

## Evidence Gate

`frontier-rollout-budget-report` accepts either offline case files or paired uniform/information JSONL sessions. Only raw paired session logs can authorize advisory runtime context. A live gate requires:

- exact planner, action backend, verifier, task stream, seed, total budget, temperature, and exploration-floor controls;
- distinct baseline and candidate sessions for every pair;
- successful connect and complete terminal boundaries;
- identical branch inputs and ledgers;
- recorded integer allocations that exactly replay under both policies;
- no completion, verifier-reject, action-failure, prerequisite-resolution, or unsafe-action regression under configured thresholds;
- deterministic action verification enabled for every candidate outcome and again at advisory runtime;
- positive allocation gain on branches that later resolve prerequisites;
- enough held-out interval observations, a passing coverage lower bound, and bounded optimistic misses;
- a matching approved episode-abort gate and source-event fingerprint whenever recovered rounds are claimed;
- complete filename/path/content manifests and a canonical whole-gate integrity hash.

Structured case files and built-in controls can exercise schemas and allocation mechanics but cannot impersonate live evidence.

## Runtime Modes

- `off`: no allocation work. Default.
- `shadow`: compute and log the slate. No gate is required because planner input and behavior are unchanged.
- `advisory`: add the fixed ledger and top branch intervals to LLM planner context only after an approved, exact-provenance gate loads.

All modes hard-code:

- `automatic_retry_allowed=false`;
- `automatic_branch_execution_allowed=false`;
- `budget_extension_allowed=false`.

Action verification, goal verification, emergency interrupts, and task readiness remain authoritative.

## Current Evidence

Deterministic built-ins cover shelter logs, torch coal, and safe-route prerequisites. Under an eight-round pool, information allocation differs from uniform, preserves the full budget, and gives more rounds to the branch labeled by the later synthetic resolution. These are offline controls only. No tracked live Minecraft report currently qualifies advisory mode.
