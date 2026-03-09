from abc import ABC, abstractmethod
from typing import Dict, List, Any

import random

class BaseGameState(ABC):
    """
    Abstract Base Class for all game states.
    This defines the contract that the GameManager uses to run any game.
    """
    def __init__(self, game_options: Dict[str, Any], logger):
        self.tick = 0
        self.players = []
        self.game_options = game_options
        self.logger = logger
        self.replay_data = []

        if 'seed' in game_options:
            self.seed = game_options['seed']
            random.seed(self.seed)
            self.logger.info(f"Initialized random seed: {self.seed}")

    @abstractmethod
    def update(self, actions: List[Dict[str, Any]]) -> None:
        """Advance the game state by one tick based on player actions."""
        pass

    @abstractmethod
    def is_game_over(self) -> bool:
        """Check if the game has reached a terminal state."""
        pass

    @abstractmethod
    def get_input(self, player_id: int) -> str:
        """Serialize the game state into a JSON string for a specific player."""
        pass

    @abstractmethod
    def get_initial_info(self) -> Dict[str, Any]:
        """Get the initial parameters to send to strategies before the game starts."""
        pass

    @abstractmethod
    def get_player_results(self) -> List[Dict[str, Any]]:
        """Return a list of detailed results for each player (score, rank, etc.)."""
        pass

    @abstractmethod
    def get_winner_index(self) -> int:
        """Determine the winner. Returns -1 for a tie."""
        pass

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Serialize the entire current game state for replays."""
        pass