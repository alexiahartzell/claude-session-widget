#!/usr/bin/env python3
"""Tint Terminal.app tabs a distinct colour per Claude Code session.

Hook use (stdin JSON from Claude Code):
  SessionStart -> pick a colour no other open tab uses, apply it.
  SessionEnd   -> restore the tab's original background and text colour.
  Set CLAUDE_WIDGET_TINT=off to turn the hook off.

Manual use (the /tint command):
  tint.py              give this tab a different random free colour
  tint.py set NAME     give this tab a named colour
  tint.py reset        restore this tab's original colours
  tint.py list         show the current colours and which tab has what
  tint.py all          tint every tab that has a running claude
  tint.py scheme NAME  switch scheme: muted, jewel, dusk, ocean, colourblind, forest,
                       ember, aurora, desert, berry, nordic, autumn, neon, galaxy, tropical
  tint.py mode MODE    switch mode: auto (follow macOS), dark, light
Only acts inside Apple Terminal.
"""
import json, os, random, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import widgetlib as w

STATE_DIR = w.TINT_DIR

# Each scheme lists its dark tab backgrounds as (name, hex). The light mode of a
# scheme uses the same hues as soft light backgrounds, made by light_of().
DARK = {
    # Dark, quiet backgrounds.
    "muted": [
        ("midnight", "172128"), ("plum", "20132c"), ("forest", "11261b"), ("wine", "2b121b"), ("teal", "182e2c"),
        ("espresso", "312b20"), ("indigo", "131624"), ("moss", "232713"), ("rust", "2b1814"), ("mulberry", "30202f"),
    ],
    # Deeper, more saturated colours that are easy to tell apart.
    "jewel": [
        ("sapphire", "042242"), ("emerald", "073828"), ("ruby", "40060e"), ("amethyst", "0d0239"), ("amber", "3b370e"),
        ("turquoise", "113c42"), ("jade", "083905"), ("violet", "370b39"), ("copper", "462c12"), ("magenta", "410f29"),
    ],
    # Twilight purples and roses, with sunset orange and amber.
    "dusk": [
        ("twilight", "22273e"), ("orchid", "281d2f"), ("rosewood", "301316"), ("lagoon", "162831"), ("heather", "1b1736"),
        ("sunset", "332019"), ("mauve", "33152a"), ("amber", "2d2614"), ("aubergine", "2c1331"), ("cerise", "3e232f"),
    ],
    # Sea blues and teals, with coral, sand, kelp and urchin.
    "ocean": [
        ("abyss", "14273c"), ("shallows", "08342e"), ("coral", "3c130b"), ("kelp", "212f07"), ("deep", "121633"),
        ("sand", "362a09"), ("urchin", "22062d"), ("seaglass", "092e18"), ("anemone", "311126"), ("reef", "112b31"),
    ],
    # Ten hues picked by simulating protanopia, deuteranopia and tritanopia, so
    # every pair of card colours stays as different as ten colours allow for each.
    "colourblind": [
        ("cinnabar", "460c19"), ("copper", "3f2816"), ("amber", "37350a"), ("brass", "2a3422"), ("jade", "173a29"),
        ("lagoon", "222e39"), ("harbour", "26253a"), ("indigo", "23103f"), ("orchid", "4b0e36"), ("raspberry", "463b40"),
    ],
    # Pines, mosses, bark and mushrooms.
    "forest": [
        ("pine", "162922"), ("fern", "182b0e"), ("moss", "1e2615"), ("bark", "22110b"), ("lichen", "322e12"),
        ("spruce", "162e2f"), ("bramble", "341b2b"), ("acorn", "231b12"), ("canopy", "0d2416"), ("mushroom", "271416"),
    ],
    # Fire reds, flame oranges, coal and smoke.
    "ember": [
        ("ember", "370703"), ("flame", "381c05"), ("ash", "423906"), ("coal", "3a0d1d"), ("glow", "3c3f02"),
        ("cinder", "380b12"), ("smoke", "240340"), ("brick", "471e13"), ("garnet", "40102d"), ("sienna", "3f2d0b"),
    ],
    # Northern-lights greens, glacier blues and violets.
    "aurora": [
        ("borealis", "123922"), ("glacier", "0e333c"), ("polar", "0b1a3e"), ("nebula", "1a0834"), ("solar", "430d2b"),
        ("spectre", "113632"), ("violet", "381039"), ("ice", "112336"), ("verdant", "073307"), ("magenta", "330e13"),
    ],
    # Sand, terracotta, sage and canyon reds.
    "desert": [
        ("sand", "312e22"), ("terracotta", "351a19"), ("sage", "2c3b23"), ("clay", "3b2a1c"), ("mesa", "2e2021"),
        ("cactus", "21372c"), ("dune", "373619"), ("canyon", "321921"), ("oasis", "1b2e2d"), ("twilight", "251c2c"),
    ],
    # Plums, raspberries, blueberries and cherries.
    "berry": [
        ("plum", "2f092f"), ("raspberry", "3c151b"), ("blackberry", "140c39"), ("currant", "2d0b0a"), ("blueberry", "152437"),
        ("cherry", "2e1912"), ("grape", "2d173d"), ("elderberry", "34152d"), ("cranberry", "2f0d1d"), ("bilberry", "161c3d"),
    ],
    # Fjord blues, frost, pine and birch.
    "nordic": [
        ("fjord", "273540"), ("slate", "202330"), ("frost", "2b3335"), ("pine", "274033"), ("granite", "362d28"),
        ("aurora", "1d302d"), ("heather", "392d3b"), ("birch", "38382f"), ("tundra", "2a3422"), ("steel", "29253d"),
    ],
    # Rust, ochre, olive, maroon and pumpkin.
    "autumn": [
        ("rust", "2e0909"), ("ochre", "372c15"), ("olive", "232c09"), ("maroon", "341220"), ("pumpkin", "341b12"),
        ("chestnut", "2d1013"), ("harvest", "2f2c08"), ("cider", "281908"), ("hazel", "15280b"), ("plum", "2d102b"),
    ],
    # Bright, saturated electric colours. The easiest to tell apart.
    "neon": [
        ("cyber", "002c41"), ("laser", "46063f"), ("volt", "2a4200"), ("ultra", "190041"), ("blaze", "431600"),
        ("acid", "433400"), ("electric", "09204f"), ("toxic", "004c28"), ("hot", "4f0921"), ("radium", "004341"),
    ],
    # Deep space blues, nebula pinks and violets.
    "galaxy": [
        ("void", "141e36"), ("nebula", "2a1426"), ("comet", "183737"), ("quasar", "150b2c"), ("stardust", "330e1d"),
        ("orion", "12242e"), ("pulsar", "0c3324"), ("supernova", "290a0a"), ("cosmos", "1e152c"), ("zenith", "260928"),
    ],
    # Coral, mango, lime, lagoon and hibiscus.
    "tropical": [
        ("coral", "46070d"), ("mango", "3f3305"), ("lime", "2b3a02"), ("lagoon", "06303a"), ("hibiscus", "400526"),
        ("palm", "04411c"), ("lapis", "04143a"), ("orchid", "3a0f43"), ("papaya", "371e06"), ("reef", "083832"),
    ],
}
PALETTE_SIZE = 10                                # every scheme has this many colours
SCHEMES = DARK
TEXT = {"dark": "e8e6ee", "light": "1f2329"}     # tab text colour in each mode


