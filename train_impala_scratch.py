#!/usr/bin/env python3
"""Train Round-1 Space Miners agent from scratch with IMPALA."""

from __future__ import annotations

import argparse
import os
import shutil
import time
from collections import deque
from pathlib import Path

import ray
from ray.rllib.algorithms.impala import IMPALAConfig
from ray.rllib.models import ModelCatalog
from ray.rllib.policy.policy import PolicySpec
from ray.tune.registry import register_env

from space_miners_rl.callbacks import OpponentSyncCallback
from space_miners_rl.env import SpaceMinersRound1SelfPlayEnv
from space_miners_rl.model import SpaceMinersAttentionModel, count_trainable_parameters
from space_miners_rl.policy_mapping import map_agent_to_policy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Round 1 IMPALA training")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--checkpoint-dir", type=Path, default=Path("checkpoints/impala_round1"))
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument(
        "--restore-from",
        type=Path,
        default=None,
        help="Optional checkpoint path to resume from.",
    )
    parser.add_argument("--ray-address", type=str, default=None, help="e.g. auto, ray://host:10001")
    parser.add_argument("--num-workers", type=int, default=8)
    parser.add_argument("--num-envs-per-worker", type=int, default=1)
    parser.add_argument("--num-gpus", type=float, default=0.0)
    parser.add_argument("--max-ticks", type=int, default=250)
    parser.add_argument("--max-asteroids", type=int, default=20)
    parser.add_argument("--train-batch-size", type=int, default=16000)
    parser.add_argument("--rollout-fragment-length", type=int, default=250)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--gamma", type=float, default=0.999)
    parser.add_argument("--entropy-coeff", type=float, default=6e-5)
    parser.add_argument("--vf-loss-coeff", type=float, default=0.5)
    parser.add_argument("--grad-clip", type=float, default=40.0)
    parser.add_argument("--score-reward-scale", type=float, default=0.0002)
    parser.add_argument("--terminal-win-reward", type=float, default=1.0)
    parser.add_argument("--score-norm", type=float, default=2000.0)
    parser.add_argument("--self-play-sync-interval", type=int, default=25)
    parser.add_argument("--opponent-mode", type=str, choices=["noop", "selfplay"], default="noop")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--d-model", type=int, default=128)
    parser.add_argument("--num-heads", type=int, default=4)
    parser.add_argument("--attention-layers", type=int, default=2)
    parser.add_argument("--trunk-hidden", type=int, default=512)
    return parser.parse_args()


def _maybe_disable_new_api_stack(config: IMPALAConfig) -> IMPALAConfig:
    if hasattr(config, "api_stack"):
        return config.api_stack(enable_rl_module_and_learner=False, enable_env_runner_and_connector_v2=False)
    return config


def _configure_sampling(config: IMPALAConfig, args: argparse.Namespace) -> IMPALAConfig:
    """Support both new and legacy Ray sampling APIs."""
    if hasattr(config, "env_runners"):
        return config.env_runners(
            num_env_runners=args.num_workers,
            num_envs_per_env_runner=args.num_envs_per_worker,
            rollout_fragment_length=args.rollout_fragment_length,
        )
    return config.rollouts(
        num_rollout_workers=args.num_workers,
        num_envs_per_worker=args.num_envs_per_worker,
        rollout_fragment_length=args.rollout_fragment_length,
    )


def build_config(args: argparse.Namespace) -> IMPALAConfig:
    env_name = "space_miners_round1_selfplay_v0"
    register_env(env_name, lambda cfg: SpaceMinersRound1SelfPlayEnv(cfg))
    ModelCatalog.register_custom_model("space_miners_attn_model", SpaceMinersAttentionModel)

    test_env = SpaceMinersRound1SelfPlayEnv(
        {
            "max_ticks": args.max_ticks,
            "max_asteroids": args.max_asteroids,
            "score_reward_scale": args.score_reward_scale,
            "terminal_win_reward": args.terminal_win_reward,
            "score_norm": args.score_norm,
            "opponent_mode": args.opponent_mode,
            "seed": args.seed,
        }
    )
    obs_space = test_env.observation_space
    act_space = test_env.action_space

    OpponentSyncCallback.configure(
        args.self_play_sync_interval,
        sync_enabled=(args.opponent_mode == "selfplay"),
    )

    config = IMPALAConfig()
    config = _maybe_disable_new_api_stack(config)
    config = config.environment(
            env=env_name,
            env_config={
                "max_ticks": args.max_ticks,
                "max_asteroids": args.max_asteroids,
                "score_reward_scale": args.score_reward_scale,
                "terminal_win_reward": args.terminal_win_reward,
                "score_norm": args.score_norm,
                "opponent_mode": args.opponent_mode,
                "seed": args.seed,
            },
        )
    config = config.framework("torch").resources(num_gpus=args.num_gpus)
    config = _configure_sampling(config, args)
    config = (
        config.training(
            lr=args.lr,
            gamma=args.gamma,
            train_batch_size=args.train_batch_size,
            grad_clip=args.grad_clip,
            entropy_coeff=args.entropy_coeff,
            vf_loss_coeff=args.vf_loss_coeff,
            model={
                "custom_model": "space_miners_attn_model",
                "_disable_preprocessor_api": True,
                "custom_model_config": {
                    "d_model": args.d_model,
                    "num_heads": args.num_heads,
                    "attention_layers": args.attention_layers,
                    "trunk_hidden": args.trunk_hidden,
                },
            },
        )
        .callbacks(OpponentSyncCallback)
        .multi_agent(
            policies={
                "main": PolicySpec(observation_space=obs_space, action_space=act_space, config={}),
                "opponent": PolicySpec(observation_space=obs_space, action_space=act_space, config={}),
            },
            policy_mapping_fn=map_agent_to_policy,
            policies_to_train=["main"],
        )
        .debugging(log_level="WARN")
    )
    return config


