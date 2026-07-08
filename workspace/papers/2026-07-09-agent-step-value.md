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
  - The next refinement is ASV-style before/after state-transition scoring so high-value feedback is based on progress, not only result success.
**Next Action**: Add state-delta value labels to `action-value-report` using pre/post observation windows and `GoalVerifier`-style bounded checks.
