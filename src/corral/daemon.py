"""iTerm2 AutoLaunch daemon: status bar, tab colours, notifications, hotkey RPCs."""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import iterm2

from corral import launcher, popover, restore, settings, state, store

POLL_SECONDS = 0.5
PICK_TIMEOUT = 600
CORRAL_BIN = os.environ.get("CORRAL_BIN", os.path.expanduser("~/.local/bin/corral"))
COLORS = {
    state.WAITING: iterm2.Color(230, 60, 60),
    state.DONE: iterm2.Color(80, 200, 120),
}
USE_OSC9 = True  # iTerm's own notification (tied to the tab); False falls back to osascript
CURRENT_SESSION = iterm2.Reference("id")  # RPC arg bound to the invoking session


class Daemon:
    def __init__(self, app: iterm2.App) -> None:
        self.app = app
        self.active_id: str | None = None
        self.known: dict[str, str] = {}  # iterm_id -> last seen state
        self.painted: dict[str, str | None] = {}  # iterm_id -> colour key applied
        self.summary = state.summary([])
        self.sessions: list[state.Session] = []
        self.tabs: dict[str, int] = {}
        self.settings = settings.load()
        self.history = restore.load()  # keep what earlier runs saw, for `corral restore`
        self.history_saved = 0.0
        self.terminations: dict[str, asyncio.Future] = {}
        self.lock = asyncio.Lock()
        self.app_active = True  # started by a claude hook, so iTerm is almost surely frontmost
        self.tasks: list[asyncio.Task] = []

    def live_sessions(self) -> list[state.Session]:
        return [s for s in store.load_all() if self.app.get_session_by_id(s.iterm_id)]

    def prune_dead(self) -> None:
        for s in store.load_all():
            if not self.app.get_session_by_id(s.iterm_id):
                store.delete(s.iterm_id)

    async def tick(self) -> None:
        async with self.lock:
            await self._tick()

    def current_session_id(self) -> str | None:
        """The session you're looking at, or None when iTerm isn't the frontmost app."""
        if not self.app_active:
            return None
        window = self.app.current_window
        tab = window.current_tab if window else None
        session = tab.current_session if tab else None
        return session.session_id if session else None

    async def _tick(self) -> None:
        self.settings = settings.load()  # small file; re-read so `corral settings` applies live
        self.active_id = self.current_session_id()
        sessions = self.live_sessions()
        now = time.time()
        for i, s in enumerate(sessions):
            try:
                sessions[i] = await self._update(s, now)
            except Exception as exc:  # one bad session must not freeze the rest
                print(f"corral: {s.iterm_id}: {exc!r}")
        live_ids = {s.iterm_id for s in sessions}
        for iterm_id in [i for i, key in self.painted.items() if key and i not in live_ids]:
            try:
                await self.paint(iterm_id, None)  # claude exited but the tab is still open
            except Exception as exc:
                print(f"corral: clear {iterm_id}: {exc!r}")
        self.known = {s.iterm_id: s.state for s in sessions}
        self.summary = state.summary(sessions)
        self.tabs = self.tab_numbers()
        order = {iterm_id: i for i, iterm_id in enumerate(self.tabs)}
        self.sessions = sorted(sessions, key=lambda s: order.get(s.iterm_id, len(order)))
        if now - self.history_saved >= restore.SAVE_EVERY:
            self.history = restore.record(self.history, self.sessions, now)
            restore.save(self.history)
            self.history_saved = now

    def tab_numbers(self) -> dict[str, int]:
        """iterm_id -> its tab's number within its window (the ⌘N), in window/tab order."""
        return {
            session.session_id: n
            for window in self.app.terminal_windows
            for n, tab in enumerate(window.tabs, start=1)
            for session in tab.sessions
        }

    def status(self, session_id: str | None) -> list[str]:
        return state.status_variants(self.sessions, self.tabs, session_id, self.settings.group)

    async def _update(self, s: state.Session, now: float) -> state.Session:
        is_active = s.iterm_id == self.active_id
        if s.state == state.DONE and is_active:
            if store.read(s.iterm_id) == s:  # don't clobber a newer hook write
                s = replace(s, state=state.IDLE, since=now)
                store.write(s)
        colour = state.tab_color_key(s.state, is_active) if self.settings.tab_colours else None
        await self.paint(s.iterm_id, colour)
        prev = self.known.get(s.iterm_id)
        if prev is not None and prev != s.state and s.state in (state.WAITING, state.DONE):
            if not is_active:
                await self.notify(s)
        return s

    async def paint(self, iterm_id: str, key: str | None) -> None:
        # Untracked tabs count as uncoloured, so corral only ever clears colours it applied.
        if self.painted.get(iterm_id) == key:
            return
        session = self.app.get_session_by_id(iterm_id)
        if session is None:
            self.painted.pop(iterm_id, None)
            return
        profile = iterm2.LocalWriteOnlyProfile()
        profile.set_use_tab_color(key is not None)
        if key is not None:
            profile.set_tab_color(COLORS[key])
        await session.async_set_profile_properties(profile)
        self.painted[iterm_id] = key

    async def notify(self, s: state.Session) -> None:
        text = state.attention_text(s)
        if USE_OSC9:
            session = self.app.get_session_by_id(s.iterm_id)
            if session is not None:
                await session.async_inject(f"\x1b]9;{text}\x07".encode())
            return
        script = f'display notification {json_quote(text)} with title "corral"'
        subprocess.Popen(["osascript", "-e", script])

    async def jump(self, st: str, current_id: str) -> None:
        target = state.next_target(self.live_sessions(), st, current_id)
        if target is not None:
            await self.focus(target)

    async def focus(self, iterm_id: str) -> None:
        session = self.app.get_session_by_id(iterm_id)
        if session is not None:
            await session.async_activate(select_tab=True, order_window_front=True)
            await self.app.async_activate()

    async def pick(self, origin_id: str) -> None:
        origin = self.app.get_session_by_id(origin_id)
        if origin is None:
            return
        fd, out = tempfile.mkstemp(prefix="corral-pick-")
        os.close(fd)
        profile = iterm2.LocalWriteOnlyProfile()
        profile.set_use_custom_command("Yes")
        profile.set_command(f"{shlex.quote(CORRAL_BIN)} pick --out {shlex.quote(out)}")
        profile.set_close_sessions_on_end(True)
        picker = await origin.async_split_pane(vertical=False, profile_customizations=profile)
        done = asyncio.get_running_loop().create_future()
        self.terminations[picker.session_id] = done
        try:
            await asyncio.wait_for(done, PICK_TIMEOUT)
        except asyncio.TimeoutError:
            await picker.async_close(force=True)
        finally:
            self.terminations.pop(picker.session_id, None)
        chosen = Path(out).read_text().strip()
        Path(out).unlink(missing_ok=True)
        if chosen:
            await self.focus(chosen)

    async def watch_focus(self, connection: iterm2.Connection) -> None:
        async with iterm2.FocusMonitor(connection) as monitor:
            while True:
                update = await monitor.async_get_next_update()
                if update.application_active is not None:
                    self.app_active = update.application_active.application_active
                try:
                    await self.tick()
                except Exception as exc:
                    print(f"corral focus error: {exc!r}")

    async def watch_terminations(self, connection: iterm2.Connection) -> None:
        async with iterm2.SessionTerminationMonitor(connection) as monitor:
            while True:
                session_id = await monitor.async_get()
                try:
                    if store.valid_id(session_id):
                        store.delete(session_id)
                    self.known.pop(session_id, None)
                    self.painted.pop(session_id, None)
                    future = self.terminations.get(session_id)
                    if future is not None and not future.done():
                        future.set_result(None)
                except Exception as exc:
                    print(f"corral termination error: {exc!r}")


