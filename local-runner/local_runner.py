#!/usr/bin/env python3
"""
Local Game Runner for AI Competition

A lightweight entry point for running any supported game locally.
This script allows participants to run games locally without needing the full
competition infrastructure. It uses the same core game logic as the main system.
"""

import argparse
import logging
import os
import json
import sys
import time
import importlib
from datetime import datetime
from base_game_state import BaseGameState

# ANSI color codes for console output
class ColorFormatter(logging.Formatter):
    # Color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[37m',     # White
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }

    def format(self, record):
        # Get the color for this log level
        color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        # Format the message with color
        formatted = super().format(record)
        return f"{color}{formatted}{self.COLORS['RESET']}"

# Configure logging
logger = logging.getLogger("local_runner")
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
color_formatter = ColorFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(color_formatter)
logger.addHandler(ch)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Import from the existing codebase
from game_manager import GameManager
from strategy_runner import StrategyRunner
from replay_runner import ReplayRunner, load_replay_data
from utils import round_floats

def get_game_state_class(game_name: str) -> type[BaseGameState]:
    """Dynamically imports the game state class from the specified game module."""
    try:
        module_path = f"games.{game_name}.state"
        module = importlib.import_module(module_path)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, BaseGameState) and attr is not BaseGameState:
                return attr
        raise ImportError(f"No BaseGameState subclass found in {module_path}")
    except (ImportError, ModuleNotFoundError) as e:
        logger.error(f"Could not load game module for '{game_name}': {e}")
        raise

def setup_file_logger(log_file):
    """Set up a file logger in addition to console output"""
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return file_handler

def run_local_game(game_manager, game_state_class, game_settings, run_commands, save_replay_path, game_name):
    """A standalone function to run a local game, replacing the old method."""
    logger.info("Starting local game")
    game_state = game_state_class(game_settings, logger=logger)

    # Prepare strategy configurations
    strategies = []
    for i, run_command in enumerate(run_commands):
        parts = run_command.split()
        identifier = parts[-1] if parts else f"strategy_{i}"
        strategies.append({
            "id": f"local_{i}",
            "file": identifier,
            "run_command": run_command
        })

    start_time = time.time()
    game_manager.strategy_runner.initialize_strategies(game_state, strategies, logger=logger)

    strategy_names = [s['file'].split('/')[-1].split('.')[0] for s in strategies]
    logger.info("=== PLAYER ASSIGNMENTS ===")
    for i, run_command in enumerate(run_commands):
        logger.info(f"Player {i}: {strategy_names[i]} -> {run_command}")
    logger.info("=" * 26)

    initial_state = game_state.to_dict()

    try:
        while not game_state.is_game_over():
            actions = game_manager.strategy_runner.get_actions(game_state)

            # Check for strategy failures
            failed_strategies = [
                (i, strategy_names[i]) for i, action in enumerate(actions)
                if action is None and game_state.players[i].is_active
            ]

            if failed_strategies:
                logger.error("=== STRATEGY FAILURES DETECTED ===")
                for player_id, name in failed_strategies:
                    reason = game_state.players[player_id].disqualification_reason
                    logger.error(f"Player {player_id} ({name}) failed: {reason}")
                    stderr = game_manager.strategy_runner.strategy_stderr[player_id]
                    if stderr:
                        logger.error(f"Player {player_id} ({name}) stderr:\n" + "".join(stderr))
                raise RuntimeError("Strategy execution failed.")

            game_state.update(actions)

            if game_state.tick % 100 == 0:
                scores = [f"P{i}({strategy_names[i]}): {p.score}" for i, p in enumerate(game_state.players)]
                logger.info(f"Turn {game_state.tick}: {', '.join(scores)}")

    finally:
        game_manager.strategy_runner.cleanup_strategies()

    end_time = time.time()
    game_duration = end_time - start_time
    logger.info(f"Local game completed in {game_duration:.2f}s")

    winner_index = game_state.get_winner_index()
    logger.info("=== FINAL RESULTS ===")
    for i, player in enumerate(game_state.players):
        winner_indicator = " 🏆 WINNER" if i == winner_index else ""
        logger.info(f"Player {i} ({strategy_names[i]}): Score: {player.score}{winner_indicator}")

    if winner_index == -1:
        logger.info("The game ended in a tie.")

    # Save replay if requested
    if save_replay_path:
        replay_package = {
            'gameName': game_name,
            'initialState': initial_state,
            'replayData': game_state.replay_data,
            'winnerIndex': winner_index,
            'timeInfo': {'gameDuration': int(game_duration * 1000), 'ticks': game_state.tick},
            'seed': game_settings.get('seed')
        }
        
        # Round all floats to 6 decimal places to reduce file size
        replay_package = round_floats(replay_package, decimals=6)
        
        with open(save_replay_path, 'w') as f:
            json.dump(replay_package, f)
        logger.info(f"Replay saved to {save_replay_path}")

