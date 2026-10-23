# The managed "Skill routing" block

skill-health drafts this block; the user decides whether it goes into `~/.claude/CLAUDE.md` (or a project CLAUDE.md for project-only rules). Only the text between the markers is managed. Everything else in CLAUDE.md is never touched.

```
## Skill routing
<!-- skillkit:begin -->
- Review for a merge verdict → /l3east:audit. Bugs in a diff only → /code-review. Security → /security-review. Never superpowers:requesting-code-review.
- Push or open a PR → /l3east:ship only. Never superpowers:finishing-a-development-branch.
- New branch → /dev. Never starting-new-branch or superpowers:using-git-worktrees unless a worktree is required.
- Diagram → figma:figma-generate-diagram when the target is Figma or FigJam; engineering-diagrams for docs in the repo.
- First action of a turn → using-superpowers picks the skill. serena initial_instructions only when editing TypeScript symbols. karpathy-guidelines never on its own.
<!-- skillkit:end -->
```

Rules for each line:
- One situation per line, in the form `<situation> → /<skill>`. Add `Never <other>` when a member is being excluded.
- Name skills exactly as the slash listing shows them (`/l3east:audit`, `superpowers:brainstorming`).
- Write a line for a cluster with verdict C or X. An R cluster gets a line only when the loser is a plugin skill that cannot be removed on its own (an exclusion line, listed under the user's commands until applied); otherwise R needs no line because the loser is disabled.
- Keep the block under 15 lines. If it grows past that, the skill set needs pruning, not more rules.
- English, because CLAUDE.md on this machine is English.

Applying the block (only after the user says go):
1. If markers exist, replace the text between them. If not, append the whole block at the end of the file.
2. Show the diff before writing.
3. Never touch lines outside the markers.
