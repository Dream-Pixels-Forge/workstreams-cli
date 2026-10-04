"""Terminal multiplexer implementations + platform-aware default detection."""

import shutil
import subprocess
import sys
from typing import Dict

from .base import MultiplexerBase
from .tmux import TmuxMultiplexer
from .zellij import ZellijMultiplexer
from .tmux_compatible import TmuxCompatibleMultiplexer
from .lmux import LmuxMultiplexer

__all__ = [
    "MultiplexerBase",
    "TmuxMultiplexer",
    "ZellijMultiplexer",
    "LmuxMultiplexer",
    "get_multiplexer",
    "resolve_default_multiplexer",
]

# Name -> binary that must be on PATH. The TmuxCompatibleMultiplexer wraps
# any binary whose CLI is compatible with tmux (send-keys, new-window, ...).
# NOTE: "lmux" is NOT tmux-compatible; it has a native dialect
# (LmuxMultiplexer JSON verbs) and is handled by its own class.
_TMUX_COMPATIBLE = {
    "nami": "nami",
    "wmux": "wmux",
    "herdr": "herdr",
}

# Ordered preference list per platform. We pick the FIRST that is installed.
# lmux is the top Linux choice because it is purpose-built for AI coding
# agents and workstreams now drives it natively.
_PLATFORM_PREFERENCE = {
    "win": ["wmux", "lmux", "zellij", "tmux"],
    "mac": ["tmux", "zellij", "nami", "lmux", "wmux"],
    "linux": ["lmux", "zellij", "tmux"],
}


def _installed(name: str) -> bool:
    """Return True if the CLI binary for `name` is on PATH.

    For the tmux-compatible wrappers (wmux, nami, herdr) we additionally
    require that the binary actually exposes a tmux-style command.

    `lmux` is special-cased: it speaks its OWN native dialect
    and is driven by its dedicated class (LmuxMultiplexer)
    — never the tmux wrapper.
    """
    if name == "lmux":
        if shutil.which("lmux") is None:
            return False
        return _supports_lmux_dialect("lmux")
    if name in ("tmux", "zellij"):
        binary = name
    elif name in _TMUX_COMPATIBLE:
        binary = _TMUX_COMPATIBLE[name]
    else:
        return False
    if shutil.which(binary) is None:
        return False
    if name in _TMUX_COMPATIBLE:
        return _supports_tmux_dialect(binary)
    return True


_tmux_dialect_cache: Dict[str, bool] = {}
_lmux_dialect_cache: Dict[str, bool] = {}


def _supports_lmux_dialect(binary: str) -> bool:
    """Heuristic: does `binary` expose lmux's native verb-dialect?

    Probes ``<binary> help`` for the canonical native verbs:
    ``workspace.create`` AND ``surface.send_text``. A binary that has these
    is driven natively by :class:`LmuxMultiplexer` (JSON socket protocol).
    """
    key = binary
    if key in _lmux_dialect_cache:
        return _lmux_dialect_cache[key]
    result = False
    try:
        proc = subprocess.run([binary, "help"], capture_output=True, text=True, timeout=5)
        help_text = (proc.stdout or "") + (proc.stderr or "")
        has_workspace = "workspace.create" in help_text
        has_send_text = "surface.send_text" in help_text or "surface.send-text" in help_text
        result = has_workspace and has_send_text
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        result = False
    _lmux_dialect_cache[key] = result
    return result


