"""Training callbacks."""

from __future__ import annotations

from typing import Any

from ray.rllib.algorithms.callbacks import DefaultCallbacks


class OpponentSyncCallback(DefaultCallbacks):
    """Copies main policy weights into opponent policy every N iterations."""

    update_interval = 25
    sync_enabled = True

    @classmethod
    def configure(cls, update_interval: int, sync_enabled: bool = True) -> None:
        cls.update_interval = max(1, int(update_interval))
        cls.sync_enabled = bool(sync_enabled)

    @staticmethod
    def _sync(algorithm) -> None:
        main_policy = algorithm.get_policy("main")
        opponent_policy = algorithm.get_policy("opponent")
        opponent_policy.set_weights(main_policy.get_weights())

    @staticmethod
    def _extract_scores(episode: Any) -> tuple[float, float]:
        info0 = {}
        info1 = {}
        if hasattr(episode, "last_info_for"):
            info0 = episode.last_info_for("player_0") or {}
            info1 = episode.last_info_for("player_1") or {}

        score0 = float(info0.get("score", 0.0))
        if "score" in info1:
            score1 = float(info1.get("score", 0.0))
        else:
            score1 = float(info0.get("opponent_score", 0.0))
        return score0, score1

    @staticmethod
    def _extract_winner_from_env(base_env: Any, env_index: int) -> int | None:
        if base_env is None or not hasattr(base_env, "get_sub_environments"):
            return None
        sub_envs = base_env.get_sub_environments()
        if not sub_envs or env_index >= len(sub_envs):
            return None
        winner = getattr(sub_envs[env_index], "last_winner", None)
        if winner in (-1, 0, 1):
            return int(winner)
        return None

    def on_episode_end(self, *, episode, base_env=None, env_index=0, **kwargs):
        """Emit per-episode metrics from player_0 (main policy) perspective."""
        score0, score1 = self._extract_scores(episode)
        score_diff = score0 - score1

        winner = self._extract_winner_from_env(base_env=base_env, env_index=int(env_index))
        if winner is None:
            eps = 1e-6
            if score_diff > eps:
                winner = 0
            elif score_diff < -eps:
                winner = 1
            else:
                winner = -1

        episode.custom_metrics["main_win"] = 1.0 if winner == 0 else 0.0
        episode.custom_metrics["main_loss"] = 1.0 if winner == 1 else 0.0
        episode.custom_metrics["main_tie"] = 1.0 if winner == -1 else 0.0
        episode.custom_metrics["main_score"] = float(score0)
        episode.custom_metrics["opp_score"] = float(score1)
        episode.custom_metrics["score_diff"] = float(score_diff)

    def on_algorithm_init(self, *, algorithm, **kwargs):
        if self.sync_enabled:
            self._sync(algorithm)

    def on_train_result(self, *, algorithm, result: dict, **kwargs):
        iteration = int(result.get("training_iteration", 0))
        custom_metrics = result.setdefault("custom_metrics", {})

        # Convenience aliases for dashboards/CLI while preserving RLlib's *_mean values.
        if "main_win_mean" in custom_metrics:
            custom_metrics["winrate"] = float(custom_metrics["main_win_mean"])
        if "score_diff_mean" in custom_metrics:
            custom_metrics["score_diff_avg"] = float(custom_metrics["score_diff_mean"])

        if self.sync_enabled and iteration > 0 and iteration % self.update_interval == 0:
            self._sync(algorithm)
            custom_metrics["opponent_synced"] = 1.0
