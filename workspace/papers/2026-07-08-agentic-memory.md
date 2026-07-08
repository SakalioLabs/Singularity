# Paper Card: Agentic Memory

**Title**: Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for Large Language Model Agents
**Source**: https://arxiv.org/abs/2601.01885
**Date**: 2026
**Type**: Paper
**Core Problem**: Long-horizon agents need a unified policy for when to store, retrieve, summarize, update, or discard memory across both short-term and long-term contexts.
**Core Method**:
  - Exposes memory operations as tool-like actions available to the agent policy.
  - Unifies long-term and short-term memory management instead of splitting them into separate heuristic controllers.
  - Trains memory behavior with progressive reinforcement learning and step-wise rewards.
**Borrowable Points**:
  - Treat memory operations as explicit decisions with feedback, not hidden side effects.
  - Keep write/read/update/discard choices observable so downstream task performance can be linked to memory behavior.
  - Start with advisory policy labels before enforcing learned gates.
**Singularity Adaptation**:
  - `MemoryLifecyclePolicy` now emits per-operation decisions for Agent memory writes, reads, and management operations.
  - The default mode is advisory and preserves existing writes; `enforce_memory_write_gate` can suppress noisy writes once enough trace evidence exists.
  - `memory_policy_feedback` can tune the policy after offline reports over real session logs.
**Next Action**: Compare advisory memory decisions against real benchmark outcomes, then promote stable high-precision rules into enforced gates.
