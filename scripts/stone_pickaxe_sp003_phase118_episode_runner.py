"""Run the frozen SP-003 harness with the Phase 118 process-local overlay."""

from __future__ import annotations

import stone_pickaxe_sp003_episode_runner as frozen_runner

from singularity.evaluation.stone_pickaxe_sp003_phase118_runtime import (
    StonePickaxeSP003Phase118RuntimeAgent,
)


def main() -> int:
    frozen_runner.StonePickaxeSP003Phase116RuntimeAgent = (
        StonePickaxeSP003Phase118RuntimeAgent
    )
    return frozen_runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
