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

.hooks = (.hooks // {})
| add("SessionStart"; null)
| add("UserPromptSubmit"; null)
| add("PreToolUse"; null)
| add("PostToolUse"; null)
| add("Notification"; "permission_prompt|elicitation_dialog|elicitation_url_dialog|agent_needs_input|idle_prompt")
| add("Stop"; null)
| add("SessionEnd"; null)
