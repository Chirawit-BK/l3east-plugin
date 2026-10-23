"""Judge a shell command for the sleep hook: find every git and gh call wherever it sits, and refuse the pushes and
merges it cannot resolve. Reads and local-only commands pass. This is a text check, not a sandbox."""
from __future__ import annotations

import os
import re
import shlex
import subprocess

SEPARATOR_CHARS = set("&|;()")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
NESTED_DEPTH = 3
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                  "--attr-source", "--super-prefix"}
RISKY_GIT_CONFIG_RE = re.compile(r"^(alias\.|remote\..*\.push|push\.|url\..*\.pushinsteadof)", re.I)
KNOWN_GIT_COMMANDS = {
    "add", "am", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file", "check-ignore", "checkout",
    "cherry", "cherry-pick", "clean", "clone", "commit", "config", "describe", "diff", "difftool", "fetch",
    "for-each-ref", "format-patch", "fsck", "gc", "grep", "help", "init", "log", "ls-files", "ls-remote", "ls-tree",
    "merge", "merge-base", "mv", "notes", "pull", "push", "range-diff", "rebase", "reflog", "remote", "reset",
    "restore", "rev-list", "rev-parse", "revert", "rm", "shortlog", "show", "show-ref", "sparse-checkout", "stash",
    "status", "submodule", "switch", "symbolic-ref", "tag", "update-index", "version", "whatchanged", "worktree",
}
PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSH_BANNED_OPTS = {"--all", "--mirror", "--delete", "--prune", "--force"}
GH_VALUE_OPTS = {"-R", "--repo", "--hostname"}
KNOWN_GH_COMMANDS = {
    "alias", "api", "attestation", "auth", "browse", "cache", "codespace", "completion", "config", "extension",
    "gist", "gpg-key", "help", "issue", "label", "org", "pr", "project", "release", "repo", "ruleset", "run",
    "search", "secret", "ssh-key", "status", "variable", "workflow",
}
API_MERGE_RE = re.compile(r"/pulls/\d+/merge\b|/merges\b|mergePullRequest|mergeBranch|enablePullRequestAutoMerge")
API_REF_WRITE_RE = re.compile(r"/git/refs\b|/contents/|updateRef|createRef|deleteRef|createCommitOnBranch")
API_WRITE_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}
UNRESOLVED_RE = re.compile(r"[$`*?\[]")
SHELL_SCRIPT_FLAG_RE = re.compile(r"-[a-zA-Z]*c[a-zA-Z]*")
PROTECTED_BRANCHES = {"main", "master", "dev", "develop"}
FORCE = "force-push is not allowed (use --force-with-lease on your own branch)"


def name(program: str) -> str:
    return os.path.basename(program)


