# USAGE.md - Singularity Minecraft LLM Agent

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- JDK 17+ (for MC server)
- MC 1.20.4 server jar

### Setup
```powershell
# Clone and install
git clone https://github.com/SakalioLabs/Singularity.git
cd Singularity
.\setup.ps1
```

### Running the Agent

**Terminal 1: MC Server**
```powershell
cd mc-server
java -Xmx1G -Xms512M -jar server.jar nogui
```

**Terminal 2: Bot Bridge**
```powershell
node src/bot/bot_server.js
```

**Terminal 3: Agent**
```powershell
# With OpenAI
$env:OPENAI_API_KEY = "sk-..."
python -m singularity.main run --goal "Gather 3 oak logs" --llm-provider openai --llm-model gpt-4o-mini

# With DeepSeek
python -m singularity.main run --goal "Gather wood" --llm-provider openai --llm-model deepseek-chat --api-key YOUR_KEY --base-url https://api.deepseek.com/v1

# With local Ollama
python -m singularity.main run --goal "Gather wood" --llm-provider ollama --llm-model llama3

# Rule-based (no LLM needed)
python -m singularity.main run --goal "Gather 3 oak logs"
```

### Running Benchmarks
```powershell
# M1 benchmarks (basic actions)
python -m singularity.main benchmark --suite m1

# M2 benchmarks (LLM planning)
python -m singularity.main benchmark --suite m2

# Both
python -m singularity.main benchmark --suite all
```

### Running Tests
```powershell
# Goal generator tests
python tests/test_goal_generator.py

# M2 integration (needs OPENAI_API_KEY)
$env:OPENAI_API_KEY = "sk-..."
python tests/test_m2_integration.py
```

## Architecture

```
User Goal (NL) -> Planner (LLM) -> TaskSystem -> SkillLibrary -> ActionController -> Mineflayer Bot
                                               |                                    |
                                               v                                    v
                                           Memory (L0-L6)                     MC Server
                                               ^
                                               |
                                           Observer -> Reflector
```

## Key Modules

| Module | File | Purpose |
|--------|------|---------|
| Agent | core/agent.py | Main observe-think-act loop |
| Planner | core/planner.py | LLM-powered goal decomposition |
| TaskSystem | core/task_system.py | Hierarchical task state machine |
| SkillLibrary | core/skill_library.py | 17 builtin + custom skills |
| Memory | core/memory.py | L0-L6 layered memory system |
| Observer | observation/observer.py | Game state collection (32-block scan) |
| ActionController | action/controller.py | Safe action execution |
| GoalGenerator | core/goal_generator.py | Autonomous survival goals (M4) |
| Explorer | core/explorer.py | Open-world exploration (M5) |
| SkillExtractor | core/skill_extractor.py | Extract skills from traces (M3) |
| KnowledgeBase | data/knowledge_base.py | Crafting recipes and game knowledge |
| SessionLogger | logging/session_logger.py | JSONL structured logging |

## LLM Provider Configuration

### OpenAI
```
--llm-provider openai --llm-model gpt-4o-mini
```

### Anthropic
```
--llm-provider anthropic --llm-model claude-3-5-sonnet-20241022
```

### DeepSeek
```
--llm-provider openai --llm-model deepseek-chat --base-url https://api.deepseek.com/v1
```

### Qwen
```
--llm-provider openai --llm-model qwen-turbo --base-url https://dashscope.aliyuncs.com/compatible-mode/v1
```

### Ollama (local)
```
--llm-provider ollama --llm-model llama3
```
