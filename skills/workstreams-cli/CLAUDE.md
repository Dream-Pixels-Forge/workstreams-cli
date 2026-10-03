# workstreams

## Install
pip install workstreams-cli
npx skills add https://github.com/Dream-Pixels-Forge/workstreams-cli/tree/main/skills

## Usage
workstreams init --project myproj --workstreams 3
workstreams start --multiplexer tmux --cmd "claude"
workstreams dispatch --workstream 1 --subagent claude-code --issue 42 --prompt "Fix auth"
workstreams monitor

This skill enables visual dispatch of coding-agent work to subagents in real terminal windows with live monitoring.