def _supports_tmux_dialect(binary: str) -> bool:
    """Heuristic: does `binary` accept tmux-style subcommands?

    Probing method:
      1. Run `<binary> help` — look for canonical tmux verbs
         (new-session / has-session / send-keys / capture-pane).
      2. If that's inconclusive (tmux has no `help` subcommand and dumps
         to stderr instead), run `<binary> new-session -P` and treat
         "command not found" / "unknown command" in stderr as a negative.

    For `lmux` the help text exposes `workspace.create` / `surface.send-key`
    instead of the tmux verbs, so this probe correctly returns False and
    auto-detect skips it — only an explicit user-configured `lmux` will
    attempt the wrapper.
    """
    import subprocess as _sp
    key = binary
    if key in _tmux_dialect_cache:
        return _tmux_dialect_cache[key]
    result = False
    try:
        proc = _sp.run([binary, "help"], capture_output=True, text=True, timeout=5)
        help_text = (proc.stdout or "") + (proc.stderr or "")
        # Require BOTH a session verb and a key verb. `lmux` happens to
        # mention "capture-pane" in one subcommand's description but is
        # missing session.send-keys / new-session entirely, so a single
        # hit is not enough to call it tmux-compatible.
        has_session = any(m in help_text for m in ("new-session", "has-session"))
        has_keys = any(m in help_text for m in ("send-keys", "send-text"))
        result = has_session and has_keys
    except (_sp.TimeoutExpired, FileNotFoundError, OSError):
        result = False
    if not result:
        # Secondary probe: tmux has no `help`; `new-session -P` on a bad
        # socket prints an error but the command exists. Only count as
        # "no dialect" when we see an explicit unknown-command message.
        try:
            proc = _sp.run([binary, "new-session", "-P"],
                           capture_output=True, text=True, timeout=5)
            err = (proc.stderr or "").lower()
            if proc.returncode != 0 and ("unknown command" in err or "invalid command" in err):
                result = False
        except (_sp.TimeoutExpired, FileNotFoundError, OSError):
            pass
    _tmux_dialect_cache[key] = result
    return result


def resolve_default_multiplexer(interactive: bool = False, quiet: bool = False) -> str:
    """Pick the best available multiplexer for the current platform.

    Returns a string name (tmux, zellij, lmux, wmux, ...). When
    `interactive` and no preference is installed, asks the user. When
    `quiet`, never prompts — falls back to the first available, or "tmux".
    """
    platform = sys.platform
    if platform.startswith("win"):
        key = "win"
    elif platform == "darwin":
        key = "mac"
    else:
        key = "linux"

    preference = _PLATFORM_PREFERENCE[key]
    available = [m for m in preference if _installed(m)]

    primary = preference[0]
    if _installed(primary):
        return primary
    if available:
        return available[0]

    # Nothing on the preference list is installed.
    if interactive and sys.stdin.isatty():
        options = [m for m in preference if _installed(m)] or _PLATFORM_PREFERENCE[key]
        print("No preferred multiplexer found on this system. Available options:")
        for i, opt in enumerate(options, start=1):
            print(f"  {i}. {opt}")
        print("Which one? [1]: ", end="", flush=True)
        try:
            choice = int(input().strip() or "1")
        except (ValueError, EOFError):
            choice = 1
        return options[choice - 1] if 1 <= choice <= len(options) else options[0]

    # Quiet / non-interactive: fall back to tmux (the most universal one).
    if _installed("tmux"):
        return "tmux"
    return "tmux"  # the caller will surface the "install tmux" hint


def get_multiplexer(name: str, config) -> MultiplexerBase:
    """Get a multiplexer instance by name."""
    if name == "default" or not name:
        # Resolve the platform-aware default; the user can override this in
        # .workstreams.yaml by setting `multiplexer: tmux` (or any other).
        name = resolve_default_multiplexer(interactive=False)
    multiplexers = {
        "tmux": TmuxMultiplexer,
        "zellij": ZellijMultiplexer,
        "lmux": LmuxMultiplexer,
    }
    cls = multiplexers.get(name)
    if not cls:
        # Fallback: a tmux-compatible wrapper binary (nami/herdr).
        if name in _TMUX_COMPATIBLE:
            binary = _TMUX_COMPATIBLE[name]
            return TmuxCompatibleMultiplexer(config, binary)
        raise ValueError(
            f"Unknown multiplexer: {name}. "
            f"Supported: {', '.join(multiplexers)} plus tmux-compatible: "
            f"{', '.join(_TMUX_COMPATIBLE)} or 'default' (auto-detect)."
        )
    return cls(config)
