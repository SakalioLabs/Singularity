# Repo Card: Mindcraft

**URL**: https://github.com/kolbytn/mindcraft
**License**: MIT
**Language**: JavaScript (Node.js)
**MC Version**: 1.20+
**Activity**: Active (4k+ stars, regular updates through 2024-2025)
**Description**: LLM-powered Minecraft agent platform using Mineflayer + OpenAI/Anthropic APIs.
**Architecture**:
  - Agent loop: observe -> LLM plan -> execute -> observe
  - Mineflayer bot for game interaction
  - Multiple LLM support (GPT-4, Claude, Gemini, local models)
  - Skills system (code generation + storage)
  - Memory system (conversation history + knowledge)
  - Self-evaluation and correction
**Dependencies**: mineflayer, mineflayer-pathfinder, minecraft-data, openai, anthropic
**Install Difficulty**: Easy (npm install + API key)
**Reproducibility**: High
**Reusable Modules**:
  - Mineflayer bot integration pattern
  - LLM prompt engineering for Minecraft
  - Skills code generation and execution
  - Multi-model support (OpenAI, Anthropic, Gemini, local)
  - Error handling and retry logic
**Risks**:
  - Early-stage project, may have stability issues
  - Relies on LLM code generation without strong sandboxing
  - API costs can escalate
**Value to Project**: Direct engineering reference. Our architecture closely mirrors Mindcraft's approach but with more structured task system and memory layers.
**Can We Fork/Integrate**: Yes (MIT license). Can study code and reimplement with our architecture enhancements.
