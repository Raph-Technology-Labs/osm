---
name: create-spec
description: Create a new feature spec document from docs/specs/TEMPLATE.md, filled in based on a short description of the feature.
argument-hint: <short-feature-description>
allowed-tools: Read, Write, Bash(git *)
disable-model-invocation: true
---

# Create Spec

Argument: $ARGUMENTS (a short description of the feature)

1. Read `docs/specs/TEMPLATE.md` for the structure — don't invent a different
   shape.
2. Ask clarifying questions if the description doesn't give you enough to
   fill in Problem Statement, Functional Requirements, and Acceptance
   Criteria meaningfully. Don't fabricate acceptance criteria the user hasn't
   actually stated or implied.
3. Create a new file at `docs/specs/<NN>-<kebab-case-feature-name>.md`
   (increment `<NN>` past whatever's already in `docs/specs/`).
4. If this feature touches the indexer or PLC/register layer, explicitly
   reference the relevant Critical Rule number(s) from CLAUDE.md in the
   Constraints section — don't silently assume the reader will remember them.
5. Create a new git branch named `feature/<kebab-case-feature-name>` and
   switch to it, so the spec and its eventual implementation live together on
   one branch from the start.

Stop after creating the spec — do not start writing implementation code in
the same invocation. The spec needs review first (per the SDD workflow in
CLAUDE.md's linked docs), not immediate implementation.
