"""One-time iTerm setup over the Python API: corral status bar item + hotkeys.

Run with `uv run python -m corral.iterm_setup` (install.sh does this). Idempotent: it
only adds what's missing and never replaces a hotkey that's already taken.
"""

from __future__ import annotations

import base64
import copy
import json

import iterm2
from iterm2 import rpc
from iterm2.binding import BindingAction, KeyBinding
from iterm2.keyboard import Keycode, Modifier
from iterm2.notifications import RPC_ROLE_STATUS_BAR_COMPONENT

from corral import daemon

COMPONENT_CLASS = "iTermStatusBarRPCProvidedTextComponent"
GIT_COMPONENT = {"class": "iTermStatusBarGitComponent", "configuration": {"knobs": {}}}
REQUEST_KEY = "registration request v2"
HYPER = [Modifier.CONTROL, Modifier.OPTION, Modifier.COMMAND]
_KEYS = [  # ⌃⌥⌘W / ⌃⌥⌘D / ⌃⌥⌘P
    (ord("w"), Keycode.ANSI_W, "corral_next_waiting(session_id: id)", "⌃⌥⌘W"),
    (ord("d"), Keycode.ANSI_D, "corral_next_done(session_id: id)", "⌃⌥⌘D"),
    (ord("p"), Keycode.ANSI_P, "corral_pick(session_id: id)", "⌃⌥⌘P"),
]


def _binding(char: int, keycode: Keycode, invocation: str) -> KeyBinding:
    action = BindingAction.INVOKE_SCRIPT_FUNCTION
    return KeyBinding(char, HYPER, keycode, action, invocation, None, None)


BINDINGS = {b.key: b.encode for b in (_binding(c, k, i) for c, k, i, _ in _KEYS)}
LABELS = {i: label for _, _, i, label in _KEYS}


def component_entry() -> dict:
    request = iterm2.api_pb2.RPCRegistrationRequest()
    request.name = daemon.STATUS_FUNCTION
    request.arguments.add().name = "knobs"
    request.arguments.add().name = "session_id"
    default = request.defaults.add()
    default.name, default.path = "session_id", "id"
    request.role = RPC_ROLE_STATUS_BAR_COMPONENT
    daemon.status_component().set_fields_in_proto(request.status_bar_component_attributes)
    encoded = base64.b64encode(request.SerializeToString()).decode()
    return {"class": COMPONENT_CLASS, "configuration": {REQUEST_KEY: encoded, "knobs": {}}}


def _is_corral(component: dict) -> bool:
    encoded = component.get("configuration", {}).get(REQUEST_KEY)
    if component.get("class") != COMPONENT_CLASS or not encoded:
        return False
    request = iterm2.api_pb2.RPCRegistrationRequest.FromString(base64.b64decode(encoded))
    return request.status_bar_component_attributes.unique_identifier == daemon.COMPONENT_ID


def add_component(layout: dict | None) -> dict:
    """Add corral's item (refreshing a stale one) and iTerm's git item if missing."""
    layout = copy.deepcopy(layout) if layout else {"components": []}
    components = layout.setdefault("components", [])
    corral = [i for i, c in enumerate(components) if _is_corral(c)]
    for i in corral:
        components[i] = component_entry()
    if not corral:
        components.append(component_entry())
    if not any(c.get("class") == GIT_COMPONENT["class"] for c in components):
        components.append(copy.deepcopy(GIT_COMPONENT))
    return layout


def add_bindings(keymap: dict) -> tuple[dict, list[str]]:
    """Return (new keymap, invocations skipped because their key is taken)."""
    keymap = copy.deepcopy(keymap)
    bound = {v.get("Text") for v in keymap.values() if v.get("Action") == 60}
    skipped = []
    for key, entry in BINDINGS.items():
        if entry["Text"] in bound:
            continue
        if key in keymap:
            skipped.append(entry["Text"])
            continue
        keymap[key] = entry
    return keymap, skipped


async def _setup(connection: iterm2.Connection) -> None:
    partial = await iterm2.PartialProfile.async_get_default(connection)
    profile = await partial.async_get_full_profile()
    await profile._async_simple_set(  # no public setter for the layout in iterm2 2.30
        "Status Bar Layout", add_component(profile._simple_get("Status Bar Layout"))
    )
    await profile.async_set_status_bar_enabled(True)
    print(f"status bar: corral is in profile {profile.name!r}")

    proto = await rpc.async_get_preference(connection, "GlobalKeyMap")
    raw = proto.preferences_response.results[0].get_preference_result.json_value
    keymap, skipped = add_bindings(json.loads(raw) if raw else {})
    await rpc.async_set_preference(connection, "GlobalKeyMap", json.dumps(keymap))
    for invocation, label in LABELS.items():
        note = "  (key already taken — bind it yourself)" if invocation in skipped else ""
        print(f"hotkey: {label}  {invocation}{note}")


def main() -> None:
    iterm2.run_until_complete(_setup)


if __name__ == "__main__":
    main()
