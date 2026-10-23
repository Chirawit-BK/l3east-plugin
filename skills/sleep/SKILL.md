---
name: sleep
description: Unattended run of one task to its end while the user is away (asleep, out). Use only when the user types /l3east:sleep <task>, optionally with "merge". Not for normal sessions; never start it yourself.
disable-model-invocation: true
---

# Sleep mode

The user typed `/l3east:sleep <task>` and left. Drive the task to its end without them.

## The grant

- This message is the answer to CLAUDE.md's start-of-task autonomy ask: **yes**. Push and open PRs through `/l3east:ship` with no confirmations.
- **Merge only when the user's own `/l3east:sleep` message says so** (`/l3east:sleep merge ...`, or words like "merge ได้", "merge it"). Without that, stop at merge-ready.
- A granted merge still needs every gate: CI green, no **Act on** from ship's interrogate, verified on the real surface, base is not `main`/`master` or a prod branch. Merge with `gh pr merge --merge --match-head-commit <verified-sha>`. Any gate fails → don't merge, log why, keep going on what's left.
- Never, even here: `AskUserQuestion`, force-push to a shared branch, deploy, prod migration, deleting data. Messages to real people are drafted for the morning report, never sent.

## Run it

1. Follow the **Autonomous run** playbook of `pstack:poteto-mode`. Write the exit condition as a checkable predicate first.
2. Keep the decision log with `pstack:show-me-your-work` at `.audit/sleep-<task-slug>.tsv` in the work dir (not committed). First row: the task and the predicate.
3. Decide every fork yourself, by tier, and log each one above tier 1:

   | tier | looks like | do |
   |---|---|---|
   | 1 easy | naming, an option the repo already uses | decide, no row needed |
   | 2 observable | faster? passes? renders? | prototype it, let the result decide |
   | 3 judgment | design, tradeoff, two sane options | spawn 2-3 subagents on different models, each argues one option against the code; you pick and log every side's best point |
   | 4 user-only | product or requirement call | take the safest default, log "if wrong, tell me X", keep going |

4. A call blocked by auto mode or a missing permission: log it with result `blocked`, never retry the same call, do the rest of the work.
5. After a compaction, a resume, or a wait for a usage limit to reset, read the log tail and the todo list before the next step. The limit wait itself is handled by Claude Code, not by you.

## Ending

A Stop hook sends you back to work until your last message ends with one of these lines. Never print one early.

- `SLEEP-DONE` when the predicate is met (merge-ready, or merged when granted).
- `SLEEP-BLOCKED: <reason>` when every remaining step needs the user or an irreversible action.

Before that line, write the morning report:

- the predicate and its final state
- each PR (URL) and its merge state, with the gate that stopped a merge
- tier 3 and 4 decisions only, one line each with its log row timestamp, so the user can find a wrong call fast
- the **Attention** section from show-me-your-work's cross-model review of the log
- drafted messages waiting for approval
- everything skipped or blocked, and why
