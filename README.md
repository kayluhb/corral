# corral

Keyboard-first status for many `claude` sessions running in ordinary iTerm2 tabs.
Claude Code hooks record each session's state. An iTerm2 AutoLaunch script uses that state
to show a status bar summary, colour the tabs that need you and send notifications. Three
hotkeys jump to the sessions that need you. Nothing replaces your tabs or needs clicking.

## Install

```sh
./install.sh
```

The script runs `uv tool install` (which provides `corral` and `corral-hook`), writes the
iTerm AutoLaunch shim, and merges hook entries into `~/.claude/settings.json`. Your original
settings are backed up to `settings.json.corral-bak`. Then do these one-time iTerm2 steps:

1. Settings → General → Magic: tick **Enable Python API**. Then Scripts → Manage → **Install Python Runtime**.
2. Restart iTerm2, or run Scripts → AutoLaunch → `corral.py`.
3. Settings → Profiles → *profile* → Session → **Configure Status Bar**: drag **corral** into the bar.
4. Settings → Keys → Key Bindings → `+`, then choose **Invoke Script Function** and add:
   - `corral_next_waiting(session_id: id)`
   - `corral_next_done(session_id: id)`
   - `corral_pick(session_id: id)`
5. Restart running `claude` sessions so they load the hooks.

## Hotkeys

| Function | Does |
|---|---|
| `corral_next_waiting` | Focus the session that has waited longest for you. Press again to cycle. |
| `corral_next_done` | Same, for finished sessions you haven't looked at yet. |
| `corral_pick` | Open an fzf switcher in a temporary split. Enter jumps to the session; Esc cancels. |

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
override the location. The daemon logs to iTerm's Scripts → Manage → Console.

## Uninstall

```sh
uv tool uninstall corral
rm "$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch/corral.py"
rm -rf ~/.local/state/corral
```

Then remove the hook entries whose command is `corral-hook` from `~/.claude/settings.json`,
or restore `settings.json.corral-bak`.

## Known limitations

- If you deny a permission prompt, the session stays "waiting" until Claude's next event. That is usually Stop, after which it shows as done.
- A claude that is killed without a SessionEnd keeps a stale state until its tab closes or a new claude starts there.
- On the tab you're in, corral sets "no custom tab colour", which overrides any custom tab colour in your profile.
- The hook takes about 70ms per call and runs on every tool use.
