# Paper Card: The Blind Curator

**Title**: The Blind Curator: How a Biased Judge Silently Disables Skill Retirement in Self-Evolving Agents

**Source**: https://arxiv.org/abs/2607.07436

**Date Reviewed**: 2026-07-10

**Core Method**: Analyzes contribution-based skill retirement under corrupted rewards and isolates how false-pass bias prevents failed skills from being retired.

**Evidence**:
- Symmetric noise preserves retirement behavior, while sufficiently high false-pass bias disables it even with more data.
- Aggregate task quality can remain stable while the retirement mechanism has already failed.
- Proposes a low-cost defect-injection audit to test judge behavior before deployment.

**Useful Transfer**:
- Never retire Minecraft skills from an LLM judge score alone.
- Separate genuine retirement from capacity eviction or file pruning.
- Require verifier-backed injected failures and a no-skill baseline before runtime quarantine.

**Project Action**: Implemented per-judge defect-injection calibration, fixed-control no-skill contribution reports, and a live-evidence retirement gate. Approved results can only add task-family exclusions to an in-memory `SkillLibrary` overlay; built-ins remain available, skill files are preserved, and automatic deletion is always disabled. Live Minecraft evidence is still pending.
