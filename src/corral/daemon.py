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

from corral import state, store

POLL_SECONDS = 0.5
PICK_TIMEOUT = 600
CORRAL_BIN = os.environ.get("CORRAL_BIN", os.path.expanduser("~/.local/bin/corral"))
COLORS = {
    state.WAITING: iterm2.Color(255, 176, 0),
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
        self.terminations: dict[str, asyncio.Future] = {}
        self.lock = asyncio.Lock()

    def live_sessions(self) -> list[state.Session]:
        return [s for s in store.load_all() if self.app.get_session_by_id(s.iterm_id)]

    def prune_dead(self) -> None:
        for s in store.load_all():
            if not self.app.get_session_by_id(s.iterm_id):
                store.delete(s.iterm_id)

    async def tick(self) -> None:
        async with self.lock:
            await self._tick()

    async def _tick(self) -> None:
        sessions = self.live_sessions()
        now = time.time()
        for i, s in enumerate(sessions):
            if s.state == state.DONE and s.iterm_id == self.active_id:
                if store.read(s.iterm_id) == s:  # don't clobber a newer hook write
                    s = replace(s, state=state.IDLE, since=now)
                    store.write(s)
                    sessions[i] = s
            await self.paint(s)
            prev = self.known.get(s.iterm_id)
            if prev is not None and prev != s.state and s.state in (state.WAITING, state.DONE):
                if s.iterm_id != self.active_id:
                    await self.notify(s)
        self.known = {s.iterm_id: s.state for s in sessions}
        self.summary = state.summary(sessions)

    async def paint(self, s: state.Session) -> None:
        key = state.tab_color_key(s.state, s.iterm_id == self.active_id)
        if self.painted.get(s.iterm_id, "unset") == key:
            return
        session = self.app.get_session_by_id(s.iterm_id)
        if session is None:
            return
        profile = iterm2.LocalWriteOnlyProfile()
        profile.set_use_tab_color(key is not None)
        if key is not None:
            profile.set_tab_color(COLORS[key])
        await session.async_set_profile_properties(profile)
        self.painted[s.iterm_id] = key

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
                if update.active_session_changed:
                    self.active_id = update.active_session_changed.session_id
                    await self.tick()

    async def watch_terminations(self, connection: iterm2.Connection) -> None:
        async with iterm2.SessionTerminationMonitor(connection) as monitor:
            while True:
                session_id = await monitor.async_get()
                if store.valid_id(session_id):
                    store.delete(session_id)
                self.known.pop(session_id, None)
                self.painted.pop(session_id, None)
                future = self.terminations.get(session_id)
                if future is not None and not future.done():
                    future.set_result(None)


def json_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def main(connection: iterm2.Connection) -> None:
    app = await iterm2.async_get_app(connection)
    daemon = Daemon(app)
    window = app.current_terminal_window
    if window and window.current_tab:
        daemon.active_id = window.current_tab.current_session.session_id

    component = iterm2.StatusBarComponent(
        short_description="corral",
        detailed_description="Claude session status (waiting / working / done)",
        knobs=[],
        exemplar="✋2 ⚙3 ✓1",
        update_cadence=1.0,
        identifier="com.calebbrown.corral",
    )

    @iterm2.StatusBarRPC
    async def corral_status(knobs):
        return daemon.summary

    @iterm2.RPC
    async def corral_next_waiting(session_id=CURRENT_SESSION):
        await daemon.jump(state.WAITING, session_id)

    @iterm2.RPC
    async def corral_next_done(session_id=CURRENT_SESSION):
        await daemon.jump(state.DONE, session_id)

    @iterm2.RPC
    async def corral_pick(session_id=CURRENT_SESSION):
        await daemon.pick(session_id)

    await component.async_register(connection, corral_status)
    await corral_next_waiting.async_register(connection)
    await corral_next_done.async_register(connection)
    await corral_pick.async_register(connection, timeout=PICK_TIMEOUT + 5)

    daemon.prune_dead()
    asyncio.create_task(daemon.watch_focus(connection))
    asyncio.create_task(daemon.watch_terminations(connection))
    while True:
        try:
            await daemon.tick()
        except Exception as exc:  # keep the daemon alive; surface in Script Console
            print(f"corral tick error: {exc!r}")
        await asyncio.sleep(POLL_SECONDS)


def run() -> None:
    iterm2.run_forever(main)
