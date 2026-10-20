"""The git branch a session's folder is on, read from .git/HEAD.

No `git` subprocess: the daemon redraws every second for every session.
"""

from __future__ import annotations

from pathlib import Path

_REF = "ref: refs/heads/"


def branch(cwd: str) -> str:
    """The branch checked out at cwd (or a short sha when detached), or "" outside a repo."""
    if not cwd:
        return ""
    try:
        head = _git_dir(Path(cwd))
        text = (head / "HEAD").read_text().strip() if head else ""
    except OSError:
        return ""
    if text.startswith(_REF):
        return text[len(_REF) :]
    return text[:7]


def _git_dir(folder: Path) -> Path | None:
    for parent in (folder, *folder.parents):
        dot_git = parent / ".git"
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():  # a worktree or submodule: "gitdir: <path>"
            target = dot_git.read_text().strip().removeprefix("gitdir:").strip()
            return parent / target  # an absolute target replaces parent
    return None
