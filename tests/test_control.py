import asyncio
import shutil
import tempfile

import pytest

from corral import control


@pytest.fixture
def short_state(monkeypatch):
    # Unix socket paths are capped at 104 bytes on macOS; pytest's tmp_path is too long.
    directory = tempfile.mkdtemp(prefix="corral-")
    monkeypatch.setenv("CORRAL_STATE_DIR", directory)
    yield directory
    shutil.rmtree(directory)


def test_request_round_trips_through_the_socket(short_state):
    async def handle(message):
        return {"ok": True, "echo": message}

    async def run():
        server = await control.serve(handle)
        try:
            return await asyncio.to_thread(control.request, {"op": "ping"})
        finally:
            server.close()

    assert asyncio.run(run()) == {"ok": True, "echo": {"op": "ping"}}


def test_handler_errors_come_back_as_errors(short_state):
    async def handle(message):
        raise RuntimeError("boom")

    async def run():
        server = await control.serve(handle)
        try:
            return await asyncio.to_thread(control.request, {"op": "ping"})
        finally:
            server.close()

    assert "boom" in asyncio.run(run())["error"]


def test_socket_is_private_whatever_the_umask(short_state):
    import os

    async def run():
        old = os.umask(0)
        try:
            server = await control.serve(lambda message: None)
        finally:
            os.umask(old)
        # Python 3.13+ unlinks the socket on close, so stat it first.
        mode = control.path().stat().st_mode & 0o777
        server.close()
        return mode

    assert asyncio.run(run()) == 0o600


def test_request_without_a_daemon_raises(short_state):
    with pytest.raises(control.Unavailable):
        control.request({"op": "ping"})


def test_paste_wraps_text_so_newlines_do_not_submit():
    assert control.paste("a\nb") == "\x1b[200~a\nb\x1b[201~"
    # Other control characters are dropped, so the text can't end the paste early or send keys.
    assert control.paste("a\x1b[201~b\x03\tc") == "\x1b[200~a[201~b\tc\x1b[201~"


def test_long_requests_fit(short_state):
    async def handle(message):
        return {"ok": True, "size": len(message["text"])}

    async def run():
        server = await control.serve(handle)
        try:
            return await asyncio.to_thread(control.request, {"text": "é" * 100_000})
        finally:
            server.close()

    assert asyncio.run(run()) == {"ok": True, "size": 100_000}


def screen(*lines):
    """Lines of cells; text inside [brackets] is faint."""
    out = []
    for line in lines:
        cells, faint = [], False
        for ch in line:
            if ch in "[]":
                faint = ch == "["
            else:
                cells.append((ch, faint))
        out.append(cells)
    return out


RULE = "─" * 20


def test_draft_is_what_you_typed_into_the_input_box():
    lines = screen("⏺ Done.", RULE, "❯\xa0half a pro", "  mpt, two lines", RULE, "  ~/p main")
    assert control.draft(lines) == "half a pro  mpt, two lines"


def test_no_draft_in_an_empty_box_or_one_showing_a_faint_suggestion():
    assert control.draft(screen(RULE, "❯\xa0", RULE)) == ""
    assert control.draft(screen(RULE, '❯\xa0[Try "refactor x.py"]', RULE)) == ""


def test_draft_ignores_earlier_prompts_in_the_transcript():
    lines = screen("❯\xa0an old prompt", "⏺ Sure.", RULE, "❯\xa0", RULE)
    assert control.draft(lines) == ""


def test_no_input_box_on_screen_means_no_draft():
    assert control.draft(screen("Select model", "❯\xa01. Opus")) == ""


def test_draft_ignores_a_faint_suggestion_after_typed_text():
    assert control.draft(screen(RULE, "❯\xa0fix[ the bug]", RULE)) == "fix"


def test_draft_reads_the_last_input_box_when_an_earlier_prompt_has_a_rule_above_it():
    lines = screen(RULE, "❯\xa0an old prompt", "⏺ Sure.", RULE, "❯\xa0", RULE)
    assert control.draft(lines) == ""
