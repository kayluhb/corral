from __future__ import annotations

import argparse
import sys
from pathlib import Path

from corral import pick


def main() -> None:
    parser = argparse.ArgumentParser(prog="corral")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pick", help="fuzzy-pick a claude session")
    p.add_argument("--out", type=Path, required=True, help="file to write the chosen iTerm id to")
    args = parser.parse_args()
    sys.exit(pick.run(args.out))
