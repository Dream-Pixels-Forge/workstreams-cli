"""Tests for platform-aware default multiplexer resolution."""

import sys
sys.path.insert(0, "src")

from unittest import mock
from pathlib import Path

from workstreams.multiplexer import (
    resolve_default_multiplexer,
    get_multiplexer,
    _PLATFORM_PREFERENCE,
    _installed,
)
from workstreams.models import WorkstreamsConfig


def _cfg():
    return WorkstreamsConfig(
        project="p", multiplexer="default", layout="even-horizontal",
        base_branch="main", workstreams=[], shared_deps=[], base_path=".",
        agent="auto",
    )


def test_default_resolves_to_a_concrete_name():
    # Whatever this machine has, "default" must never come back as "default".
    name = resolve_default_multiplexer(interactive=False)
    assert name != "default"
    assert name in {"tmux", "zellij", "lmux", "wmux", "nami", "herdr"}


def test_primary_wins_when_installed(monkeypatch):
    # Simulate: only the platform primary is installed.
    monkeypatch.setattr("workstreams.multiplexer._installed",
                        lambda n: n == _PLATFORM_PREFERENCE["linux"][0])
    got = resolve_default_multiplexer(interactive=False)
    assert got == _PLATFORM_PREFERENCE["linux"][0]


def test_falls_back_to_first_available_when_primary_missing(monkeypatch):
    # Primary not installed, but the second preference is.
    primary = _PLATFORM_PREFERENCE["linux"][0]
    second = _PLATFORM_PREFERENCE["linux"][1]
    monkeypatch.setattr("workstreams.multiplexer._installed",
                        lambda n: n == second)
    got = resolve_default_multiplexer(interactive=False)
    assert got == second
    assert got != primary


def test_nothing_installed_returns_tmux(monkeypatch):
    monkeypatch.setattr("workstreams.multiplexer._installed", lambda n: False)
    got = resolve_default_multiplexer(interactive=False)
    assert got == "tmux"


def test_get_multiplexer_default_returns_concrete_class():
    mux = get_multiplexer("default", _cfg())
    # Should be one of the concrete multiplexer classes, not None / not default.
    from workstreams.multiplexer import MultiplexerBase
    assert isinstance(mux, MultiplexerBase)
    assert mux.name != "default"


def test_get_multiplexer_empty_string_resolves():
    mux = get_multiplexer("", _cfg())
    from workstreams.multiplexer import MultiplexerBase
    assert isinstance(mux, MultiplexerBase)
    assert mux.name != "default"


def test_explicit_name_still_works(monkeypatch):
    # "tmux" must be honored even if the resolver would pick otherwise.
    monkeypatch.setattr("workstreams.multiplexer._installed", lambda n: False)
    mux = get_multiplexer("tmux", _cfg())
    assert mux.name == "tmux"


def test_unknown_name_raises():
    try:
        get_multiplexer("definitely-not-a-mux", _cfg())
        raised = False
    except ValueError:
        raised = True
    assert raised, "unknown multiplexer name should raise ValueError"


def test_platform_preference_lists_are_sane():
    # Each platform's primary must be a known multiplexer name.
    for key, pref in _PLATFORM_PREFERENCE.items():
        assert len(pref) >= 3
        for m in pref:
            assert m in {"tmux", "zellij", "lmux", "wmux", "nami", "herdr"}

def test_lmux_not_tmux_compatible(monkeypatch):
    """lmux is NOT in the tmux-compatible wrapper family; it has its own
    native dialect. The wrapper path must never be used for it."""
    import workstreams.multiplexer as m
    m._lmux_dialect_cache.clear()
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/lmux" if name == "lmux" else None)
    # lmux is not in _TMUX_COMPATIBLE — the native-dialect detector handles it.
    assert "lmux" not in m._TMUX_COMPATIBLE
    # Native dialect OFF -> not usable natively.
    monkeypatch.setattr("workstreams.multiplexer._supports_lmux_dialect", lambda b: False)
    assert m._installed("lmux") is False


def test_lmux_native_dialect_recognised(monkeypatch):
    """A binary exposing the native lmux verbs IS detected as usable."""
    import workstreams.multiplexer as m
    m._lmux_dialect_cache.clear()
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/lmux" if name == "lmux" else None)
    monkeypatch.setattr("workstreams.multiplexer._supports_lmux_dialect", lambda b: True)
    assert m._installed("lmux") is True


def test_zellij_dialect_recognised(monkeypatch):
    """zellij IS in the platform list and we trust its CLI shape via
    the explicit class; the dialect probe is only for the wrapper
    family."""
    import workstreams.multiplexer as m
    m._tmux_dialect_cache.clear()
    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/zellij")
    # zellij goes through the non-wrapper path, so _installed is True
    # purely based on `shutil.which`.
    assert m._installed("zellij") is True


def test_auto_detect_picks_lmux_when_natively_supported(monkeypatch):
    """On Linux, lmux is top-preference. If its native dialect is present,
    auto-detect returns 'lmux' even if zellij is also installed."""
    import workstreams.multiplexer as m
    import shutil
    m._lmux_dialect_cache.clear()
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/bin/lmux" if name in ("lmux", "zellij") else None,
    )
    monkeypatch.setattr("workstreams.multiplexer._supports_lmux_dialect", lambda b: True)
    got = m.resolve_default_multiplexer(interactive=False)
    assert got == "lmux"


def test_auto_detect_falls_to_zellij_when_lmux_not_usable(monkeypatch):
    """On Linux, if lmux is present but NOT natively supported, auto-detect
    must fall through to zellij (the next preference)."""
    import workstreams.multiplexer as m
    import shutil
    m._lmux_dialect_cache.clear()
    monkeypatch.setattr(
        shutil, "which",
        lambda name: "/usr/bin/lmux" if name in ("lmux", "zellij") else None,
    )
    monkeypatch.setattr("workstreams.multiplexer._supports_lmux_dialect", lambda b: False)
    got = m.resolve_default_multiplexer(interactive=False)
    assert got == "zellij"
