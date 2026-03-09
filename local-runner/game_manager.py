import time
import json
import copy
import logging
import os
from typing import Dict, List, Optional
from base_game_state import BaseGameState
from strategy_runner import StrategyRunner
from replay_runner import ReplayRunner, load_replay_data
from utils import round_floats

# API support is optional
try:
    from api_handler import APIHandler, GameStatus
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False

class GameManager:
    def __init__(self, strategy_runner: StrategyRunner, api_handler: Optional['APIHandler'] = None, logger: logging.Logger = None):
        if api_handler is not None and not API_AVAILABLE:
            raise ImportError("API support is not available.")
        self.strategy_runner = strategy_runner
        self.api_handler = api_handler
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(__name__)
            self.logger.setLevel(logging.INFO)

            # Create console handler and set level to INFO
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)

            # Create formatter
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

            # Add formatter to console handler
            ch.setFormatter(formatter)

            # Add console handler to logger
            self.logger.addHandler(ch)

        self.initial_state = None  # Initialize initial_state

    def run_game(self, game_data: Dict, game_state_class: type[BaseGameState]):
        game_id = game_data['_id']

        # Use the provided logger
        logger = self.logger

        try:
            game_options = game_data.get('settings', {})
            
            # Ensure seed is present
            if 'seed' not in game_options:
                import random
                seed = random.randint(0, 2**32 - 1)
                game_options['seed'] = seed
                logger.info(f"Generated random seed for game {game_id}: {seed}")
            else:
                logger.info(f"Using provided seed for game {game_id}: {game_options['seed']}")

            game_state = game_state_class(game_options, logger=logger)
            self.initial_state = game_state.to_dict()
            strategies = game_data['strategies']

            for s in strategies:
                if s['language'] in ['cpp', 'go', 'rust', 'swift', 'csharp', 'c', 'kotlin']:
                    s['run_command'] = './main'
                elif s['language'] == 'python':
                    s['run_command'] = 'python3 main.py'
                elif s['language'] == 'javascript':
                    s['run_command'] = 'node main.js'
                elif s['language'] == 'java':
                    s['run_command'] = 'java \
                        -cp "/usr/lib/jackson/*:." \
                        -XX:+UseG1GC \
                        -XX:+ExplicitGCInvokesConcurrent \
                        -XX:MaxMetaspaceSize=32m \
                        -XX:ReservedCodeCacheSize=8m \
                        -Xss256k \
                        -Xms180m \
                        -Xmx180m \
                        -XX:+AlwaysPreTouch \
                        -XX:+TieredCompilation \
                        Main'
                elif s['language'] == 'scala':
                    s['run_command'] = 'java \
                        -cp "/usr/lib/circe/*:." \
                        -XX:+UseG1GC \
                        -XX:+ExplicitGCInvokesConcurrent \
                        -XX:MaxMetaspaceSize=32m \
                        -XX:ReservedCodeCacheSize=8m \
                        -Xss256k \
                        -Xms180m \
                        -Xmx180m \
                        -XX:+AlwaysPreTouch \
                        -XX:+TieredCompilation \
                        Main'
                else:
                    raise Exception(f"Don't know how to run {s['language']}")

            self.strategy_runner.initialize_strategies(game_state, strategies, logger=logger)

            start_time = time.time()

            while not game_state.is_game_over():
                actions = self.strategy_runner.get_actions(game_state)
                game_state.update(actions)

            end_time = time.time()

            self.strategy_runner.cleanup_strategies()

            result = self._prepare_game_results(strategies, game_state, start_time, end_time)
            result['timeInfo'].update(game_data['timeInfo'])
            if self.api_handler:
                self.api_handler.store_game_results(game_id, result)
        except Exception as e:
            logger.exception(f"Error processing game {game_id}")
            # Re-raise the exception so the game_runner knows there was an error
            raise

    def _prepare_game_results(self, strategies: List[Dict], game_state: BaseGameState, start_time: float, end_time: float) -> Dict:
        player_results = game_state.get_player_results()

        # Add generic info tracked by the strategy_runner
        for i, res in enumerate(player_results):
            res['strategyId'] = strategies[i]['_id']
            res['stderr'] = ''.join(self.strategy_runner.strategy_stderr[i])[:100000]

        results = {
            'winnerIndex': game_state.get_winner_index(),
            'playerResults': player_results,
            'replayData': game_state.replay_data,
            'initialState': self.initial_state,
            'timeInfo': {
                'processingStartedAt': int(start_time * 1000),
                'processingEndedAt': int(end_time * 1000),
                'gameDuration': int((end_time - start_time) * 1000),
            },
            'seed': game_state.game_options.get('seed')
        }
        
        # Round all floats to 6 decimal places to reduce payload size
        results = round_floats(results, decimals=6)
        
        return results

    def run_replay(self, replay_file: str, strategy_file: str, player_position: int, last_tick: int = None):
        replay_data = load_replay_data(replay_file)
        self.replay_runner = ReplayRunner(replay_data, self.strategy_runner, logger=self.logger)

        self.logger.info(f"Running replay for player {player_position} using strategy file: {strategy_file}")
        self.replay_runner.run_replay(player_position, strategy_file, last_tick=last_tick)
        self.logger.info("Replay completed")
