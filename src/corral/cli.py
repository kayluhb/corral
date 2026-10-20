from __future__ import annotations

import argparse
import sys
from pathlib import Path

from corral import commands, pick, restore, settings, state


def main() -> None:
    parser = argparse.ArgumentParser(prog="corral")
    parser.description = "With no command, reopens the claude sessions from last time (restore)."
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("pick", help="fuzzy-pick a claude session")
    p.add_argument("--out", type=Path, required=True, help="file to write the chosen iTerm id to")
    p.add_argument("--only", help="comma-separated iTerm ids to offer (default: all)")
    sub.add_parser("daemon", help="run the iTerm daemon (launchd runs this)")
    p = sub.add_parser("list", help="list claude sessions, most urgent first")
    p.add_argument("--json", action="store_true", help="print JSON with full ids")
    target = "session: an iTerm id, a unique prefix of one, or a project name"
    states = sorted(state.PRIORITY)
    p = sub.add_parser("wait", help="wait until a session stops working (or reaches --until)")
    p.add_argument("target", help=target)
    p.add_argument("--until", action="append", choices=states, help="state to wait for; repeat")
    p.add_argument("--timeout", type=float, help="seconds; exits 1 when it runs out")
    p = sub.add_parser("send", help="type a prompt into a session and press Enter")
    p.add_argument("target", help=target)
    p.add_argument("text", nargs="+", help="the prompt; - reads it from stdin")
    p.add_argument("--wait", action="store_true", help="then wait until that turn stops")
    p.add_argument("--timeout", type=float, help="with --wait: seconds; exits 1 when it runs out")
    sub.add_parser("restore", help="reopen the claude sessions that were running last time")
    sub.add_parser("settings", help="change corral's settings (arrow-key menu)")
    sub.add_parser("setup", help="add the corral status bar item and hotkeys to iTerm")
    args = parser.parse_args()
    if args.command == "pick":
        only = set(filter(None, args.only.split(","))) if args.only is not None else None
        sys.exit(pick.run(args.out, only))
    if args.command == "list":
        sys.exit(commands.list_sessions(as_json=args.json))
    if args.command == "wait":
        until = set(args.until) if args.until else commands.STOPPED
        sys.exit(commands.wait(args.target, until=until, timeout=args.timeout))
    if args.command == "send":
        text = sys.stdin.read() if args.text == ["-"] else " ".join(args.text)
        wait_until = commands.STOPPED if args.wait else None
        sys.exit(commands.send(args.target, text, wait_until=wait_until, timeout=args.timeout))
    if args.command == "settings":
        sys.exit(settings.menu())
    if args.command in (None, "restore"):
        sys.exit(restore.run())
    # iterm2 is only needed by these two; keep `pick` stdlib-only and fast.
    if args.command == "daemon":
        from corral import daemon

        daemon.run()
    else:
        from corral import iterm_setup

        iterm_setup.main()


if __name__ == "__main__":
    main()
