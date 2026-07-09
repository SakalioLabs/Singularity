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
- Failing live phases: 4 (M1, M3, M5, M6)
- Repeat-verified runtime phases: 0

## Engineering Delivered

- Mineflayer bridge, structured observations, canonical action control, safety verification, and session logging.
- Rule and LLM planning, hierarchical tasks, readiness reporting, deterministic prerequisite recovery, reflection, and goal verification.
- Layered memory, task continuity, typed retrieval, promptware filtering, attribution gates, skill memory, skill lifecycle, and transfer gates.
- Autonomous curriculum, runtime interrupts, world-model/frontier reports, causal evidence, and controlled self-evolution reports.
- Vision analysis, optional screenshot plumbing, visual action grounding, and screenshot evidence validation.
- Multi-agent shared state, role execution, bridge preflight, schedule comparison, and single-agent baseline machinery.
- Evidence and ablation tooling for action verification/value, memory policy, plan cache, mixed initiative, coaching, visual review, and runtime profiles.
- Machine-checkable M3/M5/M6 live adapters with distinct-session deduplication and transfer/world-model/visual-action support gates.
- Rule and LLM planning cycles now retrieve typed memory through strict per-read and per-decision character budgets, emit a schema-v2 contract, and exclude non-planning causal reads from bounded-context evidence. Rule selection remains world-state-driven and reports that memory has not yet influenced its action choice.
- Autonomous runs now emit observations, plans, selected goals, and terminal subgoal outcomes as non-nested machine-checkable events; queued tasks no longer silently replace the goal whose plan is being executed.

## Evidence That Still Matters

- Latest tracked M1 benchmark file records BM-001..005 as failures with empty inventories.
- No tracked successful M2 benchmark suite is available.
- No three-run first-night survival evidence is available.
- Existing M3 traces show no memory reads or writes, no completed goals, and 2,601 unbounded context cycles.
- Existing M5 traces cover 22 moving sessions and pass the world-model feedback gate, but complete 0 of 27 goals.
- Existing M6 traces contain no verified screenshots and no live-source visual-action interventions.
- No live BM-701 multi-agent execution report is available.
- M3, M5, and M6 acceptance is machine-checkable; all 37 existing sessions were ingested and none qualifies.
- The bounded-memory and autonomous-event fixes apply only to future sessions. They do not upgrade or rewrite the historical evidence above.

## Research Direction

- MineExplorer: hidden prerequisite graphs and rule-based milestones should define progress rather than final-text claims.
- MineNPC-Task: task attempts should be scored against explicit dependencies, bounded knowledge, and machine-checkable validators.
- AgenticSTS: every planner decision should use bounded typed retrieval instead of accumulating raw transcripts.
- WorldLines: memory should preserve visibility, state revisions, and action-native evidence under partial observability.
- SelfMem: memory-policy variants should be optimized offline from retrieval cost and downstream outcomes, then promoted only through existing gates.
- MAGE execution-state memory: active task paths, completed checkpoints, failed branches, and revision boundaries should be represented separately before automatic rollback is enabled.
- OpenClaw and Hermes: durable memory, procedural skills, maintenance passes, and workspace separation are useful only when action authority and promotion gates remain explicit.

## Immediate Sequence

1. Restore a healthy Minecraft server and bridge runtime.
2. Re-run M1 and use the new readiness recovery path on missing-resource failures.
3. Promote no capability until the ledger reports `repeat_verified`.
4. Re-run M3/M5 with the new bounded-memory and autonomous-event contracts, then collect three distinct qualifying sessions for each adapter; M6 still requires screenshot-backed visual interventions.
5. Continue research-driven improvements only with baseline/candidate traces and regression gates.
