# Paper Card: WhisperBench / MemGhost

**Title**: When Claws Remember but Do Not Tell: Stealthy Memory Injection in Persistent Personal Agents
**Source**: https://arxiv.org/abs/2607.05189
**Date**: 2026
**Type**: Persistent-agent security benchmark
**Core Problem**: Persistent agents can silently write untrusted external content into memory and later reuse it as trusted state.
**Core Method**: Introduces WhisperBench for end-to-end stealth memory injection and MemGhost for one-shot payload generation against persistent personal agents.
**Memory / Task Mechanism**:
  - Evaluates whether poisoned facts or preferences are written, hidden from the user, and later influence behavior.
  - Tests real workflow surfaces rather than only prompt-level attacks.
  - Transfers across agent architectures and memory backends, so defenses cannot assume one storage format.
**Borrowable Points**:
  - Treat every memory, skill, and policy patch promotion as a provenance-sensitive write.
  - Require explicit gate reports before externally influenced state becomes runtime behavior.
  - Log why a write is trusted, which evidence supports it, and where it is allowed to apply.
**Singularity Adaptation**:
  - Runtime mixed-policy patch loading now honors approved gate reports before offline patch artifacts can affect `ActionController` or mixed-initiative template policy.
  - Experiment-derived skill promotion now honors discovery skill gates before candidates are written to the persistent skill library.
  - Durable memory writes now run a promptware scanner before promotion: obvious instruction override, role hijack, credential exfiltration, tool hijack, persistence, and C2-loop payloads are routed to high-priority review or strict suppression.
  - Durable memory reads and transfer-experience retrieval now reuse the same scanner so suspicious recalled state is filtered before planner context; `memory-promptware-report` audits memory stores offline without printing raw memory payloads.
**Next Action**: Run `memory-promptware-report` on live autonomous/M7 memory stores and compare flagged entries against downstream task outcomes before enabling stricter default memory enforcement.
