---
description: Show, hide or quit the session panel, rename this card, or mute banners for a while
argument-hint: show | hide | quit | name <text> | mute [minutes] | unmute | summary on|off | pet drop|kit|sprout|off
allowed-tools: Bash(python3 *session-state.py*)
---

Output of the widget command:

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session-state.py" cmd $ARGUMENTS`

Repeat that output to the user in one short line. Do not run anything else.
