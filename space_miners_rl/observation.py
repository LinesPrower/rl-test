"""Observation encoding for Round 1 self-play training."""

from __future__ import annotations

import math

import gymnasium as gym
import numpy as np

from space_miners_rl.game_imports import GAME_HEIGHT, GAME_WIDTH, MAX_VELOCITY, ROUND1_SHIP_COUNT


GLOBAL_FEATURES = 8
SHIP_FEATURES = 12
ASTEROID_FEATURES = 23
ASTEROID_SIZES = ("small", "medium", "large")

_ASTEROID_RADIUS = {"small": 5.0, "medium": 10.0, "large": 20.0}
_ASTEROID_MASS = {"small": 15.0, "medium": 20.0, "large": 30.0}
_ASTEROID_POINTS = {"small": 5.0, "medium": 10.0, "large": 20.0}
_MAX_ASTEROID_RADIUS = 20.0
_MAX_ASTEROID_MASS = 30.0
_MAX_ASTEROID_POINTS = 20.0
_BASE_COLLECTION_RADIUS = 100.0
_DIAG = math.sqrt(GAME_WIDTH * GAME_WIDTH + GAME_HEIGHT * GAME_HEIGHT)
_TIME_NORM_DENOM = _DIAG / MAX_VELOCITY


def make_observation_space(max_asteroids: int) -> gym.spaces.Dict:
    return gym.spaces.Dict(
        {
            "global": gym.spaces.Box(low=-5.0, high=5.0, shape=(GLOBAL_FEATURES,), dtype=np.float32),
            "my_ships": gym.spaces.Box(
                low=-5.0, high=5.0, shape=(ROUND1_SHIP_COUNT, SHIP_FEATURES), dtype=np.float32
            ),
            "opp_ships": gym.spaces.Box(
                low=-5.0, high=5.0, shape=(ROUND1_SHIP_COUNT, SHIP_FEATURES), dtype=np.float32
            ),
            "asteroids": gym.spaces.Box(
                low=-5.0, high=5.0, shape=(max_asteroids, ASTEROID_FEATURES), dtype=np.float32
            ),
            "asteroid_mask": gym.spaces.Box(low=0.0, high=1.0, shape=(max_asteroids,), dtype=np.float32),
        }
    )


def _canonical_xyv(x: float, y: float, vx: float, vy: float, player_id: int) -> tuple[float, float, float, float]:
    if player_id == 0:
        return x, y, vx, vy
    return GAME_WIDTH - x, y, -vx, vy


def _encode_ship(
    ship: dict,
    own_base_x: float,
    enemy_base_x: float,
    player_id: int,
    is_own: bool,
) -> np.ndarray:
    x = float(ship["position"]["x"])
    y = float(ship["position"]["y"])
    vx = float(ship["velocity"]["x"])
    vy = float(ship["velocity"]["y"])
    x, y, vx, vy = _canonical_xyv(x, y, vx, vy, player_id)

    rel_own_x = own_base_x - x
    rel_own_y = GAME_HEIGHT / 2.0 - y
    rel_enemy_x = enemy_base_x - x
    rel_enemy_y = GAME_HEIGHT / 2.0 - y

    speed = math.sqrt(vx * vx + vy * vy)
    diag = math.sqrt(GAME_WIDTH * GAME_WIDTH + GAME_HEIGHT * GAME_HEIGHT)
    dist_own_base = math.sqrt(rel_own_x * rel_own_x + rel_own_y * rel_own_y)
    dist_enemy_base = math.sqrt(rel_enemy_x * rel_enemy_x + rel_enemy_y * rel_enemy_y)

    return np.asarray(
        [
            x / GAME_WIDTH,
            y / GAME_HEIGHT,
            vx / MAX_VELOCITY,
            vy / MAX_VELOCITY,
            speed / MAX_VELOCITY,
            dist_own_base / diag,
            dist_enemy_base / diag,
            rel_own_x / GAME_WIDTH,
            rel_own_y / GAME_HEIGHT,
            rel_enemy_x / GAME_WIDTH,
            rel_enemy_y / GAME_HEIGHT,
            1.0 if is_own else 0.0,  # is_own
        ],
        dtype=np.float32,
    )


