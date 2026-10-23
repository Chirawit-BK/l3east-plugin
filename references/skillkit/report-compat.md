# skill-compat report template

Write to OUT/report.md (OUT is set by the skill; the scan JSON sits beside it). In chat, print only the verdict, its one-sentence reason, the "Against what is already loaded" table and the path to the report.

The outer code fence below is the template wrapper and is not part of the written file.
Never print a secret value in the report; name the key only. Show MCP keys as scheme and host only (`url:https://mcp.example.com`, or `cmd:` plus the first word of the command), never the full key.
Caveats always include: token figures are chars/4 estimates; transcript parsing is unofficial (same as skill-health).

```
# skill-compat — {{candidate}} ({{date}})

Source: {{path or URL}} · read as text only, nothing executed
Adds: {{n_skills}} skills, {{n_commands}} commands, {{n_hooks}} hooks, {{n_mcp}} MCP servers · est. +{{tokens}} tokens per turn

## Verdict: {{install | skip | install, then disable X}}
{{one sentence why}}

## Against what is already loaded
| candidate item | existing item (source, uses) | class | note |
|---|---|---|---|
{{rows: one per overlapping pair; R/C/X from the subagent, S/H/M from scripts; uses "unknown" when null; MCP items as scheme+host}}

## Hooks and MCP
- hook overlaps added: {{list or none}}
- MCP duplicates added: {{list as scheme+host, or none}}
- plaintext secrets in candidate config: {{yes/no; server names only}}

## Description check
{{desc_lint issues for the candidate's own entries}}

## Routing lines to add if installed
{{proposed_rules from C or X clusters, or "none needed"}}

## Actions for the user
{{proposals, not applied: judge drop_or_disable items and proposed_rules from R clusters, each naming a skill in the inventory; or "none"}}

## Caveats
{{caveats: chars/4 estimates, scan warnings, unknown verdicts, judge proposals dropped because they name a skill not in the inventory}}
```
