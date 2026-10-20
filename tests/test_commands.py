import json

import pytest

from corral import commands, control, store
from corral.state import DONE, IDLE, WAITING, WORKING, Session

A = "AAAA1111-0000-0000-0000-000000000000"
B = "BBBB2222-0000-0000-0000-000000000000"
C = "BBBB3333-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))


def put(iterm_id, st, cwd="/p/x", since=1.0, claude="c1", prompt=""):
    s = Session(iterm_id, claude, cwd, st, since, prompt)
    store.write(s)
    return s


class Clock:
    """Fake time: sleep() advances now and runs the scripted change due at that tick."""

    def __init__(self, changes=()):
        self.t = 100.0
        self.changes = list(changes)

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        if self.changes:
            self.changes.pop(0)()


def wait(target, clock, **kw):
    return commands.wait(target, now=clock.now, sleep=clock.sleep, **kw)


# resolve


def test_resolve_by_full_id_prefix_or_project():
    sessions = [put(A, IDLE, "/p/hydrogen"), put(B, IDLE, "/p/lasso"), put(C, IDLE, "/p/lasso")]
    assert commands.resolve(sessions, A).iterm_id == A
    assert commands.resolve(sessions, "aaaa").iterm_id == A  # ids are case-insensitive
    assert commands.resolve(sessions, "BBBB3").iterm_id == C
    assert commands.resolve(sessions, "hydrogen").iterm_id == A


def test_resolve_rejects_ambiguous_and_unknown():
    sessions = [put(A, IDLE, "/p/hydrogen"), put(B, IDLE, "/p/lasso"), put(C, IDLE, "/p/lasso")]
    with pytest.raises(commands.CommandError, match="matches 2 sessions"):
        commands.resolve(sessions, "lasso")
    with pytest.raises(commands.CommandError, match="matches 2 sessions"):
        commands.resolve(sessions, "BBBB")
    with pytest.raises(commands.CommandError, match="no claude session"):
        commands.resolve(sessions, "nope")


# list


def test_list_prints_urgent_first_with_short_ids(capsys):
    put(A, IDLE, "/p/hydrogen", since=1.0)
    put(B, WAITING, "/p/lasso", since=2.0, prompt="fix the tests")
    assert commands.list_sessions(as_json=False, now=lambda: 62.0) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("BBBB2222  ✋ lasso")
    assert lines[0].endswith("1m  fix the tests")
    assert lines[1].startswith("AAAA1111  ⚪ hydrogen")


def test_list_json_has_full_ids_and_project(capsys):
    put(A, WORKING, "/p/hydrogen")
    commands.list_sessions(as_json=True)
    [row] = json.loads(capsys.readouterr().out)
    assert row["iterm_id"] == A and row["project"] == "hydrogen" and row["state"] == WORKING


def test_list_when_empty(capsys):
    assert commands.list_sessions(as_json=False) == 0
    assert "no claude sessions" in capsys.readouterr().out
    commands.list_sessions(as_json=True)
    assert json.loads(capsys.readouterr().out) == []


# wait


def test_wait_returns_once_session_stops_working():
    put(A, WORKING)
    clock = Clock([lambda: None, lambda: put(A, DONE, since=101.0)])
    assert wait(A, clock) == 0
    assert clock.t == 101.0


def test_wait_returns_at_once_when_already_there():
    put(A, WAITING)
    clock = Clock()
    assert wait(A, clock) == 0
    assert clock.t == 100.0


def test_wait_until_a_given_state():
    put(A, WORKING)
    clock = Clock([lambda: put(A, DONE), lambda: put(A, WAITING)])
    assert wait(A, clock, until={WAITING}) == 0
    assert clock.t == 101.0


def test_wait_times_out():
    put(A, WORKING)
    assert wait(A, Clock(), timeout=2.0) == 1


def test_wait_after_ignores_states_reached_before_then():
    put(A, DONE, since=50.0)  # finished before the prompt was sent
    clock = Clock([lambda: put(A, WORKING, since=100.5), lambda: put(A, DONE, since=101.0)])
    assert wait(A, clock, after=100.0) == 0
    assert clock.t == 101.0


def test_wait_fails_when_session_ends():
    put(A, WORKING)
    assert wait(A, Clock([lambda: store.delete(A)])) == 2


def test_wait_fails_when_another_claude_takes_the_tab():
    put(A, WORKING, claude="first")
    assert wait(A, Clock([lambda: put(A, IDLE, claude="second")])) == 2


def test_wait_unknown_target(capsys):
    assert wait("nope", Clock()) == 2
    assert "no claude session" in capsys.readouterr().err


# send


def test_send_asks_the_daemon_to_type_the_prompt(monkeypatch):
    put(A, IDLE, "/p/hydrogen")
    sent = []
    monkeypatch.setattr(control, "request", lambda msg: sent.append(msg) or {"ok": True})
    assert commands.send("hydrogen", "run the tests") == 0
    assert sent == [{"op": "send", "iterm_id": A, "text": "run the tests"}]


def test_send_reports_daemon_errors(monkeypatch, capsys):
    put(A, IDLE)
    monkeypatch.setattr(control, "request", lambda msg: {"error": "it is waiting on you"})
    assert commands.send(A, "hi") == 2
    assert "it is waiting on you" in capsys.readouterr().err


def test_send_when_daemon_is_not_running(capsys):
    put(A, IDLE)
    assert commands.send(A, "hi") == 2
    assert "daemon" in capsys.readouterr().err


def test_send_wait_waits_for_that_prompts_turn(monkeypatch):
    put(A, DONE, since=50.0)
    monkeypatch.setattr(control, "request", lambda msg: {"ok": True})
    clock = Clock([lambda: put(A, WORKING, since=100.5), lambda: put(A, DONE, since=101.0)])
    code = commands.send(A, "go", wait_until=commands.STOPPED, now=clock.now, sleep=clock.sleep)
    assert code == 0
    assert clock.t == 101.0


def test_list_shows_branches(tmp_path, capsys):
    repo = tmp_path / "hydrogen"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    put(A, IDLE, str(repo))
    commands.list_sessions(as_json=False)
    assert "hydrogen (main)" in capsys.readouterr().out
    commands.list_sessions(as_json=True)
    assert json.loads(capsys.readouterr().out)[0]["branch"] == "main"
