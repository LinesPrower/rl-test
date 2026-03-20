"""Discrete action mapping for Round 1 ships.

Per ship:
- acceleration branch: 41 logits = no_acc + (8 directions * 5 magnitudes)
- push branch: 2 logits = no_push / push
"""

from __future__ import annotations

from typing import Iterable, Sequence

import gymnasium as gym
import numpy as np

from space_miners_rl.game_imports import MAX_ACCELERATION, ROUND1_SHIP_COUNT


# 8 cardinal/intercardinal directions.
_DIRECTIONS = (
    (1.0, 0.0),
    (0.70710678, 0.70710678),
    (0.0, 1.0),
    (-0.70710678, 0.70710678),
    (-1.0, 0.0),
    (-0.70710678, -0.70710678),
    (0.0, -1.0),
    (0.70710678, -0.70710678),
)

ACCEL_LOGITS_PER_SHIP = 41
PUSH_LOGITS_PER_SHIP = 2


def make_team_action_space() -> gym.spaces.MultiDiscrete:
    # Flattened per ship pair: [accel_0, push_0, accel_1, push_1, accel_2, push_2].
    nvec: list[int] = []
    for _ in range(ROUND1_SHIP_COUNT):
        nvec.extend([ACCEL_LOGITS_PER_SHIP, PUSH_LOGITS_PER_SHIP])
    return gym.spaces.MultiDiscrete(np.asarray(nvec, dtype=np.int64))


def decode_ship_action(accel_action_id: int, push_action_id: int) -> tuple[float, float, bool]:
    # 0 => no acceleration.
    if accel_action_id == 0:
        ax, ay = 0.0, 0.0
    elif 1 <= accel_action_id <= 40:
        # 1..40 => 8 directions x 5 magnitudes.
        local_id = accel_action_id - 1
        direction_id = local_id // 5
        magnitude_level = (local_id % 5) + 1  # 1..5
        magnitude = (magnitude_level / 5.0) * MAX_ACCELERATION
        dx, dy = _DIRECTIONS[direction_id]
        ax, ay = dx * magnitude, dy * magnitude
    else:
        raise ValueError(f"Unknown acceleration action id: {accel_action_id}")

    if push_action_id == 0:
        push = False
    elif push_action_id == 1:
        push = True
    else:
        raise ValueError(f"Unknown push action id: {push_action_id}")

    return ax, ay, push


def decode_team_action(team_action: Iterable[int] | Sequence[int]) -> dict:
    team_action = list(team_action)
    expected = ROUND1_SHIP_COUNT * 2
    if len(team_action) != expected:
        raise ValueError(f"Expected {expected} team action items, got {len(team_action)}")

    commands = []
    for ship_id in range(ROUND1_SHIP_COUNT):
        accel_id = int(team_action[2 * ship_id])
        push_id = int(team_action[2 * ship_id + 1])
        ax, ay, push = decode_ship_action(accel_id, push_id)
        commands.append(
            {
                "ship_id": ship_id,
                "acceleration": {"x": float(ax), "y": float(ay)},
                "push": bool(push),
            }
        )
    return {"commands": commands}
