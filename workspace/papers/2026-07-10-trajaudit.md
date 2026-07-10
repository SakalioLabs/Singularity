# Paper Card: TrajAudit

**Title**: TrajAudit: Automated Failure Diagnosis for Agentic Coding Systems

**Source**: https://arxiv.org/abs/2605.26563

**Date Reviewed**: 2026-07-10

**Core Method**: Uses pattern-based filtering and test-failure priors to reduce noisy long execution trajectories before an investigator agent retrieves additional evidence and produces a diagnosis.

**Evidence**:
- Introduces RootSE with 93 real agentic software-maintenance failures.
- Reports more than 24.4 percentage points higher localization accuracy than evaluated baselines.
- Reports at least 18% lower token consumption by filtering irrelevant trajectory content and retrieving details on demand.
- Evidence is specific to repository-level coding agents, not embodied game execution.

**Useful Transfer**:
- Preserve a full sanitized dependency graph outside the model-visible diagnosis packet.
- Give the reviewer only the peak transition plus minimal adjacent/dependency-linked evidence by default.
- Make full-graph export explicit rather than flooding every report with routine transitions.

**Project Action**: `critical-transition-report` defaults to compact per-diagnosis evidence packets and graph summaries. `--include-graphs` exposes all sanitized units and dependency edges for offline audit. Raw planner reasoning is represented only by presence and a fingerprint.

**Non-Claim**: Singularity has not implemented TrajAudit's coding investigator or reproduced RootSE results. The transfer is limited to noise filtering and on-demand graph disclosure.