def main():
    """Main entry point for the local game runner"""
    parser = argparse.ArgumentParser(description="Local Game Runner")

    # Game selection
    parser.add_argument("--game", default="space_miners_hard", help="Name of the game to run (e.g., 'space_miners')")

    # Game modes
    parser.add_argument(
        "--local",
        nargs='+',
        help="Run a local game with specified strategy run commands (e.g., 'python strat1.py' './strat2')"
    )

    # Generic game settings using --game-options
    parser.add_argument(
        '--game-options',
        nargs='*',
        help="Game-specific options as key=value pairs (e.g., ship_count=3 initial_asteroids=15)"
    )
    
    # Preset selection for convenient round configuration
    parser.add_argument(
        '--preset',
        type=str,
        choices=['Round 1', 'Round 2', 'Final Round'],
        help="Game preset (Round 1, Round 2, or Final Round). Overrides preset in --game-options."
    )
    
    parser.add_argument("--max-ticks", type=int, default=1000, help="Maximum game ticks (default: 1000)")

    # Replay options
    parser.add_argument("--replay", help="Path to replay file to view or debug against")
    parser.add_argument(
        "--strategy",
        help="Run command for debugging with a replay (same format as --local, e.g., 'python3 my_strategy.py' or './my_bot')"
    )
    parser.add_argument("--player", type=int, choices=[0, 1], help="Your player position (0 or 1) when debugging with a replay")
    parser.add_argument("--last-tick", type=int, help="When replaying, stop at this tick index (inclusive)")
    parser.add_argument("--save-replay", help="Save replay to specified file")

    # Logging options
    parser.add_argument("--log-file", help="Log to specified file in addition to console")
    
    # Determinism
    parser.add_argument("--seed", type=int, help="Seed for random number generator")

    # Enforce timeouts
    parser.add_argument("--enforce-timeouts", action="store_true", help="Enforce timeouts for READY check and game turns")

    args = parser.parse_args()
    if args.last_tick is not None and args.last_tick < 0:
        parser.error("--last-tick must be >= 0")
    if args.last_tick is not None and not args.replay:
        parser.error("--last-tick can only be used with --replay")

    file_handler = setup_file_logger(args.log_file) if args.log_file else None

    try:
        GameStateClass = get_game_state_class(args.game)
    except ImportError:
        logger.critical(f"Failed to load game '{args.game}'. Make sure 'games/{args.game}/' exists and is a valid game module.")
        sys.exit(1)

    strategy_runner = StrategyRunner(docker_manager=None, logger=logger, enforce_timeouts=args.enforce_timeouts)
    game_manager = GameManager(strategy_runner=strategy_runner, api_handler=None, logger=logger)

    try:
        if args.replay and not args.strategy:
            logger.info(f"Viewing replay from '{args.replay}'")
            replay_data = load_replay_data(args.replay)
            replay_runner = ReplayRunner(replay_data, strategy_runner, logger=logger)
            replay_runner.run_replay(None, None, last_tick=args.last_tick)

        elif args.replay and args.strategy and args.player is not None:
            logger.info(f"Debugging strategy '{args.strategy}' against replay '{args.replay}'")
            game_manager.run_replay(args.replay, args.strategy, args.player, last_tick=args.last_tick)

        elif args.local:
            if len(args.local) < 2:
                parser.error("Please provide at least two strategy run commands for local play.")

            import random
            
            # Determine seed
            if args.seed is not None:
                seed = args.seed
                logger.info(f"Using provided seed: {seed}")
            else:
                seed = random.randint(0, 2**32 - 1)
                logger.info(f"Generated random seed: {seed}")

            game_settings = {
                "max_ticks": args.max_ticks,
                "seed": seed
            }
            
            # Apply --preset if provided (takes precedence)
            if args.preset:
                game_settings['preset'] = args.preset
                logger.info(f"Using preset: {args.preset}")
            
            # Apply additional --game-options
            if args.game_options:
                for opt in args.game_options:
                    key, value = opt.split('=', 1)
                    try:
                        # Convert to int if possible, otherwise string
                        game_settings[key] = int(value)
                    except ValueError:
                        game_settings[key] = value

            logger.info(f"Starting local game '{args.game}' with settings: {game_settings}")

            run_local_game(
                game_manager=game_manager,
                game_state_class=GameStateClass,
                game_settings=game_settings,
                run_commands=args.local,
                save_replay_path=args.save_replay,
                game_name=args.game
            )

        else:
            parser.print_help()

    except Exception as e:
        logger.error(f"Error during execution: {e}", exc_info=True)

    finally:
        if file_handler:
            file_handler.close()
            logger.removeHandler(file_handler)

if __name__ == "__main__":
    main()
