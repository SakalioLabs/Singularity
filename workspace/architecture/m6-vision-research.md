# M6: Vision and Multimodal Enhancement - Research Analysis

## Overview
M6 explores integrating visual input alongside structured API data to improve the agent's understanding of Minecraft worlds.

## Key Papers
- **STEVE-1** (2023): Text-conditioned behavior generation via latent action pretraining. Demonstrates zero-shot text-to-behavior without human demos.
- **OmniJARVIS** (2024): Unified vision-language-action model for open-world Minecraft. State-of-the-art VLA reference.
- **JARVIS-1** (2023): Multimodal memory with pretrained visual backbone. Near-human performance on many tasks.

## Approach Options

### Option A: Screenshot + VLM (Vision Language Model)
- Capture game screenshots
- Send to GPT-4V or similar VLM for scene understanding
- Use VLM output to augment structured API observations
- **Pros**: No training needed, leverages frontier models
- **Cons**: High latency (1-3s per frame), high cost ($0.01-0.10 per image)

### Option B: Minimap / Overhead View
- Use server-side map plugins for top-down view
- Process minimap as structured data (biome types, structures)
- **Pros**: Lower latency, structured data
- **Cons**: Limited information, needs server plugin

### Option C: Block-level Visual Grounding
- Use raycasting from bot to identify visible blocks
- Build spatial memory of surroundings
- **Pros**: No vision model needed, low latency
- **Cons**: Limited to what raycast can detect

## Recommendation
Start with Option C (block-level grounding) as it aligns with our existing Mineflayer API approach. Option A (VLM) should be tested in M6 as an A/B comparison against API-only performance.

## Implementation Plan
1. Enhance observer to build spatial grid of visible blocks
2. Test VLM integration with screenshot capture
3. Run A/B comparison on same tasks
4. Write decision report on whether to continue investing in vision

## Decision Criteria
- If vision adds >20% task success on ambiguous tasks: continue investment
- If vision adds <10% improvement: defer to later, API-first is sufficient
- Latency must stay under 2s per decision cycle for real-time tasks
