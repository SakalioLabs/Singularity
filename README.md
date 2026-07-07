# Singularity - Minecraft LLM Agent

> An evolving modular agent system that drives a Minecraft Java Edition player through natural-language goals, progressing from basic connectivity to autonomous multi-agent collaboration.

[![M0: Research Baseline](https://img.shields.io/badge/M0-Complete-brightgreen)]()
[![M1: Minimum Viable Bot](https://img.shields.io/badge/M1-In%20Progress-yellow)]()
[![Minecraft](https://img.shields.io/badge/Minecraft-1.20.4-green)]()
[![Python](https://img.shields.io/badge/Python-3.12-blue)]()
[![Node.js](https://img.shields.io/badge/Node.js-24.x-blue)]()

## Architecture

```
User Goal (Natural Language)
        |
        v
  +-----------+
  |  Planner  |  LLM-powered: strategic / tactical / action plans
  +-----------+
        |
        v
  +-----------+
  | Task System|  Hierarchical tasks, dependencies, priorities, state machine
  +-----------+
        |
        v
  +---------------+
  | Skill Library |  Reusable action units: code, action sequences, NL strategies
  +---------------+
        |
        v
  +------------------+
  | Action Controller|  Pre-check, execute, post-verify, timeout, rollback
  +------------------+
        |
        v
  +------------------+
  | Minecraft Server |  Via Mineflayer / Baritone / Mod API
  +------------------+
        |
        v
  +---------------+
  |  Observation  |  Position, health, inventory, entities, blocks, time, weather
  +---------------+
        |
        v
  +-----------+
  | Reflector |  Failure analysis, strategy adjustment, memory updates
  +-----------+
        |
        v
  +-----------+
  |  Memory   |  L0-L6 layered memory system
  +-----------+
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Agent Core | Python 3.12 | Main observe-think-act loop |
| Bot Interface | Mineflayer (Node.js) | Minecraft protocol interaction |
| Pathfinding | mineflayer-pathfinder | Navigation with obstacle avoidance |
| LLM Backend | OpenAI / Anthropic / DeepSeek / Ollama | Planning, reflection, skill generation |
| Memory | Markdown + JSON (Phase 1) | Human-readable, git-tracked knowledge |
| Task System | Python state machine | Hierarchical task management |
| Skill Library | Python dataclass + file storage | Versioned reusable skills |
| Evaluation | Python benchmark suite | Structured task evaluation |

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+
- JDK 17+ (for Minecraft server)
- Minecraft Java Edition server (1.20.4)

### Installation

```bash
# Clone repository
git clone https://github.com/SakalioLabs/Singularity.git
cd Singularity

# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies
npm install

# Download Minecraft server (requires manual setup)
# See docs/SERVER_SETUP.md for details
```

### Running the Agent

```bash
# 1. Start Minecraft server
cd mc-server
java -Xmx1G -Xms512M -jar server.jar nogui

# 2. Start bot bridge (in new terminal)
node src/bot/bot_server.js

# 3. Run agent (in new terminal)
python -m singularity.main --goal "Gather 3 oak logs"

# Options:
#   --goal "natural language goal"
#   --host localhost
#   --port 25565
#   --username Singularity
#   --llm-provider openai
#   --llm-model gpt-4o-mini
#   --api-key YOUR_API_KEY
#   --log-level INFO
```

## Project Structure

```
Singularity/
©À©¤©¤ README.md                          # This file
©À©¤©¤ requirements.txt                   # Python dependencies
©À©¤©¤ package.json                       # Node.js dependencies
©À©¤©¤ src/
©¦   ©À©¤©¤ singularity/                   # Python agent package
©¦   ©¦   ©À©¤©¤ core/
©¦   ©¦   ©¦   ©À©¤©¤ agent.py              # Main observe-think-act loop
©¦   ©¦   ©¦   ©À©¤©¤ config.py             # Configuration dataclasses
©¦   ©¦   ©¦   ©À©¤©¤ planner.py            # LLM-powered goal decomposition
©¦   ©¦   ©¦   ©À©¤©¤ reflector.py          # Failure analysis and re-planning
©¦   ©¦   ©¦   ©À©¤©¤ skill_library.py      # 17 builtin skills with versioning
©¦   ©¦   ©¦   ©À©¤©¤ task_system.py        # Hierarchical task state machine
©¦   ©¦   ©¦   ©¸©¤©¤ memory.py             # L0-L6 multi-layer memory
©¦   ©¦   ©À©¤©¤ llm/
©¦   ©¦   ©¦   ©¸©¤©¤ provider.py           # Swappable LLM (OpenAI/Anthropic/Ollama)
©¦   ©¦   ©À©¤©¤ observation/
©¦   ©¦   ©¦   ©¸©¤©¤ observer.py           # Game state collection
©¦   ©¦   ©À©¤©¤ action/
©¦   ©¦   ©¦   ©¸©¤©¤ controller.py         # Action execution with safety
©¦   ©¦   ©À©¤©¤ bot/
©¦   ©¦   ©¦   ©¸©¤©¤ bridge.py             # Python-Node.js TCP socket bridge
©¦   ©¦   ©¸©¤©¤ main.py                   # CLI entry point
©¦   ©¸©¤©¤ bot/
©¦       ©¸©¤©¤ bot_server.js             # Node.js Mineflayer server
©À©¤©¤ workspace/                         # Research knowledge base
©¦   ©À©¤©¤ ROADMAP.md                    # M0-M7 phase roadmap
©¦   ©À©¤©¤ STATUS.md                     # Current project status
©¦   ©À©¤©¤ MEMORY.md                     # Long-term validated knowledge
©¦   ©À©¤©¤ DECISIONS.md                  # Architecture decisions log
©¦   ©À©¤©¤ RISKS.md                      # Risk register
©¦   ©À©¤©¤ OPEN_QUESTIONS.md            # Unresolved research questions
©¦   ©À©¤©¤ PROGRESS.md                   # Detailed progress tracking
©¦   ©À©¤©¤ papers/                       # 17 paper cards
©¦   ©À©¤©¤ repos/                        # 4 repo cards
©¦   ©À©¤©¤ architecture/                 # 8 module design docs
©¦   ©À©¤©¤ benchmarks/                   # 5 benchmark suites (14 tasks)
©¦   ©¸©¤©¤ implementation/               # 15+ technical notes
©¸©¤©¤ docs/
    ©¸©¤©¤ SERVER_SETUP.md               # Server setup guide
```

## Capability Levels

| Level | Description | Status |
|-------|-------------|--------|
| 0 | Connect to Minecraft server, read basic state, execute simple commands | **Complete** |
| 1 | Complete short tasks from natural language: move, gather, mine, craft basics | In Progress |
| 2 | Multi-step tasks: craft iron pickaxe, build a shelter, prepare night resources | Planned |
| 3 | Maintain task queue, long-term memory, skill library; retry on failure | Planned |
| 4 | Self-directed goal-setting: survival bootstrapping, resource gathering, tech tree | Planned |
| 5 | Explore unknown worlds, learn and reuse skills, adapt to new maps | Planned |
| 6 | Integrate vision / multimodal input / VLA, reduce script dependency | Planned |
| 7 | Multi-agent collaboration, division of labor, long-term human co-play | Planned |

## Research Foundation

- **17 papers** analyzed: Voyager, MineDojo, JARVIS-1, GITM, DEPS, STEVE-1, OmniJARVIS, Mindcraft, Optimus-1, ReAct, Reflexion, Code-as-Policies, Tree of Thoughts, Toolformer, Genie, SkillForge, Multi-Agent MC
- **4 key repos** evaluated: Mindcraft, Mineflayer, Baritone, MineDojo
- **5 architecture decisions** documented with rollback conditions
- **10 research questions** identified and tracked

## Design Constraints

1. **Safety First**: LLM never directly executes dangerous code. All actions go through safety layer.
2. **Interruptible**: All game actions are interruptible (stop / pause / resume / rollback).
3. **Measurable**: Every task must have measurable success criteria.
4. **Memory Integrity**: Memory must resist pollution. Only verified, reusable information enters long-term memory.
5. **License Compliance**: Research must track licenses. Record citation and reuse boundaries.
6. **Model Agnostic**: Model providers must be swappable. No single-provider lock-in.
7. **Version Pinned**: Minecraft version must be pinned per experiment.
8. **Evidence Based**: No capability claims without 3+ repeated experiment results.

## Current Phase

**M1: Minimum Viable Bot** - Environment ready, bot connects to MC server. Working on benchmark validation.

### M1 Milestones
- [x] Python agent package (agent, config, observer, action controller, bot bridge)
- [x] Node.js Mineflayer bot server with pathfinding
- [x] JDK 17 + MC 1.20.4 server environment
- [x] EXP-0001: Bot connected to MC server
- [ ] BM-001 through BM-005 benchmark validation
- [ ] Session logger with structured JSON output
- [ ] Error handling and retry logic

### Next: M2 (LLM Task Planning)
- Integrate Planner module with actual LLM API calls
- Test end-to-end goal completion
- Implement reflection and re-planning

## Contributing

This is a research project. Contributions welcome:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

## License

TBD - Research project. Individual dependencies retain their original licenses.

## Contact

- **Repository**: [SakalioLabs/Singularity](https://github.com/SakalioLabs/Singularity)
- **Email**: sakalioling@rankchord.com
- **Issues**: [GitHub Issues](https://github.com/SakalioLabs/Singularity/issues)
