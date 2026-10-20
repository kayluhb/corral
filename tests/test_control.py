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
