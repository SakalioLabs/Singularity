# Paper Card: Progressive Crystallization

**Title**: Progressive Crystallization: Turning Agent Exploration into Deterministic, Lower-Cost Workflows in Production

**Source**: https://arxiv.org/abs/2607.07052

**Date Reviewed**: 2026-07-10

**Core Method**: Treats agent exploration as workflow discovery, then promotes repeatedly validated behavior through agentic, hybrid, and deterministic execution stages while demoting regressions.

**Evidence**:
- Reports a production AIOps deployment processing tens of thousands of incidents per month.
- Deterministic execution reportedly grew from 0% to 45% over eight months.
- Per-incident agent cost reportedly fell by more than 70% despite incident volume doubling.
- The evidence is operational and domain-specific; it is not Minecraft evidence.

**Useful Transfer**:
- Offline successful trajectories should become planner guidance before they gain direct execution authority.
- Promotion and regression checks must be entry-scoped so one workflow cannot certify an unrelated cache entry.
- Deterministic reuse should require repeated live success, stable plan matching, and zero verifier regression.
- A regressing workflow should automatically fall back to agentic execution without deleting its audit trail.

**Project Action**: Upgraded the plan-transition cache to `progressive_workflow_crystallization_v1`. Offline entries are hybrid-only, three distinct matched live sessions are required by default for deterministic reuse, and entry-scoped action, goal, or verifier regressions demote only the affected workflow.