def segments(command: str, depth: int = 0) -> list[list[str]]:
    """Every simple command's argv, plus the commands inside quoted scripts (bash -c, eval, "$( )"). ValueError if
    the quoting does not balance."""
    text = command.replace("\\\n", "").replace("`", " ; ").replace("\n", " ; ")
    lex = shlex.shlex(text, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    found, current = [], []
    for token in lex:
        if set(token) <= SEPARATOR_CHARS:
            found.append(current)
            current = []
        else:
            current.append(token)
    found.append(current)
    result = []
    for argv in (a for a in found if a):
        result.append(argv)
        if depth < NESTED_DEPTH:
            for k in range(1, len(argv)):
                if is_script(argv, k):
                    result.extend(segments(argv[k], depth + 1))
    return result


def is_script(argv: list[str], k: int) -> bool:
    """Whether argv[k] is shell code that will run: bash -c/-lc, eval, env -S, a here-string, or "$( )"."""
    prev = argv[k - 1]
    return ("$(" in argv[k]
            or (SHELL_SCRIPT_FLAG_RE.fullmatch(prev) is not None and any(name(t) in SHELLS for t in argv[:k - 1]))
            or prev in ("-S", "--split-string", "<<<")
            or any(name(t) == "eval" for t in argv[:k]))


def calls(argv: list[str], tool: str) -> list[list[str]]:
    """Each slice of argv that starts at a token naming `tool`, so any prefix (sudo -u x, timeout 9, nice -n 5)
    is ignored."""
    return [argv[i:] for i, token in enumerate(argv) if name(token) == tool]


def git_alias(alias: str, cwd: str | None) -> str | None:
    try:
        res = subprocess.run(["git", "config", "--get", f"alias.{alias}"], capture_output=True, text=True,
                             timeout=5, cwd=cwd if cwd and os.path.isdir(cwd) else None)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout.strip() or None if res.returncode == 0 else None


def git_problem(argv: list[str], cwd: str | None, depth: int = 0) -> str | None:
    """Why this git call is refused during a sleep run, or None. Only pushes, and calls that could be pushes."""
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        if argv[i] in GIT_VALUE_OPTS:
            value = argv[i + 1] if i + 1 < len(argv) else ""
            if argv[i] in ("-c", "--config-env") and RISKY_GIT_CONFIG_RE.match(value):
                return "git -c alias or push config is not allowed"
            i += 2
        else:
            i += 1
    if i >= len(argv):
        return None
    sub, rest = argv[i], argv[i + 1:]
    if UNRESOLVED_RE.search(sub):
        return f"cannot tell what 'git {sub}' does; write the git subcommand plainly"
    if sub == "push":
        return push_problem(rest)
    if sub in KNOWN_GIT_COMMANDS or depth > 0:
        return None
    expansion = git_alias(sub, cwd)
    if not expansion:
        return None
    if expansion.startswith("!"):
        return check(expansion[1:] + " " + shlex.join(rest), cwd, depth + 1)[0]
    try:
        return git_problem(["git", *shlex.split(expansion), *rest], cwd, depth + 1)
    except ValueError:
        return f"cannot read the git alias '{sub}'"


def push_problem(rest: list[str]) -> str | None:
    positional, rest = [], list(rest)
    while rest:
        token = rest.pop(0)
        if token in PUSH_VALUE_OPTS:
            rest = rest[1:]
        elif token in PUSH_BANNED_OPTS or token.startswith("--force="):
            return f"git push {token} is not allowed"
        elif re.fullmatch(r"-[a-zA-Z]+", token) and set(token) & set("df"):
            return "git push -d / -f are not allowed (use --force-with-lease on your own branch)"
        elif not token.startswith("-"):
            positional.append(token)
    if any(UNRESOLVED_RE.search(t) for t in positional):
        return "name the remote and branch literally (no $, backticks or globs) in a push"
    if len(positional) < 2:
        return "name the remote and the branch explicitly: git push <remote> <branch>"
    for ref in positional[1:]:
        if ref.startswith("+"):
            return FORCE
        source, _, dest = ref.partition(":") if ":" in ref else (ref, "", ref)
        dest = dest.removeprefix("refs/heads/")
        if not source or not dest:
            return "deleting a remote branch is not allowed"
        if dest in ("HEAD", "@"):
            return "name the destination branch explicitly instead of HEAD"
        if dest in PROTECTED_BRANCHES:
            return f"never push to {dest}"
    return None


def gh_command(argv: list[str]) -> tuple[str | None, list[str]]:
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        i += 2 if argv[i] in GH_VALUE_OPTS else 1
    return (argv[i], argv[i + 1:]) if i < len(argv) else (None, [])


def gh_problem(argv: list[str]) -> tuple[str | None, bool]:
    """(why this gh call is refused, whether it is a `gh pr merge`). Only merges and ref writes count."""
    command, rest = gh_command(argv)
    if command is None:
        return None, False
    if UNRESOLVED_RE.search(command):
        return f"cannot tell what 'gh {command}' does; write it plainly", False
    if command == "pr":
        sub, _ = gh_command(["gh", *rest])
        if sub and UNRESOLVED_RE.search(sub):
            return f"cannot tell what 'gh pr {sub}' does; write it plainly", False
        return None, sub == "merge"
    if command == "api":
        if any(API_MERGE_RE.search(t) for t in rest):
            return "merging through gh api is not allowed; use the one gh pr merge form", False
        writes = any(t in API_WRITE_FLAGS or re.fullmatch(r"(-X|--method)(=?)(PUT|PATCH|POST|DELETE)", t) or
                     t.upper() in ("PUT", "PATCH", "POST", "DELETE") for t in rest)
        if writes and any(API_REF_WRITE_RE.search(t) for t in rest):
            return "writing refs or files through gh api is not allowed", False
        return None, False
    if command not in KNOWN_GH_COMMANDS:
        return f"unknown gh command '{command}' (an alias?) is not allowed during a sleep run", False
    return None, False


def check(command: str, cwd: str | None = None, depth: int = 0) -> tuple[str | None, list[list[str]], list[list[str]]]:
    """(denial reason or None, the gh pr merge calls found, all segments). Merges are left to the caller's grant
    and form checks; everything else that is refused gets a reason here."""
    try:
        argvs = segments(command)
    except ValueError:
        if re.search(r"\b(git|gh)\b", command):
            return "this command's quoting does not balance, and it calls git or gh; rewrite it", [], []
        return None, [], []
    merges = []
    for argv in argvs:
        for call in calls(argv, "git"):
            problem = git_problem(call, cwd, depth)
            if problem:
                return problem, merges, argvs
        for call in calls(argv, "gh"):
            problem, is_merge = gh_problem(call)
            if problem:
                return problem, merges, argvs
            if is_merge:
                merges.append(call)
        if any(API_MERGE_RE.search(t) for t in argv) and not calls(argv, "gh"):
            return "merging through the GitHub API is not allowed; use the one gh pr merge form", merges, argvs
    return None, merges, argvs


def looks_risky(command: str, cwd: str | None = None) -> bool:
    reason, merges, _ = check(command, cwd)
    return bool(reason or merges)
