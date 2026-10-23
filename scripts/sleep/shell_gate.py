"""Read a shell command as argv segments, so the sleep hook gates what runs rather than words in quoted text."""
from __future__ import annotations

import os
import re
import shlex

SEPARATOR_CHARS = set("&|;()")
SHELLS = {"bash", "sh", "zsh"}
WRAPPERS = {"env", "sudo", "command", "nohup", "time", "exec", "xargs", "nice"}
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
PUSH_BANNED_OPTS = {"--all", "--mirror", "--delete", "-d", "--prune"}
API_MERGE_RE = re.compile(r"/pulls/\d+/merge\b|/merges\b|mergePullRequest|mergeBranch|enablePullRequestAutoMerge")
ASSIGNMENT_RE = re.compile(r"^\w+=")
SUBSTITUTION_RE = re.compile(r"\$\(|`|<\(")
RISKY_WORD_RE = re.compile(r"merge|\bpush\b", re.I)
PROTECTED_BRANCHES = {"main", "master", "dev", "develop"}


def segments(command: str) -> list[list[str]]:
    """Each simple command's argv, with wrappers (env, sudo, bash -c, eval) unwrapped. ValueError if unparseable."""
    lex = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    out, current = [], []
    for token in lex:
        if set(token) <= SEPARATOR_CHARS:
            out.append(current)
            current = []
        else:
            current.append(token)
    out.append(current)
    return [unwrapped for argv in out if argv for unwrapped in unwrap(argv)]


def unwrap(argv: list[str]) -> list[list[str]]:
    while argv and (ASSIGNMENT_RE.match(argv[0]) or name(argv[0]) in WRAPPERS):
        argv = argv[1:]
        while argv and (argv[0].startswith("-") or ASSIGNMENT_RE.match(argv[0])):
            argv = argv[1:]
    if not argv:
        return []
    if name(argv[0]) in SHELLS and "-c" in argv[:-1]:
        return segments(argv[argv.index("-c") + 1])
    if name(argv[0]) == "eval":
        return segments(" ".join(argv[1:]))
    return [argv]


def name(program: str) -> str:
    return os.path.basename(program)


def is_merge(argv: list[str]) -> bool:
    return (name(argv[0]) == "gh" and "merge" in argv[1:]) or any(API_MERGE_RE.search(t) for t in argv)


def push_problem(argv: list[str]) -> str | None:
    """Why this git push is not allowed during a sleep run, or None when it is not a push or is fine."""
    if name(argv[0]) != "git":
        return None
    i = 1
    while i < len(argv) and argv[i].startswith("-"):
        i += 2 if argv[i] in GIT_VALUE_OPTS else 1
    if i >= len(argv) or argv[i] != "push":
        return None
    rest, positional = argv[i + 1:], []
    while rest:
        token = rest.pop(0)
        if token in PUSH_VALUE_OPTS:
            rest = rest[1:]
        elif token in PUSH_BANNED_OPTS:
            return f"git push {token} is not allowed"
        elif token in ("--force", "-f") or (re.fullmatch(r"-[a-zA-Z]+", token) and "f" in token):
            return "force-push is not allowed (use --force-with-lease on your own branch)"
        elif not token.startswith("-"):
            positional.append(token)
    if len(positional) < 2:
        return "name the remote and the branch explicitly: git push <remote> <branch>"
    for ref in positional[1:]:
        if ref.startswith("+"):
            return "force-push is not allowed (use --force-with-lease on your own branch)"
        source, _, dest = ref.partition(":") if ":" in ref else (ref, "", ref)
        dest = dest.removeprefix("refs/heads/")
        if not source or not dest:
            return "deleting a remote branch is not allowed"
        if dest in ("HEAD", "@"):
            return "name the destination branch explicitly instead of HEAD"
        if dest in PROTECTED_BRANCHES:
            return f"never push to {dest}"
    return None


def looks_risky(command: str) -> bool:
    """A merge, or a push that would be refused, judged without the grant. Unparseable text counts by its words."""
    try:
        argvs = segments(command)
    except ValueError:
        return bool(RISKY_WORD_RE.search(command))
    if SUBSTITUTION_RE.search(command) and RISKY_WORD_RE.search(command):
        return True
    return any(is_merge(a) or push_problem(a) for a in argvs)
