"""`corral doctor`: check each piece corral needs, and say how to fix what's missing."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from corral import control, pick

Check = tuple[bool, str]  # (ok, detail: what's wrong and how to fix it)
HOOKS_JQ = Path(__file__).resolve().parent / "merge-hooks.jq"
HOTKEY_FUNCTIONS = ("corral_next_waiting", "corral_next_done", "corral_pick")
_ADD = re.compile(r'^\| add\("(\w+)"', re.MULTILINE)


def hook_events(jq: str) -> list[str]:
    """The Claude Code events install.sh gives corral hooks for."""
    return _ADD.findall(jq)


def settings_path() -> Path:
    override = os.environ.get("CLAUDE_SETTINGS")
    return Path(override) if override else Path.home() / ".claude" / "settings.json"


def iterm_pref(key: str) -> str | None:
    result = subprocess.run(
        ["defaults", "read", "com.googlecode.iterm2", key], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def check_hooks(path: Path, events: Iterable[str]) -> Check:
    def has_corral(event: str) -> bool:
        entries = hooks.get(event) or []
        commands = (hook.get("command", "") for entry in entries for hook in entry.get("hooks", []))
        return any(command.endswith("corral-hook") for command in commands)

    try:
        hooks = json.loads(path.read_text()).get("hooks", {})
        missing = [event for event in events if not has_corral(event)]
    except (OSError, ValueError, AttributeError, KeyError, TypeError):  # also hand-edited oddities
        return False, f"can't read {path}; run ./install.sh"
    if missing:
        return False, f"no corral hook for {', '.join(missing)}; run ./install.sh"
    return True, ""


def check_python_api(pref: Callable[[str], str | None] = iterm_pref) -> Check:
    if pref("EnableAPIServer") == "1":
        return True, ""
    return False, "turn on iTerm2 → Settings → General → Magic → Enable Python API, then restart"


def check_hotkeys(pref: Callable[[str], str | None] = iterm_pref) -> Check:
    keymap = pref("GlobalKeyMap") or ""
    missing = [function for function in HOTKEY_FUNCTIONS if function not in keymap]
    if missing:
        return False, f"not bound: {', '.join(missing)}; run `corral setup`"
    return True, ""


def daemon_process() -> bool:
    # Not launcher.running(): taking the lock, even briefly, can stop a daemon starting.
    return subprocess.run(["pgrep", "-f", "corral.cli daemon"], capture_output=True).returncode == 0


RESTART = "pkill -f 'corral.cli daemon' to restart it"


def check_daemon() -> Check:
    try:
        reply = control.request({"op": "ping"})
        running = reply.get("version")
    except control.Unavailable:
        if daemon_process():
            return False, f"an older daemon is running; {RESTART}"
        return False, "not running; it starts with the next claude event in iTerm"
    if reply.get("iterm") is False:  # older daemons don't say
        return False, f"it lost its iTerm connection; {RESTART}"
    installed = control.version()
    if running != installed:
        old = f"corral {running}" if running else "an older corral"
        return False, f"it runs {old}, but {installed} is installed; {RESTART}"
    return True, ""


def check_fzf() -> Check:
    return (True, "") if pick._fzf() else (False, "the ⌘P picker needs it: brew install fzf")


def report(checks: Iterable[tuple[str, Callable[[], Check]]]) -> int:
    failed = 0
    for label, check in checks:
        ok, detail = check()
        failed += not ok
        print(f"✓ {label}" if ok else f"✗ {label}: {detail}")
    return 1 if failed else 0


def run() -> int:
    def hooks() -> Check:
        try:
            events = hook_events(HOOKS_JQ.read_text())
        except OSError:
            return False, f"can't read {HOOKS_JQ} to compare against; run ./install.sh"
        return check_hooks(settings_path(), events)

    return report(
        [
            ("Claude Code hooks", hooks),
            ("iTerm2 Python API", check_python_api),
            ("iTerm2 hotkeys", check_hotkeys),
            ("corral daemon", check_daemon),
            ("fzf", check_fzf),
        ]
    )
