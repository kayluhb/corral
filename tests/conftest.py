import pytest


@pytest.fixture(autouse=True)
def no_daemon_autostart(monkeypatch):
    # The hook starts the real iTerm daemon otherwise (also in hook subprocess tests).
    monkeypatch.setenv("CORRAL_NO_AUTOSTART", "1")
