# Paper Card: SkillCenter

**Title**: SkillCenter: A Large-Scale Source-Grounded Skill Library for Autonomous AI Agents

**Source**: https://arxiv.org/abs/2607.07676

**Date Reviewed**: 2026-07-10

**Core Method**: Builds a large skill library through multi-source acquisition, an LLM quality gate, template generation, iterative source grounding, and controlled publishing.

**Evidence**:
- Reports 216,938 structured skills across 24 domain bundles.
- The filtered subset contains 114,565 source-grounded skills alongside 102,373 community skills.
- Source grounding maps retained claims to exact source quotations and ships in offline-searchable SQLite FTS5 bundles.

**Useful Transfer**:
- Skill scale makes provenance and retrieval structure more important, not less.
- Keep source-grounded and community-derived skills distinguishable.
- Retrieval traces should expose why a skill was selected without injecting whole source documents.

**Project Action**: Singularity keeps skill governance/provenance in contracts and emits a sanitized route trace. External bulk skill import remains disabled until source, license, promptware, and Minecraft-action compatibility checks are explicit.
