# Coachable Agents for Interactive Gameplay

- **Source**: https://arxiv.org/abs/2607.00642
- **Date reviewed**: 2026-07-09
- **Submitted**: 2026-07-01
- **Authors**: Roberto Capobianco et al.
- **Domain**: Runtime-controllable game and embodied agents

## Core Idea

The paper frames runtime control as a style layer: the user can choose how an agent solves the task while the primary task objective remains intact. The implementation uses UVFA-style conditioning and training choices to keep style coherence across different interactive domains.

## Singularity Mapping

- Treat style as advisory policy, not as a permission bypass.
- Inject compact style instructions into planner context so LLM planning can prefer safe, exploratory, efficient, resourceful, or builder-like behavior.
- Bias autonomous curriculum candidates after deterministic candidate generation, preserving task readiness, verifier checks, and safety gates.
- Record the active style and reranked candidates in `CurriculumManager.last_decision` for later ablation and session review.

## Implemented Follow-Up

- Added `CoachPolicy` with `safe`, `explorer`, `efficient`, `resourceful`, and `builder` profiles.
- Added `Config.coach_style`, `Config.enable_coaching_policy`, and CLI `--coach-style`.
- Wired advisory coach context into `Agent._think_llm()`.
- Wired coach-biased curriculum reranking into autonomous goal selection only after ready tasks are considered.
- Added `coach-style-ablation` so style-biased curriculum changes can be replayed from default cases, JSON/JSONL case files, or session-log observations before live autonomous runs.
- Added `coach-style-gate` so a style needs enough saved ablation cases and score-changing evidence before it is treated as benchmark-ready.

## Next Experiments

- Add per-style session metrics: survival risk, exploration coverage, resource readiness, and plan compliance.
- Promote styles from static weights to learned preference profiles only after enough verifier-checked episodes exist.
