# Paper Card: SVA Action Evaluation

**Title**: Look Before You Leap: Distilling Tree Search into Action Evaluation for Frozen VLA Models
**Source**: https://arxiv.org/abs/2607.03751
**Date**: 2026-07-04
**Type**: Test-time action evaluation for frozen VLA policies
**Core Problem**: Frozen VLA models can generate good actions in their candidate distribution, but pass@1 execution fails because the policy lacks a strong action evaluator.
**Core Method**: Uses simulation-time MCTS to collect return-labeled trajectories, distills them into a lightweight Q-value evaluator, and deploys by selecting among multiple candidate actions with an uncertainty-regularized score.
**Memory / Task Mechanism**:
  - Separate action proposal from consequence evaluation.
  - Use offline rollouts to create action-value supervision.
  - Deploy a lightweight evaluator without requiring simulator access at inference time.
**Borrowable Points**:
  - Use session logs and verifier outcomes to build Minecraft action-value datasets.
  - Rank multiple planner outputs by expected prerequisite satisfaction, safety, and progress.
  - Track pass@k-style evidence: whether good Minecraft actions exist among alternatives even when the first executed action fails.
**Singularity Adaptation**:
  - Current implementation starts with deterministic `ActionVerifier` status and score rather than learned Q-values.
  - Added `ActionCandidateSelector`, a conservative candidate selector that only replaces a planner action when the original is verifier-rejected and a feasible prerequisite repair is available.
  - Added `action-candidate-report` and saved `logs/benchmarks/action_candidate_m1_2026-07-09.json`; the current M1 replay has 200 actions, 0 original rejects, 0 replacements, and 0 unchanged rejects.
  - Added `ActionValueProfile` and `action-value-report`; `--action-value-feedback` now gives candidate scoring a small historical value bias without overriding verifier feasibility.
  - Reloaded PEAM-style failure-correction pairs as `value_repair` candidates, so logged recovery actions can compete with deterministic repair candidates after verifier rejection.
**Next Action**: Re-run on live M1/M2 retries where missing-material failures are likely, then add pass@k-style planner alternatives once action-value feedback has enough failed/recovery examples.
