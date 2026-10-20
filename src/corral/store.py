"""One JSON file per iTerm session in the corral state dir."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, fields
from pathlib import Path

from corral.state import PRIORITY, Session

_ID = re.compile(r"^[A-Za-z0-9-]+$")


def state_dir() -> Path:
    override = os.environ.get("CORRAL_STATE_DIR")
    return Path(override) if override else Path.home() / ".local" / "state" / "corral"


def valid_id(iterm_id: str) -> bool:
    return bool(_ID.match(iterm_id))


def _path(iterm_id: str) -> Path:
    if not valid_id(iterm_id):
        raise ValueError(f"invalid iterm id: {iterm_id!r}")
    return state_dir() / f"{iterm_id}.json"


_FIELDS = {f.name for f in fields(Session)}
_STR_FIELDS = ("iterm_id", "claude_session_id", "cwd", "state", "last_prompt")


def _well_typed(session: Session) -> bool:
    if not all(isinstance(getattr(session, f), str) for f in _STR_FIELDS):
        return False
    since = session.since
    return isinstance(since, (int, float)) and not isinstance(since, bool)


def _parse(path: Path) -> Session | None:
    try:
        data = json.loads(path.read_text())
        # Ignore fields written by other corral versions so a schema change never hides sessions.
        session = Session(**{k: v for k, v in data.items() if k in _FIELDS})
    except (OSError, ValueError, TypeError, AttributeError):  # AttributeError: not an object
        return None
    if not _well_typed(session):
        return None
    if session.state not in PRIORITY or not valid_id(session.iterm_id):
        return None
    return session


def read(iterm_id: str) -> Session | None:
    return _parse(_path(iterm_id))


def write(session: Session) -> None:
    import tempfile  # here, not at the top: most hook calls don't change the state

    path = _path(session.iterm_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(session), f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def delete(iterm_id: str) -> None:
    _path(iterm_id).unlink(missing_ok=True)


def load_all() -> list[Session]:
    directory = state_dir()
    if not directory.is_dir():
        return []
    sessions = (_parse(p) for p in sorted(directory.glob("*.json")))
    return [s for s in sessions if s is not None]
