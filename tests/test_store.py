import pytest

from corral import store
from corral.state import DONE, Session


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setenv("CORRAL_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state"


def s(iterm_id="ABC-1"):
    return Session(iterm_id, "c1", "/x/p", DONE, 3.0, "hi")


def test_roundtrip():
    store.write(s())
    assert store.read("ABC-1") == s()


def test_read_missing_is_none():
    assert store.read("NOPE") is None


def test_delete_and_delete_missing():
    store.write(s())
    store.delete("ABC-1")
    store.delete("ABC-1")
    assert store.read("ABC-1") is None


def test_valid_id_rejects_path_tricks():
    assert store.valid_id("0F3A-99")
    for bad in ("", "../x", "a/b", "a b", "x.json"):
        assert not store.valid_id(bad)


def test_write_rejects_invalid_id():
    with pytest.raises(ValueError):
        store.write(s("../evil"))


def test_load_all_skips_corrupt_and_unknown_state(tmp_state):
    store.write(s("GOOD"))
    (tmp_state / "TRUNC.json").write_text('{"iterm_id": "TRU')
    (tmp_state / "LIST.json").write_text("[1, 2]")
    (tmp_state / "BADSTATE.json").write_text(
        '{"iterm_id":"BADSTATE","claude_session_id":"c","cwd":"/","state":"weird","since":0}'
    )
    (tmp_state / "notes.txt").write_text("ignore me")
    assert [x.iterm_id for x in store.load_all()] == ["GOOD"]


def test_load_all_empty_when_dir_missing():
    assert store.load_all() == []


def test_write_leaves_no_temp_files(tmp_state):
    store.write(s())
    assert sorted(p.name for p in tmp_state.iterdir()) == ["ABC-1.json"]
