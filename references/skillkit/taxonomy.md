# Conflict taxonomy

Every finding gets exactly one class. Classes R, C and X need a subagent verdict; the rest are decided by script output alone.

| class | name | what it means | decided by | action |
|---|---|---|---|---|
| R | redundant | Same job, same kind of output. Loading both only adds a coin flip. | subagent | keep one; disable or uninstall the rest |
| C | complementary | Neighbouring jobs: different phase, scope, or target. Both earn their place. | subagent | one routing line per situation in CLAUDE.md |
| X | contradictory | When both are loaded, their bodies give opposite orders (ask vs do not ask, push vs never push, verbose vs terse, two "I must run first" claims). | subagent, checked against CLAUDE.md and the output style | state precedence in CLAUDE.md, or disable one |
| S | shadow / cross-scope duplicate | Same bare name in two scopes. Personal beats project (project copy never loads). Plugin skills are namespaced, so a vendored copy and the plugin both load. | `inventory.same_name`; the judge is not consulted for a cluster linked only by same name (every member has the same `name`) | delete the copy that never loads; pick plugin or vendored, not both |
| H | hook / policy | Two sources hook the same event and matcher; a plugin policy blocks another plugin's hook; a user-scope hook runs a project tool in every repo. | `hooks_mcp.hook_overlaps`, `suspicious_global_hooks` | move the hook to project scope; whitelist; drop one |
| M | MCP duplicate or secret | Same server registered twice (same URL or command, or same name from two sources), or any MCP server whose config carries a plaintext secret. | `hooks_mcp.mcp_duplicates`, `mcp_same_name`, `mcp[].has_plaintext_secret` | remove one registration; rotate any plaintext secret and move it to an environment variable |
| D | dead weight | Zero uses in the window across Skill tool, slash and MCP calls. | `desc_lint` issue `never_used_in_window`, `usage.mcp_servers` | review list only; project-scoped skills fire in one repo, hooks-driven skills never show as uses |
| P | misplaced scope | A personal skill used in one project only, or a plugin loaded in a project that never uses it. | `usage.*.by_project` vs inventory | move to `<repo>/.claude/skills`; `enabledPlugins` per project |
| Q | description quality | Over 1,536 chars (cut), under 60 (vague), no trigger phrase, no "not for", broad words with no exclusion. | `desc_lint` | propose a new description |

## Verdict rules for the subagent

- R only when one member fully covers the other's job. If either does something the other cannot, it is C.
- X requires a quotable sentence from each side. A difference in tone is not X.
- Usage counts are evidence, never the verdict. A zero-use member is a drop candidate only when another member covers its job.
- "none" is allowed: coincidental word overlap with different jobs.
- Clusters link on description overlap, shared rare name tokens (a token used by at most five skills), same name, or explicit mentions; common tokens such as `figma` do not link, so a family of 20 same-prefix skills is judged through its description overlap only. Description-overlap and name-token links both stop at 20 members; same-name and mention links do not.

## Severity for the report order

1. X with CLAUDE.md or the output style (behaviour flips every turn)
2. M with a plaintext secret
3. H on PreToolUse / UserPromptSubmit
4. R
5. X between skills
6. S
7. M without a secret
8. H on other events
9. C
10. P
11. D
12. Q
