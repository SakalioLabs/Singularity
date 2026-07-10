# Paper Card: Recall-Controlled Early Abort

**Title**: Doomed from the Start: Early Abort of LLM Agent Episodes via a Recall-Controlled Probe Cascade

**Source**: https://arxiv.org/abs/2607.06503

**Date Reviewed**: 2026-07-10

**Core Method**: Calibrates one failure probe per interaction round and jointly allocates per-round recall budgets so the full cascade preserves a requested episode-level success recall.

**Evidence**:
- Evaluates hidden-state probes on TextCraft with two open-weight agent models.
- Meets reported global recall targets from 90% to 97%.
- At 90% recall, reports inference-compute savings of 47.1% +/- 10.3% and 37.2% +/- 8.8% for the two evaluated models.
- Behavior-only probes save roughly half as much in the reported setting; hosted Minecraft APIs may not expose hidden activations.

**Useful Transfer**:
- Sequential safety gates need an episode-level false-abort budget because per-round errors accumulate.
- Early termination must preserve successful trajectories at a calibrated recall target, not merely improve average cost.
- Sample-size sufficiency should be part of the gate before high-recall claims are accepted.

**Project Action**: Implemented `behavior_surface_v1` as a weaker hosted-API-compatible cascade. It reconstructs goal-bounded episodes from JSONL, ignores free-form prompt text, calibrates per-round thresholds with one-sided Clopper-Pearson bounds, searches budgets on a disjoint validation split, evaluates once on a held-out test split, and binds runtime use to fixed planner/backend/verifier/task-stream/seed provenance. Runtime remains `off` by default; synthetic evidence can never authorize active termination, and no current live Minecraft gate is approved.

**Non-Claim**: The project does not expose hidden activations and therefore does not reproduce the paper's hidden-state probe, early-round AUC, token savings, or wall-clock savings. Its current cost proxy is saved planner rounds only.
