import sys

from corral import cli, commands, restore


def test_bare_corral_runs_restore(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["corral"])
    monkeypatch.setattr(restore, "run", lambda: calls.append(1) or 0)
    try:
        cli.main()
    except SystemExit as exit:
        assert exit.code == 0
    assert calls == [1]


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["corral", *argv])
    try:
        cli.main()
    except SystemExit as exit:
        return exit.code


def test_list_wait_and_send_reach_their_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(commands, "list_sessions", lambda as_json: calls.append(as_json) or 0)
    monkeypatch.setattr(commands, "wait", lambda *a, **kw: calls.append((a, kw)) or 0)
    monkeypatch.setattr(commands, "send", lambda *a, **kw: calls.append((a, kw)) or 0)
    assert run_cli(monkeypatch, "list", "--json") == 0
    assert run_cli(monkeypatch, "wait", "lasso", "--until", "done", "--timeout", "5") == 0
    assert run_cli(monkeypatch, "send", "lasso", "run", "the tests", "--wait") == 0
    assert calls == [
        True,
        (("lasso",), {"until": {"done"}, "timeout": 5.0}),
        (("lasso", "run the tests"), {"wait_until": commands.STOPPED, "timeout": None}),
    ]


def test_wait_defaults_to_until_stopped(monkeypatch):
    calls = []
    monkeypatch.setattr(commands, "wait", lambda *a, **kw: calls.append(kw) or 0)
    run_cli(monkeypatch, "wait", "lasso")
    assert calls == [{"until": commands.STOPPED, "timeout": None}]


def test_new_runs_in_the_current_folder(monkeypatch, tmp_path):
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setattr(commands, "new", lambda *a: calls.append(a) or 0)
    assert run_cli(monkeypatch, "new", "fix-auth", "fix", "the", "login") == 0
    assert calls == [
        ("fix-auth", "fix the login", str(tmp_path), "/bin/bash", commands.open_tab_next_to_you)
    ]


def test_doctor_and_explain(monkeypatch):
    from corral import doctor

    calls = []
    monkeypatch.setattr(doctor, "run", lambda: calls.append("doctor") or 1)
    monkeypatch.setattr(commands, "explain", lambda target: calls.append(target) or 0)
    assert run_cli(monkeypatch, "doctor") == 1
    assert run_cli(monkeypatch, "explain", "lasso") == 0
    assert calls == ["doctor", "lasso"]


def test_send_dash_reads_the_prompt_from_stdin(monkeypatch):
    import io

    calls = []
    monkeypatch.setattr(commands, "send", lambda *a, **kw: calls.append(a) or 0)
    monkeypatch.setattr(sys, "stdin", io.StringIO("line one\nline two\n"))
    assert run_cli(monkeypatch, "send", "lasso", "-") == 0
    assert calls == [("lasso", "line one\nline two\n")]
