"""Round 1 self-play environment for RLlib."""

from __future__ import annotations

import logging
import random
from typing import Any

from ray.rllib.env.multi_agent_env import MultiAgentEnv

from space_miners_rl.action_space import decode_team_action, make_team_action_space
from space_miners_rl.game_imports import SpaceMinersHardGameState
from space_miners_rl.observation import encode_player_observation, make_observation_space


class SpaceMinersRound1SelfPlayEnv(MultiAgentEnv):
    """Two-agent env where player_0 and player_1 both act each tick."""

    def __init__(self, env_config: dict[str, Any] | None = None):
        super().__init__()
        env_config = dict(env_config or {})

        self.max_ticks = int(env_config.get("max_ticks", 1000))
        self.max_asteroids = int(env_config.get("max_asteroids", 20))
        self.score_reward_scale = float(env_config.get("score_reward_scale", 0.0002))
        self.terminal_win_reward = float(env_config.get("terminal_win_reward", 1.0))
        self.score_norm = float(env_config.get("score_norm", 2000.0))
        self.opponent_mode = str(env_config.get("opponent_mode", "noop")).lower()
        if self.opponent_mode not in {"noop", "selfplay"}:
            raise ValueError(f"Unsupported opponent_mode={self.opponent_mode!r}, expected 'noop' or 'selfplay'")
        self.base_seed = env_config.get("seed")

        worker_offset = int(env_config.get("worker_index", 0)) * 100_000
        vector_offset = int(env_config.get("vector_index", 0)) * 10_000
        derived_seed = None if self.base_seed is None else int(self.base_seed) + worker_offset + vector_offset
        self.rng = random.Random(derived_seed)

        self.observation_space = make_observation_space(self.max_asteroids)
        self.action_space = make_team_action_space()
        self.possible_agents = ["player_0", "player_1"]
        self.agents = list(self.possible_agents)

        self._state: SpaceMinersHardGameState | None = None
        self._prev_scores = (0.0, 0.0)
        self.last_winner = -1

        self.logger = logging.getLogger("space_miners_rl.env")
        self.logger.setLevel(logging.WARNING)

    def _new_seed(self, override_seed: int | None) -> int:
        if override_seed is not None:
            return int(override_seed)
        return self.rng.randint(0, 2**31 - 1)

    def _obs_for(self, player_id: int) -> dict:
        assert self._state is not None
        return encode_player_observation(
            game_state=self._state,
            player_id=player_id,
            max_ticks=self.max_ticks,
            max_asteroids=self.max_asteroids,
            score_norm=self.score_norm,
        )

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        game_options = {
            "preset": "Round 1",
            "max_ticks": self.max_ticks,
            "seed": self._new_seed(seed),
        }
        self._state = SpaceMinersHardGameState(game_options=game_options, logger=self.logger)
        self._prev_scores = (0.0, 0.0)
        self.last_winner = -1

        observations = {
            "player_0": self._obs_for(0),
            "player_1": self._obs_for(1),
        }
        infos = {
            "player_0": {"score": 0.0, "opponent_score": 0.0},
            "player_1": {"score": 0.0, "opponent_score": 0.0},
        }
        return observations, infos

    def step(self, action_dict):
        assert self._state is not None

        a0 = action_dict.get("player_0", [0, 0, 0, 0, 0, 0])
        if self.opponent_mode == "noop":
            a1 = [0, 0, 0, 0, 0, 0]
        else:
            a1 = action_dict.get("player_1", [0, 0, 0, 0, 0, 0])
        decoded_actions = [decode_team_action(a0), decode_team_action(a1)]
        self._state.update(decoded_actions)

        score0 = float(self._state.players[0].score)
        score1 = float(self._state.players[1].score)
        delta0 = score0 - self._prev_scores[0]
        delta1 = score1 - self._prev_scores[1]
        self._prev_scores = (score0, score1)

        r0 = self.score_reward_scale * (delta0 - delta1)
        r1 = self.score_reward_scale * (delta1 - delta0)

        done = self._state.is_game_over()
        if done:
            self.last_winner = int(self._state.get_winner_index())
            if self.last_winner == 0:
                r0 = self.terminal_win_reward
                r1 = -self.terminal_win_reward
            elif self.last_winner == 1:
                r0 = -self.terminal_win_reward
                r1 = self.terminal_win_reward

        rewards = {"player_0": float(r0), "player_1": float(r1)}
        terminateds = {"player_0": done, "player_1": done, "__all__": done}
        truncateds = {"player_0": False, "player_1": False, "__all__": False}

        infos = {
            "player_0": {"score": score0, "opponent_score": score1},
            "player_1": {"score": score1, "opponent_score": score0},
        }

        observations = {
            "player_0": self._obs_for(0),
            "player_1": self._obs_for(1),
        }
        return observations, rewards, terminateds, truncateds, infos
