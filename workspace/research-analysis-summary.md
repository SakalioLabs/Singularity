# Research Analysis Summary - Singularity Project

> Last updated: 2026-07-07
> Synthesizes findings from 17 papers, 4 repos, and architectural analysis.

## Key Research Questions Answered

### RQ1: What action space should the agent use?
**Answer**: Hybrid approach (DEC-001). Start with structured Mineflayer API calls, allow code-as-skill later.
- GITM shows 300+ structured text actions work for diamond obtainment (67.5% success)
- Voyager shows code-as-skill (JS functions) enables open-ended exploration
- Our choice: Mineflayer API actions with optional code skills, wrapped in safety layer

### RQ2: How should the task system handle long-horizon goals?
**Answer**: Hierarchical task tree (HTN-like) with state machine.
- DEPS demonstrates describe-explain-plan-select loop improves multi-task completion
- Optimus-1 uses knowledge graphs for long-horizon planning
- Our choice: TaskSystem with proposed/active/completed/failed states, priority-based scheduling

### RQ3: What memory technology stack?
**Answer**: Start with Markdown + JSON, evaluate SQLite/vector after M3.
- JARVIS-1 shows multimodal episodic memory improves retrieval
- GITM shows text-only memory can work for structured tasks
- Our choice: L0-L6 layered memory, human-readable Markdown for auditability

### RQ4: How should skills be represented?
**Answer**: Multi-layer: NL strategy, action sequence tactics, code primitives.
- Voyager code-as-skill achieved 3.3x more unique items explored
- Code-as-Policies shows LLM-generated code is viable for robot control
- Our choice: SkillLibrary with primitive/composite/strategic layers, version-tracked

### RQ5: How to inject Minecraft domain knowledge?
**Answer**: Hybrid: structured recipe DB + tech tree + RAG for edge cases.
- MineDojo demonstrates value of internet-scale knowledge
- Our choice: mc-knowledge-base.md + tech-tree.md + prompt engineering

### RQ6: How to reduce LLM hallucination?
**Answer**: Structured output + pre/post-condition checks + reflection.
- Reflexion shows verbal self-reflection improves retry success significantly
- Our choice: JSON schema validation, ActionController pre-checks, Reflector on failure

### RQ7: How to evaluate reliably?
**Answer**: Fixed-seed benchmarks for M1-M3, aggregate for M4+.
- MineDojo provides 1000+ task benchmark framework
- Our choice: 14 benchmark tasks across 5 suites, 3+ repetitions required

### RQ8: When to transition from API to human-like control?
**Answer**: API sufficient for M0-M5. Evaluate vision at M6.
- STEVE-1 and OmniJARVIS show VLA is possible but high cost/latency
- Our choice: Structured API as primary, vision as optional enhancement at M6

### RQ9: Multi-agent communication protocol?
**Answer**: Deferred to M7. Start with shared memory.
- Limited existing work on MC multi-agent
- Our choice: Simple shared-memory approach, evaluate message passing later

### RQ10: How to maintain system evolution?
**Answer**: Modular architecture + comprehensive logging + version control.
- Our choice: Module boundaries with defined interfaces, session JSONL logs, git-based versioning

## Architectural Decisions from Research

| Decision | Chosen Approach | Key Evidence |
|----------|----------------|--------------|
| DEC-001 Route F | Hybrid LLM + Mineflayer + Skill Library | Voyager, GITM, Mindcraft |
| DEC-002 MC Version | 1.20.4 | Mineflayer stability, plugin ecosystem |
| DEC-003 Bot Library | Mineflayer primary | Mindcraft success, rich plugin ecosystem |
| DEC-004 LLM Provider | Swappable interface | Provider landscape changes rapidly |
| DEC-005 Memory Format | Markdown + JSON | Human-readable, git-tracked, LLM-native |

## State of the Art Comparison

| System | Action Space | Memory | Planning | Our Comparison |
|--------|-------------|--------|----------|----------------|
| Voyager | JS Code | Skill Lib | LLM Curriculum | Similar skill library, add task system |
| GITM | 300+ Text Actions | Text KB | Structured Plans | Similar action space, add reflection |
| JARVIS-1 | MineRL | Multimodal | LLM+Visual | We use API-first, defer vision to M6 |
| Mindcraft | Mineflayer | Conversation | LLM Chat | We add formal task system + memory |
| Optimus-1 | Structured | KG+Episodic | Hierarchical | Similar hierarchy, add skill extraction |

## Recommendations for Next Steps

1. **M1 Completion**: Run BM-001 through BM-005 to validate basic functionality
2. **M2 Priority**: Wire Planner to real LLM API, test with simple goals first
3. **Token Budgeting**: Set per-task token limits to control costs (RISK-003)
4. **Knowledge Injection**: Load crafting recipes into prompt context for M2
5. **Reflection Testing**: Verify Reflexion-style reflection improves retry success
