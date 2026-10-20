import json
import shlex
import time

import pytest

from corral import commands, control, launcher, store
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


def test_resolve_a_hex_like_project_name_is_ambiguous_with_an_id_prefix():
    # "bbbb" is a project here, but also the start of B's id: don't silently pick either.
    sessions = [put(A, IDLE, "/p/bbbb"), put(B, IDLE, "/p/lasso")]
    with pytest.raises(commands.CommandError, match="matches 2 sessions"):
        commands.resolve(sessions, "bbbb")


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
    captured = capsys.readouterr()
    assert captured.out == "" and "no claude sessions" in captured.err  # stdout stays parseable
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
    assert clock.t == pytest.approx(100.6)  # a 0.1s poll to see it start, then 0.5s


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
    assert clock.t == pytest.approx(100.6)  # a 0.1s poll to see it start, then 0.5s


def test_list_shows_branches(tmp_path, capsys):
    repo = tmp_path / "hydrogen"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    put(A, IDLE, str(repo))
    commands.list_sessions(as_json=False)
    assert "hydrogen (main)" in capsys.readouterr().out
    commands.list_sessions(as_json=True)
    assert json.loads(capsys.readouterr().out)[0]["branch"] == "main"


# new


def make_repo(root):
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return root


def run_new(name, prompt, repo, clock):
    opened = []

    def open_tab(command):
        opened.append(shlex.split(command))
        return A

    code = commands.new(name, prompt, str(repo), "/bin/zsh", open_tab, clock.now, clock.sleep)
    return code, opened


def test_new_opens_a_worktree_claude_and_prints_its_id(tmp_path, capsys):
    repo = make_repo(tmp_path / "my repo")
    started = [lambda: put(A, IDLE, str(repo)), lambda: put(A, WORKING, str(repo), since=101.0)]
    clock = Clock(started)  # its SessionStart hook runs, then its prompt's turn starts
    prompt = "-d: don't break the regex \\d+"  # starts with -, so it must follow --
    code, opened = run_new("fix-auth", prompt, repo, clock)
    assert code == 0
    assert capsys.readouterr().out == f"{A}\n"
    [(shell, flags, inner)] = opened
    assert (shell, flags) == ("/bin/zsh", "-lic")
    # iTerm rewrites backslashes in a tab's command, so the prompt travels in a file.
    assert "\\" not in inner and "regex" not in inner
    [prompt_file] = store.state_dir().glob("prompt-*")
    assert prompt_file.read_text() == prompt
    assert prompt_file.stat().st_mode & 0o077 == 0
    quoted = shlex.quote(str(prompt_file))
    assert inner == (
        f"cd '{repo}' && claude --worktree fix-auth -- \"$(cat {quoted}; rm -f {quoted})\""
        "; exec /bin/zsh -l"
    )


def test_new_without_a_prompt(tmp_path):
    repo = make_repo(tmp_path / "proj")
    _, opened = run_new("x", "", repo, Clock([lambda: put(A, IDLE, str(repo))]))
    assert opened[0][2] == f"cd {repo} && claude --worktree x; exec /bin/zsh -l"


def test_new_needs_a_git_repo(tmp_path, capsys):
    code = commands.new("x", "", str(tmp_path), "/bin/zsh", lambda c: A, time.time, time.sleep)
    assert code == 2
    assert "not in a git repository" in capsys.readouterr().err


def test_new_still_prints_the_id_when_claude_is_slow_to_start(tmp_path, capsys):
    repo = make_repo(tmp_path / "proj")
    code, _ = run_new("x", "", repo, Clock())
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == f"{A}\n" and "hasn't started" in captured.err


# explain


def test_explain_says_iterm_supplies_the_state(monkeypatch, capsys):
    put(A, WAITING, "/p/hydrogen", since=40.0, claude="c-9", prompt="fix it")
    reply = {
        "ok": True,
        "tab_open": True,
        "iterm_status": WAITING,
        "focused": False,
        "tab_colour": WAITING,
    }
    monkeypatch.setattr(control, "request", lambda msg: reply)
    assert commands.explain("hydrogen", now=lambda: 100.0) == 0
    out = capsys.readouterr().out
    assert A in out and "✋ waiting for 1m" in out
    assert "iTerm's Claude Code integration" in out
    assert "claude --resume c-9" in out and "fix it" in out
    assert "red" in out


