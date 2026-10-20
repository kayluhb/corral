"""The daemon's control socket, so commands like `corral send` can act through iTerm.

One JSON object per line each way over a Unix socket in the state dir. The socket is mode 0600,
so only you can connect and it needs no token (unlike the popover's localhost server).
"""

from __future__ import annotations

import asyncio
import json
import re
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path

from corral import store

TIMEOUT = 5.0
LIMIT = 16 * 1024 * 1024  # longest request line; asyncio's default 64 KiB is a long prompt
_PASTE_START, _PASTE_END = "\x1b[200~", "\x1b[201~"
_UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # control characters except tab and newline


class Unavailable(Exception):
    """The daemon isn't running (or isn't listening)."""


def version() -> str:
    from importlib.metadata import version  # here, not at the top: the hook imports this module

    return version("corral")


def path() -> Path:
    return store.state_dir() / "daemon.sock"


def paste(text: str) -> str:
    """text as a bracketed paste, so its newlines don't submit it line by line."""
    return f"{_PASTE_START}{_UNSAFE.sub('', text)}{_PASTE_END}"


async def serve(handle: Callable[[dict], Awaitable[dict]]) -> asyncio.Server:
    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), TIMEOUT)
            try:
                reply = await handle(json.loads(line))
            except Exception as exc:  # one bad request must not hurt the daemon
                reply = {"error": f"{exc!r}"}
            writer.write(json.dumps(reply).encode() + b"\n")
            await writer.drain()
        except Exception as exc:
            print(f"corral control: {exc!r}")
        finally:
            writer.close()

    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)  # left by a daemon that didn't exit cleanly; we hold the lock
    server = await asyncio.start_unix_server(on_connect, path=str(target), limit=LIMIT)
    target.chmod(0o600)  # not left to the umask: anyone who connects can type into claude
    return server


def request(message: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(TIMEOUT)
        reply = b""
        try:
            sock.connect(str(path()))
            sock.sendall(json.dumps(message).encode() + b"\n")
            while not reply.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                reply += chunk
        except OSError as exc:  # also the timeout
            raise Unavailable from exc
    if not reply:
        raise Unavailable
    return json.loads(reply)
