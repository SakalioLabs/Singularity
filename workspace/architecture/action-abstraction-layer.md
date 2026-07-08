# Action Abstraction Layer
> Status: first implementation pass, 2026-07-08

## Purpose

Keep Singularity's planner and task system independent from a single execution backend.

The canonical action format remains:

```json
{"type": "craft", "parameters": {"item": "torch", "count": 4}}
```

`ActionMapper` converts canonical actions into backend-specific commands.

## Backends

### Mineflayer

Status: executable.

Canonical actions map directly to Mineflayer bridge commands such as `move_to`, `dig`, `craft`, `equip`, and `use_item`.

### Desktop Keyboard/Mouse

Status: planned, not executable.

Canonical actions map to planned desktop commands such as:
- `move_to` -> `keyboard_mouse_nav`
- `craft` -> `open_inventory_craft`
- `equip` -> `hotbar_equip`
- `use_item` -> `right_click_use`

`ActionController` refuses to execute this backend for now and returns a structured result that includes `backend_command` and `backend_params`.

## Feedback Loop

`action-abstraction-report` produces `action_abstraction_feedback` policy hints from session logs. The feedback groups canonical action usage, backend command usage, unknown action types, and low-level visual-control candidates by action type. `BenchmarkRunner.apply_action_abstraction_feedback()` can hand those hints to any policy object that implements `record_action_abstraction_feedback()`.

`ActionGranularityPolicy` is the first consumer. It records those hints and chooses a backend for each action while exposing the decision in `ActionController` results as `control_policy`. Mineflayer remains the safe executable default; visual/desktop preferences are preserved as explicit policy evidence and only selected when the policy is configured to allow planned or executable desktop backends.

## Why This Matters

Recent VLA/game-agent work such as JARVIS-VLA, Game-TARS, OpenHA, and CrossAgent uses keyboard-mouse, unified action spaces, or mixed action abstractions. This layer lets us keep the practical Mineflayer backend for M1-M7 while preserving a clean path toward visual desktop control and cross-level action selection later.

## Next Steps

- Add a desktop backend executor behind the same `BackendCommand` interface.
- Record backend command traces in benchmark logs.
- Compare Mineflayer API and `ActionGranularityPolicy` task performance in M6/M7.
- Run `action-abstraction-report` on real benchmark/session logs to compare policy hints by task family and identify where Mineflayer API control should yield to visual desktop control.
