# Claude session widget

A small always-on-top panel that lists every Claude Code session you have open.

- **A card pulses** when a session needs your input or a permission.
- **Click a card** to jump to that session's Terminal tab.
- **Drag the header** to move the panel. The **×** hides it until a session next needs you.

## Requirements

- **macOS** with Apple's **Terminal** app. Clicking a card does not switch tabs in iTerm or other terminals.
- **`python3` on your PATH with Tkinter.** Anaconda and the python.org installer both include it. Check with:

```
python3 -c "import tkinter; print('ok')"
```

## Install

In any Claude Code session, run:

```
/plugin marketplace add <this repository URL or a local folder path>
/plugin install session-widget@session-widget
```

Then start a new Claude Code session. The panel appears in the bottom-right corner.

## Commands

```
/session-widget:widget show
/session-widget:widget hide
/session-widget:widget quit
/session-widget:widget name <text>
```

`name` gives the current session a custom label on its card.

## Notes

- **State and logs** go to `~/.claude/widget/`. Set `CLAUDE_WIDGET_HOME` to use another folder.
- **Card colours** come from optional per-tab tint files in `~/.claude/tint-state/`. Without them every card is grey.
- **macOS asks once** for permission to let Python control Terminal. Allow it, or clicking a card does nothing.
- **Headless runs** such as `claude -p` are ignored.

## Tests

```
python3 -m pytest tests
```
