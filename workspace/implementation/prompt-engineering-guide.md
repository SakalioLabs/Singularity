# LLM Prompt Engineering Guide for Minecraft Agent

## System Prompt Template
You are a Minecraft survival agent. Given the current game state and a goal, output a JSON plan.

Available actions: move_to(x,z), look_at(x,y,z), dig(x,y,z), place(x,y,z,item), craft(item,count), attack(entity_id), equip(item,dest), use_item(), chat(msg), wait(ms)

Output format:
{"status":"in_progress|complete|blocked","reasoning":"...","actions":[{"type":"action_name","parameters":{...}}]}

## Key Principles
1. Always check inventory before crafting
2. Prefer safe actions (no lava, no heights)
3. Use tools for their intended purpose (pickaxe for stone, axe for wood)
4. Eat food when health < 15
5. Build shelter before nightfall
6. Never break bedrock or end portal frames

## Common Failure Patterns and Fixes
- "No recipe found" -> Check if crafting table is needed (3x3 grid)
- "Block cannot be broken" -> Wrong tool or need better tool tier
- "Path not found" -> Target unreachable, try alternate direction
- "Inventory full" -> Drop or store non-essential items
- "Entity not found" -> Mob moved or despawned, re-scan

## Token Optimization
- Summarize inventory as counts, not full item objects
- Only include nearby entities within 16 blocks
- Compress block scans to unique types with counts
- Use shorthand for common actions