def test_explain_without_a_daemon_says_the_source_is_unknown(monkeypatch, capsys):
    put(A, WORKING)

    def down(msg):
        raise control.Unavailable

    monkeypatch.setattr(control, "request", down)
    monkeypatch.setattr(launcher, "acquire", lambda: pytest.fail("took the daemon lock"))
    assert commands.explain(A) == 0
    out = capsys.readouterr().out
    assert "unknown" in out and "corral doctor" in out


def test_explain_says_hooks_supply_the_state_when_iterm_reports_nothing(monkeypatch, capsys):
    put(A, WORKING)
    reply = {
        "ok": True,
        "tab_open": True,
        "iterm_status": None,
        "focused": True,
        "tab_colour": None,
    }
    monkeypatch.setattr(control, "request", lambda msg: reply)
    commands.explain(A)
    out = capsys.readouterr().out
    assert "corral's hooks" in out and "you're looking at it" in out and "no colour" in out


def test_explain_unknown_target(capsys):
    assert commands.explain("nope") == 2


def test_wait_after_needs_the_turn_to_start_first():
    # iTerm still reporting the last turn's done gets written with a fresh since.
    put(A, DONE, since=50.0)
    clock = Clock([lambda: put(A, DONE, since=100.5)])
    assert wait(A, clock, after=100.0) == 2  # never started within START_TURN


def test_send_wait_refuses_a_busy_session(monkeypatch, capsys):
    put(A, WORKING)
    sent = []
    monkeypatch.setattr(control, "request", lambda msg: sent.append(msg) or {"ok": True})
    assert commands.send(A, "go", wait_until=commands.STOPPED) == 2
    assert sent == [] and "corral wait" in capsys.readouterr().err


def test_open_tab_reports_an_unreachable_iterm(monkeypatch):
    import iterm2

    def refuse(coro):
        raise SystemExit(1)  # what iterm2 does on ConnectionRefusedError

    monkeypatch.setattr(iterm2, "run_until_complete", refuse)
    with pytest.raises(commands.CommandError, match="iTerm"):
        commands.open_tab_next_to_you("true")


def test_new_with_a_prompt_returns_once_its_turn_starts(tmp_path):
    # Otherwise a `corral wait` right after would see claude's start-up idle and return.
    repo = make_repo(tmp_path / "proj")
    clock = Clock(
        [
            lambda: put(A, IDLE, str(repo), since=100.1),
            lambda: None,
            lambda: put(A, WORKING, str(repo), since=100.3),
        ]
    )
    code, _ = run_new("x", "go", repo, clock)
    assert code == 0
    assert store.read(A).state == WORKING and clock.t >= 100.3


def test_new_removes_the_prompt_file_when_the_tab_does_not_open(tmp_path, capsys):
    repo = make_repo(tmp_path / "proj")

    def fail(command):
        raise commands.CommandError("iTerm didn't open the tab")

    code = commands.new("x", "go", str(repo), "/bin/zsh", fail, time.time, time.sleep)
    assert code == 2 and "didn't open" in capsys.readouterr().err
    assert list(store.state_dir().glob("prompt-*")) == []


def test_new_with_a_prompt_fails_when_its_turn_never_starts(tmp_path, capsys):
    repo = make_repo(tmp_path / "proj")
    code, _ = run_new("x", "go", repo, Clock([lambda: put(A, IDLE, str(repo), since=100.1)]))
    assert code == 2 and "didn't start a turn" in capsys.readouterr().err


def test_explain_reports_a_daemon_error(monkeypatch, capsys):
    put(A, WORKING)
    monkeypatch.setattr(control, "request", lambda msg: {"error": "RuntimeError('boom')"})
    assert commands.explain(A) == 0
    out = capsys.readouterr().out
    assert "daemon failed: RuntimeError('boom')" in out and "tab:" not in out


def test_explain_a_closed_tab(monkeypatch, capsys):
    put(A, DONE)
    reply = {"ok": True, "tab_open": False, "iterm_status": None, "tab_colour": DONE}
    monkeypatch.setattr(control, "request", lambda msg: reply)
    commands.explain(A)
    assert "tab:     closed (the state file is left over); corral gave it green" in (
        capsys.readouterr().out
    )


def test_explain_strips_terminal_escapes_from_the_folder(monkeypatch, capsys):
    put(A, IDLE, cwd="/p/evil\x1b]0;pwned\x07")
    monkeypatch.setattr(control, "request", lambda msg: {"ok": True})
    commands.explain(A)
    assert "\x1b" not in capsys.readouterr().out
