# Paper Card: MineNPC-Task

**Title**: MineNPC-Task: Task Suite for Memory-Aware Minecraft Agents
**Source**: https://arxiv.org/abs/2601.05215
**Date**: 2026
**Type**: Benchmark / evaluation harness
**Core Problem**: Minecraft companion agents need evaluation on natural player-authored requests, not only synthetic task prompts or privileged world-state checks.
**Core Method**: Expert co-play requests are normalized into parametric templates with dependencies, required slots, targeted clarification questions, bounded Mineflayer action/perception constraints, and machine-checkable validators.
**Memory / Task Mechanism**:
  - Plan previews expose a short dependency-ordered subtask chain.
  - Missing slots trigger a single targeted clarification instead of broad guessing.
  - Clarification answers can become scoped preference memory with provenance.
  - Validators judge only bounded in-world evidence: inventory/equipment deltas, position changes, nearby loaded-chunk blocks/entities, and recent chat.
  - A bounded-knowledge policy forbids admin commands, global map/seed introspection, and scans beyond loaded chunks.
**Borrowable Points**:
  - Add user-authored task templates with explicit parameters and dependencies.
  - Separate validator-backed outcome evidence from planner self-report.
  - Treat clarification as a memory-writing event, but keep it scoped and auditable.
  - Report invalid runs when an agent uses privileged shortcuts.
**Singularity Adaptation**:
  - Added `src/singularity/evaluation/mixed_initiative.py` with seed MineNPC-style templates for collecting oak logs and fetching a named pickaxe.
  - Added `mixed-initiative-report` CLI to compile a natural-language goal into a plan preview, one surfaced clarification, subtask records, scoped memory-write candidates, and optional bounded-evidence validation.
  - Added `BoundedEvidenceValidator` for inventory, inventory-delta, equipment, flag, nearby-block/entity, chat, action-success, and position-delta checks, plus policy violations for admin commands, hidden evidence, and over-wide scans.
  - Added `mixed-initiative-trace-report` to replay session logs through the same template validators and compare bounded validator outcomes against logged `GoalVerifier` decisions.
**Next Action**: Mine recurring chat/session-log requests into more templates, then connect template validators into live benchmark denominators for mixed-initiative tasks.
