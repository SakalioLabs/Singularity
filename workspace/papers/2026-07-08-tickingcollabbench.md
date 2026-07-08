# Paper Card: TickingCollabBench

**Title**: Multi-agent Framework for Time-Sensitive Complementary Collaboration in Minecraft
**Source**: https://arxiv.org/abs/2606.15684
**Date**: 2026
**Authors**: Juheon Yi, Jinglu Wang, Xiaoyi Zhang, Yan Lu
**Type**: Paper + Benchmark
**Core Problem**: Many multi-agent benchmarks do not stress real-time constraints, mandatory cooperation, dynamic environments, and heterogeneous capabilities together.
**Core Method**: TickingCollabBench, a Minecraft benchmark for time-sensitive complementary collaboration with declarative task generation.
**System Architecture**:
  - Heterogeneous agents receive complementary roles.
  - YAML-style task specifications define timed events and environment dynamics.
  - Feasibility verifier filters invalid generated tasks.
  - Oracle comparison highlights coordination and latency failures.
**Memory Mechanism**: Shared state and communication are evaluation targets rather than the main method.
**Task Mechanism**: Strict deadlines and failure risks force coordination under partial observability.
**Key Results**: Reports that LLM agents struggle under latency, dynamic events, and role heterogeneity.
**Reproduction Difficulty**: Medium; benchmark schema can be approximated before full environment generation.
**Borrowable Points**:
  - Add deadlines and feasibility checks to collaboration tasks.
  - Test role heterogeneity, not just multiple identical agents.
  - Record latency as a first-class metric.
**Current Singularity Mapping**:
  - `Task.deadline` and `RuntimeSupervisor` deadline interrupts are ready.
  - Multi-agent module already has leader/worker roles.
**Next Action**: Define M7 benchmark YAML schema with roles, deadlines, shared state, and feasibility checks.

