#!/usr/bin/env python3
"""Evaluate a trained checkpoint in self-play env."""

from __future__ import annotations

import argparse

import ray
from ray.rllib.algorithms.algorithm import Algorithm

from space_miners_rl.env import SpaceMinersRound1SelfPlayEnv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate checkpoint winrate")
    parser.add_argument("--checkpoint", type=str, required=True)
    parser.add_argument("--episodes", type=int, default=50)
    parser.add_argument("--max-ticks", type=int, default=1000)
    parser.add_argument("--max-asteroids", type=int, default=20)
    parser.add_argument("--seed", type=int, default=777)
    parser.add_argument("--main-policy", type=str, default="main")
    parser.add_argument("--opp-policy", type=str, default="opponent")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    ray.init(ignore_reinit_error=True, log_to_driver=False)
    algo = Algorithm.from_checkpoint(args.checkpoint)
    env = SpaceMinersRound1SelfPlayEnv(
        {
            "max_ticks": args.max_ticks,
            "max_asteroids": args.max_asteroids,
            "seed": args.seed,
        }
    )

    wins = 0
    losses = 0
    ties = 0
    for _ in range(args.episodes):
        obs, _ = env.reset()
        done = False
        while not done:
            action_dict = {}
            action_dict["player_0"] = algo.compute_single_action(
                observation=obs["player_0"],
                policy_id=args.main_policy,
                explore=False,
            )
            action_dict["player_1"] = algo.compute_single_action(
                observation=obs["player_1"],
                policy_id=args.opp_policy,
                explore=False,
            )
            obs, _, terminateds, _, _ = env.step(action_dict)
            done = bool(terminateds["__all__"])

        if env.last_winner == 0:
            wins += 1
        elif env.last_winner == 1:
            losses += 1
        else:
            ties += 1

    total = max(1, args.episodes)
    print(f"episodes={args.episodes} wins={wins} losses={losses} ties={ties} winrate={wins/total:.3f}")
    algo.stop()
    ray.shutdown()


if __name__ == "__main__":
    main()

