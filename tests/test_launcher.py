import pytest

from corral import hook, launcher


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.delenv("CORRAL_NO_AUTOSTART")
    monkeypatch.setattr(launcher, "spawn", lambda: calls.append(1))
    return calls


def test_not_running_when_lock_free():
    assert launcher.running() is False
    assert launcher.running() is False  # checking doesn't leave the lock held


def test_running_while_daemon_holds_lock():
    fd = launcher.acquire()
    assert fd is not None
    assert launcher.running() is True
    assert launcher.acquire() is None  # a second daemon can't start


def test_ensure_running_spawns_when_not_running(spawned):
    launcher.ensure_running()
    assert spawned == [1]


def test_ensure_running_leaves_running_daemon_alone(spawned):
    fd = launcher.acquire()
    assert fd is not None
    launcher.ensure_running()
    assert spawned == []


def test_autostart_can_be_disabled(spawned, monkeypatch):
    monkeypatch.setenv("CORRAL_NO_AUTOSTART", "1")
    launcher.ensure_running()
    assert spawned == []


def test_hook_starts_daemon_for_iterm_sessions_only(spawned):
    ev = {"hook_event_name": "UserPromptSubmit", "session_id": "c1", "cwd": "/x"}
    hook.handle(ev, None, 1.0)
    assert spawned == []
    hook.handle(ev, "w0t0p0:ABC-1", 1.0)
    assert spawned == [1]
