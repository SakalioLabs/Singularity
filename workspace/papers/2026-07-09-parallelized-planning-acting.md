# Paper Card: Parallelized Planning-Acting

**Title**: Parallelized Planning-Acting for Efficient LLM-based Multi-Agent Systems in Minecraft
**Source**: https://arxiv.org/abs/2503.03505
**Date**: 2025-03-05; revised 2026-03-07
**Type**: Minecraft multi-agent execution architecture
**Core Problem**: Minecraft MAS agents often serialize high-latency LLM planning before low-level execution, which makes dynamic collaboration brittle when the world changes faster than planning cycles.
**Core Method**:
  - Splits the agent loop into a planning thread and an acting thread.
  - Uses centralized memory and communication state for planning.
  - Lets the acting side continue skill execution while accepting interrupts from fresher plans.
  - Targets real-time responsiveness in Minecraft multi-agent tasks.
**Why It Matters for Minecraft**:
  - M7 collaboration currently dispatches Agent roles in waves and relies on completed role runs before the next coordination point.
  - Time-sensitive shelter/resource tasks can benefit from interruptible action execution when another role discovers danger, missing dependencies, or a better opportunity.
  - The design pairs naturally with existing shared-state commits, action verification, and role bridge preflight.
**Singularity Adaptation**:
  - Add an M7 `plan_act_latency_report` that measures planner wait time, action execution overlap, interrupt opportunity count, and stale-plan action count from role logs.
  - Introduce a gated `parallel_plan_act_mode` only after offline replay shows fewer stale actions without increasing verifier rejections.
  - Keep the acting side constrained by existing action verification and skill gates; planner interrupts should replace only unfinished plan suffixes.
**Next Action**: Build an offline M7 plan/act latency report from collaboration and Agent role logs, then use it to decide where interruptible execution would help before changing live role dispatch.
