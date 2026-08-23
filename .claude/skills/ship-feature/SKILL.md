---
name: ship-feature
description: Commit, push, open a PR, and merge the current feature branch — full git workflow in one shot, via the GitHub MCP server
allowed-tools: Read, Bash(git *), mcp__github__*
disable-model-invocation: true
---

Requires the `github` MCP server to be connected — run `/mcp` first and
confirm it shows "Connected" before using this command.

Do the following, in order, and show the result of each step before moving to
the next:

1. Run `git status` and `git diff` to see what's actually changed. Summarize
   it in plain terms before writing a commit message — don't write a generic
   message.

2. Commit all changes with a conventional-commit-style message
   (`feat:`, `fix:`, `refactor:`, etc.) that accurately describes the change,
   based on what you actually see in the diff, not the branch name.

3. Push to the current branch (not main — confirm the current branch first
   with `git branch --show-current`; if it's `main` or `master`, stop and ask
   before proceeding, don't push directly to main).

4. Create a pull request into `main` via the GitHub MCP server, with a title
   and description generated from the actual diff and, if one exists, the
   relevant spec document.

5. If explicitly asked to merge (don't merge automatically without being
   told): merge using squash merge, switch to `main`, pull latest, and delete
   the feature branch both locally and on the remote.

If any register list, PLC register map, or the `IndexerSlotTracker` file was
touched in this change, flag that explicitly in the PR description — those
changes need a second pair of eyes before merge, per CLAUDE.md.
