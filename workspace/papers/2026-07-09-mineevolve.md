# Paper Card: MineEvolve

**Title**: MineEvolve: Self-Evolution with Accumulated Knowledge for Long-Horizon Embodied Minecraft Agents
**Source**: https://arxiv.org/abs/2603.13131
**Date**: 2026
**Type**: Minecraft self-evolution / execution-feedback framework
**Core Problem**: Long-horizon Minecraft agents fail when static plans meet missing tools, blocked paths, GUI errors, or stagnant execution, and they need to turn those failures into reusable behavioral knowledge.
**Core Method**: Uses Monitor to type subgoal feedback, Inducer to derive skills and remedies, Curator to validate/merge/retrieve knowledge, and Adaptor to repair unfinished plan suffixes after repeated failure or stagnation.
**Memory / Task Mechanism**:
  - Converts state changes, inventory changes, failures, progress, and stagnation into structured feedback.
  - Separates successful skill induction from failed/stagnant remedy induction.
  - Uses accumulated knowledge to adapt the remainder of a plan rather than restarting blindly.
**Borrowable Points**:
  - Treat failed and stagnant executions as first-class learning signals, not just unsuccessful episodes.
  - Emit typed monitor feedback before curating new skills, memories, or policy patches.
  - Repair only the unfinished plan suffix after repeated failures.
**Singularity Adaptation**:
  - Added `self-evolution-report` to summarize progress, regression, stagnation, repeated failures, typed feedback counts, remedy candidates, and adaptor recommendations from session logs.
  - The report now discounts successful actions without observed state, inventory, or verifier deltas, recording no-progress successes and repeated success loops before any plan-suffix repair is considered.
  - The report now flags blocked/empty plans that fail before any executable action, and runtime LLM planning can fall back to deterministic prerequisite rules before the goal loop gives up.
  - `self_evolution_feedback` mirrors existing memory/action/discovery feedback payloads so later policies can consume execution knowledge safely.
**Next Action**: Re-run live M1/M2 after the blocked-plan fallback and compare zero-action failures, planner-fallback events, and no-progress success loops against the saved 2026-07-09 report.
