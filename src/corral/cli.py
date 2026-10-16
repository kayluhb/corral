from __future__ import annotations

import argparse
import sys
from pathlib import Path

from corral import pick, restore, settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="corral")
    parser.description = "With no command, reopens the claude sessions from last time (restore)."
    sub = parser.add_subparsers(dest="command")
    p = sub.add_parser("pick", help="fuzzy-pick a claude session")
    p.add_argument("--out", type=Path, required=True, help="file to write the chosen iTerm id to")
    sub.add_parser("daemon", help="run the iTerm daemon (launchd runs this)")
    sub.add_parser("restore", help="reopen the claude sessions that were running last time")
    sub.add_parser("settings", help="change corral's settings (arrow-key menu)")
    sub.add_parser("setup", help="add the corral status bar item and hotkeys to iTerm")
    args = parser.parse_args()
    if args.command == "pick":
        sys.exit(pick.run(args.out))
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
