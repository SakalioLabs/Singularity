# Paper Card: Agent Memory System Characterization

**Title**: Agent Memory: Characterization and System Implications of Stateful Long-Horizon Workloads
**Source**: https://arxiv.org/abs/2606.06448
**Date**: 2026
**Type**: Systems characterization of agent memory construction, retrieval, and generation workloads
**Core Problem**: Memory systems are often compared only by final task quality, hiding where latency, cost, freshness, and maintenance work move across the write and read paths.
**Core Method**: Profiles representative memory systems by construction, retrieval, and generation phases and derives deployment recommendations around scheduling, capability floors, amortization, freshness, and fleet management.
**Memory / Task Mechanism**:
  - Separates memory construction cost from retrieval and downstream generation cost.
  - Treats query volume and maintenance scheduling as first-class design variables.
  - Exposes freshness versus latency tradeoffs instead of assuming more memory is always better.
**Borrowable Points**:
  - Minecraft memory evaluation should report read/write/maintenance cost per successful task milestone.
  - Consolidation and indexing should run at bounded maintenance points, not unpredictably inside urgent action loops.
  - Memory backends should meet a minimum capability and latency contract before runtime profiles enable them.
**Singularity Adaptation**:
  - Existing memory lifecycle, attribution, bounded-context, and maintenance reports provide the event substrate.
  - `capability-evidence-report` prevents those reports from being mistaken for live Minecraft capability.
  - A future memory systems profile should join latency/token cost with state-grounded task success and freshness errors.
**Next Action**: Extend M3 acceptance with construction/retrieval/generation latency, freshness violations, and repeated cross-session task recovery.
