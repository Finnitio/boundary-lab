# Issue tracker: GitHub (upstream)

This clone is a fork. Issues and specs live on the **upstream** repo `JWSound/boundary-lab`; work happens on branches of the fork `Finnitio/boundary-lab` and lands upstream via pull requests. Use the `gh` CLI for all operations.

`gh` resolves the repo from `origin` (the fork), so always pass `-R JWSound/boundary-lab` for issue and PR commands.

## Conventions

- **Create an issue**: `gh issue create -R JWSound/boundary-lab --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view -R JWSound/boundary-lab <number> --json number,title,body,labels,comments`.
- **List issues**: `gh issue list -R JWSound/boundary-lab --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Make an issue a sub-issue of a parent**: `gh issue create -R JWSound/boundary-lab --parent <parent> ...`, or `gh issue edit -R JWSound/boundary-lab <parent> --add-sub-issue <child>` afterwards (`gh` 2.94+). Older `gh`: `gh api --method POST repos/JWSound/boundary-lab/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>` (database id, as in **Blocking** below). Without sub-issues, put `Part of #<parent>` at the top of the child body.
- **Comment on an issue**: `gh issue comment -R JWSound/boundary-lab <number> --body "..."`
- **Apply / remove labels**: `gh issue edit -R JWSound/boundary-lab <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close -R JWSound/boundary-lab <number> --comment "..."`

Labelling, assigning and closing need upstream write access. If a command fails with a permission error, skip it and leave a comment stating the intended label/state instead.

## Fork / pull request workflow

Remotes: `origin` = fork (`Finnitio/boundary-lab`), `upstream` = `https://github.com/JWSound/boundary-lab.git`.

1. `git fetch upstream`
2. Branch off upstream: `git switch -c fix/<slug> upstream/main` (use `feat/<slug>` for features).
3. Commit with Conventional Commits. Fork-local config (`CLAUDE.md`, `.claude/`, `.agent/`) is untracked via `.git/info/exclude`; never force-add it.
   Create PRs only when the user asks for one, scoped to a single feature or fix.
4. `git push -u origin <branch>`
5. `gh pr create -R JWSound/boundary-lab --base main --head Finnitio:<branch> --title "..." --body "..."`; reference the issue with `Fixes #<n>`.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view -R JWSound/boundary-lab <number> --comments` and `gh pr diff -R JWSound/boundary-lab <number>` for the diff.
- **List external PRs for triage**: `gh api --paginate 'repos/JWSound/boundary-lab/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close` (all with `-R JWSound/boundary-lab`).

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue on `JWSound/boundary-lab`.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets. All commands target `-R JWSound/boundary-lab` (`<owner>/<repo>` = `JWSound/boundary-lab`).

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (see **Make an issue a sub-issue of a parent**). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
