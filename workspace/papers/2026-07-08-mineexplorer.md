# Paper Card: MineExplorer

**Title**: Evaluating Open-World Exploration of MLLM Agents in Minecraft
**Source**: https://arxiv.org/abs/2605.30931
**Date**: 2026
**Type**: Benchmark / evaluation framework
**Core Problem**: Open-world Minecraft agents need to sustain exploration, not only complete short atomic tasks or exploit domain-specific Minecraft priors.
**Core Method**: MineExplorer evaluates MLLM agents in Minecraft with a ReAct-style capability formulation over perception, reasoning, and action while reducing the confounding effect of Minecraft-specific knowledge.
**Memory / Task Mechanism**:
  - Treats exploration as a capability that must be measured over time.
  - Separates perception, reasoning, and action failure modes.
  - De-emphasizes tasks that can be solved mainly by memorized Minecraft priors.
**Borrowable Points**:
  - Add exploration-specific metrics to autonomous mode instead of using only inventory unlocks.
  - Track whether new places, blocks, entities, and hazards are discovered across a run.
  - Report perception/reasoning/action failure categories from session traces.
**Singularity Adaptation**:
  - `CurriculumManager` already proposes exploration goals from novelty and readiness signals.
  - `exploration-trace-report` now summarizes visited position spread, path distance, newly observed block/entity/resource types, visual evidence coverage, hazard encounters, multi-step plans, and failed action categories from session logs.
  - `world-model-report` complements coverage metrics by reconstructing visited cells, transitions, resource hotspots, danger cells, and frontier candidates from the same logs, then emits `world_model_feedback` for curriculum reranking.
  - `world-model-feedback-gate` keeps map-derived frontier/hotspot feedback review-only until the report has ready logs and structured actionable cell evidence.
  - Long-term: use exploration coverage as a benchmark dimension alongside M1/M2 completion, M6 visual evidence quality, and M7 collaboration overlap.
**Next Action**: Run the reports and gate on real autonomous logs, then connect approved coverage plus frontier metrics back into curriculum novelty scoring.
