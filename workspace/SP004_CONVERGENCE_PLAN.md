# SP-004 Stone-to-Iron Convergence Plan

## Objective

Starting with exactly one stone pickaxe and no carried cobblestone, coal, raw iron, iron ingots, furnace, or iron pickaxe:

1. Mine exactly eight distinct stone blocks.
2. Mine exactly ten distinct coal ore blocks.
3. Mine exactly three distinct iron ore blocks.
4. Find an observed crafting table or craft and place one.
5. Craft and place exactly one furnace.
6. Smelt exactly three raw iron with one coal in one zero-retry action.
7. Use two existing sticks or craft exactly four sticks once.
8. Craft exactly one iron pickaxe and prove it in terminal inventory.

## Fixed Runtime Contract

- Policy: `iron-pickaxe-sp004-stone-to-iron-runtime-v1`
- Action guard: `iron-pickaxe-sp004-action-guard-v1`
- Machine verifier: `iron-pickaxe-sp004-machine-verifier-v1`
- Planner protocol: `stone-pickaxe-skill-fixed-v1`, extended only for runtime mode `sp004`
- LLM: user-configured OpenAI-compatible endpoint with model `grok-4.5`
- Bridge entry point: `node src/bot/sp004_bot_server.js` (the frozen shared bridge remains unchanged)
- Planner output: one grounded action per planning call
- Smelt attempts: one
- Automatic action retry: false
- Evidence path: `workspace/evals/sp004_runs/<episode-id>`
- Capability credit: false
- M4 credit: false

## Current State

Offline implementation and focused regressions pass. Episode `sp004_live_20260724_032722`
passed the exact initial-state and bridge preflight with one stone pickaxe, two existing
sticks, an observed crafting table, and the zero-retry smelt policy. Its first Planner
request returned HTTP 502, so the run terminated `empty_plan` with zero gameplay
actions. The immutable episode is classified `infrastructure_provider_http_502` and
grants no capability or M4 credit. The next admissible step is a bounded provider probe
without Minecraft after this evidence is committed and pushed; another live episode is
not authorized by this record. Probe `sp004_provider_probe_20260724_034229` then made
one zero-retry chat request and received HTTP 502; a separate read-only models request
was disconnected before any response. Minecraft was not started. The provider is
currently unavailable, and a new live episode remains unauthorized until the provider
recovers and a fresh bounded no-Minecraft probe passes.

The recovery gate is now executable as
`python scripts/iron_pickaxe_sp004_provider_probe.py --output
workspace/evals/<unique-probe-name>.json`. It makes one 15-second-bounded request with
SDK retries disabled, records no credential or raw response, refuses output overwrite,
and never starts Minecraft. Probe `sp004_provider_probe_20260724_035327` exercised the
same gate controls and again received HTTP 502, so the live hold remains in force.

The controlled launcher is
`scripts/iron-pickaxe-sp004-runtime.ps1 -EpisodeId <unique-id>`. It requires synchronized
`main`, fresh evidence and world paths, accepted EULA state, free controlled ports, and
an operator account. It runs the provider recovery gate before every process start.
Only a passing probe may start Paper and the isolated bridge, initialize the exact
stone-pickaxe/stick/table/8-stone/10-coal/3-iron fixture, and invoke one bounded episode.
Its `finally` block stops only owned processes and restores the original server
properties.

## Blocked Audit

Three consecutive goal turns now contain equivalent one-attempt, zero-retry probes
against canonical `http://192.168.3.27:8317/v1` with model `grok-4.5`; all returned
HTTP 502 before any response bytes. The third canonical probe is
`sp004_recovery_audit_turn3_equivalent_20260724`. The earlier turn-three diagnostic
without `/v1` is retained but explicitly excluded from the threshold. No probe started
Minecraft or granted a live retry. The objective is blocked on external provider
recovery; work resumes only after the reusable bounded probe passes, at which point the
controlled launcher may start one fresh episode.

The goal was subsequently resumed. Resumed audit r1 reached the canonical provider but
returned HTTP 401 `AuthenticationError` rather than the prior HTTP 502. This is a new
blocking condition, classified `provider_authentication_failed`, so its resumed blocked
audit count is 1/3 and the prior 502 threshold is not reused. Minecraft was not
started. A valid credential must be configured outside chat and a fresh bounded probe
must pass before the controlled launcher can run.

## Live Acceptance

A live episode passes only when all independent verifier criteria pass, including:

- exact initial inventory boundary;
- exact 8/10/3 distinct source counts and action counts;
- only required ore-family digs;
- one observed or made crafting table;
- one furnace craft and placement;
- one settled smelt action with three raw iron consumed, three ingots collected, and one coal consumed;
- valid stick provenance;
- one iron-pickaxe craft;
- no failed actions;
- ordered stage history;
- terminal `iron_pickaxe: 1`;
- supplied progress exactly matching action-result reconstruction.

One passing episode is lifecycle evidence only. Stable autonomous capability requires separately authorized independent repeats.
