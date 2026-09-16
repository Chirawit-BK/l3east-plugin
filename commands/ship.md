---
name: ship
description: Push the current branch and prepare a PR title and description
---

You are my "push and PR" assistant for this repo.

When I run this command, it means:

- I have already committed my changes (use the /commit command separately).
- I want you to help me push the current branch, and if appropriate, prepare a PR title and description.
- There are no extra arguments — infer context from:
  - git status
  - git log (recent commits)
  - current branch name

---

## 🔁 Flow

Follow this checklist, using Bash / Read tools where appropriate:

1. **Check branch & status**

   - Detect current branch: `git rev-parse --abbrev-ref HEAD`.
   - Run `git status -sb` and summarize:
     - are there uncommitted changes?
     - is the branch ahead/behind its remote?
   - If there are uncommitted changes:
     - ask me whether to stop (so I can run `/commit`), or proceed with push-only for already committed work.

2. **Decide branch category**

   Classify the current branch into one of these:

   - **Main branches** (no PR needed):
     - Names like: `main`, `master`, `dev`, `develop` (and treat similar trunk branches as main if obvious).
   - **Ticket-style branches**:
     - Branch includes ticket codes like `ABC-123`, for example:
       - `bug/MSM-122_MSM-231`
       - `feat/MSM-10-add-filter`
     - Treat any token that looks like `ABC-123` as a ticket code.
   - **Issue-based branches**:
     - Pattern like: `bug/issue-43`, `improve/issue-23`, etc.
   - **Other branches**:
     - Anything else, e.g.:
       - `bug/fix-something`
       - `feat/add-payment-filter`
       - `hotfix/xyz`

3. **Push logic**

   - Ask me to confirm before pushing:
     - Show branch name and ahead/behind status.
   - Upon confirmation, run:
     - `git push` (or `git push -u origin <branch>` if no upstream is set yet).
   - After the push, continue depending on the branch category.

4. **Main branches (`main`, `dev`, `develop`, etc.)**

   - For main/trunk branches:
     - Do **not** prepare a PR.
     - Just:
       - confirm that the branch has been pushed
       - show the remote tracking status briefly
     - End the flow.

5. **Ticket-style branches (e.g. `bug/MSM-122_MSM-231`)**

   - Extract all ticket codes that match the pattern `ABC-123` from the branch name.
     - Example:
       - Branch: `bug/MSM-122_MSM-231`
       - Tickets: `MSM-122`, `MSM-231`
   - Infer a short summary of the change from the recent commits and/or diff.

   **PR title:**

   - Build a title that includes the tickets, for example:

     ```text
     [MSM-122][MSM-231] Fix double charge in payment history
     ```

   **PR description:**

   - Use this template and fill it with real content:

     ```md
     **Title**
     [MSM-122][MSM-231] <short summary>

     ---

     ## 🎫 Tickets

     - [MSM-122](https://abboncorp.atlassian.net/browse/MSM-122)
     - [MSM-231](https://abboncorp.atlassian.net/browse/MSM-231)

     ## 🛠️ What's new / Changes / Fixes

     - ...

     ## Testing

     - [ ] How it was tested
     - [ ] Commands or scenarios used
     - [ ] Any missing tests or follow-ups

     ## 📝 Notes

     - ...

     ## Impact / Risk

     - What could break?
     - Any migrations, config changes, or deployment notes?

     ## Screenshots (if UI)

     - Before:
     - After:
     ```

   - Fill in:

     - `<short summary>` with a concise description.
     - Concrete bullet points under **Changes**.
     - Any relevant details under **Testing**, **Notes**, and **Impact / Risk**.

   - Show me the final PR title + description as Markdown so I can copy-paste into the Git hosting UI.
   - **Do not** include any AI-signature text like `Generated with Claude Code`.

6. **Issue-based branches (`bug/issue-43`, `improve/issue-23`, etc.)**

   - Extract the issue number(s) from the branch name, e.g.:
     - `bug/issue-43` → `43`
   - Assume the repo uses `#<number>` to refer to issues (e.g. GitHub issues).

   **PR title:**

   - Create a short, descriptive title based on the recent work, optionally including the issue reference, for example:

     ```text
     Fix payment history filter (issue #43)
     ```

   **PR description:**

   - Use this structure:

     ```md
     **Title**
     Fix payment history filter (issue #43)

     ---

     ## Issue

     - #43

     ## Summary

     - ...

     ## Changes

     - ...

     ## Testing

     - [ ] How it was tested
     - [ ] Commands or scenarios used

     ## Notes

     - ...

     ## Impact / Risk

     - ...
     ```

   - Fill based on the recent commits and inferred behavior change.
   - Again, no AI-signature text in the PR content.

7. **Other branches (e.g. `bug/fix-something`, `feat/add-payment-filter`)**

   - No ticket codes and no `issue-<n>` pattern.
   - Create a normal PR:

     **PR title:**

     - Short, clear, human-readable summary of the change.

     **PR description:**

     ```md
     **Title**
     <short summary>

     ---

     ## Summary

     - ...

     ## Changes

     - ...

     ## Testing

     - [ ] How it was tested
     - [ ] Commands or scenarios used

     ## Notes

     - ...

     ## Impact / Risk

     - ...
     ```

   - Fill in based on the latest commits/diff.
   - Do not add any AI-signature text.

8. **Optional: offer `gh pr create`**

   - If `gh` CLI is available and configured:

     - Offer to create a PR automatically, e.g.:

       ```bash
       gh pr create --title "<title>" --body "<body>"
       ```

     - Always show me the title and body first, and ask for explicit confirmation before running any `gh pr` command.

---

## 🧠 General rules

- When in doubt, ask me instead of guessing.
- Keep explanations short and focused: this is a “push & PR” command.
- Never add "Generated with Claude Code" or similar AI-signature text into commits or PRs.
