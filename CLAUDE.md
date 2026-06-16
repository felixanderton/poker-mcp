# CLAUDE.md

## Agents

| Agent | Purpose |
|---|---|
| `reviewer` | Read-only code review — run before committing |
| `feature-writer` | Implements features from a spec |
| `test-writer` | Writes tests matching project conventions |
| `issue-writer` | Files GitHub issues for bugs and features found during review |
| `project-setup` | Run once at project start to bootstrap everything |

## Conventions

- Make the minimum change needed; do not refactor beyond the task scope
- Read existing code before modifying anything
- Run the `reviewer` agent before committing non-trivial changes
