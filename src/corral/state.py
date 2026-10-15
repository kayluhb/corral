"""Pure session-state logic shared by the hook, picker and iTerm daemon."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

WAITING = "waiting"
WORKING = "working"
DONE = "done"
IDLE = "idle"
DELETE = "delete"

PRIORITY = (WAITING, DONE, WORKING, IDLE)
ICONS = {WAITING: "✋", WORKING: "⚙", DONE: "✓", IDLE: "·"}
SUMMARY_STATES = (WAITING, WORKING, DONE)
WAITING_NOTIFICATIONS = frozenset(
    {"permission_prompt", "elicitation_dialog", "elicitation_url_dialog", "agent_needs_input"}
)
LIFECYCLE_EVENTS = frozenset({"SessionStart", "Stop", "SessionEnd"})
PROMPT_LIMIT = 80

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")


@dataclass
class Session:
    iterm_id: str
    claude_session_id: str
    cwd: str
    state: str
    since: float
    last_prompt: str = ""


def target_state(event: dict) -> str | None:
    name = event.get("hook_event_name")
    if event.get("agent_id") and name in LIFECYCLE_EVENTS:
        return None
    if name == "SessionStart":
        return IDLE
    if name in ("UserPromptSubmit", "PostToolUse"):
        return WORKING
    if name == "Notification":
        return WAITING if event.get("notification_type") in WAITING_NOTIFICATIONS else None
    if name == "Stop":
        return DONE
    if name == "SessionEnd":
        return DELETE
    return None


def transition(
    prev: Session | None, event: dict, iterm_id: str, target: str, now: float
) -> Session:
    name = event.get("hook_event_name")
    if prev is None or name == "SessionStart":
        prev = Session(iterm_id, "", "", "", now)
    since = prev.since if prev.state == target else now
    last_prompt = prev.last_prompt
    if name == "UserPromptSubmit":
        last_prompt = clean(str(event.get("prompt") or ""), PROMPT_LIMIT)
    return replace(
        prev,
        claude_session_id=str(event.get("session_id") or prev.claude_session_id),
        cwd=str(event.get("cwd") or prev.cwd),
        state=target,
        since=since,
        last_prompt=last_prompt,
    )


def clean(text: str, limit: int) -> str:
    text = _SPACES.sub(" ", _CONTROL.sub(" ", text)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def project_name(cwd: str) -> str:
    return os.path.basename(cwd.rstrip("/")) or "?"


def attention_text(session: Session) -> str:
    what = "needs you" if session.state == WAITING else "done"
    return clean(f"{project_name(session.cwd)}: {what}", PROMPT_LIMIT)


def ordered(sessions: Iterable[Session]) -> list[Session]:
    return sorted(sessions, key=lambda s: (PRIORITY.index(s.state), s.since))


def next_target(sessions: Iterable[Session], state: str, current_id: str | None) -> str | None:
    ids = [s.iterm_id for s in sorted(sessions, key=lambda s: s.since) if s.state == state]
    if not ids:
        return None
    if current_id in ids:
        return ids[(ids.index(current_id) + 1) % len(ids)]
    return ids[0]


def summary(sessions: Iterable[Session]) -> str:
    sessions = list(sessions)
    parts = []
    for st in SUMMARY_STATES:
        count = sum(1 for s in sessions if s.state == st)
        if count:
            parts.append(f"{ICONS[st]}{count}")
    return " ".join(parts) or ICONS[IDLE]


def tab_color_key(state: str, is_active: bool) -> str | None:
    if is_active or state not in (WAITING, DONE):
        return None
    return state
