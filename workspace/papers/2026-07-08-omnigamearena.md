# Paper Card: OmniGameArena

**Title**: OmniGameArena: A Unified UE5 Benchmark for VLM Game Agents with Improvement Dynamics
**Source**: https://arxiv.org/abs/2606.09826
**Date**: 2026-06-08
**Type**: Benchmark / reflection-harness evaluation
**Core Problem**: Many game-agent benchmarks report one cold-start score and miss whether a VLM agent improves across bounded reflection rounds or overfits a narrow skill prompt.
**Core Method**: Builds twelve Unreal Engine 5 games with unified action interfaces and introduces an Improvement Dynamics Curve that tracks autonomous skill-prompt refinement across repeated evaluation rounds and held-out variants.
**Memory / Task Mechanism**:
  - Evaluates repeated reflection and skill prompt updates as first-class signals.
  - Tests whether learned improvements transfer to held-out task variants.
  - Uses unified action protocols across solo, PvP, and cooperative settings.
**Borrowable Points**:
  - Measure skill-promotion and policy-feedback loops across repeated replay rounds, not only before/after one run.
  - Add held-out variants when approving learned skills or task templates.
  - Track whether visual-action suggestions improve monotonically, plateau, or regress.
**Singularity Adaptation**:
  - Existing promotion/goal/visual-action ablations can be extended into small improvement curves over repeated session-log replays.
  - Mixed-initiative templates can use held-out natural-language paraphrases as variants before becoming default auto-selected templates.
  - M7 collaboration tests can borrow the same idea by replaying schedule-policy changes against held-out collaboration specs.
**Next Action**: Add a lightweight repeated-replay harness for mixed-initiative template variants and visual-action grounding cases.
