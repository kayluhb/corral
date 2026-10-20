import asyncio
import time

import pytest
from iterm2 import api_pb2
from iterm2.screen import LineContents

from corral import control as control_module
from corral import daemon, settings, state, store
from corral.state import DONE, IDLE, WAITING, WORKING, Session


class FakeSession:
    def __init__(self, session_id, fail=False):
        self.session_id = session_id
        self.fail = fail
        self.colors: list[bool] = []  # use_tab_color values applied, in order
        self.injected: list[bytes] = []
        self.typed: list[str] = []  # async_send_text calls, in order
        self.on_type = None  # called after each async_send_text
        self.status = None  # iTerm's Claude Code integration status; None when it reports none
        self.screen = ["─" * 10, "❯\xa0", "─" * 10]  # claude's empty input box

    async def async_get_screen_contents(self):
        return FakeScreen(self.screen)

    async def async_get_variable(self, name):
        assert name == "status"
        return self.status

    async def async_set_profile_properties(self, profile):
        if self.fail:
            raise RuntimeError("boom")
        self.colors.append(profile._LocalWriteOnlyProfile__values["Use Tab Color"] == "true")

    async def async_inject(self, data):
        self.injected.append(data)

    async def async_send_text(self, text):
        self.typed.append(text)
        if self.on_type:
            self.on_type()

    async def async_split_pane(self, **kwargs):
        raise AssertionError("opened a second picker")

    async def async_close(self, force=False):
        self.closed = True


class FakeLine:
    def __init__(self, text):
        self.string = text

    def string_at(self, x):
        return self.string[x]

    def style_at(self, x):
        return None


class FakeScreen:
    def __init__(self, lines):
        self.number_of_lines = len(lines)
        self.lines = [FakeLine(text) for text in lines]

    def line(self, i):
        return self.lines[i]


class FakeTab:
    def __init__(self, sessions):
        self.sessions = sessions
        self.tab_id = sessions[0].session_id
        self.titles: list[str] = []  # titles set, in order

    async def async_set_title(self, title):
        self.titles.append(title)


class FakeApp:
    def __init__(self, sessions, current, tabs=None, windows=None):
        """tabs: lists of sessions sharing a tab (splits); default one tab per session.

        windows: lists of tabs (each a list of sessions); overrides tabs.
        """
        self.sessions = {s.session_id: s for s in sessions}
        self.current = current
        windows = windows or [tabs or [[s] for s in sessions]]
        self.window_tabs = [[FakeTab(group) for group in w] for w in windows]
        self.tab_list = [tab for w in self.window_tabs for tab in w]

    def get_session_by_id(self, session_id):
        return self.sessions.get(session_id)

    def tab(self, session_id):
        return next(t for t in self.tab_list if any(s.session_id == session_id for s in t.sessions))

    @property
    def terminal_windows(self):
        return [
            type("Window", (), {"tabs": tabs, "window_id": f"W{n}"})()
            for n, tabs in enumerate(self.window_tabs)
        ]

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
    assert a.injected and b"is done" in a.injected[0]
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
    assert d.status("C")[0] == "1 🟠 B | 3 ✋ A"
    assert d.status("A")[0] == "1 🟠 B | 3 [✋ A]"


def two_windows():
    a, b, c = FakeSession("A"), FakeSession("B"), FakeSession("C")
    d = daemon.Daemon(FakeApp([a, b, c], current="A", windows=[[[a], [b]], [[c]]]))
    put("A", WORKING)
    put("B", WAITING)
    put("C", WAITING)
    tick(d)
    return d


def test_status_bar_lists_only_its_own_window():
    d = two_windows()
    assert d.status("A")[0] == "1 [🟠 A] | 2 ✋ B"
    assert d.status("C")[0] == "1 [✋ C]"


def test_status_bar_is_quiet_in_a_window_without_claude():
    other = FakeSession("O")
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a, other], current="A", windows=[[[a]], [[other]]]))
    put("A", WAITING)
    tick(d)
    assert d.status("O") == [state.QUIET]


def test_jump_stays_in_the_current_window(monkeypatch):
    d = two_windows()
    focused = []

    async def focus(iterm_id):
        focused.append(iterm_id)

    monkeypatch.setattr(d, "focus", focus)
    asyncio.run(d.jump(WAITING, "C"))  # C is the only waiting session in its window
    asyncio.run(d.jump(WAITING, "A"))
    assert focused == ["C", "B"]


def test_pick_again_closes_the_open_picker():
    a, picker = FakeSession("A"), FakeSession("P")
    d = daemon.Daemon(FakeApp([a, picker], current="P", tabs=[[a, picker]]))

    async def run():
        d.terminations["P"] = asyncio.get_running_loop().create_future()
        await d.pick("P")  # pressed from inside the picker pane

    asyncio.run(run())
    assert getattr(picker, "closed", False)


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


