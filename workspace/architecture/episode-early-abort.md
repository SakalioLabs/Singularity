# Recall-Controlled Episode Viability

## Purpose

Long Minecraft goals can consume 80-100 planner cycles after a trajectory has stopped making useful progress. `behavior_surface_v1` adds a bounded, evidence-gated decision about whether another planner cycle is justified.

It is inspired by *Doomed from the Start* (arXiv:2607.06503), but it is not a reproduction of that paper's hidden-activation probe. Hosted model APIs do not expose the required residual-stream activations.

## Signal Contract

The scorer reads only typed runtime evidence:

- action success and failure rates;
- deterministic action-verifier rejects;
- structured error-event density;
- repeated canonical action signatures;
- observed inventory or position progress;
- plans that yielded no action;
- explicit blocked or empty-plan events.

Goal text, planner reasoning, reflection text, and backend error strings do not affect the score. The persisted gate contains thresholds and hashed task identities, not raw prompt content.

## Evidence Pipeline

1. Reconstruct complete `goal_start` to `goal_end` trajectories.
2. Keep calibration, validation, and test sessions disjoint, with one goal episode per independent session and no duplicated input paths.
3. Calibrate each round's smallest threshold whose one-sided Clopper-Pearson survival lower bound meets its recall budget.
4. Search recall-budget vectors on validation data under a global success-recall certificate.
5. Evaluate the selected vector once on held-out test data.
6. Approve active abort only when test recall is certified, failed episodes are actually shortened, and all evidence is complete `live_trace` data.

The saved policy includes a canonical payload hash plus per-source filename, path fingerprint, content SHA-256, and byte count. It does not copy goals or event bodies into the gate. Runtime reload rechecks the hash plus all certificate, split-integrity, evidence-count, and provenance invariants instead of trusting a mutable `readiness` field.

At confidence `alpha=0.05`, a target recall of 0.95 requires at least 59 successful episodes even for a no-op policy. If the data cannot support the promise, the gate abstains.

## Runtime Modes

- `off`: no scoring and no behavior change. This is the default.
- `shadow`: log configured probes and `would_abort` decisions, but continue execution.
- `active`: terminate the current goal only when an approved gate and exact planner/backend/verifier/task-stream/seed identity match.

Health, hostile, deadline, and return-to-base interrupts remain separate fast safety mechanisms. Early abort does not retry automatically, restore world state, bypass goal verification, or claim that a failed goal is complete.

## Current Evidence

Deterministic tests cover calibration, sample complexity, prompt-text independence, split integrity, provenance mismatch, shadow behavior, active Agent logging, and runtime-profile validation. These are offline controls, not Minecraft capability evidence. Fresh M1/M2 live trajectories are still required before any active gate can be approved.
