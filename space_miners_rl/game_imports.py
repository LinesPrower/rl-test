"""Imports for local runner game modules."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_RUNNER_DIR = PROJECT_ROOT / "local-runner"

if str(LOCAL_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_RUNNER_DIR))

from games.space_miners_hard.state import (  # noqa: E402
    MAX_ACCELERATION,
    MAX_VELOCITY,
    SpaceMinersHardGameState,
)

# World geometry is fixed by the local runner's hard mode rules.
GAME_WIDTH = 1280.0
GAME_HEIGHT = 800.0
ROUND1_SHIP_COUNT = 3