def test_tick_records_each_sessions_window():
    from corral import restore

    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="A", windows=[[[a]], [[b]]]))
    store.write(Session("A", "c1", "/p/A", WORKING, 1.0))
    store.write(Session("B", "c2", "/p/B", WORKING, 1.0))
    tick(d)
    history = restore.load()
    assert (history["c1"]["window"], history["c2"]["window"]) == ("W0", "W1")


def test_grouping_comes_from_corral_settings(monkeypatch):
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="A"))
    store.write(Session("A", "c1", "/p/hydrogen", WORKING, 1.0))
    store.write(Session("B", "c2", "/p/hydrogen", WAITING, 1.0))
    tick(d)
    assert d.status("A")[0] == "1 [🟠 hydrogen] | 2 ✋ hydrogen"
    settings.save(settings.Settings(group=True))
    tick(d)
    assert d.status("A")[0] == "1 [hydrogen 🟠✋]"


def test_tab_colours_off_clears_and_stops_painting():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WAITING)
    tick(d)
    assert a.colors == [True]
    settings.save(settings.Settings(tab_colours=False))
    tick(d)
    assert a.colors == [True, False]
    put("A", DONE)
    tick(d)
    assert a.colors == [True, False]


def test_waiting_tab_is_red_and_done_tab_green():
    assert daemon.COLORS[WAITING].red > 200 and daemon.COLORS[WAITING].green < 100
    assert daemon.COLORS[DONE].green > daemon.COLORS[DONE].red


TITLE = "\\(currentSession.presentationName)"


def test_tab_title_shows_waiting_only():
    a, b, c, other = FakeSession("A"), FakeSession("B"), FakeSession("C"), FakeSession("O")
    app = FakeApp([a, b, c, other], current="O")
    d = daemon.Daemon(app)
    put("A", WAITING)
    put("B", WORKING)
    put("C", DONE)
    tick(d)
    assert app.tab("A").titles == [f"✋ {TITLE}"]
    assert app.tab("C").titles == [""]  # iTerm's tab status dot already shows done
    assert app.tab("B").titles == [""]  # Claude Code's own title already shows working
    assert app.tab("O").titles == []  # not a claude tab: never touched
    tick(d)
    assert app.tab("A").titles == [f"✋ {TITLE}"]  # unchanged: not set again


def test_split_tab_shows_most_urgent_icon():
    a, b = FakeSession("A"), FakeSession("B")
    app = FakeApp([a, b], current="A", tabs=[[a, b]])
    d = daemon.Daemon(app)
    put("A", WORKING)
    put("B", WAITING)
    tick(d)
    assert app.tab("A").titles == [f"✋ {TITLE}"]


def test_tab_title_resets_when_claude_exits():
    a = FakeSession("A")
    app = FakeApp([a], current="A")
    d = daemon.Daemon(app)
    put("A", WAITING)
    tick(d)
    put("A", WORKING)  # permission granted: back to Claude Code's own title
    tick(d)
    put("A", WAITING)
    tick(d)
    store.delete("A")
    tick(d)
    assert app.tab("A").titles == [f"✋ {TITLE}", "", f"✋ {TITLE}", ""]


def test_fresh_daemon_clears_titles_an_earlier_run_left_on_claude_tabs():
    a, other = FakeSession("A"), FakeSession("O")
    app = FakeApp([a, other], current="O")
    d = daemon.Daemon(app)
    put("A", WORKING)
    tick(d)
    tick(d)
    assert app.tab("A").titles == [""]  # reset once, not every tick
    assert app.tab("O").titles == []


def test_follows_iterm_status_when_it_reports_one():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WORKING)
    tick(d)
    a.status = WAITING
    tick(d)
    assert store.read("A").state == WAITING
    assert a.injected and b"needs you" in a.injected[0]


def test_keeps_its_own_state_without_iterm_status():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WAITING)
    tick(d)
    assert store.read("A").state == WAITING


def test_late_hook_write_does_not_override_iterm_status():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WAITING)
    a.status = WORKING  # permission granted
    tick(d)
    put("A", WAITING)  # corral's delayed permission_prompt Notification lands
    tick(d)
    assert store.read("A").state == WORKING


def test_hook_leaving_waiting_is_not_undone_by_an_unchanged_iterm_status():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WORKING)
    a.status = WAITING
    tick(d)
    put("A", WORKING)  # you answered; corral's hook got there before iTerm's
    tick(d)
    assert store.read("A").state == WORKING
    a.status = DONE
    tick(d)
    assert store.read("A").state == DONE


def test_parallel_tool_leaving_waiting_shows_working_until_iterm_changes():
    # Known heuristic gap: a main-agent PostToolUse (no agent_id) for a parallel tool
    # leaves waiting while another tool still waits; corral can't tell it from an answer.
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WORKING)
    a.status = WAITING
    tick(d)
    put("A", WORKING)  # parallel tool's PostToolUse; the prompt is still open
    tick(d)
    tick(d)
    assert store.read("A").state == WORKING
    a.status = WORKING
    tick(d)
    a.status = WAITING
    tick(d)
    assert store.read("A").state == WAITING


