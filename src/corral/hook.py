"""Claude Code hook: record this iTerm session's claude state. Always exits 0."""

from __future__ import annotations

import json
import os
import sys
import time

from corral import state, store


def iterm_id_from_env(value: str | None) -> str | None:
    if not value:
        return None
    iterm_id = value.rsplit(":", 1)[-1]
    return iterm_id if store.valid_id(iterm_id) else None


def handle(event: dict, env_value: str | None, now: float) -> None:
    iterm_id = iterm_id_from_env(env_value)
    if iterm_id is None:
        return
    target = state.target_state(event)
    if target is None:
        return
    if target == state.DELETE:
        store.delete(iterm_id)
        return
    prev = store.read(iterm_id)
    session = state.transition(prev, event, iterm_id, target, now)
    if session != prev:
        store.write(session)


def _iterm_session_env() -> str | None:
    # tmux panes and editors launched from iTerm inherit a stale ITERM_SESSION_ID.
    if os.environ.get("TERM_PROGRAM") != "iTerm.app":
        return None
    return os.environ.get("ITERM_SESSION_ID")


def main() -> None:
    try:
        event = json.loads(sys.stdin.read() or "null")
        if isinstance(event, dict):
            handle(event, _iterm_session_env(), time.time())
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
