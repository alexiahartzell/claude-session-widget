---
description: Session widget. Usage: /widget [show | hide | quit | name <text>]
argument-hint: show | hide | quit | name <text>
allowed-tools: Bash(python3 *session-state.py:*)
---
Result: !`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session-state.py" cmd $ARGUMENTS`

Tell the user the result above in one short line. Do not run anything else.
