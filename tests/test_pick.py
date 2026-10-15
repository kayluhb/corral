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
    assert "🐄" in line and "corral" in line and "1m" in line and "fix the bug" in line


def test_parse_choice():
    assert pick.parse_choice("ID-1\t🐄 corral ...\n") == "ID-1"
    assert pick.parse_choice("") is None
    assert pick.parse_choice("../x\tjunk") is None
