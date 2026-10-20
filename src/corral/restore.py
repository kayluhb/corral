"""Reopen the claude sessions that were running when iTerm last quit.

The daemon keeps a history of claude sessions (cwd, last prompt, tab order, last seen).
State files can't be used: they're deleted when claude exits, including on iTerm quit.
Quitting iTerm stops every session within seconds, so the restore set is the group of
sessions that stopped together most recently and aren't running now.
"""

from __future__ import annotations

import json
import os
import shlex
import tempfile
from collections.abc import Iterable
from pathlib import Path

from corral import state, store

KEEP_SECONDS = 7 * 24 * 3600
BATCH_SECONDS = 30  # sessions last seen within this of the newest stopped together
SAVE_EVERY = 5.0  # daemon writes the history at most this often


def history_path() -> Path:
    return store.state_dir() / "restore" / "history.json"  # subdir: not a session file


def record(history: dict, live: Iterable[state.Session], now: float) -> dict:
    history = {k: v for k, v in history.items() if now - v["last_seen"] <= KEEP_SECONDS}
    for order, s in enumerate(x for x in live if x.claude_session_id):
        history[s.claude_session_id] = {
            "cwd": s.cwd,
            "last_prompt": s.last_prompt,
            "order": order,
            "last_seen": now,
        }
    return history


def last_batch(history: dict, running: set[str]) -> list[tuple[str, dict]]:
    stopped = [(k, v) for k, v in history.items() if k not in running]
    if not stopped:
        return []
    newest = max(v["last_seen"] for _, v in stopped)
    batch = [(k, v) for k, v in stopped if newest - v["last_seen"] <= BATCH_SECONDS]
    return sorted(batch, key=lambda kv: kv[1]["order"])


def resume_command(claude_id: str, cwd: str) -> str:
    return f"cd {shlex.quote(cwd)} && claude --resume {shlex.quote(claude_id)}"


def tab_command(claude_id: str, cwd: str, shell: str) -> str:
    return login_shell(resume_command(claude_id, cwd), shell)


def login_shell(command: str, shell: str) -> str:
    """A tab's own command: run command in an interactive login shell, then stay a shell.

    Typing the command into a fresh tab races shell startup, which can discard typeahead.
    """
    inner = f"{command}; exec {shlex.quote(shell)} -l"
    return f"{shlex.quote(shell)} -lic {shlex.quote(inner)}"


def load() -> dict:
    try:
        data = json.loads(history_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(history: dict) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(history, f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def run() -> int:
    running = {s.claude_session_id for s in store.load_all()}
    batch = last_batch(load(), running)
    if not batch:
        print("Nothing to restore.")
        return 0
    print(f"Reopen {len(batch)} claude session{'s' * (len(batch) != 1)}?")
    for _, v in batch:
        print(f"  {state.project_name(v['cwd']):<24} {v['last_prompt']}")
    if input("[y/N] ").strip().lower() != "y":
        return 0
    import iterm2  # only needed once you say yes; keeps the prompt fast

    async def open_tabs(connection: iterm2.Connection) -> None:
        await iterm2.async_get_app(connection)  # wires up Window.async_create_tab
        shell = os.environ.get("SHELL", "/bin/zsh")
        window = None
        for claude_id, v in batch:
            command = tab_command(claude_id, v["cwd"], shell)
            if window is None:
                window = await iterm2.Window.async_create(connection, command=command)
            else:
                await window.async_create_tab(command=command)

    iterm2.run_until_complete(open_tabs)
    print(f"Reopened {len(batch)}.")
    return 0
