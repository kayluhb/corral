"""Clickable session list shown when you click corral's status bar item.

iTerm only reports that the item was clicked, not where, so the click opens a popover
(a small web view) listing the sessions. Each row links to a tiny localhost server in the
daemon that focuses that session. A 204 reply keeps the popover on its page.
"""

from __future__ import annotations

import asyncio
import html
import re
import secrets
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from corral import state, store

_REQUEST = re.compile(r"^GET /focus/([^?\s]+)\?t=(\S+) HTTP/1\.[01]$")

_CSS = """
:root { color-scheme: light dark; --fg: #1d1d1f; --muted: #6e6e73; --hover: #0000000f;
  --current: #0071e31f; }
@media (prefers-color-scheme: dark) { :root { --fg: #f5f5f7; --muted: #98989d;
  --hover: #ffffff14; --current: #0a84ff33; } }
body { margin: 0; padding: 6px; font: 13px -apple-system, system-ui, sans-serif;
  color: var(--fg); background: transparent; }
.row { display: flex; gap: 8px; align-items: baseline; padding: 5px 8px; border-radius: 6px;
  color: inherit; text-decoration: none; white-space: nowrap; overflow: hidden; }
.row:hover { background: var(--hover); }
.current { background: var(--current); }
.tab { color: var(--muted); min-width: 1.2em; text-align: right; }
.prompt { color: var(--muted); overflow: hidden; text-overflow: ellipsis; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
  align-self: center; flex: none; }
.working { background: #f2a647; }  /* sampled from iTerm's tab dot */
.done { background: #34c759; }
.idle { background: #8e8e93; }
.quiet { padding: 8px; color: var(--muted); }
.group { padding: 8px 8px 2px; font-weight: 600; }
"""

ROW_HEIGHT = 27
WIDTH = 380


def render(
    sessions: Iterable[state.Session],
    tabs: dict[str, int],
    current: str | None,
    url: str,
    token: str,
    group: bool = False,
) -> str:
    def row(s: state.Session, show_project: bool) -> str:
        cls = "row current" if s.iterm_id == current else "row"
        href = html.escape(f"{url}/{s.iterm_id}?t={token}")
        project = state.project_name(s.cwd) if show_project else ""
        # A coloured dot like iTerm's tabs; waiting keeps the hand, as in tab titles.
        icon = (
            f"<span>{state.ICONS[s.state]}</span>"
            if s.state == state.WAITING
            else f'<span class="dot {s.state}"></span>'
        )
        return (
            f'<a class="{cls}" href="{href}">'
            f'<span class="tab">{tabs.get(s.iterm_id, "")}</span>'
            + icon
            + (f"<span>{html.escape(project)}</span>" if project else "")
            + f'<span class="prompt">{html.escape(s.last_prompt)}</span></a>'
        )

    if group:
        body = "".join(
            f'<div class="group">{html.escape(project)}</div>'
            + "".join(row(s, show_project=False) for s in members)
            for project, members in state.by_project(sessions)
        )
    else:
        body = "".join(row(s, show_project=True) for s in sessions)
    body = body or f'<div class="quiet">{html.escape(state.QUIET)}</div>'
    return f'<!doctype html><meta charset="utf-8"><style>{_CSS}</style>{body}'


def row_count(sessions: list[state.Session], group: bool) -> int:
    return len(sessions) + (len(state.by_project(sessions)) if group else 0)


def height(count: int) -> int:
    return max(count, 1) * ROW_HEIGHT + 16


def parse_request(line: str, token: str) -> str | None:
    match = _REQUEST.match(line.strip())
    if not match or not secrets.compare_digest(match.group(2), token):
        return None
    iterm_id = match.group(1)
    return iterm_id if store.valid_id(iterm_id) else None


@dataclass
class Server:
    port: int
    token: str
    server: asyncio.Server

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/focus"

    def close(self) -> None:
        self.server.close()


async def serve(on_focus: Callable[[str], Awaitable[None]]) -> Server:
    token = secrets.token_urlsafe(16)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 2)).decode("latin-1")
            iterm_id = parse_request(line, token)
            status = "204 No Content" if iterm_id else "404 Not Found"
            writer.write(f"HTTP/1.1 {status}\r\nConnection: close\r\n\r\n".encode())
            await writer.drain()
            if iterm_id:
                await on_focus(iterm_id)
        except Exception as exc:  # never let one bad request hurt the daemon
            print(f"corral popover: {exc!r}")
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return Server(port, token, server)
