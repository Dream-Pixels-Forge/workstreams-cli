"""Terminal multiplexer implementations."""
"""Terminal multiplexer implementations."""

from .base import MultiplexerBase
from .tmux import TmuxMultiplexer
from .zellij import ZellijMultiplexer
from .tmux_compatible import TmuxCompatibleMultiplexer

__all__ = ["MultiplexerBase", "TmuxMultiplexer", "ZellijMultiplexer", "get_multiplexer"]

_TMUX_COMPATIBLE = {
    "nami": "nami",
    "lmux": "lmux",
    "wmux": "wmux",
    "herdr": "herdr",
}

def get_multiplexer(name: str, config) -> MultiplexerBase:
    """Get a multiplexer instance by name."""
    multiplexers = {
        "tmux": TmuxMultiplexer,
        "zellij": ZellijMultiplexer,
    }
    if name in _TMUX_COMPATIBLE:
        binary = _TMUX_COMPATIBLE[name]
        return TmuxCompatibleMultiplexer(config, binary)
    cls = multiplexers.get(name)
    if not cls:
        raise ValueError(
            f"Unknown multiplexer: {name}. Supported: {', '.join(multiplexers)} plus tmux-compatible: {', '.join(_TMUX_COMPATIBLE)}"
        )
    return cls(config)
