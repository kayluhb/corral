# Changelog

## [1.1.1] - 2026-10-20

### Changed

- `install.sh` installs a copy of corral, so checking out another branch no longer changes the
  hook and daemon under you. `--dev` keeps the editable install. It stops a running daemon, so
  the next claude event starts the new code. `corral doctor` says when the daemon runs a
  different version.

### Fixed

- After you answer a permission prompt, the session no longer goes back to waiting when
  corral's hook runs before iTerm's.
- `corral send` refuses a session with a half-typed prompt, instead of submitting it with yours.
- `corral new` accepts a prompt that starts with `-`.
- `corral restore` reopens folders with a backslash in their path, and says when it can't
  reach iTerm.

## [1.1.0] - 2026-10-20

### Added

- `corral list`, `corral wait` and `corral send`, so scripts and other claude sessions can watch
  and drive sessions from a shell. `send` refuses a session that's waiting on you, so it can't
  answer a permission prompt.
- `corral new <name> [prompt]` opens a tab next to yours running `claude --worktree <name>` and
  prints its id once claude has started.
- `corral doctor` checks the hooks, the iTerm2 Python API and hotkeys, the daemon and fzf.
  `corral explain <session>` shows a session's state, how long it's been in it and where it
  came from.
- The popover, the ⌘P picker and `corral list` show each session's git branch.
- `corral restore --pick` chooses from every stopped claude session of the last week in fzf.

### Changed

- Restore opens one new window for each window the sessions were in, in the old tab order.
  History saved by 1.0.0 has no window and opens in one window, as before.
- The hook imports `subprocess` and `tempfile` only when it needs them.

## [1.0.0] - 2026-10-19

First tagged release: status bar, ⌘J / ⌘⇧J / ⌘P hotkeys, tab colours and notifications,
restore, iTerm2 3.7 Claude Code integration and `corral settings`.

[1.1.1]: https://github.com/kayluhb/corral/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/kayluhb/corral/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/kayluhb/corral/releases/tag/v1.0.0
