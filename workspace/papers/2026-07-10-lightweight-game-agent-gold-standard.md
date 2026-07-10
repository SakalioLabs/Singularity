# Paper Card: Gold-Standard Lightweight Game Agent

**Title**: A Gold-Standard Study of What Makes a Lightweight Game-Playing Agent Strong

**Source**: https://arxiv.org/abs/2607.06854

**Date Reviewed**: 2026-07-10

**Core Method**: Uses a strong fixed rule-based expert only as an evaluation yardstick, then isolates training ingredients over more than one hundred runs without training on that expert.

**Evidence**:
- The expert beats trained Gin Rummy agents in 70% to 99% of games.
- Trust-region updates, targeted reward, opponent curriculum, warm starts, and best-checkpoint retention improve the lightweight agent.
- Larger encoders and several heavier techniques do not break the observed ceiling, suggesting an information bottleneck rather than a capacity bottleneck.

**Useful Transfer**:
- Evaluate a Minecraft router against deterministic prerequisite and assigned-skill expectations, not against its own outputs.
- Keep the evaluator fixed while changing only routing logic.
- Report preservation and regressions, not only aggregate wins.

**Project Action**: The skill-frontier ablation fixes the skill library, world state, task intervals, action backend, verifier, task stream, and seed; only legacy versus frontier routing changes. Its built-in fixtures are a smoke-test yardstick, not live Minecraft evidence.
