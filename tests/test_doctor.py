import json

import pytest

from corral import control, doctor, launcher

HOOK = "/home/me/.local/bin/corral-hook"


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))


def settings_with(tmp_path, events):
    path = tmp_path / "settings.json"
    hooks = {e: [{"hooks": [{"type": "command", "command": HOOK}]}] for e in events}
    path.write_text(json.dumps({"hooks": hooks}))
    return path


def test_hook_events_match_what_install_merges():
    jq = doctor.HOOKS_JQ.read_text()
    assert set(doctor.hook_events(jq)) == {
        "SessionStart",
        "UserPromptSubmit",
        "PostToolUse",
        "Notification",
        "PermissionRequest",
        "Stop",
        "SessionEnd",
    }


def test_hooks_check_names_missing_events(tmp_path):
    events = ["SessionStart", "Stop"]
    ok, detail = doctor.check_hooks(settings_with(tmp_path, ["SessionStart"]), events)
    assert not ok and "Stop" in detail and "install.sh" in detail
    assert doctor.check_hooks(settings_with(tmp_path, events), events)[0]


def test_hooks_check_without_settings_file(tmp_path):
    ok, detail = doctor.check_hooks(tmp_path / "missing.json", ["Stop"])
    assert not ok and "missing.json" in detail


def test_hooks_check_with_a_malformed_settings_file(tmp_path):
    path = tmp_path / "settings.json"
    for text in ("not json", '{"hooks": []}', '{"hooks": {"Stop": ["x"]}}'):
        path.write_text(text)
        ok, detail = doctor.check_hooks(path, ["Stop"])
        assert not ok and "settings.json" in detail


def test_python_api_check():
    assert doctor.check_python_api(lambda key: "1")[0]
    ok, detail = doctor.check_python_api(lambda key: None)
    assert not ok and "Enable Python API" in detail


def test_hotkeys_check_names_unbound_functions():
    keymap = '{ "0x6a-0x100000" = { Action = 60; Text = "corral_next_waiting(session_id: id)"; }; }'
    ok, detail = doctor.check_hotkeys(lambda key: keymap)
    assert not ok and "corral_pick" in detail and "corral_next_waiting" not in detail
    everything = "corral_next_waiting corral_next_done corral_pick"
    assert doctor.check_hotkeys(lambda key: everything)[0]


def test_daemon_check(monkeypatch):
    monkeypatch.setattr(control, "version", lambda: "1.2.0")
    monkeypatch.setattr(control, "request", lambda msg: {"ok": True, "version": "1.2.0"})
    assert doctor.check_daemon()[0]

    def down(msg):
        raise control.Unavailable

    monkeypatch.setattr(control, "request", down)
    monkeypatch.setattr(launcher, "acquire", lambda: pytest.fail("took the daemon lock"))
    monkeypatch.setattr(doctor, "daemon_process", lambda: False)
    ok, detail = doctor.check_daemon()
    assert not ok and "next claude event" in detail
    monkeypatch.setattr(doctor, "daemon_process", lambda: True)
    ok, detail = doctor.check_daemon()
    assert not ok and "pkill" in detail  # an older daemon without the control socket


def test_daemon_check_flags_a_daemon_running_other_code(monkeypatch):
    monkeypatch.setattr(control, "version", lambda: "1.2.0")
    monkeypatch.setattr(control, "request", lambda msg: {"ok": True, "version": "1.1.0"})
    ok, detail = doctor.check_daemon()
    assert not ok and "runs corral 1.1.0, but 1.2.0 is installed" in detail and "pkill" in detail
    monkeypatch.setattr(control, "request", lambda msg: {"ok": True})  # 1.1.0 didn't say
    assert "runs an older corral" in doctor.check_daemon()[1]


def test_report_prints_each_check_and_fails_if_any_does(capsys):
    checks = [("hooks", lambda: (True, "")), ("daemon", lambda: (False, "not running"))]
    assert doctor.report(checks) == 1
    out = capsys.readouterr().out
    assert "✓ hooks" in out and "✗ daemon: not running" in out
    assert doctor.report(checks[:1]) == 0
