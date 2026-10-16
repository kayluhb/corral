"""corral's own settings, edited with `corral settings` (stored as JSON)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    group: bool = False
    tab_colours: bool = True


# (key, label, values in the order Enter cycles through them)
OPTIONS = (
    ("group", "Group by project", (False, True)),
    ("tab_colours", "Tab colours", (True, False)),
)


def path() -> Path:
    override = os.environ.get("CORRAL_CONFIG")
    return Path(override) if override else Path.home() / ".config" / "corral" / "settings.json"


def load() -> Settings:
    try:
        data = json.loads(path().read_text())
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    valid = {key: data[key] for key, _, values in OPTIONS if data.get(key, None) in values}
    # `True in (False, True)` also matches 1; keep only real booleans for boolean options.
    valid = {k: v for k, v in valid.items() if type(v) is type(getattr(Settings(), k))}
    return Settings(**valid)


def save(settings: Settings) -> None:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(settings), f, indent=2)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def cycle(settings: Settings, key: str) -> Settings:
    values = next(v for k, _, v in OPTIONS if k == key)
    current = values.index(getattr(settings, key))
    return replace(settings, **{key: values[(current + 1) % len(values)]})


def _show(value: object) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    return str(value)


def rows(settings: Settings) -> list[tuple[str, str]]:
    return [(label, _show(getattr(settings, key))) for key, label, _ in OPTIONS]


def menu() -> int:
    """Full-screen arrow-key menu. Each change is saved at once; the daemon picks it up."""
    import curses

    def loop(screen: curses.window) -> None:
        curses.curs_set(0)
        current, selected = load(), 0
        while True:
            screen.erase()
            screen.addstr(1, 2, "corral settings", curses.A_BOLD)
            for i, (label, value) in enumerate(rows(current)):
                attr = curses.A_REVERSE if i == selected else curses.A_NORMAL
                screen.addstr(
                    3 + i, 2, f"{'>' if i == selected else ' '} {label:<20} {value}", attr
                )
            screen.addstr(4 + len(OPTIONS), 2, "↑↓ move · enter change · q quit", curses.A_DIM)
            key = screen.getch()
            if key == ord("q"):
                return
            if key in (curses.KEY_UP, ord("k")):
                selected = (selected - 1) % len(OPTIONS)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = (selected + 1) % len(OPTIONS)
            elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
                current = cycle(current, OPTIONS[selected][0])
                save(current)

    curses.wrapper(loop)
    return 0
