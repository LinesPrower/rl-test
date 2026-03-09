import json
import logging
import importlib

def get_game_state_class(game_name: str):
    """Dynamically imports the game state class from the specified game module."""
    from base_game_state import BaseGameState
    try:
        module_path = f"games.{game_name}.state"
        module = importlib.import_module(module_path)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, BaseGameState) and attr is not BaseGameState:
                return attr
        raise ImportError(f"No BaseGameState subclass found in {module_path}")
    except (ImportError, ModuleNotFoundError) as e:
        logging.error(f"Could not load game module for '{game_name}': {e}")
        raise

class ReplayRunner:
    def __init__(self, replay_data, strategy_runner, logger: logging.Logger = None):
        self.replay_data = replay_data
        self.strategy_runner = strategy_runner
        self.logger = logger or logging.getLogger(__name__)

    def run_replay(self, player_position, strategy_file, last_tick=None):
        game_name = self.replay_data.get('gameName')
        if not game_name:
            self.logger.warning("Replay file does not specify a gameName, defaulting to 'space_miners'.")
            game_name = 'space_miners'

        try:
            GameStateClass = get_game_state_class(game_name)
            self.logger.info(f"Loaded game logic for '{game_name}'")
        except ImportError:
            self.logger.critical(f"Failed to run replay: could not load game '{game_name}'.")
            return

        initial_state = self.replay_data.get('initialState', self.replay_data.get('initial_state', {}))
        ticks_data = self.replay_data.get('replayData', self.replay_data.get('replay_data', []))
        if not ticks_data:
            self.logger.warning("Replay contains no ticks; nothing to run.")
            return

        max_tick = len(ticks_data) - 1
        if last_tick is not None:
            if last_tick < 0:
                raise ValueError("last_tick must be >= 0")
            effective_last_tick = min(last_tick, max_tick)
            if last_tick > max_tick:
                self.logger.warning(
                    f"Requested --last-tick={last_tick}, but replay has only {len(ticks_data)} ticks. "
                    f"Using last available tick {max_tick}."
                )
            self.logger.info(f"Replay will stop at tick {effective_last_tick} (inclusive).")
        else:
            effective_last_tick = max_tick

        game_state = GameStateClass.from_replay(initial_state, logger=self.logger)
        player_active_prev = [player.is_active for player in game_state.players]

        if player_position is None or strategy_file is None:
            self.logger.info("Running in view-only mode")
            for tick, frame in enumerate(ticks_data):
                if tick > effective_last_tick:
                    break
                state = frame.get('state', {})
                self.logger.info(f"Tick {tick}: Players: {[p.get('score', 0) for p in state.get('players', [])]}")
                game_state.update_from_replay(state)
                player_active_prev = self._log_replay_deactivations(game_state, tick, player_active_prev)
            return

        strategies = [None, None]
        # Keep replay debugging consistent with --local mode: strategy_file is a run command.
        strategies[player_position] = {
            'file': strategy_file, # TODO: technically this is run_command, so needs to be reworked some day, but you can't just delete it because it's used in checks in strategy_runner.py
            'run_command': strategy_file
        }
        self.strategy_runner.initialize_strategies(game_state, strategies, logger=self.logger)

        try:
            for tick, frame in enumerate(ticks_data):
                if tick > effective_last_tick:
                    break
                strategy_actions = self.strategy_runner.get_actions(game_state)
                strategy_action = strategy_actions[player_position]
                recorded_action = frame['actions'][player_position]

                self.logger.info(f"Tick {tick}:")
                self.logger.info(f"  Strategy action: {strategy_action}")
                self.logger.info(f"  Recorded action: {recorded_action}")
                self.logger.info("")

                game_state.update_from_replay(frame['state'])
                player_active_prev = self._log_replay_deactivations(game_state, tick, player_active_prev)
        finally:
            self.strategy_runner.cleanup_strategies()

    def _log_replay_deactivations(self, game_state, tick: int, player_active_prev):
        """Emit explicit logs when replay state deactivates players (failed/disqualified)."""
        player_active_curr = [player.is_active for player in game_state.players]
        for player_idx, (was_active, is_active) in enumerate(zip(player_active_prev, player_active_curr)):
            if was_active and not is_active:
                reason = game_state.players[player_idx].disqualification_reason or "unknown reason"
                self.logger.warning(
                    f"Replay marks player {player_idx} inactive at tick {tick} (reason: {reason}). "
                    "Subsequent strategy actions for this player will be None."
                )
        return player_active_curr

def load_replay_data(replay_file):
    with open(replay_file, 'r') as f:
        return json.load(f)
