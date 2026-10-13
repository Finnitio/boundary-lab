# Fork-local agent config

Fork-local agent config: versioned on orphan branch `agent-config` (worktree `.agent/`, ignored via `.git/info/exclude` like the root `CLAUDE.md` stub and `.claude/`). Never commit them to feature branches or include them in PRs. Shell permission rules: `.agent/rules.json` (read by the shared hook in `~/.claude-config`).

## Agent skills

### Issue tracker

Local markdown under `.agent/work/<feature>/` (fork-local, never upstream); PRs go from fork `Finnitio/boundary-lab` branches to upstream. See `.agent/docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `.agent/docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` + `docs/adr/`. See `.agent/docs/agents/domain.md`.
