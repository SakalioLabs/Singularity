# Dual-Loop Runtime Design
> Status: first implementation pass, 2026-07-08

## Purpose

Split responsibilities between a slower planner loop and a fast actor-side supervisor without introducing thread complexity before live benchmarks are stable.

## Runtime Shape

Planner loop:
- observes world state
- retrieves memory and skills
- creates plan actions and task metadata
- accepts/reorders tasks through `TaskSystem`

Actor loop:
- checks runtime interrupts before each action
- executes one action through `ActionController`
- observes post-action state
- writes task-state updates, memory episodes, and session logs
- yields back to the planner when an interrupt fires

## Interrupts Implemented

`RuntimeSupervisor` currently emits `InterruptDecision` for:
- `health_critical`: use available food before continuing
- `hostile_nearby`: equip the best available weapon or tool
- `task_deadline_elapsed`: yield to replanning for overdue tasks
- `return_to_base`: move toward base when exploration policy says to return

This keeps M1/M2 benchmark execution simple while giving the actor a safety layer that does not wait for a full LLM/planner cycle.

## Next Steps

- Add action timeout envelopes around long-running bridge commands.
- Let `TaskSystem` mark interrupted tasks as waiting or blocked based on interrupt reason.
- Turn repeated runtime interrupts into experience atoms for failure recovery prompts.
- Later, move planner and actor into separate cooperative loops once live benchmark traces are stable.
