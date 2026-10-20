import shlex

from corral import restore
from corral.state import IDLE, WORKING, Session


def mk(claude_id, cwd="/p/proj", prompt="", iterm_id=None):
    return Session(iterm_id or f"T-{claude_id}", claude_id, cwd, WORKING, 1.0, prompt)


def entry(cwd, last_seen, order=0, prompt="", window="W"):
    return {
        "cwd": cwd,
        "last_prompt": prompt,
        "order": order,
        "window": window,
        "last_seen": last_seen,
    }


def test_record_stamps_live_sessions_in_order():
    live = [mk("a", "/p/x", "hi"), mk("b", "/p/y")]
    history = restore.record({}, live, now=100.0, windows={"T-a": "W1", "T-b": "W2"})
    assert history == {
        "a": entry("/p/x", 100.0, 0, "hi", "W1"),
        "b": entry("/p/y", 100.0, 1, window="W2"),
    }


def test_record_keeps_gone_sessions_and_skips_ones_without_claude_id():
    history = restore.record({"old": entry("/p/z", 50.0)}, [mk("")], now=100.0, windows={})
    assert history == {"old": entry("/p/z", 50.0)}


def test_record_forgets_sessions_older_than_a_week():
    week = 7 * 24 * 3600
    history = restore.record({"old": entry("/p/z", 1.0)}, [], 1.0 + week + 1, {})
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
    assert "a" in restore.record({}, [s], now=1.0, windows={})


def test_by_window_keeps_windows_apart_in_tab_order():
    chosen = [
        ("b2", entry("/p", 1.0, 3, window="B")),
        ("a1", entry("/p", 1.0, 0, window="A")),
        ("b1", entry("/p", 1.0, 2, window="B")),
        ("a2", entry("/p", 1.0, 1, window="A")),
    ]
    windows = restore.by_window(chosen)
    assert [[k for k, _ in w] for w in windows] == [["a1", "a2"], ["b1", "b2"]]


def test_by_window_puts_entries_from_before_windows_were_recorded_together():
    old = {"cwd": "/p", "last_prompt": "", "order": 0, "last_seen": 1.0}
    windows = restore.by_window([("x", old), ("y", {**old, "order": 1})])
    assert [[k for k, _ in w] for w in windows] == [["x", "y"]]


def test_by_window_puts_unknown_windows_with_old_entries():
    old = {"cwd": "/p", "last_prompt": "", "order": 0, "last_seen": 1.0}
    chosen = [("x", old), ("y", entry("/p", 1.0, 1, window="")), ("z", entry("/p", 1.0, 2))]
    windows = restore.by_window(chosen)
    assert [[k for k, _ in w] for w in windows] == [["x", "y"], ["z"]]


def test_stopped_newest_first_skips_running_and_week_old_sessions():
    week = 7 * 24 * 3600
    history = {
        "older": entry("/p", 500.0),
        "newer": entry("/p", 900.0),
        "running": entry("/p", 1000.0),
        "ancient": entry("/p", 1000.0 - week - 1),
    }
    stopped = restore.stopped_newest_first(history, {"running"}, now=1000.0)
    assert [k for k, _ in stopped] == ["newer", "older"]


def test_format_line_is_tab_delimited_with_id_first():
    line = restore.format_line("abc", entry("/p/corral", 40.0, prompt="fix\tthe\nbug"), now=160.0)
    assert line.split("\t")[0] == "abc"
    assert line.count("\t") == 1 and "\n" not in line
    assert "corral" in line and "2m" in line and "fix the bug" in line


def test_parse_choices_keeps_only_known_ids():
    history = {"a": entry("/p/a", 1.0), "b": entry("/p/b", 1.0)}
    chosen = restore.parse_choices("b\tjunk\nnope\tjunk\na\tjunk\n", history)
    assert [k for k, _ in chosen] == ["b", "a"]


def test_pick_opens_what_you_choose_without_asking(tmp_path, monkeypatch):
    from corral import pick

    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    now = restore.time.time()
    restore.save({"a": entry("/p/a", now - 60, window="A"), "b": entry("/p/b", now, 1, window="B")})
    monkeypatch.setattr(pick, "_fzf", lambda: "fzf")
    calls = fake_fzf(monkeypatch, returncode=0, stdout="b\tb ...\n")
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError))
    opened = []
    monkeypatch.setattr(restore, "open_windows", opened.append)
    assert restore.run(choose_from_history=True) == 0
    assert [[k for k, _ in w] for w in opened[0]] == [["b"]]
    argv, offered = calls[0]
    assert "--multi" in argv
    assert [line.split("\t")[0] for line in offered.splitlines()] == ["b", "a"]


def fake_fzf(monkeypatch, returncode, stdout):
    calls = []

    def run(argv, input, **_):
        calls.append((argv, input))
        return type("Result", (), {"returncode": returncode, "stdout": stdout})()

    monkeypatch.setattr(restore.subprocess, "run", run)
    return calls


def test_pick_cancelled_opens_nothing(tmp_path, monkeypatch):
    from corral import pick

    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    restore.save({"a": entry("/p/a", restore.time.time())})
    monkeypatch.setattr(pick, "_fzf", lambda: "fzf")
    fake_fzf(monkeypatch, returncode=130, stdout="")
    opened = []
    monkeypatch.setattr(restore, "open_windows", opened.append)
    assert restore.run(choose_from_history=True) == 0
    assert opened == []


def test_pick_with_only_week_old_history_skips_fzf(tmp_path, monkeypatch, capsys):
    from corral import pick

    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    restore.save({"a": entry("/p/a", restore.time.time() - restore.KEEP_SECONDS - 1)})
    monkeypatch.setattr(pick, "_fzf", lambda: "fzf")
    calls = fake_fzf(monkeypatch, returncode=0, stdout="")
    assert restore.run(choose_from_history=True) == 0
    assert calls == []
    assert "Nothing to restore." in capsys.readouterr().out


def test_pick_without_fzf_fails(tmp_path, monkeypatch, capsys):
    from corral import pick

    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    restore.save({"a": entry("/p/a", restore.time.time())})
    monkeypatch.setattr(pick, "_fzf", lambda: None)
    assert restore.run(choose_from_history=True) == 1
    assert "fzf not found" in capsys.readouterr().out


def test_restore_opens_one_window_per_old_window(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    restore.save(
        {"a": entry("/p/a", 100.0, 0, window="A"), "b": entry("/p/b", 100.0, 1, window="B")}
    )
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    opened = []
    monkeypatch.setattr(restore, "open_windows", opened.append)
    assert restore.run() == 0
    assert [[k for k, _ in w] for w in opened[0]] == [["a"], ["b"]]


def test_open_windows_starts_each_window_then_adds_its_tabs(monkeypatch):
    import asyncio
    import sys
    import types

    calls = []

    class Window:
        @staticmethod
        async def async_create(connection, command):
            calls.append(("window", command))
            return Window()

        async def async_create_tab(self, command):
            calls.append(("tab", command))

    async def async_get_app(connection):
        pass

    iterm2 = types.SimpleNamespace(
        Window=Window,
        async_get_app=async_get_app,
        run_until_complete=lambda main: asyncio.run(main(None)),
    )
    monkeypatch.setitem(sys.modules, "iterm2", iterm2)
    monkeypatch.setattr(restore, "tab_command", lambda claude_id, cwd, shell: claude_id)
    restore.open_windows(
        [[("a1", entry("/p", 1.0)), ("a2", entry("/p", 1.0, 1))], [("b1", entry("/p", 1.0, 2))]]
    )
    assert calls == [("window", "a1"), ("tab", "a2"), ("window", "b1")]
