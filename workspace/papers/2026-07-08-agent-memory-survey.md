# Paper Card: Memory for Autonomous LLM Agents

**Title**: Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Open Challenges
**Source**: https://arxiv.org/abs/2603.07670
**Date**: 2026
**Type**: Survey
**Core Problem**: Autonomous agents need memory systems that can write, manage, and read useful experience over long horizons while avoiding stale, noisy, or unbounded context.
**Core Method**:
  - Formalizes agent memory as a write-manage-read loop coupled to perception and action.
  - Categorizes memory by temporal scope, representational substrate, and control policy.
  - Surveys evaluation practices for whether memory improves downstream agent behavior rather than only retrieval scores.
**Borrowable Points**:
  - Treat memory writes, memory management, and memory reads as separately measurable policy decisions.
  - Evaluate memory by task impact, staleness, update correctness, and retrieval usefulness.
  - Log enough lifecycle evidence to diagnose whether failures come from missing writes, bad management, or bad reads.
**Singularity Adaptation**:
  - `memory-policy-report` uses the write/manage/read framing for offline session audits.
  - Future memory policy can consume `memory_policy_feedback` to tune write gates, consolidation review, and retrieval instrumentation.
**Next Action**: Add online `memory_read`, `memory_write`, and `memory_manage` session events around `MemorySystem` and compare reports across real benchmark logs.
