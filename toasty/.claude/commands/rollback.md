---
description: Roll back code to a per-prompt git checkpoint. Usage /rollback (last prompt), /rollback 2 (two prompts back), /rollback <hash>
allowed-tools: Bash(git log:*), Bash(git reset:*), Bash(git status:*), Bash(git diff:*), Bash(git show:*), Bash(git reflog:*)
---

## Current repo state
- Recent checkpoints: !`git log --oneline -15`
- Uncommitted changes: !`git status --short | head -30`

## Your task

Roll the working tree back to an earlier git checkpoint. Argument given: "$ARGUMENTS"

Every user prompt automatically creates a "checkpoint: <timestamp>" commit of the state
*before* that prompt's work (via the UserPromptSubmit hook). Note that invoking /rollback
itself also just fired that hook — so if there were uncommitted changes, they were
committed as the newest checkpoint, and HEAD is the state you likely want to undo.

Interpret the argument:
- **No argument**: undo the most recent prompt's changes → `git reset --hard HEAD~1`
- **A number n**: undo the last n prompts → `git reset --hard HEAD~n`
- **A commit hash**: `git reset --hard <hash>`

Before resetting:
1. Show `git log --oneline -5` and state clearly which commit you will reset to and what
   changes (files) will be undone (`git diff --stat <target> HEAD`).
2. Then perform the reset. Do NOT run `git clean` — untracked files (like .env) must survive.

After resetting, show `git log --oneline -3` and `git status --short`, and remind the user:
a rollback is itself recoverable — `git reflog` lists the abandoned checkpoints, and
`git reset --hard <reflog-hash>` returns to them.
