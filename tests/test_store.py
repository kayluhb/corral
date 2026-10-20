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


@pytest.mark.parametrize(
    "body",
    [
        '{"iterm_id":123,"claude_session_id":"c","cwd":"/","state":"done","since":0}',
        '{"iterm_id":"X","claude_session_id":"c","cwd":"/","state":"done","since":null}',
        '{"iterm_id":"X","claude_session_id":"c","cwd":"/","state":"done","since":"1"}',
        '{"iterm_id":"X","claude_session_id":"c","cwd":"/","state":"done","since":true}',
        '{"iterm_id":"X","claude_session_id":5,"cwd":"/","state":"done","since":0}',
        '{"iterm_id":"X","claude_session_id":"c","cwd":"/","state":["done"],"since":0}',
        '{"iterm_id":"X","claude_session_id":"c","cwd":"/","state":"done","since":0,'
        '"last_prompt":7}',
        '{"iterm_id":"X","claude_session_id":"c","cwd":"/","state":"waiting","since":0,'
        '"waiting_agent":7}',
    ],
)
def test_load_all_skips_wrong_field_types(tmp_state, body):
    store.write(s("GOOD"))
    (tmp_state / "X.json").write_text(body)
    assert [x.iterm_id for x in store.load_all()] == ["GOOD"]


def test_extra_fields_from_other_versions_are_ignored(tmp_state):
    tmp_state.mkdir(parents=True, exist_ok=True)
    body = '{"iterm_id": "A", "claude_session_id": "c", "cwd": "/p", "state": "done",'
    (tmp_state / "A.json").write_text(body + ' "since": 1.0, "tool": "Bash"}')
    assert store.read("A") == Session("A", "c", "/p", DONE, 1.0)


def test_old_file_without_waiting_agent_loads_as_main_agent(tmp_state):
    tmp_state.mkdir(parents=True, exist_ok=True)
    body = '{"iterm_id": "A", "claude_session_id": "c", "cwd": "/p", "state": "waiting",'
    (tmp_state / "A.json").write_text(body + ' "since": 1.0, "last_prompt": ""}')
    assert store.read("A") == Session("A", "c", "/p", "waiting", 1.0, "", None)


def test_waiting_agent_roundtrips():
    session = Session("ABC-1", "c1", "/x/p", "waiting", 3.0, "hi", "sub1")
    store.write(session)
    assert store.read("ABC-1") == session
