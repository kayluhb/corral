# Changelog

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

[1.1.0]: https://github.com/kayluhb/corral/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/kayluhb/corral/releases/tag/v1.0.0
