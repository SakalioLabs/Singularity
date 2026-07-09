# LLM-in-Sandbox Elicits General Agentic Intelligence

- **Source**: https://arxiv.org/abs/2601.16206
- **Date reviewed**: 2026-07-09
- **Submitted**: 2026-01-22
- **Authors**: Daixuan Cheng et al.
- **Domain**: General agentic intelligence through sandboxed computer environments

## Core Idea

The paper studies how giving an LLM a minimal computer sandbox can elicit broad agentic behaviors beyond coding. The sandbox exposes file management, script execution, and external resource access so the model can externalize long context, run checks, and organize intermediate artifacts.

## Singularity Mapping

- Use sandbox-style artifacts as explicit, inspectable planner scratchpads instead of hidden prompt-only reasoning.
- Store curriculum ablations, plan/action audits, and memory quality probes as replayable files before allowing runtime policy changes.
- Treat the Minecraft world model plus session logs as the agent's domain sandbox: local files and scripts can test hypotheses before the live bot spends server time.
- Keep sandbox outputs behind gates, mirroring existing `world-model-feedback-gate`, `skill-memory-quality-gate`, and action-value transition gates.

## Implemented Follow-Up

- Added `coach-style-ablation`, an offline replay report that compares baseline curriculum choices against style-conditioned curriculum choices over default cases, JSON/JSONL case files, or session-log observations.
- The report writes candidate slates, score deltas, selected goals, and coach-specific reasons so style changes can be inspected before live autonomous runs.

## Next Experiments

- Add a planner scratchpad report that serializes candidate goals, constraints, and verifier assumptions to a bounded workspace file before each live plan.
- Add a sandbox replay runner that executes offline report pipelines on a frozen session bundle and emits a single promotion-ready manifest.
- Add cost and token accounting for sandbox-assisted planning versus direct prompt-only planning.
