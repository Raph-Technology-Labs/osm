# Setup — MCP, Git, First Push

Run these once, in order, after unzipping this into your repo root.

## 1. Environment variables (do this before anything else)

```bash
cp .env.example .env
```

Fill in `.env` with your real `GITHUB_PAT` and `DATABASE_URL`. This file is
gitignored — it will never be committed. Then load it into your shell:

```bash
export $(grep -v '^#' .env | xargs)
```

Add that line (or the two `export` lines individually) to your shell profile
(`~/.zshrc` / `~/.bashrc`) so it's available every session, not just this one.

## 2. Register MCP servers (project-scoped, shared via `.mcp.json`)

```bash
# GitHub — remote, http transport
claude mcp add --transport http --scope project github \
  https://api.githubcopilot.com/mcp \
  -H "Authorization: Bearer $GITHUB_PAT"

# PostgreSQL — local, stdio transport, read-only restricted mode
# (uses postgres-mcp / "Postgres MCP Pro" — the original
#  @modelcontextprotocol/server-postgres is archived/deprecated)
pipx install postgres-mcp   # or: uv pip install postgres-mcp

claude mcp add --transport stdio --scope project postgres -- \
  postgres-mcp --access-mode=restricted \
  --env DATABASE_URI="$DATABASE_URL"
```

`--scope project` writes these into `.mcp.json` at the repo root, referencing
the env vars by name — not the literal secret values — so it's safe to commit
and share with the team. Verify both connected:

```
/mcp
```

You should see `github` and `postgres` listed as `Connected`. If `postgres`
shows disconnected, confirm `DATABASE_URL` is actually exported in the shell
Claude Code is running in.

## 3. Git init and first push

```bash
git init
git add .
git commit -m "initial commit: OSM claude code setup"

git remote add origin https://github.com/Raph-Technology-Labs/raph-vision.git
git checkout -b snehal-dev
git push -u origin snehal-dev
```

(Adjust the remote URL and branch name if this isn't going into the existing
`raph-vision` repo / `snehal-dev` branch — fill in the real target before
running.)

## 4. First session

```bash
claude
```

- Trust the folder when prompted.
- Authorize in the browser window that opens (one-time).
- Ask it: *"What does this project do?"* and *"Explain the project structure
  to me"* — confirms `CLAUDE.md` is being read and the layout matches reality
  before you start delegating real work to it.

## 5. Skills vs. commands — a note on structure

Anthropic merged slash commands into skills (v2.1.3, Jan 2026) — this repo
uses `.claude/skills/<name>/SKILL.md` throughout rather than the older
`.claude/commands/<name>.md` layout. Both still work and both create the same
`/command-name` shortcut, but skills are the recommended path going forward
and win on a name collision, so there's no reason to use the old layout for
anything new.

The five original commands (`new-station`, `check-registers`, `sim-cycle`,
`seed-part`, `ship-feature`) are marked `disable-model-invocation: true` in
their frontmatter — this preserves their original behavior of only running
when you explicitly type `/new-station` etc., rather than Claude deciding on
its own to invoke them.

## 6. Subagents

`.claude/agents/` has four:
- `osm-ring-math-reviewer` — checks changes to the indexer against the three
  specific bugs already found once in this project (raw pulse division,
  conditional position flags, aggregation at the wrong station)
- `osm-plc-safety-reviewer` — checks CMD/ACK pairing, escalation severity,
  hardcoded registers/credentials
- `osm-test-writer` / `osm-test-runner` — write and run tests from the spec,
  not from the implementation (sequential — runner depends on writer)

Two skills orchestrate them: `/test-feature <spec-file>` (sequential) and
`/review-feature` (parallel — the two reviewers are independent).

Run `/agents` inside Claude Code to see them listed, and — per the course's
own advice — don't blindly trust an agent-generated file. Read each one and
confirm it actually matches how you want reviews to work before relying on it.

## 7. Spec-driven development

`docs/specs/TEMPLATE.md` is the spec shape (Problem Statement → Functional
Requirements → API Contract → Constraints → Edge Cases → Acceptance
Criteria). `/create-spec <description>` scaffolds a new one and creates a
matching feature branch. Fill in and get it reviewed *before* asking Claude
Code to implement anything against it — the two review steps (spec review,
then technical-design review) are what catch a wrong assumption before it's
in code, not an optional step to skip when in a hurry.

## Golden rules (worth keeping in mind going forward)

- Keep the MCP server list minimal — every connected server's tool
  descriptions load into context on every session start. Only `github` and
  `postgres` are wired up here; don't add more unless you'll actually use them
  regularly.
- Never commit `.env`, `.claude/settings.local.json`, or `config.yaml` — all
  three are in `.gitignore` already, don't override that.
- The `postgres` MCP server is read-only by design (`--access-mode=restricted`)
  — if you ever need it to write, that's a deliberate decision to reconsider,
  not a default to flip casually.
