"""`corral list`, `corral wait` and `corral send`: drive sessions from a shell or another claude.

list and wait read the state files directly; send needs the daemon, which types through iTerm.
Exit codes: 0 done, 1 timed out, 2 error (no such session, it ended, daemon not running...).
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict

from corral import control, state, store
from corral.pick import age
from corral.state import Session

STOPPED = frozenset({state.WAITING, state.DONE, state.IDLE})  # wait's default: not working
POLL_SECONDS = 0.5
SHORT_ID = 8


class CommandError(Exception):
    pass


def resolve(sessions: Iterable[Session], target: str) -> Session:
    """The one session target names: an iTerm id, a prefix of one, or a project name."""
    sessions = list(sessions)
    key = target.lower()
    for matches in (
        [s for s in sessions if s.iterm_id.lower() == key],
        [s for s in sessions if s.iterm_id.lower().startswith(key)],
        [s for s in sessions if state.project_name(s.cwd) == target],
    ):
        if len(matches) == 1:
            return matches[0]
        if matches:
            ids = ", ".join(s.iterm_id[:SHORT_ID] for s in matches)
            raise CommandError(f"{target!r} matches {len(matches)} sessions ({ids}); use an id")
    raise CommandError(f"no claude session matches {target!r}")


def list_sessions(as_json: bool, now: Callable[[], float] = time.time) -> int:
    sessions = state.ordered(store.load_all())
    if as_json:
        rows = [{**asdict(s), "project": state.project_name(s.cwd)} for s in sessions]
        print(json.dumps(rows, indent=2))
        return 0
    if not sessions:
        print("corral: no claude sessions")
    t = now()
    for s in sessions:
        project = state.clean(state.project_name(s.cwd), 24)
        line = (
            f"{s.iterm_id[:SHORT_ID]}  {state.ICONS[s.state]} {project:<24} {age(t - s.since):>4}"
        )
        print(f"{line}  {s.last_prompt}".rstrip())
    return 0


def wait(
    target: str,
    until: Iterable[str] = STOPPED,
    timeout: float | None = None,
    after: float = 0.0,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Block until the session is in one of the until states, entered at or after `after`.

    Gives up if the session ends or another claude takes over its tab.
    """
    until = set(until)
    try:
        pinned = resolve(store.load_all(), target)
    except CommandError as exc:
        return _fail(str(exc))
    deadline = None if timeout is None else now() + timeout
    while True:
        s = store.read(pinned.iterm_id)
        if s is None or s.claude_session_id != pinned.claude_session_id:
            return _fail(f"session {pinned.iterm_id[:SHORT_ID]} ended")
        if s.state in until and s.since >= after:
            return 0
        if deadline is not None and now() >= deadline:
            return 1
        sleep(POLL_SECONDS)


def send(
    target: str,
    text: str,
    wait_until: Iterable[str] | None = None,
    timeout: float | None = None,
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Type text into the session and press Enter; with wait_until, wait for that turn."""
    try:
        s = resolve(store.load_all(), target)
    except CommandError as exc:
        return _fail(str(exc))
    sent_at = now()
    try:
        reply = control.request({"op": "send", "iterm_id": s.iterm_id, "text": text})
    except control.Unavailable:
        return _fail("the corral daemon isn't running (it starts with the next claude event)")
    if "error" in reply:
        return _fail(reply["error"])
    if wait_until is None:
        return 0
    return wait(s.iterm_id, wait_until, timeout, after=sent_at, now=now, sleep=sleep)


def _fail(message: str) -> int:
    print(f"corral: {message}", file=sys.stderr)
    return 2
