# Paper Card: AFTER Procedural Memory

**Title**: Managing Procedural Memory in LLM Agents: Control, Adaptation, and Evaluation
**Source**: https://arxiv.org/abs/2606.23127
**Date**: 2026
**Type**: Procedural-memory transfer benchmark and management study
**Core Problem**: Procedural memories can improve repeated agent work, but it is unclear which skills transfer across tasks, roles, and model backbones versus becoming narrow workflow specializations.
**Core Method**: Introduces AFTER, a benchmark of realistic enterprise tasks spanning professional roles and procedural skills, with controlled tests for local improvement, cross-task transfer, cross-role transfer, and cross-model generalization.
**Memory / Task Mechanism**:
  - Evaluates skill refinement separately from broader transfer.
  - Distinguishes general skills from role-specialized skills that lose effectiveness under transfer.
  - Treats procedural memory deployment as a governed production decision, not a one-shot prompt artifact.
**Borrowable Points**:
  - Minecraft skills should not become task-family defaults after only one local success.
  - Runtime defaults should require controlled stream evidence for plasticity, stability, held-out generalization, and low interference.
  - Task-family and role scope should stay explicit when skills are approved.
**Singularity Adaptation**:
  - `task-stream-transfer-report` and `task-stream-transfer-gate` already provide controlled Minecraft stream evidence.
  - `skill-lifecycle-report` identifies lifecycle-ready runtime-default candidates.
  - `skill-runtime-default-gate` now joins lifecycle candidates with approved transfer gates and optional localized quality gates before default enablement.
  - `--skill-runtime-default-gate` now loads approved task-family profiles into live Agent, benchmark, and M7 Agent executor runs so learned policy skills are filtered by transfer scope at runtime.
  - `benchmark --skill-runtime-default-gate` now preflights approved candidate coverage against the selected suite's inferred task families before spending live Minecraft runtime.
**Next Action**: Run the gate on real autonomous/M7 skill stores and enable only family-scoped skill profiles whose transfer evidence remains stable on held-out variants.