def test_iterm_done_becomes_idle_once_seen_and_stays_idle():
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", WORKING)
    a.status = DONE  # iTerm keeps reporting done until the next prompt
    tick(d)
    tick(d)
    assert store.read("A").state == IDLE


def test_iterm_done_again_after_new_turn_is_done():
    a, b = FakeSession("A"), FakeSession("B")
    app = FakeApp([a, b], current="A")
    d = daemon.Daemon(app)
    put("A", WORKING)
    a.status = DONE
    tick(d)  # seen: idle
    a.status = WORKING
    tick(d)
    app.current = "B"
    a.status = DONE
    tick(d)
    assert store.read("A").state == DONE


def test_iterm_status_change_restarts_since():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WORKING)  # since 1.0
    a.status = WAITING
    tick(d)
    assert store.read("A").since > 1.0


def control(d, message):
    return asyncio.run(d.control(message))


def test_send_types_the_prompt_as_a_paste_then_enter(monkeypatch):
    monkeypatch.setattr(daemon, "SUBMIT_DELAY", 0)
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", DONE)
    assert control(d, {"op": "send", "iterm_id": "A", "text": "run\ntests"}) == {"ok": True}
    assert a.typed == ["\x1b[200~run\ntests\x1b[201~", "\r"]


def test_send_refuses_a_session_waiting_on_you():
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", WAITING)
    assert "waiting" in control(d, {"op": "send", "iterm_id": "A", "text": "1"})["error"]
    assert a.typed == []


def test_send_refuses_unknown_or_closed_sessions():
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    assert "no claude session" in control(d, {"op": "send", "iterm_id": "A", "text": "x"})["error"]
    put("GONE", IDLE)  # state file left behind, tab already closed
    assert (
        "no claude session" in control(d, {"op": "send", "iterm_id": "GONE", "text": "x"})["error"]
    )
    assert "unknown" in control(d, {"op": "nope"})["error"]


def test_ping_reports_the_version_the_daemon_started_on(monkeypatch):
    monkeypatch.setattr(control_module, "version", lambda: "1.2.0")
    d = daemon.Daemon(FakeApp([FakeSession("A")], current="A"))
    monkeypatch.setattr(control_module, "version", lambda: "9.9.9")  # an upgrade on disk
    assert control(d, {"op": "ping"}) == {"ok": True, "version": "1.2.0"}


def test_explain_reports_what_iterm_says_about_the_session():
    a, b = FakeSession("A"), FakeSession("B")
    d = daemon.Daemon(FakeApp([a, b], current="B"))
    put("A", WAITING)
    a.status = WAITING
    tick(d)
    assert control(d, {"op": "explain", "iterm_id": "A"}) == {
        "ok": True,
        "tab_open": True,
        "iterm_status": WAITING,
        "focused": False,
        "tab_colour": WAITING,
    }


def test_explain_a_session_iterm_reports_nothing_for():
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", WORKING)
    tick(d)
    reply = control(d, {"op": "explain", "iterm_id": "A"})
    assert reply["iterm_status"] is None and reply["focused"] is True
    assert control(d, {"op": "explain", "iterm_id": "GONE"})["tab_open"] is False


def test_send_refuses_when_iterm_already_says_waiting():
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", WORKING)  # the hooks haven't caught up yet
    a.status = WAITING
    assert "waiting" in control(d, {"op": "send", "iterm_id": "A", "text": "1"})["error"]
    assert a.typed == []


def test_send_holds_back_enter_if_a_prompt_appears_while_pasting(monkeypatch):
    monkeypatch.setattr(daemon, "SUBMIT_DELAY", 0)
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", WORKING)
    a.on_type = lambda: setattr(a, "status", WAITING)
    reply = control(d, {"op": "send", "iterm_id": "A", "text": "go"})
    assert "waiting" in reply["error"] and "not submitted" in reply["error"]
    assert a.typed == ["\x1b[200~go\x1b[201~"]  # no Enter


def test_send_refuses_a_session_with_a_half_typed_prompt():
    a = FakeSession("A")
    d = daemon.Daemon(FakeApp([a], current="A"))
    put("A", DONE)
    a.screen = ["─" * 10, "❯\xa0fix the", "─" * 10]
    assert "half-typed" in control(d, {"op": "send", "iterm_id": "A", "text": "go"})["error"]
    assert a.typed == []


def test_screen_cells_reads_faint_cells_and_cells_with_no_characters():
    per_cell = [(1, 2), (0, 1), (1, 1)]  # (code points, repeats): "a", "界", its right half, "b"
    line = LineContents(
        api_pb2.LineContents(
            text="a界b",
            code_points_per_cell=[
                api_pb2.CodePointsPerCell(num_code_points=n, repeats=r) for n, r in per_cell
            ],
            style=[api_pb2.CellStyle(repeats=3), api_pb2.CellStyle(faint=True, repeats=1)],
        )
    )
    assert daemon.screen_cells(line) == [("a", False), ("界", False), ("", False), ("b", True)]
