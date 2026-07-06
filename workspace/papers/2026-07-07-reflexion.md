# Paper Card: Reflexion

**Title**: Reflexion: Language Agents with Verbal Reinforcement Learning
**Source**: https://arxiv.org/abs/2303.11366
**Date**: 2023
**Authors**: Noah Shinn, Federico Cassano, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao (Princeton + MIT)
**Type**: Paper + Code
**Core Problem**: How to let LLM agents learn from failures without weight updates?
**Core Method**: Verbal self-reflection after failure. Agent generates natural language reflection, stores it, and uses it to improve next attempt.
**System Architecture**:
  - Actor: Takes actions in environment
  - Evaluator: Judges task success
  - Self-Reflection: LLM generates verbal reflection on failure
  - Memory: Stores reflections for future reference
**Key Results**:
  - Significant improvement on coding (HumanEval), reasoning, and decision tasks
  - Each retry gets better due to accumulated reflections
  - No model fine-tuning needed
  - Works with multiple LLM backends
**Borrowable Points**:
  - Failure reflection pattern — our Reflector module
  - Verbal reinforcement learning (learn from text, not rewards)
  - Memory of past failures prevents repeating mistakes
  - Retry with accumulated wisdom
**Cannot Directly Adopt**:
  - Simple task environments (not Minecraft-scale)
  - No skill library integration
**Suggestion**: Implement Reflexion-style reflection in our Reflector module. Store reflections in L2 episodic memory.
**Next Action**: Design reflection prompt template for Minecraft task failures
