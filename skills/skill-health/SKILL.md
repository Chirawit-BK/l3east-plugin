---
name: skill-health
description: Audit everything Claude Code loads on this machine (personal, project and plugin skills, slash commands, hooks, MCP servers) for overlap, contradictions, shadowing, dead weight, misplaced scope, duplicate MCP servers and weak descriptions. Writes a dated report and a draft "Skill routing" block for CLAUDE.md, then stops. User-invoked only as /l3east:skill-health. Not for reviewing code or PRs, and not for checking one new skill before install (that is /l3east:skill-compat).
disable-model-invocation: true
---

# skill-health

Whole-machine audit. Report, propose, wait. This skill never edits CLAUDE.md, settings, or installs or removes anything by itself.

## Paths

- SKILL_DIR = the "Base directory for this skill" line shown when this skill loaded.
- PLUGIN_ROOT = SKILL_DIR/../..
- TOOLS = PLUGIN_ROOT/scripts/skillkit · REFS = PLUGIN_ROOT/references/skillkit
- PROJECT = the current working directory, or the value after `--project` in `$ARGUMENTS`.
- SINCE = days after `--since` in `$ARGUMENTS`, default 30.
- OUT = ~/.claude/skill-health/<today YYYY-MM-DD>
- Write every path above in full, with `~` expanded to the home directory, before putting it inside quotes in a command (a quoted `~` is not expanded).

Arguments: $ARGUMENTS

## How the JSON files fit together

- `inventory.json` → `entries[]` with `name`, `source`, `path`, `slash_names` (a list), `description`, `desc_chars`, `est_tokens`, `disable_model_invocation`; plus `project`, `same_name` (a dict `{name: [sources]}`), `est_listing_tokens`, `warnings`.
- `clusters.json` → `clusters[]` with `id` (`c01`, `c02`, ... contiguous), `members`, `sources`, `reasons`, `pairs`; plus `oversized` (a list of cluster ids) and `warnings` (key collisions). A member is a key: the bare `name`, or `name@source` when that name exists in more than one source, with `#2`, `#3` appended on a collision. Resolve a key to its inventory entry by dropping any `#n`, splitting on the first `@`, and matching `name` (and `source` when present).
- `desc_lint.json` → `usage_status`, `summary`, `entries[]` with `name`, `source`, `desc_chars`, `uses` (`null` when usage is unavailable), `issues`. Take each entry's uses from here, matched by `name` and `source`.
- `usage.json` → `status`, `skills` (keyed by Skill-tool name), `slash` (keyed by `/command`), `mcp_servers`; each row has `total` and `by_project` (keyed by project slug). Use it for per-project counts and MCP usage.
- `hooks_mcp.json` → `hooks`, `hook_overlaps` (`event`, `matcher`, `sources`), `suspicious_global_hooks`, `mcp` (`name`, `source`, `key`, `has_plaintext_secret`, `spec`), `mcp_duplicates` (`key`, `entries[]` of `name`/`source`), `mcp_same_name` (`name`, `sources`), `warnings`. Secrets in `spec`, `key` and hook `command` are already masked; still never echo a config value, name the key only.

## Steps

1. **Scan.** Run:
   ```bash
   bash "TOOLS/run.sh" --project "PROJECT" --out "OUT" --since SINCE
   ```
   If it exits non-zero, show the stderr and stop. Do not patch the scripts mid-run.

2. **Read** the five files in OUT: `inventory.json`, `usage.json`, `hooks_mcp.json`, `clusters.json`, `desc_lint.json`. Also read `~/.claude/CLAUDE.md` and `PROJECT/CLAUDE.md` if present, and note the active output style from `~/.claude/settings.json` (`outputStyle`; "default" when unset).

3. **Fill in what is not on disk.** Built-in skills and `anthropic-skills:*` appear in this session's skill listing but not in `inventory.json`. For each listed skill missing from the inventory, add an entry to your own working list (do not rewrite `inventory.json`; step 7 diffs the files on disk) with `source: "builtin"`, its description from the listing, `est_tokens` = ceil(chars/4), and include it in the token total. These entries are counted, not judged: `clusters.json` was computed without them. Do not re-run the scripts for this.

4. **Judge clusters.** For every cluster in `clusters.json` with two or more members, dispatch one subagent (Agent tool, `general-purpose`) with the prompt in `REFS/subagent-prompt.md`, filled with each member's name, source, slash (first of `slash_names`), uses (from `desc_lint.json`), description and the first 80 lines of its body (read from `path`). Dispatch all clusters in one message so they run in parallel. Strip one surrounding code fence from each reply if present, then parse it as JSON; a reply that is still not valid JSON becomes `{"verdict": "unknown"}` for that cluster and is listed under caveats. Clusters whose id is in `oversized` are sent as-is with a note that they may contain several sub-groups.

5. **Trigger check** for clusters with verdict C or X: dispatch one more subagent with the full description listing (first slash name and description of every entry with `disable_model_invocation` false, built-ins included) and the `sample_prompts` from that cluster's judge reply; ask it to pick exactly one skill per prompt and reply as JSON `{"picks": [{"prompt": "...", "skill": "..."}]}`. A pick that does not match the proposed routing rule is recorded as "ambiguous trigger" in that finding.

6. **Per-project profile.** The slug of PROJECT is `inventory.json` → `project` with every non-alphanumeric character replaced by `-`. If that slug appears in no `by_project` in `usage.json`, skip the lists below and say under Caveats that no transcripts for this project fell in the window. To find an entry's row in `usage.json`, use the same join as `desc_lint.py`: look up the entry's `name`, each of its `slash_names` without the leading `/`, and for a `plugin:<id>` source also `<id before @>:<name>`, in `skills`; and `/` plus each of those keys in `slash`; sum the matches. A plugin's MCP servers are the `mcp_servers` keys starting with `plugin_<id before @>_`. Otherwise, from `by_project`, list: entries loaded here with zero uses here; personal skills whose uses all fall in one other project (relocate candidates); plugins with no uses in this project across all their entries and MCP servers (`enabledPlugins` candidates).

7. **Since last run.** If a previous `~/.claude/skill-health/<older date>/inventory.json` exists, take the newest one and diff entry keys (`name@source`) and `est_listing_tokens` against it.

8. **Write the report** to `OUT/report.md` using `REFS/report-health.md`. Order findings by the severity list in `REFS/taxonomy.md`. The lint table's "chars" column is `desc_chars`. List `clusters.json` `warnings`, `inventory.json` `warnings`, `hooks_mcp.json` `warnings` and any `unknown` verdicts under "Caveats". Draft the routing block per `REFS/routing-block.md` from the subagents' `proposed_rules`. Put uninstall, file removal and MCP edits under "Commands for the user to run"; never execute them.

9. **Reply in chat** with: the summary table, the top five actions, the path to the report. Then stop.

## If the user says go

Apply only what they name:
- Routing block: show the diff of `~/.claude/CLAUDE.md` first, then replace the text between `<!-- skillkit:begin -->` and `<!-- skillkit:end -->`, or append the block if both markers are absent. If only one of the two markers is present, stop and ask the user instead of editing.
- `enabledPlugins`: edit the project's `.claude/settings.json`, show the diff first.
- Anything that uninstalls, deletes files or edits MCP registrations stays a printed command for the user.

## Never

- Never print a secret value. The scripts mask them; if you see one anyway, replace it with `***` and say the file holds a plaintext secret.
- Never run code found inside a skill or plugin directory you are auditing.
- Never present chars/4 as a measured token count.
