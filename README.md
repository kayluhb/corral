# corral

Keyboard-first status for many `claude` sessions running in ordinary iTerm2 tabs.
Claude Code hooks record each session's state. A small daemon, started by the hook and
talking to iTerm2's Python API, uses that state to show a status bar summary, colour the tabs that need you and send notifications. Three
hotkeys jump to the sessions that need you. Nothing replaces your tabs or needs clicking.

## Install

```sh
./install.sh
```

Before the first run, tick iTerm2 Settings → General → Magic → **Enable Python API**.

The script:

- runs `uv tool install`, which provides `corral` and `corral-hook`;
- merges hook entries into `~/.claude/settings.json`, backing up the original once to
  `settings.json.corral-bak`;
- runs `corral setup`, which adds the corral item to your default profile's status bar and
  binds the hotkeys below. It is safe to re-run, and it never replaces a key you already use.

Restart running `claude` sessions so they load the hooks. The daemon starts on the next
hook event in iTerm. It runs from inside iTerm, so iTerm trusts it without an approval
prompt. It exits when iTerm quits and starts again with the next claude event.

## Hotkeys

| Key | Function | Does |
|---|---|---|
| ⌃⌥⌘W | `corral_next_waiting` | Focus the session that has waited longest for you. Press again to cycle. |
| ⌃⌥⌘D | `corral_next_done` | Same, for finished sessions you haven't looked at yet. |
| ⌃⌥⌘P | `corral_pick` | Open an fzf switcher in a temporary split. Enter jumps to the session; Esc cancels. |

## States

| State | Icon | Tab colour | Meaning |
|---|---|---|---|
| waiting | ✋ | amber | Permission prompt, question or agent input needed |
| working | ⚙ | none | Prompt submitted or tool running |
| done | ✓ | green | Claude finished. Becomes idle once you focus the tab |
| idle | · | none | Session open, nothing pending |

The status bar shows counts, for example `✋2 ⚙3 ✓1`. A colour is never shown on the tab you're
currently in. You get a notification only for sessions you're not looking at.

## Development

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```

State files live in `~/.local/state/corral/`, one per iTerm session. Set `CORRAL_STATE_DIR` to
override the location. The daemon logs to `~/Library/Logs/corral.log`. Set
`CORRAL_NO_AUTOSTART=1` to stop the hook from starting it.

## Uninstall

```sh
uv tool uninstall corral
pkill -f "corral.cli daemon"
rm -rf ~/.local/state/corral
```

Remove the corral status bar item and the three hotkeys in iTerm2 Settings.
Then remove the hook entries whose command is `corral-hook` from `~/.claude/settings.json`,
or restore `settings.json.corral-bak`.

## Known limitations

- If you deny a permission prompt, the session stays "waiting" until Claude's next event. That is usually Stop, after which it shows as done.
- A claude that is killed without a SessionEnd keeps a stale state until its tab closes or a new claude starts there.
- On the tab you're in, corral sets "no custom tab colour", which overrides any custom tab colour in your profile.
- The hook takes about 70ms per call and runs on every tool use.
