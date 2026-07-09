# Paper Card: Active Context Compression

**Title**: Active Context Compression: Autonomous Memory Management in LLM Agents

**Source**: https://arxiv.org/abs/2601.07190

**Date Reviewed**: 2026-07-10

**Core Method**: Adds explicit focus checkpoints so an agent can consolidate a completed exploration phase into structured knowledge and remove the superseded raw interaction span from the active context.

**Evidence**:
- Reports 22.7% aggregate token reduction on five SWE-bench Lite tasks while preserving the same 3/5 task success.
- Four tasks reduce token use by 18% to 57%, while one task incurs 110% more tokens.
- The study therefore shows task-dependent savings rather than universal compression benefit.

**Useful Transfer**:
- Compress completed Minecraft execution phases, not arbitrary recent text windows.
- Preserve a durable ledger and optimize only the planner-facing projection.
- Measure per-case context cost and downstream correctness together; an aggregate reduction must not hide an individual regression.

**Do Not Copy Blindly**:
- The experiment has only five software tasks and does not cover embodied partial observability.
- Free-text summaries can lose identifiers, prerequisites, or continuation state.
- Token reduction alone cannot authorize task recovery or world-state restoration.

**Project Action**: Singularity uses deterministic field-preserving task capsules rather than model-written deletion. Lineage ablation now reports baseline, rich, and capsule characters per case and requires identity/frontier/continuation probes plus zero failed-branch leakage before shadow-selection evidence can pass.
