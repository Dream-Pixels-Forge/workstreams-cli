"""Terminal multiplexer implementations."""

from .base import MultiplexerBase
from .tmux import TmuxMultiplexer
from .zellij import ZellijMultiplexer

__all__ = ["MultiplexerBase", "TmuxMultiplexer", "ZellijMultiplexer", "get_multiplexer"]


def get_multiplexer(name: str, config) -> MultiplexerBase:
    """Get a multiplexer instance by name."""
    multiplexers = {
        "tmux": TmuxMultiplexer,
        "zellij": ZellijMultiplexer,
    }
    cls = multiplexers.get(name)
    if not cls:
        raise ValueError(
            f"Unknown multiplexer: {name}. Supported: {', '.join(multiplexers)}"
        )
    return cls(config)
