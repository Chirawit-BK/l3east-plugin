import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "sleep"))
import shell_gate  # noqa: E402

REFUSED = {
    "comment line above": "# push the branch\ngit push origin main",
    "inline comment": "git status  # check\ngit push origin main",
    "mid-word hash": "echo a#b && gh pr merge 5 --admin",
    "for loop": "for i in 1 2; do gh pr merge $i --admin; done",
    "if block": "if true; then git push origin dev; fi",
    "brace group": "{ git push origin main; }",
    "sudo with value": "sudo -u root git push origin main",
    "nice with value": "nice -n 5 git push origin main",
    "timeout": "timeout 60 git push origin main",
    "caffeinate": "caffeinate -i git push origin main",
    "env -u": "env -u FOO git push origin main",
    "xargs": "echo main | xargs -n 1 git push origin",
    "bash -lc": "bash -lc 'git push origin main'",
    "here-string": "bash -s <<< 'git push origin main'",
    "env -S": "env -S 'git push origin main'",
    "eval": "eval 'git push origin main'",
    "variable branch": "B=main; git push origin $B",
    "variable gh subcommand": "V=merge; gh pr $V 5",
    "ansi-c quoting": "gh pr $'merge' 5 --repo o/r --squash",
    "backtick": "echo `git push origin main`",
    "backtick with split words": 'echo `g""h pr mer""ge 5 --repo o/r --squash --match-head-commit abc1234`',
    "glob refspec": "git push origin 'refs/heads/*'",
    "bundled -dv": "git push -dv origin feat/x",
    "bundled -ud": "git push -ud origin feat/x",
    "line continuation": "git push origin \\\nmain",
    "config-env": "git --config-env x=HOME push origin main",
    "inline alias": "git -c alias.p=push p origin main",
    "remote push config": "git -c remote.origin.push=refs/heads/x:refs/heads/main push origin x",
    "api ref write": "gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=1",
    "api contents write": "gh api repos/o/r/contents/a.txt -f message=x",
    "api merge via curl": "curl -X PUT https://api.github.com/repos/o/r/pulls/5/merge",
    "api merges endpoint": "gh api -X POST repos/o/r/merges -f base=feat -f head=x",
    "bare push": "git push",
    "push HEAD": "git push origin HEAD",
    "push to dev with -C": "git -C ../wt push origin dev",
    "delete refspec": "git push origin :feat/x",
    "force": "git push -f origin feat/x",
    "force refspec": "git push origin +feat/x",
    "unknown gh command": "gh m 5",
}

ALLOWED = {
    "switch": "git switch feat/x",
    "checkout": "git checkout feat/x",
    "log": "git log --oneline -5",
    "diff with substitution": "git diff $(git merge-base HEAD origin/dev)..HEAD",
    "show": "git show abc123:README.md",
    "fetch": "git fetch origin dev",
    "local merge": "git merge origin/dev",
    "pr view": "gh pr view 5 --json mergeStateStatus",
    "pr checks": "gh pr checks 5 --watch",
    "pr create mentioning merge": 'gh pr create --title "fix merge conflict" --body "ready to merge"',
    "commit mentioning push": 'git commit -m "explain git push flow"',
    "api read": "gh api repos/o/r --jq '[.allow_merge_commit]'",
    "label named merge": "gh pr edit 5 --add-label merge",
    "search merge": "gh pr list --search merge",
    "push own branch": "git push -u origin feat/x",
    "force with lease": "git push --force-with-lease origin feat/x",
    "status in worktree": "git -C ../wt status",
    "grep log": "gh run view 1 --log | grep -i merge",
    "polling loop": ('while true; do s=$(gh pr view 5 --json mergeStateStatus -q .mergeStateStatus); '
                     '[ "$s" = CLEAN ] && break; sleep 30; done'),
    "push then pr into main": "git push -u origin feat/x && gh pr create --base main --fill",
}


class ShellGateTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(shell_gate, "git_alias", return_value=None)
        self.alias = patcher.start()
        self.addCleanup(patcher.stop)

    def test_refused(self):
        for label, command in REFUSED.items():
            reason, merges, _ = shell_gate.check(command)
            self.assertTrue(reason or merges, f"{label}: {command!r}")

    def test_allowed(self):
        for label, command in ALLOWED.items():
            reason, merges, _ = shell_gate.check(command)
            self.assertIsNone(reason, f"{label}: {command!r}")
            self.assertEqual(merges, [], f"{label}: {command!r}")

    def test_merge_calls_are_returned_for_the_grant_check(self):
        reason, merges, argvs = shell_gate.check("sudo gh pr merge 5 --repo o/r --squash")
        self.assertIsNone(reason)
        self.assertEqual(merges, [["gh", "pr", "merge", "5", "--repo", "o/r", "--squash"]])
        self.assertEqual(argvs, [["sudo", "gh", "pr", "merge", "5", "--repo", "o/r", "--squash"]])

    def test_git_alias_that_pushes_is_refused_and_read_alias_passes(self):
        self.alias.side_effect = lambda alias, cwd: {"pm": "push origin main", "co": "checkout",
                                                     "sh": "!git push origin dev"}.get(alias)
        self.assertIn("main", shell_gate.check("git pm")[0])
        self.assertIn("dev", shell_gate.check("git sh")[0])
        self.assertIsNone(shell_gate.check("git co feat/x")[0])

    def test_unbalanced_quotes_refuse_only_git_or_gh(self):
        self.assertIsNotNone(shell_gate.check("git commit -m 'oops")[0])
        self.assertIsNone(shell_gate.check("echo 'oops")[0])


if __name__ == "__main__":
    unittest.main()
