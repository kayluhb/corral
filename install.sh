#!/usr/bin/env bash
# Install corral: CLI + hook + daemon (uv tool), Claude Code hooks, iTerm status bar + hotkeys.
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
uv tool install --editable "$REPO" --with "iterm2==2.30" --force

rm -f "$OLD_SHIM"  # earlier installs used iTerm AutoLaunch; never run two daemons

echo "==> Merging hooks into $SETTINGS"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"
[ -f "$SETTINGS.corral-bak" ] || cp "$SETTINGS" "$SETTINGS.corral-bak"  # keep the pre-corral original
tmp="$(mktemp)"
jq --arg cmd "$HOOK_CMD" -f "$REPO/scripts/merge-hooks.jq" "$SETTINGS" > "$tmp"
mv "$tmp" "$SETTINGS"

echo "==> iTerm2: status bar item and hotkeys"
if [ "$(defaults read com.googlecode.iterm2 EnableAPIServer 2>/dev/null)" != "1" ]; then
  cat <<'STEP'
  The iTerm2 Python API is off. Tick Settings → General → Magic → "Enable Python API",
  then re-run ./install.sh.
STEP
  exit 1
fi
"$CORRAL_BIN" setup

echo
echo "Done. Restart running claude sessions so they load the hooks."
echo "The daemon starts with the next claude hook in iTerm. Log: $LOG"
