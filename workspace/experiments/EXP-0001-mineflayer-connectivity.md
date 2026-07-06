# Experiment: EXP-0001 Mineflayer Connectivity Test

## Metadata
- Date: Planned (M1)
- Phase: M1
- Hypothesis: Mineflayer bot can connect to a local Paper 1.20.4 server and read basic state within 5 seconds

## Setup
- Minecraft version: 1.20.4
- Server type: Paper
- Bot library: Mineflayer 4.x
- LLM model: N/A (connectivity test only)
- World seed: Any

## Procedure
1. Start local Paper 1.20.4 server
2. Launch Node.js bot server
3. Connect Python agent via bridge
4. Read player state (position, health, inventory)
5. Verify state values are non-null and reasonable

## Success Criteria
- Bot connects within 5 seconds
- Player state returns valid position (non-zero coordinates)
- Health returns 20.0
- Inventory returns valid list (may be empty)

## Failure Criteria
- Connection timeout > 10 seconds
- Any state returns null or NaN
- Bot gets kicked from server

## Metrics
- Connection latency (ms)
- State read latency (ms)
- Memory usage (MB)
- Stability over 60 seconds

## Expected Risks
- Paper server may need specific configuration for offline mode
- Mineflayer version compatibility with 1.20.4
- Python-Node.js bridge socket latency
