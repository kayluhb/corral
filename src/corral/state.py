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


ICONS = {WAITING: "✋", WORKING: "🟠", DONE: "🟢", IDLE: "⚪"}
QUIET = "all quiet"  # status bar text when nothing is going on
NEEDS_YOU = "{name} needs you"  # notification texts; {name} is the project
FINISHED = "{name} is done"
SUMMARY_STATES = (WAITING, WORKING, DONE)
WAITING_NOTIFICATIONS = frozenset(
    {"permission_prompt", "elicitation_dialog", "elicitation_url_dialog", "agent_needs_input"}
)
LIFECYCLE_EVENTS = frozenset({"SessionStart", "Stop", "SessionEnd"})
PROMPT_LIMIT = 80

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
_PLACEHOLDER = re.compile(r"\[(?:Image|Pasted text) #\d+[^\]]*\]")  # Claude Code paste markers


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
    if name == "PermissionRequest":
        return WAITING
    if name == "Notification":
        kind = event.get("notification_type")
        if kind == "idle_prompt":
            return IDLE
        return WAITING if kind in WAITING_NOTIFICATIONS else None
    if name == "Stop":
        return DONE
    if name == "SessionEnd":
        return DELETE
    return None


def transition(
    prev: Session | None, event: dict, iterm_id: str, target: str, now: float
) -> Session:
    name = event.get("hook_event_name")
    if prev is not None and _is_idle_prompt(event) and prev.state != WORKING:
        return prev  # only an interrupted turn goes idle; never hide waiting/done
    if prev is None or name == "SessionStart":
        prev = Session(iterm_id, "", "", "", now)
    since = prev.since if prev.state == target else now
    last_prompt = prev.last_prompt
    if name == "UserPromptSubmit":
        last_prompt = human_prompt(str(event.get("prompt") or "")) or last_prompt
    return replace(
        prev,
        claude_session_id=str(event.get("session_id") or prev.claude_session_id),
        cwd=str(event.get("cwd") or prev.cwd),
        state=target,
        since=since,
        last_prompt=last_prompt,
    )


def _is_idle_prompt(event: dict) -> bool:
    return (
        event.get("hook_event_name") == "Notification"
        and event.get("notification_type") == "idle_prompt"
    )


def human_prompt(text: str) -> str:
    """The prompt as you typed it, or "" for system-injected ones (<task-notification> etc.)."""
    if text.lstrip().startswith("<"):
        return ""
    return clean(_PLACEHOLDER.sub(" ", text), PROMPT_LIMIT)


def clean(text: str, limit: int) -> str:
    text = _SPACES.sub(" ", _CONTROL.sub(" ", text)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def project_name(cwd: str) -> str:
    return os.path.basename(cwd.rstrip("/")) or "?"


def attention_text(session: Session) -> str:
    template = NEEDS_YOU if session.state == WAITING else FINISHED
    return clean(template.format(name=project_name(session.cwd)), PROMPT_LIMIT)


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
    return " ".join(parts) or QUIET


def by_project(sessions: Iterable[Session]) -> list[tuple[str, list[Session]]]:
    """Sessions grouped by project, groups in order of first appearance."""
    groups: dict[str, list[Session]] = {}
    for s in sessions:
        groups.setdefault(project_name(s.cwd), []).append(s)
    return list(groups.items())


def status_variants(
    sessions: Iterable[Session],
    tabs: dict[str, int],
    current: str | None,
    group: bool = False,
) -> list[str]:
    """Status bar texts, longest first; iTerm shows the longest that fits.

    tabs maps iterm_id -> tab number (the ⌘N for it); current is bracketed.
    With group, sessions of one project collapse into one entry: "1 hydrogen ✋🟠".
    """
    sessions = list(sessions)

    def mark(text: str, members: list[Session]) -> str:
        return f"[{text}]" if any(s.iterm_id == current for s in members) else text

    def entry(s: Session) -> str:
        return mark(f"{tabs.get(s.iterm_id, '')}{ICONS[s.state]} {project_name(s.cwd)}", [s])

    def group_entry(project: str, members: list[Session]) -> str:
        if len(members) == 1:
            return entry(members[0])
        icons = "".join(ICONS[s.state] for s in members)
        return mark(f"{tabs.get(members[0].iterm_id, '')} {project} {icons}".strip(), members)

    def listing(items: Iterable[Session]) -> str:
        if group:
            return "  ".join(group_entry(p, m) for p, m in by_project(items))
        return "  ".join(entry(s) for s in items)

    variants = [listing(sessions), listing(s for s in sessions if s.state != IDLE)]
    variants.append(summary(sessions))
    return [v for i, v in enumerate(variants) if v and v not in variants[:i]]


def most_urgent(states: Iterable[str]) -> str:
    return min(states, key=PRIORITY.index)


def tab_color_key(state: str, is_active: bool) -> str | None:
    if is_active or state not in (WAITING, DONE):
        return None
    return state
