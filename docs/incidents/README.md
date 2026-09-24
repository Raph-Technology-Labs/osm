# Incident reports (postmortems)

One file per problem found and fixed: what went wrong, how it was diagnosed,
the root cause, what was done, and how to stop it happening again. This is
the "incident report" / "postmortem" practice from software operations. The
reports are **blameless**: they describe the system and the process, not who
made a mistake.

**Naming:** `YYYY-MM-DD-short-slug.md` (the date the problem was seen). Add a
row to the index below in the same commit as the report.

**When to write one:** any bug that reached real hardware or a real session,
any bad config that stopped the machine, and any rejected change worth
remembering. Quick typos caught before running don't need one.

## Index

| Date | Report | Area | Severity | Status |
|---|---|---|---|---|
| 2026-09-24 | [Twin frozen / cameras not firing: encoder slipped on motor shaft](2026-09-24-encoder-slipped-on-motor-shaft.md) | Indexer hardware / PLC | High | Root cause found; coupling fix pending |
| 2026-09-24 | [Phantom revolution wraps from encoder dither](2026-09-24-phantom-revolution-wraps.md) | Indexer / dispatcher | High | Fixed `5a7444b` |
| 2026-09-24 | [Station 2 camera behind a 100 Mbit switch](2026-09-24-cam2-100mbit-link.md) | Network / camera | High | Fixed (switch replaced) + `5a7444b` |
| 2026-09-24 | [Dispatcher has no tick source: PLC offline at startup](2026-09-24-plc-offline-at-startup.md) | PLC / session start | High | Worked around; follow-up open |
| 2026-09-24 | [Backend startup fails: `KeyError: 'stations'`](2026-09-24-stations-indent-startup-failure.md) | Config | High | Fixed |
| 2026-09-24 | [Slow session start: 9 s GigE discovery per camera](2026-09-24-slow-session-start-discovery.md) | Camera / session start | Medium | Fixed |
| 2026-09-24 | [Station 2 config review before first run](2026-09-24-station2-config-review.md) | Config / pipeline | Medium | Fixed `781659b` |
| 2026-09-24 | [PLC-register strobe (sb-devNtest) not merged](2026-09-24-plc-strobe-branch-not-merged.md) | Camera / strobe | Medium | Replaced by `781659b` |
| 2026-09-24 | [Colour camera: red shown as blue](2026-09-24-bayer-red-blue-swap.md) | Camera / imaging | Medium | Fixed `781659b` |
| 2026-09-24 | [focus_live lens-setup tool issues](2026-09-24-focus-live-tool-issues.md) | Tooling | Low | Fixed `781659b` |

Severity: **High** = machine can't run or runs wrong; **Medium** = wrong
result or broken feature if it had shipped; **Low** = tooling or usability.

## Template

```markdown
# <Title>

- **Date seen:** YYYY-MM-DD
- **Area:** <indexer / camera / PLC / config / pipeline / UI / tooling>
- **Severity:** High | Medium | Low
- **Status:** Fixed <commit> | Worked around | Open
- **Fix commit(s):** <hash>

## Summary
Two or three sentences a newcomer can follow.

## Symptom
What was actually seen: error text, log lines, screenshots.

## Diagnosis
How the cause was found: commands run, what each one showed.

## Root cause
The actual cause, and why it wasn't caught earlier.

## Actions taken
What was changed (code, config, hardware).

## Prevention
Tests, checks, docs, or process that stop it from happening again.

## Follow-ups
Anything still open, with an owner if known.
```
