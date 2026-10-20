#!/usr/bin/env bash
# Install corral: CLI + hook + daemon (uv tool), Claude Code hooks, iTerm status bar + hotkeys.
# --dev installs in editable mode, so the tools run whatever this folder has checked out.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
HOOK_CMD="$HOME/.local/bin/corral-hook"
CORRAL_BIN="$HOME/.local/bin/corral"
LOG="$HOME/Library/Logs/corral.log"
OLD_SHIM="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch/corral.py"

command -v fzf >/dev/null || brew install fzf
command -v jq >/dev/null || { echo "jq is required"; exit 1; }

echo "==> Installing corral CLI, hook and daemon"
if [ "${1:-}" = "--dev" ]; then
  uv tool install --editable "$REPO" --with "iterm2==2.30" --force
else
  # A copy, so checking out another branch doesn't change the hook and daemon under you.
  uv tool install "$REPO" --with "iterm2==2.30" --force --reinstall-package corral
fi
pkill -f 'corral.cli daemon' || true  # the next claude event starts it on the new code

rm -f "$OLD_SHIM"  # earlier installs used iTerm AutoLaunch; never run two daemons

echo "==> Merging hooks into $SETTINGS"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
[ -f "$SETTINGS.corral-bak" ] || cp "$SETTINGS" "$SETTINGS.corral-bak"  # keep the pre-corral original
tmp="$(mktemp)"
jq --arg cmd "$HOOK_CMD" -f "$REPO/src/corral/merge-hooks.jq" "$SETTINGS" > "$tmp"
mv "$tmp" "$SETTINGS"

echo "==> iTerm2: status bar item and hotkeys"
if [ "$(defaults read com.googlecode.iterm2 EnableAPIServer 2>/dev/null)" != "1" ]; then
  # Same pref as Settings → General → Magic → "Enable Python API"; iTerm reads it at launch.
  defaults write com.googlecode.iterm2 EnableAPIServer -bool true
  cat <<'STEP'
  Enabled the iTerm2 Python API. Quit iTerm2 (⌘Q), reopen it, then re-run ./install.sh.
STEP
  exit 1
fi
"$CORRAL_BIN" setup

echo
echo "Done. Restart running claude sessions so they load the hooks."
echo "The daemon starts with the next claude hook in iTerm. Log: $LOG"
