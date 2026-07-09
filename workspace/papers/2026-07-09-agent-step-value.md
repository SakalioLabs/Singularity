# Paper Card: Agent Step Value

**Title**: Agent Step Value: State-Transition Measurement with State-Grounded LLM Evaluators
**Source**: https://arxiv.org/abs/2607.04419
**Date**: 2026-07
**Type**: Agent trace state-transition evaluation
**Core Problem**: Final trajectory success hides which individual actions helped or harmed progress, making it hard to improve agent policies from black-box traces.
**Core Method**: Measures each observed transition by comparing evaluator beliefs over a fixed candidate set before and after the action, producing an Agent Step Value for the transition.
**Memory / Task Mechanism**:
  - Treat action value as a state-transition property, not only a final success label.
  - Use bounded state projections so black-box traces can still be audited.
  - Preserve per-step credit for later policy, memory, and repair-candidate updates.
**Borrowable Points**:
  - Extend Singularity action-value reports beyond action success/failure.
  - Score Minecraft before/after observations for inventory deltas, visible-resource progress, safety, and goal-criterion movement.
  - Use step values to separate useful recovery actions from low-impact successful actions such as waiting.
**Singularity Adaptation**:
  - Current `action-value-report` is the non-parametric staging layer: it aggregates action signatures, outcomes, verifier statuses, task families, and failure-correction pairs.
  - `ActionValueProfile` can reload those pairs into `ActionCandidateSelector` as conservative `value_repair` candidates.
  - `action-value-report` now emits deterministic ASV-style `state_transition_value_items` when session logs contain before/after observations, labeling positive, negative, and no-progress transitions from inventory, movement, visible-resource, health, and danger deltas.
  - `action-value-report` now emits `transition_window_diagnostics` with transition coverage, action-local window counts, shared/wide observation windows, missing windows, and readiness hints before transition values can influence gates.
  - The current M1 baseline now diagnoses 198/198 transition windows as shared-observation attributions with 0 action-local windows; this is useful audit evidence, not yet a runtime policy update signal.
  - Runtime action events now carry compact action-local `pre_observation` and `post_observation` snapshots so new live logs can produce high-confidence transition values.
  - `ActionValueProfile` now treats ASV feedback as gated evidence: low-confidence transition items are skipped with reasons, while trusted transition scores are blended conservatively with outcome success rates for candidate ranking.
  - `action-value-transition-gate` adds an offline approval step for saved ASV feedback artifacts, requiring enough trusted action-local transition items and low overall low-confidence rates before transition values are considered runtime-ready.
  - `action-value-transition-evaluator-report` now compares deterministic Minecraft transition labels/scores against a configured state-grounded LLM evaluator using compact before/after state summaries.
  - Runtime `--action-value-feedback` loading can now require approved `--action-value-transition-gate` and `--action-value-transition-evaluator-report` artifacts; non-approved gates suppress ASV transition scores without discarding ordinary action outcome values.
  - `benchmark --action-value-transition-preflight` now checks the saved feedback/gate/evaluator bundle before live runs, so transition-scored benchmarks fail early when approval evidence is missing.
**Next Action**: Re-run M1/M2 with action-local pre/post observation logging, confirm `transition_window_diagnostics.action_local_transition_rate` rises and low-confidence/shared-window counts fall, then run `action-value-transition-gate` and `action-value-transition-evaluator-report --llm-evaluator` before runtime `--action-value-feedback` experiments.
