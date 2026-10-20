# Usage: jq --arg cmd "$HOME/.local/bin/corral-hook" -f merge-hooks.jq settings.json
# Replaces corral's own entries (so re-running upgrades them) and leaves every other hook alone.
def entry($matcher):
  {hooks: [{type: "command", command: $cmd, timeout: 5}]}
  + (if $matcher == null then {} else {matcher: $matcher} end);

def add($event; $matcher):
  .hooks[$event] = (
    [(.hooks[$event] // [])[] | select(any(.hooks[]?; .command == $cmd) | not)]
    + [entry($matcher)]
  );

# Events corral no longer uses: drop its entries, and the event if nothing else is left.
def retire($event):
  if .hooks[$event] then
    .hooks[$event] |= [.[] | select(any(.hooks[]?; .command == $cmd) | not)]
    | if .hooks[$event] == [] then del(.hooks[$event]) else . end
  else . end;

.hooks = (.hooks // {})
| add("SessionStart"; null)
| add("UserPromptSubmit"; null)
| add("PostToolUse"; null)
| add("Notification"; "permission_prompt|elicitation_dialog|elicitation_url_dialog|agent_needs_input|idle_prompt")
| add("PermissionRequest"; null)
| add("Stop"; null)
| add("SessionEnd"; null)
| retire("PreToolUse")
