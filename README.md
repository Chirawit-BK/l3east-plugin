# l3east plugin

Personal Claude Code plugin. Install from the local marketplace `l3east-local`.

| invoke | what |
|---|---|
| `/l3east:ship` | push the current branch and prepare a PR title and body |
| `/l3east:audit` | review a PR with a zero-context subagent and give a merge verdict |
| `/l3east:skill-health` | audit every loaded skill, command, hook and MCP server; report + draft routing block |
| `/l3east:skill-compat <candidate>` | check one new skill or plugin against the installed set before installing |
| `/l3east:sleep [merge]` | finish the work already given in this session unattended, to merge-ready (or merged, with `merge`), logging every decision |
| `/l3east:wake` | end a sleep run early because you are back |

`skill-health` and `skill-compat` share `scripts/skillkit/` (Python 3 stdlib, run with `python3 -I`), `references/skillkit/` and the `skillkit-judge` agent (`agents/skillkit-judge.md`: Read only, no shell, no file writes).

`sleep` ships three hooks (`hooks/hooks.json` → `scripts/sleep/sleep_hook.py`), keyed by session in `$CLAUDE_CONFIG_DIR/l3east/sleep/<session_id>.json`:

- UserPromptSubmit: `/l3east:sleep` opens a run (`merge` as the first word grants merge) and tells Claude the grant; `/l3east:wake` closes it. Every other prompt leaves it alone, because usage-limit auto-continue, task notifications and loop wakeups also arrive as prompts.
- Stop: while a run is open, sends Claude back to work until its last line is `SLEEP-DONE` or `SLEEP-BLOCKED: <reason>`. It lets the turn end while background tasks or session crons are pending, since they wake the session. The last of the continuation budget (`L3EAST_SLEEP_BUDGET`, default 40) asks for the morning report.
- PreToolUse: denies `AskUserQuestion` while a run is open.

`L3EAST_SLEEP_DEBUG=1` appends every hook payload (string fields cut to 300 chars) to `debug.log` in that folder.

Before a sleep run:

- Usage limits: turn on the desktop app's **Auto-continue when limits reset**. The terminal CLI has `autoContinueAtUsageLimit` for interactive sessions. Neither covers a weekly limit that resets days later.
- Claude Code ends a turn after 8 stop-hook continuations in a row with no tool call, so the skill tells Claude to wait with tools.
- The app's "Keep computer awake while Claude works" prevents idle sleep only. Keep the lid open.

Tests:

```bash
python3 -m unittest discover -s tests/skillkit -t . -p 'test_*.py' -v
python3 -m unittest discover -s tests/sleep -t . -p 'test_*.py' -v
```

Reports land in `~/.claude/skill-health/<date>/` and `~/.claude/skill-compat/`. Nothing in this plugin edits CLAUDE.md, settings or installs anything without an explicit go.
