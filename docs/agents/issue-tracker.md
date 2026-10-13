# Issue tracker: Local Markdown (fork-local)

Issues and specs live as markdown files in `.agent/work/` — the fork-local `agent-config` worktree. Never in upstream `JWSound/boundary-lab` issues, never in feature branches or PRs. Commit ticket changes on the `agent-config` branch (`git -C .agent ...`).

## Conventions

- One feature per directory: `.agent/work/<feature-slug>/`
- The spec is `.agent/work/<feature-slug>/spec.md` (or a repo spec it links, e.g. `docs/specs/<feature>.md`)
- Implementation issues are one file per ticket at `.agent/work/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`. Legacy: `cad-import/tickets.md` is a single combined file; keep using it for that feature.
- Triage state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.agent/work/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Fork / pull request workflow

Remotes: `origin` = fork (`Finnitio/boundary-lab`), `upstream` = `https://github.com/JWSound/boundary-lab.git`.

1. `git fetch upstream`
2. Branch off upstream: `git switch -c fix/<slug> upstream/main` (use `feat/<slug>` for features).
3. Commit with Conventional Commits. Fork-local config (`CLAUDE.md`, `.claude/`, `.agent/`) is untracked via `.git/info/exclude`; never force-add it.
   Create PRs only when the user asks for one, scoped to a single feature or fix.
4. `git push -u origin <branch>`
5. `gh pr create -R JWSound/boundary-lab --base main --head Finnitio:<branch> --title "..." --body "..."`. Don't reference local ticket paths in PR bodies.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.agent/work/<effort>/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.agent/work/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.agent/work/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
