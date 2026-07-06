# Status — Singularity Minecraft Agent

> Last updated: 2026-07-07

## Current Phase
**M1: Minimum Viable Bot** — In Progress

## Phase Progress

| Phase | Status | Progress |
|-------|--------|----------|
| M0: Research Baseline | **Complete** | 100% |
| M1: Minimum Viable Bot | **In Progress** | 40% |
| M2: LLM Task Planning | Not Started | 0% |
| M3: Skill Library & Memory | Not Started | 0% |
| M4: Autonomous Survival | Not Started | 0% |
| M5: Open-World Exploration | Not Started | 0% |
| M6: Vision & Multimodal | Not Started | 0% |
| M7: Multi-Agent Collab | Not Started | 0% |

## M0 Deliverables (Complete)
- [x] ROADMAP.md, MEMORY.md, DECISIONS.md, RISKS.md, OPEN_QUESTIONS.md
- [x] paper-index.md (17 papers) + detailed paper cards (Voyager, GITM)
- [x] repo-index.md (11 repos) + detailed repo card (Mindcraft)
- [x] current-architecture.md + 8 module design docs
- [x] benchmark-index.md (14 tasks), experiment-index.md
- [x] 8 skill templates, 5 implementation notes
- [x] Task tracking (backlog, active, done, blocked)

## M1 Deliverables (In Progress)
- [x] Python agent package structure (src/singularity/)
- [x] Core agent loop with observe-think-act cycle
- [x] LLM provider abstraction (OpenAI, Anthropic, Ollama)
- [x] Observation module (player state, inventory, entities, blocks)
- [x] Action controller with pre/post validation
- [x] Bot bridge (Python <-> Node.js TCP socket)
- [x] Node.js Mineflayer bot server
- [x] Entry point (main.py with CLI args)
- [x] requirements.txt, package.json
- [x] EXP-0001 connectivity test plan
- [ ] Local Minecraft server setup
- [ ] Run EXP-0001 connectivity test
- [ ] Run BM-001 through BM-005 benchmark tasks

## Key Decisions
1. Architecture: Hybrid (Route F) — LLM planner + task system + skill library + Mineflayer
2. MC Version: 1.20.4 Paper
3. Bot: Mineflayer primary, TCP socket bridge
4. LLM: Swappable (OpenAI/Anthropic/DeepSeek/Ollama)
5. Memory: Markdown + JSON (Phase 1)

## Next Steps
1. Set up local Paper 1.20.4 server
2. npm install mineflayer dependencies
3. pip install Python dependencies
4. Run EXP-0001 connectivity test
5. Run first 5 benchmark tasks (BM-001 to BM-005)
6. Begin M2 LLM task planning integration
