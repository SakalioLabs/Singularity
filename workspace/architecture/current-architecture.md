# Current Architecture — Minecraft LLM Agent

> Version: 1.0 | Date: 2026-07-07 | Status: M0 Design

## Architecture Overview

The Singularity agent uses a modular hybrid architecture (Route F) with clear separation between high-level reasoning (LLM), mid-level orchestration (task system + skill library), and low-level execution (Mineflayer bot).

## System Diagram

```
+------------------------------------------+
|            User / Human Input            |
+------------------------------------------+
                    |
                    v
+------------------------------------------+
|              Planner (LLM)               |
|  Strategic / Tactical / Action Planning  |
+------------------------------------------+
                    |
                    v
+------------------------------------------+
|            Task System                    |
|  Hierarchical tasks, dependencies,       |
|  priority, state machine                 |
+------------------------------------------+
                    |
                    v
+------------------------------------------+
|           Skill Library                   |
|  Reusable action units (code + NL),      |
|  versioning, success tracking            |
+------------------------------------------+
                    |
                    v
+------------------------------------------+
|         Action Controller                 |
|  Pre-check -> Execute -> Post-verify     |
|  Timeout, rollback, safety interrupt     |
+------------------------------------------+
                    |
                    v
+==========================================+
|        Minecraft Server (Paper 1.20.4)   |
|  Via Mineflayer bot (Node.js)            |
+==========================================+
                    |
                    v
+------------------------------------------+
|          Observation Layer                |
|  Position, health, inventory, blocks,    |
|  entities, time, weather, events         |
+------------------------------------------+
                    |
                    v
+------------------------------------------+
|         World State Layer                 |
|  Structured state, LLM-readable          |
|  summaries, state change triggers        |
+------------------------------------------+
                    |
         +--------+--------+
         |                  |
         v                  v
+----------------+  +----------------+
|    Reflector   |  |    Evaluator   |
| Failure analysis|  | Benchmarks,   |
| Re-plan trigger|  | Metrics, Reports|
+----------------+  +----------------+
         |                  |
         v                  v
+------------------------------------------+
|           Memory System (L0-L6)          |
|  Context, Working, Episodic, Semantic,   |
|  Skill, Decision, Research               |
+------------------------------------------+
                    |
                    v
+------------------------------------------+
|           Safety System                   |
|  Schema validation, pre/post guards,     |
|  execution monitoring, audit trail       |
+------------------------------------------+
```

## Module Summary

| Module | Purpose | Interface |
|--------|---------|-----------|
| Planner | NL goal -> structured plan | Input: goal + world state + memory; Output: Plan JSON |
| Task System | Task lifecycle management | create/update/query/fail tasks |
| Skill Library | Reusable action storage | list/get/execute/create skills |
| Action Controller | Execute game actions safely | execute_action(action, context) -> result |
| Observation Layer | Read game state | observe(bot) -> Observation |
| World State Layer | Structured state for LLM | summarize(observation) -> WorldState |
| Reflector | Learn from failures | analyze_failure(task, error) -> insights |
| Evaluator | Measure performance | run_benchmark(suite) -> results |
| Memory System | Multi-layer knowledge store | read/write/search/compress memory |
| Safety System | Enforce boundaries | validate/check/log actions |
| Episode Viability | Recall-controlled long-run termination | replay/calibrate/probe -> shadow or gated abort |

## Data Flow

1. User provides goal in natural language
2. Planner uses LLM + world state + memory to generate plan
3. Plan decomposes into task tree registered in Task System
4. Task System assigns skills from Skill Library
5. Action Controller executes actions on Minecraft via Mineflayer
6. Observation Layer reads game state after each action
7. World State Layer summarizes state for next planning cycle
8. Reflector analyzes failures and triggers re-planning
9. Evaluator tracks metrics across sessions
10. Memory System stores experiences, skills, and knowledge
11. Episode Viability probes only configured rounds; active abort requires an approved held-out recall certificate and exact runtime provenance

## Key Interfaces

### Plan Schema
```json
{
  "goal": "string",
  "strategic_steps": ["string"],
  "tactical_steps": ["Task"],
  "action_steps": ["Action"],
  "risk_assessment": "string",
  "success_criteria": "string",
  "failure_recovery": "string"
}
```

### Action Schema
```json
{
  "type": "string",
  "parameters": {},
  "preconditions": {},
  "expected_outcome": {},
  "timeout_ms": 30000
}
```

## Technology Decisions

See DECISIONS.md for full rationale:
- DEC-001: Hybrid architecture (Route F)
- DEC-002: Minecraft 1.20.4 (Paper)
- DEC-003: Mineflayer (primary) + Baritone (optional)
- DEC-004: Swappable LLM interface
- DEC-005: Markdown + JSON memory (Phase 1)

## Module Design Docs

Detailed design for each module:
- [Planner](module-planner.md)
- [Task System](module-task-system.md)
- [Memory System](module-memory.md)
- [Skill Library](module-skill-library.md)
- [Perception](module-perception.md)
- [Action Controller](module-action-controller.md)
- [Evaluator](module-evaluator.md)
- [Safety System](module-safety.md)
