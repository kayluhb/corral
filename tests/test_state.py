from corral import state
from corral.state import DONE, IDLE, WAITING, WORKING, Session


def mk(iterm_id="A", st=IDLE, since=0.0, cwd="/x/proj", prompt=""):
    return Session(iterm_id, "c1", cwd, st, since, prompt)


# --- target_state ---------------------------------------------------------


def test_target_state_lifecycle():
    assert state.target_state({"hook_event_name": "SessionStart"}) == IDLE
    assert state.target_state({"hook_event_name": "UserPromptSubmit"}) == WORKING
    assert state.target_state({"hook_event_name": "PostToolUse"}) == WORKING
    assert state.target_state({"hook_event_name": "Stop"}) == DONE
    assert state.target_state({"hook_event_name": "SessionEnd"}) == state.DELETE


def test_target_state_notifications():
    for t in (
        "permission_prompt",
        "elicitation_dialog",
        "elicitation_url_dialog",
        "agent_needs_input",
    ):
        ev = {"hook_event_name": "Notification", "notification_type": t}
        assert state.target_state(ev) == WAITING
    ev = {"hook_event_name": "Notification", "notification_type": "idle_prompt"}
    assert state.target_state(ev) == IDLE
    ev = {"hook_event_name": "Notification", "notification_type": "auth_success"}
    assert state.target_state(ev) is None


def test_target_state_unknown_event_ignored():
    assert state.target_state({"hook_event_name": "PreCompact"}) is None
    assert state.target_state({}) is None


def test_subagent_lifecycle_events_ignored_but_notifications_kept():
    for name in ("SessionStart", "Stop", "SessionEnd"):
        assert state.target_state({"hook_event_name": name, "agent_id": "x"}) is None
    ev = {
        "hook_event_name": "Notification",
        "notification_type": "permission_prompt",
        "agent_id": "x",
    }
    assert state.target_state(ev) == WAITING


# --- transition ------------------------------------------------------------


def test_transition_new_session():
    ev = {"hook_event_name": "SessionStart", "session_id": "c9", "cwd": "/p/app"}
    s = state.transition(None, ev, "A", IDLE, 10.0)
    assert s == Session("A", "c9", "/p/app", IDLE, 10.0, "")


def test_transition_keeps_since_when_state_unchanged():
    prev = mk(st=WORKING, since=5.0)
    ev = {"hook_event_name": "PostToolUse", "session_id": "c1", "cwd": "/x/proj"}
    assert state.transition(prev, ev, "A", WORKING, 9.0).since == 5.0


def test_transition_updates_since_on_change():
    prev = mk(st=WORKING, since=5.0)
    ev = {"hook_event_name": "Stop", "session_id": "c1", "cwd": "/x/proj"}
    assert state.transition(prev, ev, "A", DONE, 9.0).since == 9.0


def test_transition_records_cleaned_prompt():
    ev = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "c1",
        "cwd": "/x/proj",
        "prompt": "fix\nthe\tbug\x07 please",
    }
    s = state.transition(mk(), ev, "A", WORKING, 1.0)
    assert s.last_prompt == "fix the bug please"


def test_transition_keeps_prompt_on_other_events():
    prev = mk(st=WORKING, prompt="old prompt")
    ev = {"hook_event_name": "Stop", "session_id": "c1", "cwd": "/x/proj"}
    assert state.transition(prev, ev, "A", DONE, 2.0).last_prompt == "old prompt"


def test_session_start_resets_previous_claude_in_same_tab():
    prev = mk(st=WORKING, since=1.0, prompt="old")
    ev = {"hook_event_name": "SessionStart", "session_id": "new", "cwd": "/y/other"}
    s = state.transition(prev, ev, "A", IDLE, 50.0)
    assert s == Session("A", "new", "/y/other", IDLE, 50.0, "")


# --- clean / formatting ----------------------------------------------------


def test_clean_strips_controls_and_truncates():
    assert state.clean("a\x1b]9;x\x07b", 80) == "a ]9;x b"
    assert state.clean("  many   spaces ", 80) == "many spaces"
    assert state.clean("abcdefghij", 5) == "abcd…"


def test_project_name():
    assert state.project_name("/Users/c/Projects/corral") == "corral"
    assert state.project_name("") == "?"


def test_attention_text():
    assert state.attention_text(mk(st=WAITING)) == "proj: needs you"
    assert state.attention_text(mk(st=DONE)) == "proj: done"


# --- ordering / navigation / summary ---------------------------------------


def test_ordered_by_priority_then_age():
    ss = [
        mk("w2", WAITING, 5),
        mk("i", IDLE, 0),
        mk("w1", WAITING, 1),
        mk("d", DONE, 0),
        mk("k", WORKING, 0),
    ]
    assert [s.iterm_id for s in state.ordered(ss)] == ["w1", "w2", "d", "k", "i"]


def test_next_target_longest_waiting_first():
    ss = [mk("b", WAITING, 5), mk("a", WAITING, 1), mk("c", DONE, 0)]
    assert state.next_target(ss, WAITING, "zzz") == "a"
    assert state.next_target(ss, WAITING, None) == "a"


def test_next_target_cycles():
    ss = [mk("b", WAITING, 5), mk("a", WAITING, 1)]
    assert state.next_target(ss, WAITING, "a") == "b"
    assert state.next_target(ss, WAITING, "b") == "a"


def test_next_target_none_when_empty():
    assert state.next_target([mk("a", WORKING)], WAITING, "a") is None


def test_summary():
    ss = [mk("a", WAITING), mk("b", WAITING), mk("c", WORKING), mk("d", DONE), mk("e", IDLE)]
    assert state.summary(ss) == "✋2 ⚙1 ✓1"
    assert state.summary([mk("a", WORKING)]) == "⚙1"
    assert state.summary([]) == "·"


def test_tab_color_key():
    assert state.tab_color_key(WAITING, False) == WAITING
    assert state.tab_color_key(DONE, False) == DONE
    assert state.tab_color_key(WAITING, True) is None
    assert state.tab_color_key(WORKING, False) is None
    assert state.tab_color_key(IDLE, False) is None


IDLE_PROMPT = {"hook_event_name": "Notification", "notification_type": "idle_prompt"}


def test_idle_prompt_only_clears_working():
    working = mk(st=WORKING, since=1.0, prompt="p")
    assert state.transition(working, IDLE_PROMPT, "A", IDLE, 9.0).state == IDLE
    for st in (WAITING, DONE, IDLE):
        prev = mk(st=st, since=1.0, prompt="p")
        assert state.transition(prev, IDLE_PROMPT, "A", IDLE, 9.0) == prev


def test_status_variants_longest_first():
    ss = [
        mk("a", WAITING, cwd="/p/hydrogen"),
        mk("b", IDLE, cwd="/p/sanity"),
        mk("c", DONE, cwd="/p/lasso"),
    ]
    assert state.status_variants(ss) == [
        "✋ hydrogen  · sanity  ✓ lasso",
        "✋ hydrogen  ✓ lasso",
        "✋1 ✓1",
    ]


def test_status_variants_dedupes_and_handles_empty():
    assert state.status_variants([mk("a", WORKING, cwd="/p/x")]) == ["⚙ x", "⚙1"]
    assert state.status_variants([mk("a", IDLE, cwd="/p/x")]) == ["· x", "·"]
    assert state.status_variants([]) == ["·"]
