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
  - The current M1 baseline marks all transition windows as low-confidence because old logs often share one after-observation across multiple actions; this is useful audit evidence, not yet a runtime policy update signal.
  - Runtime action events now carry compact action-local `pre_observation` and `post_observation` snapshots so new live logs can produce high-confidence transition values.
  - `ActionValueProfile` now treats ASV feedback as gated evidence: low-confidence transition items are skipped with reasons, while trusted transition scores are blended conservatively with outcome success rates for candidate ranking.
**Next Action**: Run the transition-value report on fresh M1/M2 logs, then compare deterministic deltas against a state-grounded LLM evaluator before allowing transition scores to directly update runtime action ranking.
