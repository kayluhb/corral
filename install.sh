#!/usr/bin/env bash
# Install corral: CLI + hook (uv tool), iTerm AutoLaunch shim, Claude Code hooks.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
AUTOLAUNCH="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch"
HOOK_CMD="$HOME/.local/bin/corral-hook"

command -v fzf >/dev/null || brew install fzf
command -v jq >/dev/null || { echo "jq is required"; exit 1; }

echo "==> Installing corral CLI and hook"
uv tool install --editable "$REPO" --force

echo "==> Installing iTerm2 AutoLaunch shim"
mkdir -p "$AUTOLAUNCH"
sed "s|__CORRAL_SRC__|$REPO/src|" "$REPO/autolaunch/corral.py.template" > "$AUTOLAUNCH/corral.py"

echo "==> Merging hooks into $SETTINGS"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
cp "$SETTINGS" "$SETTINGS.corral-bak"
tmp="$(mktemp)"
jq --arg cmd "$HOOK_CMD" -f "$REPO/scripts/merge-hooks.jq" "$SETTINGS" > "$tmp"
mv "$tmp" "$SETTINGS"

cat <<'STEPS'

==> Manual iTerm2 steps (one time)
  1. Settings → General → Magic: tick "Enable Python API".
     Scripts → Manage → Install Python Runtime (if not already installed).
  2. Restart iTerm2 (or Scripts → AutoLaunch → corral.py).
  3. Settings → Profiles → <your profile> → Session → Configure Status Bar:
     tick "Status bar enabled", drag "corral" into the bar.
  4. Settings → Keys → Key Bindings → "+", Action "Invoke Script Function":
       corral_next_waiting(session_id: id)
       corral_next_done(session_id: id)
       corral_pick(session_id: id)
     Bind each to a hotkey of your choice.
  5. Restart any running claude sessions so they pick up the new hooks.
STEPS
