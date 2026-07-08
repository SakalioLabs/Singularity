# Paper Card: From Plan to Action

**Title**: From Plan to Action: How Well Do Agents Follow the Plan?
**Source**: https://arxiv.org/abs/2604.12147
**Date**: 2026
**Type**: Agent plan-compliance evaluation
**Core Problem**: Agent success does not prove the agent followed the provided plan; failures can also hide whether the plan was ignored, partially followed, followed out of order, or impossible to execute.
**Core Method**: Measures plan compliance across plan phase compliance, plan order compliance, and phase fidelity over large agent trajectories, showing that explicit plans and reminders can improve outcomes while poor or misaligned plans can hurt.
**Memory / Task Mechanism**:
  - Treat plan following as an observable trajectory property, not only as prompt intent.
  - Distinguish missing phases, order drift, and fidelity drift.
  - Use compliance evidence to decide whether to repair the plan, remind the agent, or change the execution policy.
**Borrowable Points**:
  - Add a plan-action audit to Singularity session logs before trusting benchmark success or failure.
  - Track whether planned actions are executed before the next plan, whether they occur in order, and whether runtime actions were unplanned.
  - Penalize empty executable plans separately from action-level mismatch.
**Singularity Adaptation**:
  - Added `plan-action-compliance-report` for session JSONL logs.
  - The report windows each `plan` event against subsequent `action` events until the next plan, then counts ordered matches, unordered matches, missing planned actions, unplanned actions, order violations, blocked plans, and empty plans.
  - Saved `logs/benchmarks/plan_action_compliance_m1_2026-07-09.json` as the current M1 baseline: the one action-producing trace follows its plans, while four failed traces are dominated by blocked empty plans.
**Next Action**: Re-run the report on live M1/M2 retries after blocked-plan fallback and use follow/precision/compliance deltas to decide whether to add plan reminders, action verifiers, or plan-repair gates.
