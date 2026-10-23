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

- UserPromptSubmit: a prompt that starts with `/l3east:sleep` opens a run; `merge` as the next word on that line grants merge. Typing it again keeps the counters, sets the grant again and restarts the TTL. `/l3east:wake` closes it. Every other prompt leaves the run open, because usage-limit auto-continue, task notifications and loop wakeups also arrive as prompts; each one gets the grant and the skill path restated. A prompt that does not look machine-made gets a wake hint. After a run closes, every prompt tells Claude the merge grant is revoked, and merges and refused pushes stay denied until a prompt that looks like a person (or `/l3east:wake`).
- Stop: while a run is open, sends Claude back to work until its last line is `SLEEP-DONE` or `SLEEP-BLOCKED: <reason>`. It lets the turn end only while a subagent, monitor or workflow is still running or pending; a lone background shell or cron gets a block that names it. The last of the continuation budget (`L3EAST_SLEEP_BUDGET`, default 40) asks for the morning report. A run expires `L3EAST_SLEEP_TTL_HOURS` (default 18) after the last `/l3east:sleep`.
- PreToolUse (`Bash`, `Monitor`, and MCP tools named `*run_in_terminal` or `*execute_shell_command`): the command is split into its simple commands (`&&`, `;`, `|`, `bash -c`, `env`, `sudo` unwrapped) and each argv is checked, so words inside quoted titles and bodies do not count. During a run it denies `AskUserQuestion`; a `git push` (global options like `-C` allowed) that does not name `<remote> <branch>`, targets `main`/`master`/`dev`/`develop` or `HEAD`, deletes, force-pushes (`--force-with-lease` is fine), or uses `--all`/`--mirror`/`--prune`; and any merge (a `gh` command with a bare `merge` word, or a `/pulls/N/merge`, `/merges`, `mergePullRequest`, `mergeBranch` or `enablePullRequestAutoMerge` call) other than exactly `gh pr merge <number> --repo <owner/repo> --match-head-commit <sha> --merge|--squash|--rebase` as one plain command. That one form still needs the merge grant and a base that `gh pr view <number> --repo <owner/repo>` reports as neither `main` nor `master`. Command substitution in a merge or push is denied. This is a text check on shell commands, not a sandbox. It runs on every matching call in every session; outside a run it only checks that no state file exists.

A hook error or an unreadable state file fails closed on asking and merging and shows a `systemMessage` otherwise; `/l3east:wake` clears an unreadable file. `L3EAST_SLEEP_DEBUG=1` appends every payload to `debug.log` in that folder, with long strings and every `command` or `prompt` field replaced by its length.

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
