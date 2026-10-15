"""Start the iTerm daemon from the hook.

The hook runs inside an iTerm session, so a daemon it starts is trusted by iTerm's
Python API without an approval prompt (launchd-started processes get rejected).
A lock file in the state dir keeps it to one daemon.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path

from corral import store

LOG = Path.home() / "Library" / "Logs" / "corral.log"


def acquire() -> int | None:
    """Take the daemon lock. Returns the fd to hold for the daemon's lifetime, or None."""
    path = store.state_dir() / "daemon.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def running() -> bool:
    fd = acquire()
    if fd is None:
        return True
    os.close(fd)
    return False


def spawn() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as log:
        subprocess.Popen(
            [sys.executable, "-m", "corral.cli", "daemon"],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,  # survive the hook and the tab that started it
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )


def ensure_running() -> None:
    if os.environ.get("CORRAL_NO_AUTOSTART"):
        return
    if not running():
        spawn()
