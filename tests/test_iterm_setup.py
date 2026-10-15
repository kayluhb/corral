import base64

from iterm2 import api_pb2

from corral import iterm_setup

EMPTY_LAYOUT = {"components": [], "advanced configuration": {"algorithm": 0}}
OTHER_COMPONENT = {"class": "iTermStatusBarClockComponent", "configuration": {"knobs": {}}}
SHIFT_ENTER = {"0xd-0x20000-0x24": {"Action": 12, "Text": "\\n", "Version": 1}}


def decode(entry):
    raw = base64.b64decode(entry["configuration"]["registration request v2"])
    return api_pb2.RPCRegistrationRequest.FromString(raw)


def test_component_entry_matches_daemon_registration():
    entry = iterm_setup.component_entry()
    assert entry["class"] == "iTermStatusBarRPCProvidedTextComponent"
    assert entry["configuration"]["knobs"] == {}
    request = decode(entry)
    assert request.name == "corral_status"
    assert [a.name for a in request.arguments] == ["knobs"]
    assert request.status_bar_component_attributes.unique_identifier == "com.calebbrown.corral"


def test_add_component_appends_and_keeps_existing():
    layout = {**EMPTY_LAYOUT, "components": [OTHER_COMPONENT]}
    result = iterm_setup.add_component(layout)
    assert result["components"][0] == OTHER_COMPONENT
    assert decode(result["components"][1]).name == "corral_status"
    assert result["advanced configuration"] == {"algorithm": 0}
    assert layout["components"] == [OTHER_COMPONENT]  # input not mutated


GIT = {"class": "iTermStatusBarGitComponent", "configuration": {"knobs": {}}}


def test_add_component_adds_git_after_corral():
    result = iterm_setup.add_component(EMPTY_LAYOUT)
    assert decode(result["components"][0]).name == "corral_status"
    assert result["components"][1] == GIT


def test_add_component_keeps_an_existing_git_item():
    layout = {**EMPTY_LAYOUT, "components": [GIT]}
    result = iterm_setup.add_component(layout)
    assert [c["class"] for c in result["components"]].count(GIT["class"]) == 1


def test_add_component_is_idempotent():
    once = iterm_setup.add_component(EMPTY_LAYOUT)
    assert iterm_setup.add_component(once) == once


def test_add_component_handles_missing_layout():
    assert len(iterm_setup.add_component(None)["components"]) == 2


def test_add_bindings_keeps_existing_and_adds_three():
    keymap, skipped = iterm_setup.add_bindings(SHIFT_ENTER)
    assert keymap["0xd-0x20000-0x24"] == SHIFT_ENTER["0xd-0x20000-0x24"]
    texts = sorted(v["Text"] for v in keymap.values() if v["Action"] == 60)
    assert texts == [
        "corral_next_done(session_id: id)",
        "corral_next_waiting(session_id: id)",
        "corral_pick(session_id: id)",
    ]
    assert skipped == []


def test_add_bindings_is_idempotent():
    once, _ = iterm_setup.add_bindings(SHIFT_ENTER)
    twice, skipped = iterm_setup.add_bindings(once)
    assert twice == once and skipped == []


def test_add_bindings_leaves_function_bound_elsewhere():
    mine = {"0x6b-0x100000": {"Action": 60, "Text": "corral_pick(session_id: id)"}}
    keymap, _ = iterm_setup.add_bindings(mine)
    picks = [k for k, v in keymap.items() if v["Text"] == "corral_pick(session_id: id)"]
    assert picks == ["0x6b-0x100000"]


def test_add_bindings_never_overwrites_a_taken_key():
    key = next(iter(iterm_setup.BINDINGS))
    taken = {key: {"Action": 12, "Text": "x"}}
    keymap, skipped = iterm_setup.add_bindings(taken)
    assert keymap[key] == {"Action": 12, "Text": "x"}
    assert len(skipped) == 1
