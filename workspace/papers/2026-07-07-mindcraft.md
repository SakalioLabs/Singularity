# P-008: Mindcraft

**Title**: Mindcraft: An Extensible Platform for Language-Guided Minecraft Agents
**Year**: 2024
**Link**: https://github.com/kolbytn/mindcraft
**Authors**: Kolby Nottingham, Prithviraj Ammanabrolu, et al.
**Priority**: P1

## Core Method
Mineflayer + LLM modular agent platform. LLM generates actions via conversation, agent executes via Mineflayer API.

## Key Contributions
- Open-source platform for LLM-driven Minecraft agents
- Modular architecture separating LLM reasoning from game execution
- Demonstrates Mineflayer + LLM is viable for varied tasks
- Community-maintained, extensible design

## Relevance to Singularity
- **Direct engineering reference**: Our architecture mirrors Mindcraft patterns
- **Bot bridge**: We use similar Python-Node.js bridge concept
- **Action space**: Mineflayer API actions chosen by LLM
- **Key difference**: We add formal TaskSystem, SkillLibrary, Memory system vs Mindcraft conversation-only approach
