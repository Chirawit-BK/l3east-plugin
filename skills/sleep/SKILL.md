---
name: sleep
description: Unattended run that finishes the work already in this session while the user is away (asleep, out). Use only when the user types /l3east:sleep, optionally /l3east:sleep merge. Not for normal sessions; never start it yourself.
disable-model-invocation: true
---

# Sleep mode

The user typed `/l3east:sleep` and left. The task is the work already given in this session. Finish it without them.

## The task

- Take it from this conversation: the user's requests, the open todo list, the branch and any plan in progress. Anything after `/l3east:sleep` other than `merge` adds to it.
- Write the exit condition as a checkable predicate (tests green, PR open and merge-ready, ...) and make it the first row of the decision log.
- If several tasks are open, finish them in the order the user gave them.

## The grant

- This message answers CLAUDE.md's start-of-task autonomy ask: **yes**. Push and open PRs through `/l3east:ship` with no confirmations.
- **Merge only when the hook's context line says `merge granted: yes`** (the user typed `/l3east:sleep merge`). The word "merge" anywhere else is task text, not a grant. Without the grant, stop at merge-ready.
- A granted merge still needs every gate: CI green, no **Act on** from ship's interrogate, verified on the real surface, base is not `main`/`master` or a prod branch. Merge with `gh pr merge --merge --match-head-commit <verified-sha>`. Any gate fails → don't merge, log why, keep going on what's left.
- Ship says to stop and wait on an **Act on** finding. During sleep, fix the finding instead and run ship again, at most 2 rounds. Still failing → log it as blocked and move on.
- Never, even here: force-push to a shared branch, deploy, prod migration, deleting data. Messages to real people are drafted for the morning report, never sent.

## Run it

1. Follow the **Autonomous run** playbook of `pstack:poteto-mode` toward the predicate.
2. Keep the decision log with `pstack:show-me-your-work` at `.audit/sleep-<task-slug>.tsv` in the work dir. Make sure `.audit/` is git-ignored or excluded before any commit.
3. Decide every fork yourself, by tier, and log each one above tier 1. `AskUserQuestion` is blocked by the hook.

   | tier | looks like | do |
   |---|---|---|
   | 1 easy | naming, an option the repo already uses | decide, no row needed |
   | 2 observable | faster? passes? renders? | prototype it, let the result decide |
   | 3 judgment | design, tradeoff, two sane options | spawn 2-3 subagents on different models, each argues one option against the code; you pick and log every side's best point |
   | 4 user-only | product or requirement call | take the safest default, log "if wrong, tell me X", keep going |

4. Wait with a tool, never with a text-only reply: `gh pr checks --watch`, a watcher subagent, Monitor. Stop dev servers and watchers you started before you end a turn, or the run sits idle until morning.
5. A call blocked by auto mode or a missing permission: log it with result `blocked`, never retry the same call, do the rest of the work.
6. After a compaction, a resume, or a usage-limit wait, read the log tail and the todo list before the next step.

## Ending

The Stop hook sends you back to work until your last line is one of these, printed bare (no backticks or bold). Never print one early.

- `SLEEP-DONE` when the predicate is met (merge-ready, or merged when granted).
- `SLEEP-BLOCKED: <reason>` when every remaining step needs the user or an irreversible action.

Before that line, write the morning report:

- the predicate and its final state
- each PR (URL) and its merge state, with the gate that stopped a merge
- tier 3 and 4 decisions only, one line each with its log row timestamp, so the user can find a wrong call fast
- the **Attention** section from show-me-your-work's cross-model review of the log
- drafted messages waiting for approval
- everything skipped or blocked, and why