def json_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


COMPONENT_ID = "com.calebbrown.corral"
STATUS_FUNCTION = "corral_status"


def status_component() -> iterm2.StatusBarComponent:
    return iterm2.StatusBarComponent(
        short_description="corral",
        detailed_description="Claude session status (waiting / working / done)",
        knobs=[],
        exemplar="1✋ hydrogen  [2🟡 corral]  3🟢 lasso",
        update_cadence=1.0,
        identifier=COMPONENT_ID,
    )


async def main(connection: iterm2.Connection) -> None:
    app = await iterm2.async_get_app(connection)
    daemon = Daemon(app)

    component = status_component()

    @iterm2.StatusBarRPC  # name must match STATUS_FUNCTION
    async def corral_status(knobs, session_id=CURRENT_SESSION):
        return daemon.status(session_id)

    @iterm2.RPC
    async def corral_next_waiting(session_id=CURRENT_SESSION):
        await daemon.jump(state.WAITING, session_id)

    @iterm2.RPC
    async def corral_next_done(session_id=CURRENT_SESSION):
        await daemon.jump(state.DONE, session_id)

    @iterm2.RPC
    async def corral_pick(session_id=CURRENT_SESSION):
        await daemon.pick(session_id)

    links = await popover.serve(daemon.focus)

    async def on_click(session_id):
        group = daemon.settings.group
        sessions, tabs = daemon.sessions, daemon.tabs
        html = popover.render(sessions, tabs, session_id, links.url, links.token, group)
        size = iterm2.util.Size(popover.WIDTH, popover.height(popover.row_count(sessions, group)))
        await component.async_open_popover(session_id, html, size)

    await component.async_register(connection, corral_status, onclick=on_click)
    await corral_next_waiting.async_register(connection)
    await corral_next_done.async_register(connection)
    await corral_pick.async_register(connection, timeout=PICK_TIMEOUT + 5)

    daemon.prune_dead()
    daemon.tasks = [  # keep references so the monitors aren't garbage-collected
        asyncio.create_task(daemon.watch_focus(connection)),
        asyncio.create_task(daemon.watch_terminations(connection)),
    ]
    while True:
        try:
            await daemon.tick()
        except Exception as exc:  # keep the daemon alive; surface in Script Console
            print(f"corral tick error: {exc!r}")
        await asyncio.sleep(POLL_SECONDS)


def run() -> None:
    lock = launcher.acquire()
    if lock is None:
        return  # another daemon is already running
    iterm2.run_forever(main)  # returns/raises when iTerm quits; the hook restarts us
