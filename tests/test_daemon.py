import asyncio
import time

import pytest

from corral import daemon, state, store
from corral.state import DONE, IDLE, WAITING, WORKING, Session


class FakeSession:
    def __init__(self, session_id, fail=False):
        self.session_id = session_id
        self.fail = fail
        self.colors: list[bool] = []  # use_tab_color values applied, in order
        self.injected: list[bytes] = []

    async def async_set_profile_properties(self, profile):
        if self.fail:
            raise RuntimeError("boom")
        self.colors.append(profile._LocalWriteOnlyProfile__values["Use Tab Color"] == "true")

    async def async_inject(self, data):
        self.injected.append(data)


class FakeApp:
    def __init__(self, sessions, current):
        self.sessions = {s.session_id: s for s in sessions}
        self.current = current

    def get_session_by_id(self, session_id):
        return self.sessions.get(session_id)

    @property
    def terminal_windows(self):
        tabs = [type("Tab", (), {"sessions": [s]})() for s in self.sessions.values()]
        return [type("Window", (), {"tabs": tabs})()]

    @property
    def current_window(self):
        session = self.sessions[self.current]
        tab = type("Tab", (), {"current_session": session})()
        return type("Window", (), {"current_tab": tab})()


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))


@pytest.fixture(autouse=True)
def use_osc9(monkeypatch):
    monkeypatch.setattr(daemon, "USE_OSC9", True)


def put(iterm_id, st):
    store.write(Session(iterm_id, "c", f"/p/{iterm_id}", st, 1.0))


def tick(d):
    asyncio.run(d.tick())


def test_done_in_focused_tab_becomes_idle():
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", DONE)
    tick(d)
    assert store.read("A").state == IDLE


def test_done_stays_done_and_notifies_while_iterm_in_background():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="A"))
    put("A", WORKING)
    tick(d)
    d.app_active = False
    put("A", DONE)
    tick(d)
    assert store.read("A").state == DONE
    assert a.injected and b"Yeehaw" in a.injected[0]
    assert a.colors[-1] is True


def test_one_failing_session_does_not_freeze_the_rest():
    bad, good = FakeSession("BAD", fail=True), FakeSession("GOOD")
    d = daemon.Daemon(FakeApp([bad, good], current="GOOD"))
    put("BAD", WAITING)
    put("GOOD", WORKING)
    tick(d)
    assert d.summary == state.summary([store.read("BAD"), store.read("GOOD")])


def test_colour_cleared_when_claude_exits_but_tab_stays():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WAITING)
    tick(d)
    assert a.colors == [True]
    store.delete("A")
    tick(d)
    assert a.colors == [True, False]


def test_never_clears_colour_corral_did_not_apply():
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", WORKING)
    tick(d)
    assert a.colors == []


def test_status_bar_lists_sessions_in_tab_order():
    a, b, c = FakeSession("A"), FakeSession("B"), FakeSession("C")
    d = daemon.Daemon(FakeApp([b, c, a], current="C"))
    put("A", WAITING)
    put("B", WORKING)
    tick(d)
    assert d.status("C")[0] == "1🐎 B  3🐄 A"
    assert d.status("A")[0] == "1🐎 B  [3🐄 A]"


def test_tick_records_restore_history_without_forgetting_earlier_sessions():
    from corral import restore

    earlier = {"cwd": "/p/x", "last_prompt": "", "order": 0, "last_seen": time.time() - 60}
    restore.save({"from-last-time": earlier})
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", WORKING)
    tick(d)
    history = restore.load()
    assert set(history) == {"from-last-time", "c"}
    assert history["c"]["cwd"] == "/p/A"
