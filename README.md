# l3east plugin

Personal Claude Code plugin. Install from the local marketplace `l3east-local`.

| invoke | what |
|---|---|
| `/l3east:ship` | push the current branch and prepare a PR title and body |
| `/l3east:audit` | review a PR with a zero-context subagent and give a merge verdict |
| `/l3east:skill-health` | audit every loaded skill, command, hook and MCP server; report + draft routing block |
| `/l3east:skill-compat <candidate>` | check one new skill or plugin against the installed set before installing |
| `/l3east:sleep [merge] <task>` | run one task unattended to merge-ready (or merged, with `merge`), logging every decision |

`skill-health` and `skill-compat` share `scripts/skillkit/` (Python 3 stdlib, run with `python3 -I`), `references/skillkit/` and the `skillkit-judge` agent (`agents/skillkit-judge.md`: Read only, no shell, no file writes).

`sleep` ships two hooks (`hooks/hooks.json` → `scripts/sleep/sleep_hook.py`). Typing `/l3east:sleep` opens `~/.claude/l3east/sleep/<session_id>.json`; any other prompt closes it. While it is open, the Stop hook sends Claude back to work until its last message ends with `SLEEP-DONE` or `SLEEP-BLOCKED: <reason>`, background work is running, or the continuation budget is spent (`L3EAST_SLEEP_BUDGET`, default 40). `L3EAST_SLEEP_DEBUG=1` logs every hook payload to `~/.claude/l3east/sleep/debug.log`.

Before a sleep run:

- Usage limits: the desktop app's **Auto-continue when limits reset** must be on (session limit only). In the terminal CLI, `autoContinueAtUsageLimit` (default `true`) does the same, for interactive sessions only, re-armed at most twice in a row, and not for a weekly reset more than 24 hours away.
- The app's "Keep computer awake while Claude works" prevents idle sleep only. Keep the lid open.

Tests:

```bash
python3 -m unittest discover -s tests/skillkit -t . -p 'test_*.py' -v
python3 -m unittest discover -s tests/sleep -t . -p 'test_*.py' -v
```

Reports land in `~/.claude/skill-health/<date>/` and `~/.claude/skill-compat/`. Nothing in this plugin edits CLAUDE.md, settings or installs anything without an explicit go.
