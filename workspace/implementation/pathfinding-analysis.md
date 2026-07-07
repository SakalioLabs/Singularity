# Pathfinding Analysis

## mineflayer-pathfinder
- Algorithm: A* with heuristic
- Supports: GoalBlock, GoalNear, GoalXZ, GoalY, GoalFollow
- Limitations: Struggles with water, lava, vertical drops, complex terrain
- Performance: ~50-200ms for 100-block paths

## Baritone
- Algorithm: Advanced A* with Minecraft-specific optimizations
- Supports: Auto-mine, auto-build, sprint, parkour
- Limitations: Java-only, version-coupled, LGPL license
- Performance: Very fast for long distances

## Our Approach
1. Use mineflayer-pathfinder for M1-M5 (JavaScript, well-maintained)
2. Add custom heuristics for Minecraft terrain
3. Fallback to direct movement if pathfinding fails
4. Monitor and log pathfinding failures for improvement
