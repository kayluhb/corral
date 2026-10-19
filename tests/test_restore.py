import shlex

from corral import restore
from corral.state import IDLE, WORKING, Session


def mk(claude_id, cwd="/p/proj", prompt="", iterm_id=None):
    return Session(iterm_id or f"T-{claude_id}", claude_id, cwd, WORKING, 1.0, prompt)


def entry(cwd, last_seen, order=0, prompt=""):
    return {"cwd": cwd, "last_prompt": prompt, "order": order, "last_seen": last_seen}


def test_record_stamps_live_sessions_in_order():
    history = restore.record({}, [mk("a", "/p/x", "hi"), mk("b", "/p/y")], now=100.0)
    assert history == {
        "a": entry("/p/x", 100.0, 0, "hi"),
        "b": entry("/p/y", 100.0, 1),
    }


def test_record_keeps_gone_sessions_and_skips_ones_without_claude_id():
    history = restore.record({"old": entry("/p/z", 50.0)}, [mk("")], now=100.0)
    assert history == {"old": entry("/p/z", 50.0)}


def test_record_forgets_sessions_older_than_a_week():
    week = 7 * 24 * 3600
    history = restore.record({"old": entry("/p/z", 1.0)}, [], now=1.0 + week + 1)
    assert history == {}


def test_last_batch_is_what_stopped_together_most_recently():
    history = {
        "closed-earlier": entry("/p/a", 100.0, 0),
        "q2": entry("/p/c", 1000.0, 2),
        "q1": entry("/p/b", 995.0, 1),
        "still-running": entry("/p/d", 1000.0, 0),
    }
    batch = restore.last_batch(history, running={"still-running"})
    assert [claude_id for claude_id, _ in batch] == ["q1", "q2"]


def test_last_batch_empty_when_nothing_to_restore():
    assert restore.last_batch({}, running=set()) == []
    assert restore.last_batch({"a": entry("/p/a", 1.0)}, running={"a"}) == []


def test_resume_command_quotes_paths():
    cmd = restore.resume_command("abc-123", "/p/my project")
    assert cmd == "cd '/p/my project' && claude --resume abc-123"


def test_tab_command_runs_resume_in_a_login_shell_then_stays_open():
    cmd = restore.tab_command("abc-123", "/p/my project", "/bin/zsh")
    assert shlex.split(cmd) == [
        "/bin/zsh",
        "-lic",
        "cd '/p/my project' && claude --resume abc-123; exec /bin/zsh -l",
    ]


def test_history_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    assert restore.load() == {}
    restore.save({"a": entry("/p/x", 1.0)})
    assert restore.load() == {"a": entry("/p/x", 1.0)}


def test_load_tolerates_a_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    restore.save({})
    restore.history_path().write_text("not json")
    assert restore.load() == {}


def test_idle_sessions_count_as_open():
    s = mk("a")
    s.state = IDLE
    assert "a" in restore.record({}, [s], now=1.0)