def light_of(h):
    """The light-mode background for a dark scheme colour: the same hue and
    saturation with the lightness mirrored, so a darker tab becomes a paler one
    and colours that differ in the dark version still differ in the light one."""
    import colorsys
    hue, light, sat = colorsys.rgb_to_hls(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)))
    r, g, b = colorsys.hls_to_rgb(hue, 1 - 0.55 * light, min(sat, 0.75))
    return "".join(f"{int(round(c * 255)):02x}" for c in (r, g, b))


def palette(scheme, mode):
    """(name, hex) backgrounds for a scheme in 'dark' or 'light' mode."""
    pal = DARK[scheme]
    return pal if mode == "dark" else [(n, light_of(h)) for n, h in pal]


NAMES = {h: n for s in DARK for m in ("dark", "light") for n, h in palette(s, m)}


def current_palette(cfg=None):
    cfg = cfg or w.load_config()
    return palette(cfg["scheme"], w.effective_mode(cfg))


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

def text_of(tty):
    """The tab's current normal text colour as hex, or None."""
    out = osa(f'''tell application "Terminal"
repeat with w in windows
repeat with t in tabs of w
if tty of t is "{tty}" then
set c to normal text color of t
return "" & (item 1 of c) & "|" & (item 2 of c) & "|" & (item 3 of c)
end if
end repeat
end repeat
return ""
end tell''')
    parts = out.split("|")
    return as_to_hex(*(int(x) for x in parts)) if len(parts) == 3 else None

