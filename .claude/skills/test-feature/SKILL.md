---
name: test-feature
description: Writes and runs tests for a specific OSM feature, given its spec file. Pass the spec filename as argument.
argument-hint: <spec-filename>
allowed-tools: Read, Edit, Bash, Task
disable-model-invocation: true
---

# Test Feature

Argument: $ARGUMENTS (a filename under `docs/specs/`)

If no argument is given, tell the user the correct format:
  /test-feature <spec-filename>

**Step 1 — Write tests.** Use the `osm-test-writer` subagent to create test
cases based on the spec file passed as argument. Do not let it look at
implementation code before it's read the spec in full.

**Step 2 — Run tests.** Use the `osm-test-runner` subagent to execute the
tests written in Step 1.

**Final output:**

```
| Total Tests | Passed | Failed | Verdict |
```

These two steps are sequential and must not run in parallel — the runner
depends on the writer's output.
