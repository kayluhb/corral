import json
import subprocess
from pathlib import Path

JQ = Path(__file__).parent.parent / "scripts" / "merge-hooks.jq"
CMD = "/Users/x/.local/bin/corral-hook"
EVENTS = ["SessionStart", "UserPromptSubmit", "PostToolUse", "Notification", "Stop", "SessionEnd"]
NOTIFICATION_MATCHER = (
    "permission_prompt|elicitation_dialog|elicitation_url_dialog|agent_needs_input|idle_prompt"
)


def merge(settings: dict) -> dict:
    r = subprocess.run(
        ["jq", "--arg", "cmd", CMD, "-f", str(JQ)],
        input=json.dumps(settings),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(r.stdout)


def corral_entries(settings, event):
    return [
        e
        for e in settings["hooks"].get(event, [])
        if any(h.get("command") == CMD for h in e.get("hooks", []))
    ]


def test_adds_all_events_to_empty_settings():
    out = merge({})
    for ev in EVENTS:
        assert len(corral_entries(out, ev)) == 1
    (notif,) = corral_entries(out, "Notification")
    assert notif["matcher"] == NOTIFICATION_MATCHER


def test_preserves_existing_hooks_and_keys():
    existing = {
        "model": "opus",
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "mempalace hook run"}]}],
            "PreCompact": [{"hooks": [{"type": "command", "command": "mempalace x"}]}],
        },
    }
    out = merge(existing)
    assert out["model"] == "opus"
    assert out["hooks"]["PreCompact"] == existing["hooks"]["PreCompact"]
    assert out["hooks"]["SessionStart"][0] == existing["hooks"]["SessionStart"][0]
    assert len(out["hooks"]["SessionStart"]) == 2


def test_idempotent():
    once = merge({})
    assert merge(once) == once


def test_upgrades_stale_corral_entry_and_keeps_others():
    old = {
        "hooks": {
            "Notification": [
                {"hooks": [{"type": "command", "command": "other"}]},
                {"matcher": "permission_prompt", "hooks": [{"type": "command", "command": CMD}]},
            ]
        }
    }
    out = merge(old)
    (notif,) = corral_entries(out, "Notification")
    assert notif["matcher"] == NOTIFICATION_MATCHER
    assert out["hooks"]["Notification"][0] == old["hooks"]["Notification"][0]
