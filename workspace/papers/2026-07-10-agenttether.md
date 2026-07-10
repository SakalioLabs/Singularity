# Paper Card: AgentTether

**Title**: AgentTether: Graph-Guided Diagnosis and Runtime Intervention for Reliable LLM Agent Operation

**Source**: https://arxiv.org/abs/2607.06273

**Date Reviewed**: 2026-07-10

**Core Method**: Groups an agent trace into decision-execution-feedback Transition Units, links them with temporal and information-flow edges in a Critical Transition Graph, localizes upstream failure-critical subtrajectories, and carries behavior-scoped repair guidance across bounded re-execution attempts. Online intervention uses evidence grounding, cooldowns, and minimal-intervention guards.

**Evidence**:
- Evaluates 261 tau-bench tasks across three domains with Qwen3.7-max and a Banking transfer study with GPT-5.4.
- Reports that most analyzed Banking failures originate in wrong/missing tool actions, often several required steps before the terminal symptom.
- Reports repair gains over blind retry and one-shot feedback, with guarded intervention providing an additional gain in the most constrained domain.
- The evidence concerns API/tool workflows, not Minecraft world-state rollback.

**Useful Transfer**:
- Allocate diagnostic effort to upstream prerequisite-producing transitions rather than the final failed action alone.
- Keep failure localization dependency-aware and branch-scoped.
- Carry unresolved/fixed state across attempts, but cap attempts under one conserved budget.
- Never turn a diagnosis directly into an unverified world-state mutation or blind retry.

**Project Action**: Added `minecraft_transition_unit_v1`, temporal/plan/artifact/target/error dependency edges, and `first_unrecovered_constraint_v1`. The deterministic localizer emits compact evidence packets plus typed unresolved Repair Memory candidates, while planner guidance, automatic retry, runtime intervention, memory promotion, and skill mutation remain disabled. `frontier_information_budget_v1` still uses local typed proxies until manually labeled live graph evidence supports a stronger gate.

**Non-Claim**: Singularity has not reproduced AgentTether's graph detector, repair model, or tau-bench results. This milestone transfers its causal-allocation and bounded-intervention constraints only.
