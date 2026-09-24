# Backend startup fails: `KeyError: 'stations'`

- **Date seen:** 2026-09-24
- **Area:** Config (`app/config/machine_config.yaml`)
- **Severity:** High: backend would not start
- **Status:** Fixed (the file matches the committed version again)
- **Fix commit(s):** none needed: the broken edit was never committed

## Summary
A manual edit left two spaces in front of the top-level `stations:` key. In
YAML that moved the whole stations list inside the `redis:` block, so the
config had no `stations` key and startup failed.

## Symptom
```
File "app/config/config_loader.py", line 716, in resolve_config_for_part
    stations=raw["stations"],
KeyError: 'stations'
ERROR:    Application startup failed. Exiting.
```
The same `KeyError` also made `tests/test_lucid_strobe.py::test_machine_config_station1_strobe_is_off_until_wired` fail.

## Diagnosis
- `git diff HEAD -- backend/app/config/machine_config.yaml` showed a single
  change: `-stations:` / `+  stations:` at line 194.
- An editor fix had been reported, but the file on disk still had the indent.
  The edit probably wasn't saved, or was made to a different copy (there are
  `machine_config copy.yaml` files next to it).

## Root cause
YAML nesting is set only by indentation, so a stray indent silently changes
the file's structure. The loader then reports a missing key rather than an
indentation problem, which makes the message hard to connect to the real cause.

## Actions taken
- Removed the two spaces (`stations:` back at column 0) and checked that the
  config loads: stations `s1, s2, r1, exit1`.

## Prevention
- Tests that load the real `machine_config.yaml` already catch this. Run
  `pytest` (or at least `tests/test_lucid_strobe.py`) after hand-editing the
  config and before restarting the backend.
- **Follow-up (suggested):** make `resolve_config_for_part` raise a clear
  error when a required top-level key is missing, for example "machine_config.yaml
  has no top-level 'stations:' -- check its indentation".
- Avoid keeping `machine_config copy*.yaml` files next to the real one. It's
  easy to edit the wrong file.
