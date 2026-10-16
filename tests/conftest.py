import pytest


@pytest.fixture(autouse=True)
def no_daemon_autostart(monkeypatch):
    # The hook starts the real iTerm daemon otherwise (also in hook subprocess tests).
    monkeypatch.setenv("CORRAL_NO_AUTOSTART", "1")


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    # Never read the real ~/.config/corral/settings.json.
    monkeypatch.setenv("CORRAL_CONFIG", str(tmp_path / "corral-settings.json"))