def _normalized_approach(vx: float, vy: float, rel_x: float, rel_y: float) -> float:
    rel_len = math.sqrt(rel_x * rel_x + rel_y * rel_y)
    if rel_len <= 1e-8:
        return 0.0
    return float((vx * rel_x + vy * rel_y) / (rel_len * MAX_VELOCITY))


def _ray_hit_base(
    x: float,
    y: float,
    vx: float,
    vy: float,
    base_x: float,
    base_y: float,
    asteroid_radius: float,
) -> tuple[float, float]:
    # Ray-circle intersection: p(t) = p0 + v*t, t >= 0.
    speed_sq = vx * vx + vy * vy
    if speed_sq <= 1e-8:
        return 0.0, 0.0

    ox = x - base_x
    oy = y - base_y
    a = speed_sq
    b = 2.0 * (ox * vx + oy * vy)
    c = ox * ox + oy * oy - _BASE_COLLECTION_RADIUS * _BASE_COLLECTION_RADIUS

    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return 0.0, 0.0

    sqrt_disc = math.sqrt(disc)
    t1 = (-b - sqrt_disc) / (2.0 * a)
    t2 = (-b + sqrt_disc) / (2.0 * a)
    valid_ts = [t for t in (t1, t2) if t >= 0.0]
    if not valid_ts:
        return 0.0, 0.0
    t_hit = min(valid_ts)

    ix = x + vx * t_hit
    iy = y + vy * t_hit
    # Keep only intersections that are valid within the playable area, with wall clearance.
    if not (
        asteroid_radius <= ix <= (GAME_WIDTH - asteroid_radius)
        and asteroid_radius <= iy <= (GAME_HEIGHT - asteroid_radius)
    ):
        return 0.0, 0.0

    return 1.0, float(min(1.0, max(0.0, t_hit / _TIME_NORM_DENOM)))


def _encode_asteroid(asteroid: dict, player_id: int) -> np.ndarray:
    x = float(asteroid["position"]["x"])
    y = float(asteroid["position"]["y"])
    vx = float(asteroid["velocity"]["x"])
    vy = float(asteroid["velocity"]["y"])
    x, y, vx, vy = _canonical_xyv(x, y, vx, vy, player_id)

    asteroid_size = asteroid["size"]
    radius = _ASTEROID_RADIUS[asteroid_size]
    mass = _ASTEROID_MASS[asteroid_size]
    points = _ASTEROID_POINTS[asteroid_size]
    one_hot = [1.0 if asteroid_size == s else 0.0 for s in ASTEROID_SIZES]

    own_base_x = 0.0
    own_base_y = GAME_HEIGHT / 2.0
    enemy_base_x = GAME_WIDTH
    enemy_base_y = GAME_HEIGHT / 2.0

    rel_own_x = own_base_x - x
    rel_own_y = own_base_y - y
    rel_enemy_x = enemy_base_x - x
    rel_enemy_y = enemy_base_y - y

    dist_own_base = math.sqrt(rel_own_x * rel_own_x + rel_own_y * rel_own_y)
    dist_enemy_base = math.sqrt(rel_enemy_x * rel_enemy_x + rel_enemy_y * rel_enemy_y)
    speed = math.sqrt(vx * vx + vy * vy)
    approach_own = _normalized_approach(vx, vy, rel_own_x, rel_own_y)
    approach_enemy = _normalized_approach(vx, vy, rel_enemy_x, rel_enemy_y)
    will_hit_own, time_to_own = _ray_hit_base(x, y, vx, vy, own_base_x, own_base_y, radius)
    will_hit_enemy, time_to_enemy = _ray_hit_base(x, y, vx, vy, enemy_base_x, enemy_base_y, radius)

    return np.asarray(
        [
            one_hot[0],  # 0 size_small
            one_hot[1],  # 1 size_medium
            one_hot[2],  # 2 size_large
            radius / _MAX_ASTEROID_RADIUS,  # 3 radius
            mass / _MAX_ASTEROID_MASS,  # 4 mass
            points / _MAX_ASTEROID_POINTS,  # 5 points
            x / GAME_WIDTH,  # 6 x
            y / GAME_HEIGHT,  # 7 y
            vx / MAX_VELOCITY,  # 8 vx
            vy / MAX_VELOCITY,  # 9 vy
            speed / MAX_VELOCITY,  # 10 speed
            dist_own_base / _DIAG,  # 11 dist_own_base
            dist_enemy_base / _DIAG,  # 12 dist_enemy_base
            rel_own_x / GAME_WIDTH,  # 13 rel_own_base_x
            rel_own_y / GAME_HEIGHT,  # 14 rel_own_base_y
            rel_enemy_x / GAME_WIDTH,  # 15 rel_enemy_base_x
            rel_enemy_y / GAME_HEIGHT,  # 16 rel_enemy_base_y
            approach_own,  # 17 approach_own_base
            approach_enemy,  # 18 approach_enemy_base
            will_hit_own,  # 19 will_hit_own_base
            time_to_own,  # 20 time_to_own_base
            will_hit_enemy,  # 21 will_hit_enemy_base
            time_to_enemy,  # 22 time_to_enemy_base
        ],
        dtype=np.float32,
    )


