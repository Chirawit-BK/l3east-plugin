# skill-health report template

Write to OUT/report.md (OUT is set by the skill). Fill every `{{...}}`; delete a section only when it has nothing to say and say so in one line.

The outer code fence below is the template wrapper and is not part of the written file.
Never print a secret value in the report; name the key only.

```
# Skill health — {{date}}

Project scanned: {{project}}
Window: last {{since}} days · usage source: {{usage_status}}

## Summary
| metric | value |
|---|---|
| skills + commands loaded | {{n_entries}} |
| est. listing tokens per turn | ~{{est_tokens}} (chars/4; run /skill-doctor for the real figure) |
| never used in window | {{n_dead}} |
| clusters judged | {{n_clusters}} ({{n_R}} R · {{n_C}} C · {{n_X}} X; same-name-only clusters are S, not judged) |
| same-name across scopes | {{n_same_name}} |
| MCP duplicates | {{n_mcp_dup}} (plaintext secrets: {{n_secret}}, counted over every MCP server, duplicate or not) |
| hook overlaps | {{n_hook_overlap}} |
| misplaced scope candidates | {{n_misplaced}} |

## Since last run ({{prev_date}} or "first run")
- added: {{added}}
- removed: {{removed}}
- est. tokens: {{prev_tokens}} → {{est_tokens}}

## Findings, most severe first
### {{class}} · {{title}}
- members: {{members}} (uses: {{uses}})
- verdict: {{verdict}} — {{reason}}
- evidence: {{quotes or script fields}}
- action: {{action}}

## Per-project profile ({{project_slug}})
- loaded here but never used here: {{list}}
- personal skills used only in one other project: {{list with that project}}
- suggested `enabledPlugins` for this project: {{list}}

## Description lint
| skill | chars | issues |
|---|---|---|
{{rows}}

## Draft routing block
{{the block from routing-block.md, filled from proposed_rules}}

## Gaps
Typed or invoked but not installed now: {{usage.json keys matching no installed entry, or "none found"}} → try /find-skills for any real need.

## Commands for the user to run (nothing was executed)
{{claude plugin uninstall ..., rm -r ..., edits to ~/.claude.json, token rotation; R-cluster routing exclusions for plugin skills}}

## Caveats
- Token figures are chars/4 estimates.
- Transcript parsing is unofficial; zero uses can mean "fires without the Skill tool" (hooks, auto-loaded guidance) or "used in a repo outside the window".
- Project-scoped skills count only inside their repo.
```
