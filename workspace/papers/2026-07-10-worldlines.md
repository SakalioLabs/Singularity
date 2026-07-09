# Paper Card: WorldLines

**Title**: WorldLines: Benchmarking and Modeling Long-Horizon Stateful Embodied Agents
**Source**: https://arxiv.org/abs/2606.18847
**Date**: 2026
**Type**: Long-horizon embodied memory benchmark and observer-grounded memory framework
**Core Problem**: Language retrieval benchmarks do not prove that an embodied agent can remember changing world state, while short-horizon embodied benchmarks rarely test persistent state use.
**Core Method**: Builds temporally extended projects containing dialogue, actions, execution feedback, object/device state changes, and evidence-linked memory and planning questions. ObsMem keeps visibility-aware memory and action-native state trails.
**Memory / Task Mechanism**:
  - Binds remembered state to what the observer could actually see.
  - Preserves action and state-transition evidence rather than only textual summaries.
  - Tests overwritten world states and partial observability explicitly.
**Borrowable Points**:
  - Minecraft memories need observation scope, state revision, and action provenance.
  - A remembered resource or structure should not be treated as currently visible or unchanged without fresh evidence.
  - Long-horizon completion claims should link task milestones to world-state evidence.
**Singularity Adaptation**:
  - Existing state revision, memory read filtering, task continuity, and action-local pre/post observations cover parts of the design.
  - `capability-evidence-report` now separates source presence from live and repeated embodied evidence.
  - The next extension should map M3/M5 acceptance to visibility-aware cross-session state recovery rather than generic memory retrieval counts.
**Next Action**: Add a live acceptance adapter that verifies a remembered landmark/resource across disappearance, revisit, state revision, and action outcomes.
