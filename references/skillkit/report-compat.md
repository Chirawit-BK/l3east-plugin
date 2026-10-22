# skill-compat report template

Print in chat and also write to `~/.claude/skill-compat/<YYYY-MM-DD>-<candidate>/report.md` (the scan JSON sits beside it).

The outer code fence below is the template wrapper and is not part of the written file.

```
# skill-compat — {{candidate}} ({{date}})

Source: {{path or URL}} · read as text only, nothing executed
Adds: {{n_skills}} skills, {{n_commands}} commands, {{n_hooks}} hooks, {{n_mcp}} MCP servers · est. +{{tokens}} tokens per turn

## Verdict: {{install | skip | install, then disable X}}
{{one sentence why}}

## Against what is already loaded
| candidate item | existing item (source, uses) | class | note |
|---|---|---|---|
{{rows: one per overlapping pair; R/C/X from the subagent, S/H/M from scripts}}

## Hooks and MCP
- hook overlaps added: {{list or none}}
- MCP duplicates added: {{list or none}}
- plaintext secrets in candidate config: {{yes/no}}

## Description check
{{desc_lint issues for the candidate's own entries}}

## Routing lines to add if installed
{{proposed_rules, or "none needed"}}

## Caveats
Same as skill-health: estimates, unofficial transcript parsing.
Never print a secret value; name the key only.
```
