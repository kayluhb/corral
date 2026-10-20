"""Reopen the claude sessions that were running when iTerm last quit.

The daemon keeps a history of claude sessions (cwd, last prompt, tab order, last seen).
State files can't be used: they're deleted when claude exits, including on iTerm quit.
Quitting iTerm stops every session within seconds, so the restore set is the group of
sessions that stopped together most recently and aren't running now. `--pick` offers the whole
history instead. Sessions reopen into one new window per window they were in.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from corral import pick, state, store

KEEP_SECONDS = 7 * 24 * 3600
BATCH_SECONDS = 30  # sessions last seen within this of the newest stopped together
SAVE_EVERY = 5.0  # daemon writes the history at most this often


def history_path() -> Path:
    return store.state_dir() / "restore" / "history.json"  # subdir: not a session file


def record(
    history: dict, live: Iterable[state.Session], now: float, windows: dict[str, str]
) -> dict:
    """windows: iterm_id -> the id of the iTerm window it's in."""
    history = {k: v for k, v in history.items() if now - v["last_seen"] <= KEEP_SECONDS}
    for order, s in enumerate(x for x in live if x.claude_session_id):
        history[s.claude_session_id] = {
            "cwd": s.cwd,
            "last_prompt": s.last_prompt,
            "order": order,
            "window": windows.get(s.iterm_id, ""),
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


def by_window(chosen: list[tuple[str, dict]]) -> list[list[tuple[str, dict]]]:
    """Split sessions into the windows they were in, in tab order.

    Entries saved before corral recorded windows all share one.
    """
    windows: dict[str, list[tuple[str, dict]]] = {}
    for kv in sorted(chosen, key=lambda kv: kv[1]["order"]):
        windows.setdefault(kv[1].get("window", ""), []).append(kv)
    return list(windows.values())


def stopped_newest_first(history: dict, running: set[str], now: float) -> list[tuple[str, dict]]:
    """Everything from the last week that isn't running; the daemon may not have pruned it."""
    stopped = [
        (k, v)
        for k, v in history.items()
        if k not in running and now - v["last_seen"] <= KEEP_SECONDS
    ]
    return sorted(stopped, key=lambda kv: kv[1]["last_seen"], reverse=True)


def format_line(claude_id: str, v: dict, now: float) -> str:
    project = state.clean(state.project_name(v["cwd"]), pick.LABEL_WIDTH)
    prompt = state.clean(v["last_prompt"], 80)
    when = pick.age(now - v["last_seen"])
    return f"{claude_id}\t{project:<{pick.LABEL_WIDTH}} {when:>4}  {prompt}"


def parse_choices(output: str, history: dict) -> list[tuple[str, dict]]:
    ids = (line.split("\t", 1)[0].strip() for line in output.splitlines())
    return [(k, history[k]) for k in ids if k in history]


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


def choose(stopped: list[tuple[str, dict]], now: float) -> list[tuple[str, dict]] | None:
    """fzf over the stopped sessions, in the order given; None when fzf is missing."""
    fzf = pick._fzf()
    if fzf is None:
        return None
    result = subprocess.run(
        [
            fzf,
            "--multi",
            "--delimiter=\t",
            "--with-nth=2..",
            "--no-sort",
            "--reverse",
            "--prompt=restore> ",
            "--header=tab: select several, enter: reopen",
        ],
        input="\n".join(format_line(k, v, now) for k, v in stopped),
        stdout=subprocess.PIPE,
        text=True,
    )
    return parse_choices(result.stdout, dict(stopped)) if result.returncode == 0 else []


def confirm(batch: list[tuple[str, dict]]) -> bool:
    print(f"Reopen {len(batch)} claude session{'s' * (len(batch) != 1)}?")
    for _, v in batch:
        print(f"  {state.project_name(v['cwd']):<24} {state.clean(v['last_prompt'], 80)}")
    return input("[y/N] ").strip().lower() == "y"


def run(choose_from_history: bool = False) -> int:
    running = {s.claude_session_id for s in store.load_all()}
    history = load()
    if all(k in running for k in history):
        print("Nothing to restore.")
        return 0
    if choose_from_history:
        now = time.time()
        stopped = stopped_newest_first(history, running, now)
        if not stopped:
            print("Nothing to restore.")
            return 0
        chosen = choose(stopped, now)
        if chosen is None:
            print("corral: fzf not found (brew install fzf)")
            return 1
    else:
        chosen = last_batch(history, running)
        if not confirm(chosen):
            return 0
    if chosen:
        open_windows(by_window(chosen))
        print(f"Reopened {len(chosen)}.")
    return 0


def open_windows(windows: list[list[tuple[str, dict]]]) -> None:
    import iterm2  # only needed once you say yes; keeps the prompt fast

    async def open_tabs(connection: iterm2.Connection) -> None:
        await iterm2.async_get_app(connection)  # wires up Window.async_create_tab
        shell = os.environ.get("SHELL", "/bin/zsh")
        for tabs in windows:
            window = None
            for claude_id, v in tabs:
                command = tab_command(claude_id, v["cwd"], shell)
                if window is None:
                    window = await iterm2.Window.async_create(connection, command=command)
                else:
                    await window.async_create_tab(command=command)

    iterm2.run_until_complete(open_tabs)
