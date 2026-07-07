# M4: Autonomous Survival Loop - Implementation Plan

## Overview
Enable the agent to self-direct survival goals: first-night shelter, resource gathering, tool progression, and threat response.

## Architecture

### Strategic Goal Generator
The agent needs a high-level goal generator that proposes survival goals based on current state:

```
Time of Day -> Night approaching? -> Shelter goal
Inventory   -> No tools?           -> Tool crafting goal  
Health      -> Low?                -> Food/healing goal
Resources   -> Missing key item?   -> Resource gathering goal
Tech Tree   -> Can upgrade tools?  -> Tool progression goal
```

### Goal Priority System
| Priority | Goal Category | Trigger |
|----------|--------------|---------|
| 1 (Critical) | Survive immediate threat | Hostile mob nearby, health < 6 |
| 2 (Urgent) | Prepare for night | Time > 10000, no shelter |
| 3 (Important) | Tool progression | Can craft better tools |
| 4 (Normal) | Resource gathering | Missing materials |
| 5 (Low) | Exploration | All urgent needs met |

### Night Cycle Awareness
```
Day phases:
  Dawn:    0-1000     (safe, resume activities)
  Day:     1000-6000  (safe, gather resources)
  Dusk:    6000-12000 (prepare shelter)
  Night:   12000-18000 (stay sheltered, craft/smelt)
  Pre-dawn: 18000-24000 (prepare for day)
```

### First Night Survival Strategy
1. **Minutes 1-3**: Punch trees, get 6+ oak logs
2. **Minutes 3-5**: Craft planks, sticks, wooden pickaxe, crafting table
3. **Minutes 5-8**: Mine cobblestone, craft stone tools
4. **Minutes 8-10**: Find coal or make charcoal, craft torches
5. **Minutes 10-15**: Build simple shelter (dirt/wood box with door)
6. **Night**: Craft furnace, smelt ores, craft better tools

### Combat/Threat Response
- Detect hostile mobs within 8 blocks
- If armed: attack nearest threat
- If unarmed: flee toward shelter
- If cornered: dig underground

## Implementation Steps

### Step 1: Strategic Goal Generator
Create `src/singularity/core/goal_generator.py`:
- Analyzes world state (time, health, inventory, threats)
- Proposes prioritized goals
- Respects night cycle constraints

### Step 2: Survival Loop Integration
Update `agent.py` to use goal generator when no explicit goal:
```python
if not self.current_goal:
    self.current_goal = self.goal_generator.next_goal(observation)
```

### Step 3: Combat Skills
Add to skill library:
- `flee_to_shelter`: Navigate to known safe position
- `attack_nearest_hostile`: Target closest hostile mob
- `dig_emergency_bunker`: Dig 3-block deep hole

### Step 4: Resource Management
Track resource chains:
- Wood -> Planks -> Sticks -> Tools
- Cobblestone -> Stone Tools
- Iron Ore -> Furnace -> Iron Ingots -> Iron Tools

## Acceptance Criteria
- [ ] Survives first night on fixed seed (3+ repetitions)
- [ ] Self-proposes next survival goals without human input
- [ ] Handles nighttime threats (shelter, combat, retreat)
- [ ] Logs success rate and failure types
