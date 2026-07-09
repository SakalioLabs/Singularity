# Paper Card: Stealthy Memory Injection in OpenClaw Agents

**Title**: When Claws Remember: Stealthy and Persistent Memory Injections in OpenClaw Agents
**Source**: https://arxiv.org/abs/2607.05189
**Date**: 2026-07-06
**Type**: Agent memory security / persistent attack paper
**Core Problem**: OpenClaw-style agents with persistent, user-updateable memories can retain malicious instructions across sessions, turning memory from a helpful context layer into a durable attack surface.
**Core Method**:
  - Demonstrates indirect prompt-injection paths that write attacker-controlled content into persistent memory.
  - Studies persistence and stealth: the dangerous payload may be activated later, outside the original interaction.
  - Targets agents that combine memory, tool use, and autonomous multi-step execution.
**Why It Matters for Minecraft**:
  - Minecraft agents increasingly keep durable task, skill, correction, visual, and collaboration memories.
  - A malicious observation, chat message, label, or review artifact could try to persist unsafe tool instructions, credential requests, or false task policies.
  - Runtime profiles should package only reviewed paths and gates, never raw user text, provider credentials, or unvalidated memory artifacts.
**Singularity Adaptation**:
  - `MemoryLifecyclePolicy` already routes promptware-like memory writes to review or suppression, and `memory-promptware-report` audits durable memory stores.
  - `runtime-profile-build` now packages only explicit gate/artifact paths and safe switches, then validates approved gates and path existence before a profile can be used as live configuration.
  - `runtime-profile-security-audit` scans profile-referenced feedback, correction, patch, value, and style artifacts with the same promptware detector before live startup. Reports identify path/field/location/hash without copying raw artifact text into the saved audit.
  - Runtime profiles deliberately do not store provider keys, prompts, or raw memory contents; secrets stay in environment variables or the current operator-controlled shell.
**Next Action**: Run `runtime-profile-security-audit` on real M1/M2/M7 runtime profiles, then inspect and quarantine any rejected referenced artifacts before live runs.
