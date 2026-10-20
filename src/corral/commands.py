"""`corral list`, `wait`, `send`, `new` and `explain`: sessions from a shell or another claude.

list and wait read the state files directly; send needs the daemon, which types through iTerm;
new opens an iTerm tab itself, as `corral restore` does.
Exit codes: 0 done, 1 timed out, 2 error (no such session, it ended, daemon not running...).
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict

from corral import control, git, launcher, restore, state, store
from corral.pick import LABEL_WIDTH, age, label
from corral.state import Session

STOPPED = frozenset({state.WAITING, state.DONE, state.IDLE})  # wait's default: not working
POLL_SECONDS = 0.5
START_TIMEOUT = 30.0  # seconds for a new tab's claude to start
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
        rows = [
            {**asdict(s), "project": state.project_name(s.cwd), "branch": git.branch(s.cwd)}
            for s in sessions
        ]
        print(json.dumps(rows, indent=2))
        return 0
    if not sessions:
        print("corral: no claude sessions")
    t = now()
    for s in sessions:
        project = state.clean(label(s.cwd), LABEL_WIDTH)
        when = age(t - s.since)
        line = f"{s.iterm_id[:SHORT_ID]}  {state.ICONS[s.state]} {project:<{LABEL_WIDTH}} {when:>4}"
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


def new(
    name: str,
    prompt: str,
    cwd: str,
    shell: str,
    open_tab: Callable[[str], str],
    now: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Open a tab running `claude --worktree name [prompt]` and print its id once it starts.

    open_tab runs a command in a new tab and returns the tab's iTerm session id.
    """
    if not git.branch(cwd):
        return _fail(f"{cwd} is not in a git repository")
    claude = f"claude --worktree {shlex.quote(name)}"
    if prompt:
        claude += f" {shlex.quote(prompt)}"
    try:
        iterm_id = open_tab(restore.login_shell(f"cd {shlex.quote(cwd)} && {claude}", shell))
    except CommandError as exc:
        return _fail(str(exc))
    print(iterm_id)  # printed either way, so a script can still find the tab
    deadline = now() + START_TIMEOUT
    while store.read(iterm_id) is None:
        if now() >= deadline:
            print(f"corral: claude hasn't started in {iterm_id[:SHORT_ID]} yet", file=sys.stderr)
            return 1
        sleep(POLL_SECONDS)
    return 0


def open_tab_next_to_you(command: str) -> str:
    """Open a tab running command in your iTerm window (a new window if there's none)."""
    import iterm2  # only `new` needs it; keeps list and wait fast

    origin = os.environ.get("ITERM_SESSION_ID", "").rsplit(":", 1)[-1]
    result: list[str] = []

    async def run(connection: iterm2.Connection) -> None:
        app = await iterm2.async_get_app(connection)
        session = app.get_session_by_id(origin) if origin else None
        window = session.window if session else app.current_terminal_window
        if window is None:
            window = await iterm2.Window.async_create(connection, command=command)
            tab = window.current_tab if window else None
        else:
            tab = await window.async_create_tab(command=command)
        if tab is not None and tab.current_session is not None:
            result.append(tab.current_session.session_id)

    iterm2.run_until_complete(run)
    if not result:
        raise CommandError("iTerm didn't open the tab")
    return result[0]


COLOUR_NAMES = {state.WAITING: "red", state.DONE: "green"}


def explain(target: str, now: Callable[[], float] = time.time) -> int:
    """Print what corral knows about a session and where its state came from."""
    try:
        s = resolve(store.load_all(), target)
    except CommandError as exc:
        return _fail(str(exc))
    try:
        live = control.request({"op": "explain", "iterm_id": s.iterm_id})
    except control.Unavailable:
        live = None
    print(f"{label(s.cwd)}  {s.iterm_id}")
    print(f"state:   {state.ICONS[s.state]} {s.state} for {age(now() - s.since)}")
    if live is None:
        why = "is too old to ask" if launcher.running() else "isn't running"
        print(f"source:  unknown: the corral daemon {why}, so this may be stale")
    elif live.get("iterm_status"):
        print(f"source:  iTerm's Claude Code integration (it reports {live['iterm_status']})")
    else:
        print("source:  corral's hooks (iTerm's Claude Code integration reports nothing here)")
    if live is not None:
        tab = "open" if live.get("tab_open") else "closed (the state file is left over)"
        focus = ", you're looking at it" if live.get("focused") else ""
        colour = COLOUR_NAMES.get(live.get("tab_colour"), "no colour")
        print(f"tab:     {tab}{focus}; corral gave it {colour}")
    print(f"folder:  {s.cwd}")
    print(f"resume:  claude --resume {s.claude_session_id}")
    if s.last_prompt:
        print(f"prompt:  {s.last_prompt}")
    return 0


def _fail(message: str) -> int:
    print(f"corral: {message}", file=sys.stderr)
    return 2
