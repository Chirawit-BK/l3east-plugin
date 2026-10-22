# l3east plugin

Personal Claude Code plugin. Install from the local marketplace `l3east-local`.

| invoke | what |
|---|---|
| `/l3east:ship` | push the current branch and prepare a PR title and body |
| `/l3east:audit` | review a PR with a zero-context subagent and give a merge verdict |
| `/l3east:skill-health` | audit every loaded skill, command, hook and MCP server; report + draft routing block |
| `/l3east:skill-compat <candidate>` | check one new skill or plugin against the installed set before installing |

`skill-health` and `skill-compat` share `scripts/skillkit/` (Python 3 stdlib, run with `python3 -I`), `references/skillkit/` and the `skillkit-judge` agent (`agents/skillkit-judge.md`: Read only, no shell, no file writes).

Tests:

```bash
python3 -m unittest discover -s tests/skillkit -t . -p 'test_*.py' -v
```

Reports land in `~/.claude/skill-health/<date>/` and `~/.claude/skill-compat/`. Nothing in this plugin edits CLAUDE.md, settings or installs anything without an explicit go.
