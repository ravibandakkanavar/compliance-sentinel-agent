# Project instructions

## Committing

Do not commit or push after individual edits. Commit and push once per completed feature:
when a feature (or a self-contained fix) is fully built and working, run

```bash
bash .claude/hooks/auto-commit.sh "<short description of the feature>"
```

This stages everything, makes one commit with that message, and pushes. Half-finished
work, exploratory edits, and answers to questions do not get a commit.