def set_bg(tty, h, text=None):
    """Set the tab background, and its normal and bold text colour when text is given."""
    r, g, b = hex_to_as(h)
    sets = f"set background color of t to {{{r}, {g}, {b}}}"
    if text:
        tr, tg, tb = hex_to_as(text)
        sets += (f"\nset normal text color of t to {{{tr}, {tg}, {tb}}}"
                 f"\nset bold text color of t to {{{tr}, {tg}, {tb}}}")
    osa(f'''tell application "Terminal"
repeat with w in windows
repeat with t in tabs of w
if tty of t is "{tty}" then
{sets}
end if
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

def save_state(tty, orig, orig_text, tint, session_id=None):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(tty), "w") as f:
        json.dump({"orig": orig, "orig_text": orig_text, "tint": tint, "name": NAMES[tint],
                   "session_id": session_id}, f)

def orig_of(tty, tabs):
    """The tab's own (background, text colour) from before any tint."""
    st = load_state(tty)
    if st:
        return st["orig"], st.get("orig_text")
    return (tabs[tty] if tabs[tty] not in NAMES else "000000"), text_of(tty)

def apply(tty, tabs, choice, session_id=None):
    orig, orig_text = orig_of(tty, tabs)
    save_state(tty, orig, orig_text, choice, session_id)
    set_bg(tty, choice, TEXT["light" if w.is_light(choice) else "dark"])
    tabs[tty] = choice
    return NAMES[choice]

def pick_free(tty, tabs, avoid=None, shuffle=False, palette=None):
    palette = palette or current_palette()
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
    set_bg(tty, orig, (st or {}).get("orig_text"))

def recolour_all(tabs, cfg):
    """Give every Claude tab a free colour from the chosen scheme and mode."""
    pal = current_palette(cfg)
    done = 0
    for tty in sorted(claude_ttys()):
        if tty in tabs:
            apply(tty, tabs, pick_free(tty, tabs, palette=pal))
            done += 1
    return done

def main(argv):
    if os.environ.get("TERM_PROGRAM") != "Apple_Terminal":
        return
    action = argv[0] if argv else "hook"
    tabs = list_tabs()

    if action == "list":
        cfg = w.load_config()
        by_hex = {h: t for t, h in tabs.items()}
        print(f"scheme: {cfg['scheme']}, mode: {cfg['mode']} ({w.effective_mode(cfg)})")
        for n, h in current_palette(cfg):
            print(f"{n:11s} #{h}  {by_hex.get(h, '')}")
        return

    if action in ("scheme", "mode"):
        choices = w.SCHEME_NAMES if action == "scheme" else w.MODES
        name = argv[1] if len(argv) > 1 else ""
        cfg = w.load_config()
        if not name:
            print(f"{action}: {cfg[action]}; choices: " + ", ".join(choices))
            return
        if name not in choices:
            print(f"unknown {action}; choices: " + ", ".join(choices))
            return
        cfg = w.save_config(**{action: name})
        n = recolour_all(tabs, cfg)
        print(f"scheme: {cfg['scheme']}, mode: {cfg['mode']}; recoloured {n} tab(s)")
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
        pal = current_palette()
        mode = w.effective_mode()
        hexes = dict(pal)
        for scheme in DARK:
            for n, h in palette(scheme, mode):
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