def encode_player_observation(
    game_state,
    player_id: int,
    max_ticks: int,
    max_asteroids: int,
    score_norm: float,
) -> dict[str, np.ndarray]:
    my_player = game_state.players[player_id]
    opp_player = game_state.players[1 - player_id]

    own_base_x = 0.0
    enemy_base_x = GAME_WIDTH

    my_ships = np.zeros((ROUND1_SHIP_COUNT, SHIP_FEATURES), dtype=np.float32)
    opp_ships = np.zeros((ROUND1_SHIP_COUNT, SHIP_FEATURES), dtype=np.float32)
    for i, ship in enumerate(my_player.ships[:ROUND1_SHIP_COUNT]):
        my_ships[i] = _encode_ship(
            ship.to_dict(),
            own_base_x,
            enemy_base_x,
            player_id,
            is_own=True,
        )
    for i, ship in enumerate(opp_player.ships[:ROUND1_SHIP_COUNT]):
        opp_ships[i] = _encode_ship(
            ship.to_dict(),
            own_base_x,
            enemy_base_x,
            player_id,
            is_own=False,
        )

    asteroid_mask = np.zeros((max_asteroids,), dtype=np.float32)
    asteroids = np.zeros((max_asteroids, ASTEROID_FEATURES), dtype=np.float32)
    asteroid_dicts = [a.to_dict() for a in game_state.asteroids]
    asteroid_dicts.sort(key=lambda a: a["id"])
    for i, asteroid in enumerate(asteroid_dicts[:max_asteroids]):
        asteroids[i] = _encode_asteroid(asteroid, player_id)
        asteroid_mask[i] = 1.0

    turn_ratio = game_state.tick / float(max(1, max_ticks))
    my_score = float(my_player.score)
    opp_score = float(opp_player.score)

    global_features = np.asarray(
        [
            turn_ratio,
            my_score / score_norm,
            opp_score / score_norm,
            (my_score - opp_score) / score_norm,
            float(len(asteroid_dicts)) / float(max_asteroids),
            0.0,  # energy disabled in Round 1
            0.0,  # upgrades disabled in Round 1
            1.0,  # bias term
        ],
        dtype=np.float32,
    )

    return {
        "global": global_features,
        "my_ships": my_ships,
        "opp_ships": opp_ships,
        "asteroids": asteroids,
        "asteroid_mask": asteroid_mask,
    }
