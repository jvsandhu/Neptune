"""Launch the Proton helper before the user asks, so Attach is near-instant.

The slow part of connecting is protontricks starting the Steam Linux Runtime container
and the helper inside the game's prefix. None of that depends on the game being attached,
so it is started once at application launch and handed to the first attach.
"""
from __future__ import annotations

import os
from pathlib import Path
import threading

from .transport import Bridge

_lock = threading.Lock()
_thread: threading.Thread | None = None
_bridge: Bridge | None = None
_error: str | None = None
_started = False


def _helper_path() -> Path:
    return Path(__file__).with_name('neptune-bridge.exe')


def _appid() -> str:
    return os.environ.get('NEPTUNE_STEAM_APPID', '2483190')


def _game_name() -> str:
    value = os.environ.get('NEPTUNE_GAME_EXE') or 'forzahorizon6.exe'
    return os.path.basename(value).lower()


def _game_running(proc_root: str = '/proc', exe_name: str | None = None) -> bool:
    """True when FH6 is already running, read from the host process list.

    Proton runs the game as a Wine process whose `comm` is the exe name, truncated to
    15 characters (`forzahorizon6.e`). No bridge is needed to check this.
    """
    name = (exe_name or _game_name()).lower()
    wanted = os.path.basename(name)[:15]
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return False
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, 'comm'), 'rb') as handle:
                comm = handle.read().decode('ascii', 'ignore').strip().lower()
        except OSError:
            continue
        if comm.startswith(wanted):
            return True
    return False


def start() -> None:
    """Begin warming the helper in the background. Safe to call more than once.

    Does nothing unless the game is already running: there is no point holding a
    helper (and a Wine process) open for a session the user is not tuning.
    """
    global _thread, _started
    if not _game_running():
        return
    with _lock:
        if _started:
            return
        _started = True
        _thread = threading.Thread(target=_warm, daemon=True, name='neptune-prewarm')
        _thread.start()


def _warm() -> None:
    global _bridge, _error
    try:
        bridge = Bridge.start(_helper_path(), _appid())
    except Exception as error:  # protontricks missing, helper failed, timed out...
        with _lock:
            _error = str(error)
        return
    with _lock:
        _bridge = bridge


def pending() -> bool:
    """True while a helper launch is still in flight."""
    with _lock:
        thread = _thread
    return thread is not None and thread.is_alive()


def acquire() -> Bridge | None:
    """Return the pre-warmed bridge, or None when there is none to hand over.

    Waits for an in-flight launch so a second helper is never started.
    """
    global _bridge
    with _lock:
        thread = _thread
    if thread is not None and thread.is_alive():
        thread.join()
    with _lock:
        bridge = _bridge
        _bridge = None
    if bridge is not None and not bridge.closed:
        return bridge
    return None


def return_bridge(bridge: Bridge | None) -> None:
    """Put a bridge back after a failed attach so the retry stays warm.

    Nothing was attached to the game, so the helper is still fresh.
    """
    global _bridge
    if bridge is None or bridge.closed:
        return
    with _lock:
        if _bridge is None:
            _bridge = bridge
            return
    try:
        bridge.abort()
    except Exception:
        pass


def close() -> None:
    """Release an unconsumed pre-warmed helper. Never blocks: there is nothing to
    restore on a helper that was never attached, so the socket is simply dropped."""
    global _bridge
    with _lock:
        bridge = _bridge
        _bridge = None
    if bridge is not None:
        try:
            bridge.abort()
        except Exception:
            pass
