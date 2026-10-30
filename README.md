# Claude session widget

**A small always-on-top panel that shows every Claude Code session you have open, and which ones need you.**

If you run several Claude Code sessions in different Terminal tabs, it is easy to lose track of the one quietly waiting for an answer. This panel sits in the corner of your screen, lists each session by its chat title, and pulses the ones that are waiting on you. Click a card to jump straight to that tab.

<p align="center">
  <img src="docs/panel.png" alt="The widget panel listing five Claude Code sessions. Two are outlined and pulsing: one waiting for permission and one waiting for input. The others are watching a background job, working, and idle." width="354">
</p>

---

## Contents

- [What it shows](#what-it-shows)
- [Requirements](#requirements)
- [Install](#install)
- [Using the panel](#using-the-panel)
- [Commands](#commands)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Updating and uninstalling](#updating-and-uninstalling)
- [Privacy](#privacy)
- [Development](#development)
- [License and contact](#license-and-contact)

---

## What it shows

Each card is one Claude Code session.

- **The title** is the name Claude Code gives the chat. Before it has one, the card shows the project folder name.
- **The second line** is the start of your last prompt, or what Claude is waiting on.
- **The word on the right** is the session's status.

| Status | Meaning | Card |
| --- | --- | --- |
| **permission** | Claude wants you to approve a tool call. | Pulses, with a macOS banner |
| **needs you** | Claude finished its turn and is waiting for your reply. | Pulses, with a macOS banner |
| **working** | Claude is busy on your last prompt. | Steady |
| **watching** | Claude is waiting on something it started: a background job, a subagent, a timer or a watcher. | Steady |
| **idle** | Nothing is happening in this session. | Steady |

Sessions that need you always sort to the top.

---

## Requirements

- **macOS.** The panel, banners and tab switching all use macOS features.
- **Apple's Terminal app** for click-to-jump. The panel works with other terminals, but clicking a card only switches tabs in Terminal.
- **Claude Code** with plugin support.
- **`python3` on your `PATH`, with Tkinter.** Anaconda, Miniconda and the python.org installer all include Tkinter. Check yours with:

```bash
python3 -c "import tkinter; print('tkinter ok')"
```

If that prints an error, install Python from [python.org](https://www.python.org/downloads/macos/) or use a conda Python. Homebrew users can run `brew install python-tk`.

No other packages are needed. The widget uses only the Python standard library.

---

## Install

Inside any Claude Code session, run these two commands:

```text
/plugin marketplace add alexiahartzell/claude-session-widget
/plugin install session-widget@session-widget
```

Then **quit and start a new Claude Code session.** The panel appears in the bottom-right corner of your screen.

**The first time you click a card**, macOS asks whether Python may control Terminal. Click **OK**, or click-to-jump will not work.

Prefer the terminal? The same install works from your shell:

```bash
claude plugin marketplace add alexiahartzell/claude-session-widget
claude plugin install session-widget@session-widget
```

---

## Using the panel

- **It starts by itself** when any Claude Code session starts. There is nothing to launch.
- **Click a card** to bring its Terminal tab to the front.
- **Drag anywhere on the panel** to move it. It remembers where you put it.
- **Click ×** to hide the panel. It comes back on its own as soon as a session needs you.
- **It hides itself** about thirty seconds after your last session closes.

Only one panel ever runs, however many sessions you open.

---

## Commands

Run these inside any Claude Code session:

| Command | What it does |
| --- | --- |
| `/session-widget:widget show` | Show the panel. |
| `/session-widget:widget hide` | Hide the panel until a session needs you. |
| `/session-widget:widget quit` | Close the panel completely. It restarts with your next session. |
| `/session-widget:widget name <text>` | Give the current session a custom title on its card. |
| `/session-widget:widget name` | Clear the custom title. |

---

## How it works

There are two small Python programs and no background service.

```text
 Claude Code session ──hook events──▶ session-state.py ──writes──▶ ~/.claude/widget/sessions/<id>.json
                                                                                 │
                         macOS banner ◀── widget.py (the panel) ◀──reads twice a second
```

1. **Claude Code runs `session-state.py` on its hook events.** These are session start and end, each prompt you send, each finished turn, permission requests, and a few tool calls.
2. **The hook writes one small status file per session.**
3. **`widget.py` reads those files twice a second** and redraws the panel when anything changes.
4. **When a session starts needing you**, the panel posts a macOS banner and reappears if it was hidden.

A few details:

- **Sessions you started before installing** still appear. The panel reads Claude Code's own list of running sessions to fill the gaps.
- **Chat titles** come from Claude Code's transcript for each session.
- **Closed sessions disappear** as soon as their process ends. Anything untouched for twelve hours is cleared too.
- **Scripted runs such as `claude -p`** are ignored, since there is no tab to jump to.
- **Hooks never block Claude.** Each one finishes in a fraction of a second and always exits cleanly, even on an error.

---

## Configuration

### State folder

Status files, logs and the panel position live in `~/.claude/widget/`. To use another folder, set `CLAUDE_WIDGET_HOME` in the environment Claude Code starts from:

```bash
export CLAUDE_WIDGET_HOME="$HOME/.local/state/claude-widget"
```

### Card colours

Cards are grey unless a colour file exists for that session's Terminal tab. Each file sits in `~/.claude/tint-state/` and is named after the tab's device, with `/` replaced by `_`. For example, `_dev_ttys003.json`:

```json
{ "tint": "1e3a5f", "name": "navy" }
```

- **`tint`** is the tab's background colour as six hex digits.
- **`name`** is a word shown on idle cards, such as "navy tab".

Find a tab's device by running `tty` in it. The panel brightens the colour for the card outline, so dark tab colours work well.

---

## Troubleshooting

**Check the logs first.** They are in your state folder:

```bash
cat ~/.claude/widget/widget.log   # the panel
cat ~/.claude/widget/hooks.log    # the hook script
```

**The panel never appears.**

- Check that `python3` has Tkinter, using the command under [Requirements](#requirements).
- Check that Claude Code found `python3`. Claude Code uses the `PATH` of the shell it was started from.
- Start a fresh Claude Code session after installing. Sessions already open do not pick up new plugins.
- Run `/session-widget:widget show` in case the panel is hidden.

**Clicking a card does nothing.**

- Click-to-jump only works in Apple's Terminal app.
- Allow Python to control Terminal under **System Settings → Privacy & Security → Automation**.

**No banners appear.**

- The banners come from AppleScript, so macOS usually lists them under **Script Editor**. Allow them in **System Settings → Notifications → Script Editor**.
- Focus modes and Do Not Disturb hide them too.

**A card stays after its session closed.**

- It clears on the next refresh once the process has ended. If it does not, run `/session-widget:widget quit`, then start a new session.

**You set the widget up by hand before installing the plugin.**

- Remove the old `session-state.py` hook entries from `~/.claude/settings.json`. Otherwise every event runs twice. That is harmless but wasteful.

---

## Updating and uninstalling

Update to the newest version:

```text
/plugin marketplace update session-widget
/plugin update session-widget@session-widget
```

Uninstall:

```text
/session-widget:widget quit
/plugin uninstall session-widget@session-widget
/plugin marketplace remove session-widget
```

Then delete the state folder if you like:

```bash
rm -rf ~/.claude/widget
```

---

## Privacy

Everything stays on your Mac.

- **No network access.** The widget never sends anything anywhere.
- **What it reads:** Claude Code's list of running sessions, and the end of each session's transcript to find its title and what it is waiting on.
- **What it stores:** the first sixty characters of your latest prompt in each session, in the state folder. Each file is deleted when its session ends.

---

## Development

### Layout

```text
.claude-plugin/
  plugin.json         the plugin manifest
  marketplace.json    lets this repository act as its own plugin source
hooks/hooks.json      which Claude Code events run the hook script
commands/widget.md    the /session-widget:widget command
scripts/
  session-state.py    the hook script, plus the command line behind /widget
  widget.py           the Tkinter panel
  widgetlib.py        shared helpers, with no Tkinter, so they are easy to test
tests/                pytest suite for the hook and the helpers
docs/panel.png        the screenshot above
```

### Run the tests

```bash
python3 -m pytest tests
```

### Try a local copy

Load your working copy into one Claude Code session without installing it:

```bash
claude --plugin-dir /path/to/claude-session-widget
```

Use a separate state folder while testing, so a test panel does not fight your everyday one:

```bash
CLAUDE_WIDGET_HOME=/tmp/widget-test claude --plugin-dir /path/to/claude-session-widget
```

Check the plugin files before a release:

```bash
claude plugin validate .
```

---

## License and contact

Released under the [MIT License](LICENSE).

Questions, bugs or ideas are welcome as a [GitHub issue](https://github.com/alexiahartzell/claude-session-widget/issues).
