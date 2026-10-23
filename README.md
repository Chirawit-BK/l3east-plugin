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

- UserPromptSubmit: `/l3east:sleep` on its own line opens a run; `merge` as the next word on that line grants merge. `/l3east:wake` closes it. Every other prompt leaves the run open, because usage-limit auto-continue, task notifications and loop wakeups also arrive as prompts; each one gets the grant restated, and one you type yourself gets a wake hint.
- Stop: while a run is open, sends Claude back to work until its last line is `SLEEP-DONE` or `SLEEP-BLOCKED: <reason>`. It lets the turn end only while a subagent, monitor or workflow is pending (at most 6 times in a row); a lone background shell or cron gets a block that names it. The last of the continuation budget (`L3EAST_SLEEP_BUDGET`, default 40) asks for the morning report. A run expires after `L3EAST_SLEEP_TTL_HOURS` (default 18).
- PreToolUse: during a run, denies `AskUserQuestion`, and denies `gh pr merge` without the merge grant, without `--match-head-commit`, or into `main`/`master` (it runs `gh pr view` to read the base). This hook runs on every Bash call in every session; outside a run it only checks that no state file exists.

Any hook error, or an unreadable state file, shows a `systemMessage` instead of failing silently. `L3EAST_SLEEP_DEBUG=1` appends every payload to `debug.log` in that folder, with strings over 80 chars replaced by their length.

Before a sleep run:

- Usage limits: turn on the desktop app's **Auto-continue when limits reset**. The terminal CLI has `autoContinueAtUsageLimit` for interactive sessions. Neither covers a weekly limit that resets days later. A turn that ends on an API error fires `StopFailure`, not `Stop`, so the hook does not spend budget on it.
- Claude Code ends a turn after 8 stop-hook continuations in a row with no tool call (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` raises it), so the skill tells Claude to wait with tools. A run that stalls that way stays open: type `/l3east:wake` in the morning.
- To end a run while Claude is mid-turn, press Esc first, then `/l3east:wake`.
- The app's "Keep computer awake while Claude works" prevents idle sleep only. Keep the lid open.

Tests:

```bash
python3 -m unittest discover -s tests/skillkit -t . -p 'test_*.py' -v
python3 -m unittest discover -s tests/sleep -t . -p 'test_*.py' -v
```

Reports land in `~/.claude/skill-health/<date>/` and `~/.claude/skill-compat/`. Nothing in this plugin edits CLAUDE.md, settings or installs anything without an explicit go.
