from corral import pick
from corral.state import WAITING, Session


def test_age():
    assert pick.age(5) == "5s"
    assert pick.age(125) == "2m"
    assert pick.age(7300) == "2h"
    assert pick.age(200000) == "2d"
    assert pick.age(-3) == "0s"


def test_format_line_is_tab_delimited_with_id_first():
    s = Session("ID-1", "c", "/p/corral", WAITING, 100.0, "fix\tthe\nbug")
    line = pick.format_line(s, 160.0)
    assert line.split("\t")[0] == "ID-1"
    assert line.count("\t") == 1
    assert "\n" not in line
    assert "✋" in line and "corral" in line and "1m" in line and "fix the bug" in line


def test_parse_choice():
    assert pick.parse_choice("ID-1\t✋ corral ...\n") == "ID-1"
    assert pick.parse_choice("") is None
    assert pick.parse_choice("../x\tjunk") is None


def test_run_lists_only_the_given_sessions(tmp_path, monkeypatch):
    from corral import store

    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    store.write(Session("ID-1", "c", "/p/mine", WAITING, 1.0))
    store.write(Session("ID-2", "c", "/p/elsewhere", WAITING, 1.0))
    seen = {}

    def fake_run(cmd, input, **kwargs):
        seen["input"] = input
        return type("Result", (), {"returncode": 1, "stdout": ""})()

    monkeypatch.setattr(pick, "_fzf", lambda: "fzf")
    monkeypatch.setattr(pick.subprocess, "run", fake_run)
    pick.run(tmp_path / "out", only={"ID-1"})
    assert "mine" in seen["input"] and "elsewhere" not in seen["input"]