def _as_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _checkpoint_path(save_result) -> str | None:
    checkpoint_obj = getattr(save_result, "checkpoint", None)
    path = getattr(checkpoint_obj, "path", None)
    if path:
        return str(path)
    if isinstance(save_result, str):
        return save_result
    return None


def _replace_checkpoint_snapshot(src_path: str, dst_path: Path) -> None:
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if dst.is_dir():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def main() -> None:
    args = parse_args()
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    if args.ray_address:
        ray.init(address=args.ray_address, ignore_reinit_error=True, log_to_driver=True)
    else:
        ray.init(ignore_reinit_error=True, log_to_driver=True)

    config = build_config(args)
    algo = config.build()

    if args.restore_from is not None:
        restore_path = str(args.restore_from)
        algo.restore(restore_path)
        print(f"Restored from checkpoint: {restore_path}")

    main_model = algo.get_policy("main").model
    params = count_trainable_parameters(main_model)
    print(f"Main policy trainable parameters: {params:,}")
    print(f"Opponent mode: {args.opponent_mode}")
    if params < 900_000 or params > 1_300_000:
        print("Warning: model is outside the target ~1M range. Adjust d_model/trunk_hidden if needed.")

    latest_checkpoint = None
    best_checkpoint_dir = args.checkpoint_dir.parent / f"{args.checkpoint_dir.name}_best"
    winrate_window: deque[float] = deque(maxlen=10)
    best_winrate_10 = float("-inf")
    best_iteration = 0
    start = time.time()
    try:
        for iteration in range(1, args.iterations + 1):
            result = algo.train()
            env_metrics = result.get("env_runners", {})
            custom_metrics = env_metrics.get("custom_metrics", {})

            ep_reward_mean = env_metrics.get("episode_reward_mean")
            if ep_reward_mean is None:
                ep_reward_mean = result.get("episode_reward_mean")

            learner_stats = result.get("info", {}).get("learner", {}).get("main", {}).get("learner_stats", {})
            entropy = _as_float_or_none(learner_stats.get("entropy"))
            winrate = _as_float_or_none(custom_metrics.get("main_win_mean"))
            lossrate = _as_float_or_none(custom_metrics.get("main_loss_mean"))
            tierate = _as_float_or_none(custom_metrics.get("main_tie_mean"))
            score_diff = _as_float_or_none(custom_metrics.get("score_diff_mean"))
            winrate_10 = None
            if winrate is not None:
                winrate_window.append(winrate)
            if len(winrate_window) == winrate_window.maxlen:
                winrate_10 = sum(winrate_window) / len(winrate_window)

            msg = [
                f"iter={iteration:04d}",
                f"timesteps_total={result.get('timesteps_total')}",
                f"reward_mean={_as_float_or_none(ep_reward_mean)}",
                f"entropy={entropy}",
            ]
            if winrate is not None:
                msg.append(f"win={winrate:.3f}")
            if lossrate is not None:
                msg.append(f"loss={lossrate:.3f}")
            if tierate is not None:
                msg.append(f"tie={tierate:.3f}")
            if score_diff is not None:
                msg.append(f"score_diff={score_diff:.3f}")
            if winrate_10 is not None:
                msg.append(f"win10={winrate_10:.3f}")
            print(
                " ".join(msg)
            )

            regular_checkpoint = iteration % args.checkpoint_every == 0
            best_checkpoint = winrate_10 is not None and winrate_10 > best_winrate_10
            if regular_checkpoint or best_checkpoint:
                latest_checkpoint = algo.save(str(args.checkpoint_dir))
                ckpt_path = _checkpoint_path(latest_checkpoint)
                if regular_checkpoint:
                    print(f"checkpoint: {ckpt_path or latest_checkpoint}")
                if best_checkpoint and ckpt_path:
                    _replace_checkpoint_snapshot(ckpt_path, best_checkpoint_dir)
                    best_winrate_10 = winrate_10
                    best_iteration = iteration
                    print(
                        f"best checkpoint updated: iter={iteration:04d} "
                        f"win10={best_winrate_10:.3f} path={best_checkpoint_dir}"
                    )
    finally:
        final_checkpoint = algo.save(str(args.checkpoint_dir))
        final_ckpt_path = _checkpoint_path(final_checkpoint)
        elapsed = time.time() - start
        print(f"final checkpoint: {final_ckpt_path or final_checkpoint}")
        if best_iteration > 0:
            print(
                f"best checkpoint summary: iter={best_iteration:04d} "
                f"win10={best_winrate_10:.3f} path={best_checkpoint_dir}"
            )
        else:
            print("best checkpoint summary: no win10 metric available yet")
        print(f"elapsed_sec: {elapsed:.1f}")
        algo.stop()
        ray.shutdown()


if __name__ == "__main__":
    os.environ.setdefault("RAY_DEDUP_LOGS", "0")
    main()
