# Paper Card: AgenticCache

**Title**: AgenticCache: Cache-Driven Asynchronous Planning for Embodied AI Agents
**Source**: https://arxiv.org/abs/2604.24039
**Date**: 2026-04-27
**Type**: Embodied planning latency and cost architecture
**Core Problem**: LLM-powered embodied agents often call the planner every step, so planning latency and token cost throttle long-horizon execution even when local plan transitions are predictable.
**Core Method**:
  - Exploits plan locality: the next plan is often predictable from current context and the previous plan.
  - Queries a runtime cache of frequent plan transitions before invoking the LLM.
  - Uses an asynchronous updater to validate, refine, and correct cached transitions.
  - Supports offline pattern prefilling so agents avoid cold-start misses at the beginning of an episode.
**Why It Matters for Minecraft**:
  - Singularity already logs plan/action/observation events and measures plan-act latency; repeated crafting, mining, and navigation subtasks should expose reusable short-horizon plan transitions.
  - M1/M2/M7 live runs spend scarce runtime on repeated planner calls; a cache can reduce duplicate LLM planning without changing action controllers.
  - Cache artifacts need the same promptware/security treatment as memories and runtime profiles because cached plans can influence future actions.
**Singularity Adaptation**:
  - Added `plan-cache-report`, which mines session logs for successful plan transitions with goal signatures, previous-plan signatures, compact state features, success rates, support counts, and promptware flags.
  - Added `PlanTransitionCache` and runtime `--enable-plan-cache --plan-cache ...`; cache reuse is default-off, requires accepted offline entries plus an approved `plan-cache-gate`, and keeps action verification plus goal verification active.
  - Added `plan-cache-runtime-report` and `plan-cache-gate` so cache artifacts can be promoted only when actual cache-hit logs stay within verifier-reject and failed-action limits.
  - Runtime profiles now support `enable_plan_cache`, `plan_cache_paths`, and `plan_cache_gate_paths`, with security audit scanning referenced cache artifacts before live startup.
  - Current implementation deliberately omits asynchronous correction until live plan-act reports prove cache hits reduce latency without increasing verifier rejects.
**Next Action**: Run `plan-cache-report` plus `plan-cache-runtime-report` on fresh M1/M2/M7 session logs, pass `plan-cache-gate`, validate/cache-scan the resulting runtime profile, then compare plan-cache hit rate, planner wait, token calls, and verifier reject counts against baseline.
