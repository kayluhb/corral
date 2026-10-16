"""fzf switcher over corral sessions."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from corral import state, store
from corral.state import Session

FZF_FALLBACKS = ("/opt/homebrew/bin/fzf", "/usr/local/bin/fzf")


def age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def format_line(s: Session, now: float) -> str:
    project = state.clean(state.project_name(s.cwd), 24)
    prompt = state.clean(s.last_prompt, 80)
    return f"{s.iterm_id}\t{state.ICONS[s.state]} {project:<24} {age(now - s.since):>4}  {prompt}"


def parse_choice(line: str) -> str | None:
    iterm_id = line.split("\t", 1)[0].strip()
    return iterm_id if iterm_id and store.valid_id(iterm_id) else None


def _fzf() -> str | None:
    found = shutil.which("fzf")
    if found:
        return found
    return next((p for p in FZF_FALLBACKS if Path(p).exists()), None)


def run(out: Path) -> int:
    out.write_text("")
    sessions = state.ordered(store.load_all())
    if not sessions:
        print("corral: no claude sessions")
        time.sleep(1)
        return 0
    fzf = _fzf()
    if fzf is None:
        print("corral: fzf not found (brew install fzf)")
        time.sleep(2)
        return 1
    now = time.time()
    lines = "\n".join(format_line(s, now) for s in sessions)
    result = subprocess.run(
        [
            fzf,
            "--delimiter=\t",
            "--with-nth=2..",
            "--no-sort",
            "--reverse",
            "--prompt=claude> ",
            "--height=100%",
        ],
        input=lines,
        stdout=subprocess.PIPE,
        text=True,
    )
    if result.returncode == 0:
        choice = parse_choice(result.stdout)
        if choice:
            out.write_text(choice)
    return 0
