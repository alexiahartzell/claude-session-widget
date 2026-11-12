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
        ("midnight", "0d1b2a"), ("plum", "1e1026"), ("forest", "0c1f16"), ("wine", "26101a"),
        ("teal", "0c2224"), ("espresso", "211810"), ("indigo", "14132b"), ("moss", "1a200e"),
        ("rust", "261410"), ("mulberry", "2a1428"),
    ],
    # Deeper, more saturated colours that are easy to tell apart.
    "jewel": [
        ("sapphire", "0d2547"), ("emerald", "0a2e22"), ("ruby", "3a0d1e"), ("amethyst", "1f0f3d"),
        ("amber", "3a2805"), ("turquoise", "05302f"), ("jade", "12300a"), ("violet", "2d0a3a"),
        ("copper", "3a1a05"), ("magenta", "3a0a2e"),
    ],
    # Twilight purples and roses, with sunset orange and amber.
    "dusk": [
        ("twilight", "171a29"), ("orchid", "2a182a"), ("rosewood", "36151e"), ("lagoon", "182e3a"), ("heather", "292637"),
        ("sunset", "291710"), ("mauve", "2c1f27"), ("amber", "292510"), ("aubergine", "1f0f29"), ("cerise", "360b28"),
    ],
    # Sea blues and teals, with coral, sand, kelp and urchin.
    "ocean": [
        ("abyss", "0e2342"), ("shallows", "0a3932"), ("coral", "351512"), ("kelp", "2c3a18"), ("deep", "13163f"),
        ("sand", "352613"), ("urchin", "291532"), ("seaglass", "143823"), ("anemone", "301626"), ("reef", "0d3645"),
    ],
    # Ten hues picked by simulating protanopia, deuteranopia and tritanopia, so
    # every pair of card colours stays as different as ten colours allow for each.
    "colourblind": [
        ("cinnabar", "402620"), ("copper", "402f20"), ("amber", "403720"), ("brass", "404020"),
        ("jade", "20402b"), ("lagoon", "203740"), ("harbour", "202f40"), ("indigo", "222040"),
        ("orchid", "402035"), ("raspberry", "402024"),
    ],
    # Pines, mosses, bark and mushrooms.
    "forest": [
        ("pine", "0f3429"), ("fern", "153014"), ("moss", "2c4010"), ("bark", "352017"), ("lichen", "292814"),
        ("spruce", "0d2729"), ("bramble", "291b22"), ("acorn", "2d200d"), ("canopy", "16291c"), ("mushroom", "381f1f"),
    ],
    # Fire reds, flame oranges, coal and smoke.
    "ember": [
        ("ember", "45140e"), ("flame", "2c1a0a"), ("ash", "292624"), ("coal", "331720"), ("glow", "312a0c"),
        ("cinder", "2d1013"), ("smoke", "3d3845"), ("brick", "361f17"), ("garnet", "3b1529"), ("sienna", "3b301a"),
    ],
    # Northern-lights greens, glacier blues and violets.
    "aurora": [
        ("borealis", "10361f"), ("glacier", "0f3840"), ("polar", "1b2544"), ("nebula", "211636"), ("solar", "290a1b"),
        ("spectre", "21403a"), ("violet", "361036"), ("ice", "212e3b"), ("verdant", "0e2a0c"), ("magenta", "301017"),
    ],
    # Sand, terracotta, sage and canyon reds.
    "desert": [
        ("sand", "453a1b"), ("terracotta", "2f150c"), ("sage", "30412a"), ("clay", "2c2319"), ("mesa", "301a19"),
        ("cactus", "172a1f"), ("dune", "43431e"), ("canyon", "2b1219"), ("oasis", "1d4245"), ("twilight", "3a3040"),
    ],
    # Plums, raspberries, blueberries and cherries.
    "berry": [
        ("plum", "451c44"), ("raspberry", "300d15"), ("blackberry", "151029"), ("currant", "451613"), ("blueberry", "0e182a"),
        ("cherry", "3a2016"), ("grape", "2a1a32"), ("elderberry", "3b1c33"), ("cranberry", "3a1626"), ("bilberry", "141629"),
    ],
    # Fjord blues, frost, pine and birch.
    "nordic": [
        ("fjord", "1b2b3b"), ("slate", "20232d"), ("frost", "2d4045"), ("pine", "1f3228"), ("granite", "413a33"),
        ("aurora", "112e2b"), ("heather", "382d3b"), ("birch", "363429"), ("tundra", "313b29"), ("steel", "2a2740"),
    ],
    # Rust, ochre, olive, maroon and pumpkin.
    "autumn": [
        ("rust", "31150d"), ("ochre", "29220d"), ("olive", "3c451b"), ("maroon", "3c0c19"), ("pumpkin", "402210"),
        ("chestnut", "371817"), ("harvest", "3a381d"), ("cider", "41321c"), ("hazel", "2c3921"), ("plum", "2e1e28"),
    ],
    # Bright, saturated electric colours. The easiest to tell apart.
    "neon": [
        ("cyber", "072230"), ("laser", "41032b"), ("volt", "253d09"), ("ultra", "1a032a"), ("blaze", "351705"),
        ("acid", "2b2406"), ("electric", "07143a"), ("toxic", "08331c"), ("hot", "3f050d"), ("radium", "06322f"),
    ],
    # Deep space blues, nebula pinks and violets.
    "galaxy": [
        ("void", "121b35"), ("nebula", "411538"), ("comet", "1a393f"), ("quasar", "1a0829"), ("stardust", "2e1722"),
        ("orion", "1b3043"), ("pulsar", "173a30"), ("supernova", "41101c"), ("cosmos", "25233a"), ("zenith", "2b1c2d"),
    ],
    # Coral, mango, lime, lagoon and hibiscus.
    "tropical": [
        ("coral", "3a1215"), ("mango", "352a09"), ("lime", "283410"), ("lagoon", "143b44"), ("hibiscus", "360823"),
        ("palm", "143c1f"), ("lapis", "0a1f43"), ("orchid", "281530"), ("papaya", "3a1b09"), ("reef", "0b362c"),
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
