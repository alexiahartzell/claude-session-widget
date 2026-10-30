#!/usr/bin/env python3
"""Tint Terminal.app tabs a distinct colour per Claude Code session.

Hook use (stdin JSON from Claude Code):
  SessionStart -> pick a palette colour no other open tab uses, apply it.
  SessionEnd   -> restore the tab's original background.
  Set CLAUDE_WIDGET_TINT=off to turn the hook off.

Manual use (the /tint command):
  tint.py all          tint every tab that has a running claude
  tint.py shuffle      give this tab a different random free colour
  tint.py set NAME     give this tab a named palette colour
  tint.py reset        restore this tab's original background
  tint.py list         show the palette and which tab has what
  tint.py scheme NAME  switch colour scheme (auto, muted, jewel, pastel, colourblind)
Only acts inside Apple Terminal.
"""
import json, os, random, subprocess, sys

STATE_DIR = os.path.expanduser("~/.claude/tint-state")

# Colour schemes: (name, hex) backgrounds for Terminal tabs. Every hex is unique
# across schemes, so a tab's colour alone says it was tinted by this script.
SCHEMES = {
    # Dark, muted backgrounds that keep light text readable.
    "muted": [
        ("midnight", "0d1b2a"), ("plum", "1e1026"), ("forest", "0c1f16"), ("wine", "26101a"),
        ("teal", "0c2224"), ("espresso", "211810"), ("indigo", "14132b"), ("moss", "1a200e"),
        ("slate", "171c24"), ("rust", "261410"), ("mulberry", "2a1428"), ("olive", "1f2010"),
        ("cobalt", "0f1a36"), ("sea", "0e2a20"), ("cocoa", "2a1e1a"),
    ],
    # Deeper, more saturated darks that are easier to tell apart at a glance.
    "jewel": [
        ("sapphire", "0d2547"), ("emerald", "0a2e22"), ("ruby", "3a0d1e"), ("amethyst", "1f0f3d"),
        ("amber", "3a2805"), ("turquoise", "05302f"), ("garnet", "330a12"), ("jade", "12300a"),
        ("violet", "2d0a3a"), ("copper", "3a1a05"), ("lapis", "0a1a40"), ("magenta", "3a0a2e"),
    ],
    # Light backgrounds for light Terminal profiles with dark text.
    "pastel": [
        ("lavender", "efe6fb"), ("mint", "e2f4e8"), ("rose", "fbe4e6"), ("sky", "e1eefa"),
        ("butter", "fbf3d5"), ("sand", "f1e7dc"), ("aqua", "ddf3f1"), ("blush", "f8e3f0"),
        ("sage", "e9eedf"), ("periwinkle", "e6e6fa"), ("peach", "fdeadb"), ("ice", "e4f1f5"),
    ],
    # Dark versions of the Okabe-Ito palette, chosen to stay distinct with colour blindness.
    "colourblind": [
        ("orange", "3a2800"), ("skyblue", "162d3b"), ("bluegreen", "00281d"), ("yellow", "353210"),
        ("blue", "001d2d"), ("vermillion", "361800"), ("reddishpurple", "33202a"), ("grey", "262626"),
    ],
}
DEFAULT_SCHEME = "auto"              # muted on dark profiles, pastel on light ones
NAMES = {h: n for pal in SCHEMES.values() for n, h in pal}
CONFIG_PATH = os.path.join(STATE_DIR, "scheme.json")


def is_light(h):
    """True when a hex colour is light enough to need dark text."""
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b > 140


def load_scheme():
    try:
        with open(CONFIG_PATH) as f:
            name = json.load(f).get("scheme")
        return name if name in SCHEMES or name == "auto" else DEFAULT_SCHEME
    except Exception:
        return DEFAULT_SCHEME


def save_scheme(name):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump({"scheme": name}, f)


def palette_for(orig, scheme=None):
    """The (name, hex) list to use on a tab whose own background is orig."""
    scheme = scheme or load_scheme()
    if scheme == "auto":
        scheme = "pastel" if is_light(orig) else "muted"
    return SCHEMES[scheme]


def hex_to_as(h):
    return tuple(int(h[i:i+2], 16) * 257 for i in (0, 2, 4))

def as_to_hex(r, g, b):
    return "".join(f"{v // 257:02x}" for v in (r, g, b))

def tty_of_pid(pid):
    """Walk up from pid until a process with a real tty is found."""
    pid = str(pid)
    for _ in range(12):
        try:
            out = subprocess.check_output(
                ["ps", "-o", "ppid=,tty=", "-p", pid], text=True).split()
        except Exception:
            return None
        if len(out) < 2:
            return None
        ppid, tty = out
        if tty.startswith("ttys"):
            return "/dev/" + tty
        if ppid in ("0", "1"):
            return None
        pid = ppid
    return None

def headless_claude(pid):
    """True when the nearest claude ancestor has no tty of its own (a `claude -p` run)."""
    pid = str(pid)
    for _ in range(12):
        try:
            out = subprocess.check_output(
                ["ps", "-o", "ppid=,tty=,comm=", "-p", pid], text=True).split(None, 2)
        except Exception:
            return False
        if len(out) < 3:
            return False
        ppid, tty, comm = out
        if os.path.basename(comm.strip()) == "claude":
            return not tty.startswith("ttys")
        if ppid in ("0", "1"):
            return False
        pid = ppid
    return False


def claude_ttys():
    try:
        pids = subprocess.check_output(["pgrep", "-x", "claude"], text=True).split()
    except subprocess.CalledProcessError:
        return set()
    return {t for t in (tty_of_pid(p) for p in pids) if t}

