import json
import os
import subprocess
import sys

import pytest

from corral import hook, store
from corral.state import DONE, IDLE, WORKING

ITERM = "w0t1p0:0F3A-99"


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state"


def ev(name, **extra):
    return {"hook_event_name": name, "session_id": "c1", "cwd": "/x/proj", **extra}


def test_iterm_id_from_env():
    assert hook.iterm_id_from_env(ITERM) == "0F3A-99"
    assert hook.iterm_id_from_env("0F3A-99") == "0F3A-99"
    assert hook.iterm_id_from_env(None) is None
    assert hook.iterm_id_from_env("") is None
    assert hook.iterm_id_from_env("w0:../../etc") is None


def test_full_lifecycle():
    hook.handle(ev("SessionStart"), ITERM, 1.0)
    assert store.read("0F3A-99").state == IDLE
    hook.handle(ev("UserPromptSubmit", prompt="go"), ITERM, 2.0)
    assert store.read("0F3A-99").state == WORKING
    hook.handle(ev("Stop"), ITERM, 3.0)
    assert store.read("0F3A-99").state == DONE
    hook.handle(ev("SessionEnd"), ITERM, 4.0)
    assert store.read("0F3A-99") is None


def test_unchanged_state_does_not_rewrite(tmp_state):
    hook.handle(ev("UserPromptSubmit", prompt="go"), ITERM, 2.0)
    path = tmp_state / "0F3A-99.json"
    before = path.stat().st_mtime_ns
    os.utime(path, ns=(before - 10_000_000, before - 10_000_000))
    stamped = path.stat().st_mtime_ns
    hook.handle(ev("PostToolUse"), ITERM, 3.0)
    assert path.stat().st_mtime_ns == stamped


def test_no_iterm_env_is_noop(tmp_state):
    hook.handle(ev("SessionStart"), None, 1.0)
    assert not tmp_state.exists()


def test_ignored_event_is_noop(tmp_state):
    hook.handle(ev("PreCompact"), ITERM, 1.0)
    assert not tmp_state.exists()


def iterm_env(**extra):
    return {**os.environ, "TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": ITERM, **extra}


def run_hook(stdin, env):
    return subprocess.run(
        [sys.executable, "-m", "corral.hook"],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize("stdin", ["", "not json", "[1,2]", "null"])
def test_main_survives_bad_stdin(stdin, tmp_state):
    r = run_hook(stdin, iterm_env())
    assert r.returncode == 0
    assert r.stdout == ""
    assert not tmp_state.exists()


def test_main_end_to_end(tmp_state):
    r = run_hook(json.dumps(ev("UserPromptSubmit", prompt="hello")), iterm_env())
    assert r.returncode == 0 and r.stdout == ""
    data = json.loads((tmp_state / "0F3A-99.json").read_text())
    assert data["state"] == WORKING and data["last_prompt"] == "hello"


def test_main_outside_iterm(tmp_state):
    env = {k: v for k, v in os.environ.items() if k != "ITERM_SESSION_ID"}
    r = run_hook(json.dumps(ev("SessionStart")), env)
    assert r.returncode == 0
    assert not tmp_state.exists()


@pytest.mark.parametrize("term_program", ["tmux", "vscode", ""])
def test_main_ignores_inherited_iterm_id_in_other_terminals(term_program, tmp_state):
    r = run_hook(json.dumps(ev("SessionStart")), iterm_env(TERM_PROGRAM=term_program))
    assert r.returncode == 0
    assert not tmp_state.exists()


def test_idle_prompt_clears_interrupted_working():
    hook.handle(ev("UserPromptSubmit", prompt="go"), ITERM, 1.0)
    hook.handle(ev("Notification", notification_type="idle_prompt"), ITERM, 70.0)
    assert store.read("0F3A-99").state == IDLE
