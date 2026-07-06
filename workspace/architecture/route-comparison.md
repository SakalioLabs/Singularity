# Technical Route Comparison

## Route A: Mineflayer + LLM Planner (Mindcraft-style)
- Pros: Fast iteration, rich API, good community
- Cons: Node.js dependency, abstract actions
- Fit: Our M1-M3 default path
- Risk: Medium

## Route B: Mineflayer + Baritone + LLM
- Pros: Excellent pathfinding, navigation automation
- Cons: Version coupling, LGPL license, mod complexity
- Fit: M5 exploration enhancement
- Risk: Medium-High

## Route C: Voyager-like Code-as-Skill
- Pros: Self-improving skill library, open-ended exploration
- Cons: Code execution safety, expensive GPT-4 calls
- Fit: M3 skill library inspiration
- Risk: Medium

## Route D: Forge/Fabric Mod + LLM
- Pros: Full game access, closest to real player
- Cons: High engineering cost, version-locked
- Fit: M6+ if vision integration needed
- Risk: High

## Route E: Visual Input + VLA
- Pros: Most human-like, reduces API dependency
- Cons: High latency, high training cost, hard to evaluate
- Fit: M6 research phase only
- Risk: High

## Route F: Hybrid (Our Default)
- Pros: Incremental, flexible, de-risked
- Cons: More integration points
- Fit: All phases
- Risk: Low-Medium

## Decision: Route F confirmed. Start with A, add B for navigation, C for skills, D/E only if justified by M6 research.
