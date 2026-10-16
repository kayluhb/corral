import pytest

from corral import settings
from corral.settings import Settings


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setenv("CORRAL_CONFIG", str(path))
    return path


def test_defaults_when_no_file():
    assert settings.load() == Settings(group=False, theme="ranch", tab_colours=True)


def test_roundtrip():
    settings.save(Settings(group=True, theme="classic", tab_colours=False))
    assert settings.load() == Settings(group=True, theme="classic", tab_colours=False)


def test_bad_values_and_unknown_keys_fall_back_to_defaults(config):
    config.write_text('{"group": "yes", "theme": "disco", "tab_colours": false, "x": 1}')
    assert settings.load() == Settings(tab_colours=False)
    config.write_text("not json")
    assert settings.load() == Settings()


def test_cycle_moves_to_next_value_and_wraps():
    s = settings.cycle(Settings(), "theme")
    assert s.theme == "classic"
    assert settings.cycle(s, "theme").theme == "ranch"
    assert settings.cycle(Settings(), "group").group is True


def test_rows_show_labels_and_values():
    assert settings.rows(Settings()) == [
        ("Group by project", "off"),
        ("Theme", "ranch"),
        ("Tab colours", "on"),
    ]
