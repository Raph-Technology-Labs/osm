"""
PreToolUse hook — blocks dangerous shell commands from touching protected files.

Matches the course's block-dangerous.py pattern: only blocks if the command is
BOTH a dangerous operation AND targets a protected file. Extended here to cover
the OSM-specific files where an accidental delete/overwrite is a hardware-safety
issue, not just a code bug (register maps, PLC config, migrations, .env).
"""

import sys
import json

data = json.load(sys.stdin)
command = data.get("tool_input", {}).get("command", "")

# Files/paths where a destructive command is a real-world problem, not just an
# inconvenience -- extend this list rather than replacing it wholesale.
PROTECTED_PATHS = [
    ".env",
    "migrations/",
    "register_map",
    "modbus_client.py",
    "recipes/",
    "config.yaml",
]

DANGEROUS_COMMANDS = ["rm ", "rm-", "unlink", ">", "truncate", "DROP TABLE", "TRUNCATE"]

for dangerous in DANGEROUS_COMMANDS:
    if dangerous in command:
        for protected in PROTECTED_PATHS:
            if protected in command:
                print(
                    f"BLOCKED: cannot run '{command}' -- "
                    f"'{protected}' is a protected path. If this is intentional, "
                    f"run it manually outside Claude Code.",
                    file=sys.stderr,
                )
                sys.exit(2)

sys.exit(0)
