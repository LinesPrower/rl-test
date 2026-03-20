"""Policy mapping function for self-play env."""

from __future__ import annotations


def map_agent_to_policy(agent_id: str, *args, **kwargs) -> str:
    if agent_id == "player_0":
        return "main"
    return "opponent"