def osa(script):
    return subprocess.check_output(["osascript", "-e", script], text=True).strip()

def list_tabs():
    out = osa('''tell application "Terminal"
set o to ""
repeat with w in windows
repeat with t in tabs of w
set c to background color of t
set o to o & (tty of t) & "|" & (item 1 of c) & "|" & (item 2 of c) & "|" & (item 3 of c) & linefeed
end repeat
end repeat
return o
end tell''')
    tabs = {}
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) == 4:
            tabs[parts[0]] = as_to_hex(*(int(x) for x in parts[1:]))
    return tabs

def set_bg(tty, h):
    r, g, b = hex_to_as(h)
    osa(f'''tell application "Terminal"
repeat with w in windows
repeat with t in tabs of w
if tty of t is "{tty}" then set background color of t to {{{r}, {g}, {b}}}
end repeat
end repeat
end tell''')

def state_path(tty):
    return os.path.join(STATE_DIR, tty.replace("/", "_") + ".json")

def load_state(tty):
    try:
        with open(state_path(tty)) as f:
            return json.load(f)
    except Exception:
        return None

def save_state(tty, orig, tint, session_id=None):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(tty), "w") as f:
        json.dump({"orig": orig, "tint": tint, "name": NAMES[tint],
                   "session_id": session_id}, f)

def orig_of(tty, tabs):
    """The tab's own background from before any tint."""
    st = load_state(tty)
    return st["orig"] if st else (tabs[tty] if tabs[tty] not in NAMES else "000000")

def apply(tty, tabs, choice, session_id=None):
    save_state(tty, orig_of(tty, tabs), choice, session_id)
    set_bg(tty, choice)
    tabs[tty] = choice
    return NAMES[choice]

def pick_free(tty, tabs, avoid=None, shuffle=False, palette=None):
    palette = palette or palette_for(orig_of(tty, tabs))
    used = {h for t, h in tabs.items() if t != tty}
    free = [h for _, h in palette if h not in used and h != avoid]
    if free:
        return random.choice(free) if shuffle else free[0]
    pool = [h for _, h in palette if h != avoid] or [h for _, h in palette]
    if shuffle:
        return random.choice(pool)
    n = int("".join(ch for ch in tty if ch.isdigit()) or 0)
    return pool[n % len(pool)]

def tint_if_needed(tty, tabs, session_id=None):
    if tabs[tty] in NAMES:
        return NAMES[tabs[tty]]          # already tinted: keep it
    return apply(tty, tabs, pick_free(tty, tabs), session_id)

def restore(tty, tabs):
    st = load_state(tty)
    orig = st["orig"] if st else "000000"
    if st:
        os.remove(state_path(tty))
    set_bg(tty, orig)

def main(argv):
    if os.environ.get("TERM_PROGRAM") != "Apple_Terminal":
        return
    action = argv[0] if argv else "hook"
    tabs = list_tabs()

    if action == "list":
        scheme = load_scheme()
        by_hex = {h: t for t, h in tabs.items()}
        shown = SCHEMES if scheme == "auto" else {scheme: SCHEMES[scheme]}
        print(f"scheme: {scheme}")
        for sname, pal in shown.items():
            if scheme == "auto" and sname not in ("muted", "pastel"):
                continue
            for n, h in pal:
                print(f"{n:13s} #{h}  {by_hex.get(h, '')}")
        return

    if action == "scheme":
        name = argv[1] if len(argv) > 1 else ""
        if not name:
            print(f"scheme: {load_scheme()}; choices: auto, " + ", ".join(SCHEMES))
            return
        if name != "auto" and name not in SCHEMES:
            print("unknown scheme; choices: auto, " + ", ".join(SCHEMES))
            return
        save_scheme(name)
        done = []
        for tty in sorted(claude_ttys()):
            if tty in tabs:
                pal = palette_for(orig_of(tty, tabs), name)
                done.append(apply(tty, tabs, pick_free(tty, tabs, palette=pal)))
        print(f"scheme: {name}; recoloured {len(done)} tab(s)")
        return

    if action == "all":
        for tty in sorted(claude_ttys()):
            if tty in tabs:
                print(f"{tty}: {tint_if_needed(tty, tabs)}")
        return

    tty = tty_of_pid(os.getpid())
    if not tty or tty not in tabs:
        return

    if action == "hook":
        if os.environ.get("CLAUDE_WIDGET_TINT", "").lower() in ("off", "0", "false", "no"):
            return                           # the user turned automatic tinting off
        if headless_claude(os.getpid()):
            return                           # `claude -p` runs must not touch tab colours
        data = {}
        if not sys.stdin.isatty():
            try:
                data = json.loads(sys.stdin.read() or "{}")
            except Exception:
                data = {}
        if "hook_event_name" not in data:
            action = "shuffle"               # run by hand with no args
        elif data["hook_event_name"] == "SessionEnd":
            restore(tty, tabs)
            return
        else:
            tint_if_needed(tty, tabs, data.get("session_id"))
            return

    if action == "shuffle":
        print(apply(tty, tabs, pick_free(tty, tabs, avoid=tabs[tty], shuffle=True)))
    elif action == "set":
        name = argv[1] if len(argv) > 1 else ""
        pal = palette_for(orig_of(tty, tabs))
        hexes = dict(pal)
        for p in SCHEMES.values():
            for n, h in p:
                hexes.setdefault(n, h)
        if name not in hexes:
            print("unknown colour; choices: " + ", ".join(n for n, _ in pal))
            return
        print(apply(tty, tabs, hexes[name]))
    elif action == "reset":
        restore(tty, tabs)
        print("reset")
    else:
        print(__doc__)

if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:
        print(f"tint: {e}", file=sys.stderr)
