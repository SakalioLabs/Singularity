# PROGRESS.md -- Evidence-Backed Progress

## Current Assessment

Singularity has broad source coverage and a large passing offline test surface, but the full Minecraft Agent system is not complete. The authoritative capability report is `workspace/evals/capability_evidence_current.json`.

Current report outcome:

- Readiness: `rejected`
- Claim audit: `approved`
- System status: `incomplete`
- Declared-complete phases audited: 1 (M0 only)
- Supported completion claims: 1 (M0 research baseline)
- Contradicted completion claims: 0 after status correction
- Unsupported completion claims: 0 after status correction
- Failing live phases: 1 (M1)
- Repeat-verified runtime phases: 0

## Engineering Delivered

- Mineflayer bridge, structured observations, canonical action control, safety verification, and session logging.
- Rule and LLM planning, hierarchical tasks, readiness reporting, deterministic prerequisite recovery, reflection, and goal verification.
- Layered memory, task continuity, typed retrieval, promptware filtering, attribution gates, skill memory, skill lifecycle, and transfer gates.
- Autonomous curriculum, runtime interrupts, world-model/frontier reports, causal evidence, and controlled self-evolution reports.
- Vision analysis, optional screenshot plumbing, visual action grounding, and screenshot evidence validation.
- Multi-agent shared state, role execution, bridge preflight, schedule comparison, and single-agent baseline machinery.
- Evidence and ablation tooling for action verification/value, memory policy, plan cache, mixed initiative, coaching, visual review, and runtime profiles.

## Evidence That Still Matters

- Latest tracked M1 benchmark file records BM-001..005 as failures with empty inventories.
- No tracked successful M2 benchmark suite is available.
- No three-run first-night survival evidence is available.
- No verified screenshot-backed live session is available.
- No live BM-701 multi-agent execution report is available.
- M3, M5, and M6 still need explicit machine-checkable live acceptance mappings in the capability ledger.

## Research Direction

- MineExplorer: hidden prerequisite graphs and rule-based milestones should define progress rather than final-text claims.
- MineNPC-Task: task attempts should be scored against explicit dependencies, bounded knowledge, and machine-checkable validators.
- AgenticSTS: every planner decision should use bounded typed retrieval instead of accumulating raw transcripts.
- WorldLines: memory should preserve visibility, state revisions, and action-native evidence under partial observability.
- OpenClaw and Hermes: durable memory, procedural skills, maintenance passes, and workspace separation are useful only when action authority and promotion gates remain explicit.

## Immediate Sequence

1. Restore a healthy Minecraft server and bridge runtime.
2. Re-run M1 and use the new readiness recovery path on missing-resource failures.
3. Promote no capability until the ledger reports `repeat_verified`.
4. Add live evidence adapters for cross-session memory, exploration, and screenshot/VLM behavior.
5. Continue research-driven improvements only with baseline/candidate traces and regression gates.
