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

## Why This Matters

Recent VLA/game-agent work such as JARVIS-VLA, Game-TARS, OpenHA, and CrossAgent uses keyboard-mouse, unified action spaces, or mixed action abstractions. This layer lets us keep the practical Mineflayer backend for M1-M7 while preserving a clean path toward visual desktop control and cross-level action selection later.

## Next Steps

- Add a desktop backend executor behind the same `BackendCommand` interface.
- Record backend command traces in benchmark logs.
- Compare Mineflayer API and desktop-control task performance in M6/M7.
- Run `action-abstraction-report` on real benchmark/session logs to count canonical action types, backend command types, failed backend mappings, and tasks that may need lower-level visual control.
