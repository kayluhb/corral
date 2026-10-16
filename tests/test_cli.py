import sys

from corral import cli, restore


def test_bare_corral_runs_restore(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["corral"])
    monkeypatch.setattr(restore, "run", lambda: calls.append(1) or 0)
    try:
        cli.main()
    except SystemExit as exit:
        assert exit.code == 0
    assert calls == [1]
