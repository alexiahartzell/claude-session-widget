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
                       ember, aurora, desert, berry, nordic, autumn, neon, galaxy, tropical,
                       dracula, crewtractor
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
    # Soft, greyish colours from every part of the rainbow. The default.
    "muted": [
        ("mulberry", "2d2026"), ("forest", "162e26"), ("wine", "261111"), ("teal", "1a272a"), ("rust", "241e1a"),
        ("midnight", "141d2c"), ("espresso", "2f301a"), ("indigo", "111126"), ("moss", "132a14"), ("plum", "251123"),
    ],
    # Deep, rich colours from every part of the rainbow.
    "jewel": [
        ("magenta", "470926"), ("emerald", "0f3e2c"), ("ruby", "390001"), ("turquoise", "033643"), ("copper", "4a3312"),
        ("sapphire", "0c1e40"), ("amber", "3e3f00"), ("amethyst", "020138"), ("jade", "023905"), ("violet", "380035"),
    ],
    # Only purples, lilacs, mauves and dusty roses.
    "dusk": [
        ("twilight", "141629"), ("aubergine", "3b1835"), ("evening", "12122d"), ("mauve", "3c2935"), ("heather", "333242"),
        ("plum", "2c121e"), ("lavender", "241b29"), ("rosewood", "402d30"), ("orchid", "24132b"), ("cerise", "39171c"),
    ],
    # Only sea greens, teals and blues, from shallows to the deep.
    "ocean": [
        ("kelp", "062817"), ("reef", "243747"), ("seaglass", "24473c"), ("current", "0f2a46"), ("lagoon", "03231a"),
        ("harbour", "111321"), ("shallows", "042120"), ("abyss", "11143d"), ("tide", "011e26"), ("deep", "000239"),
    ],
    # Ten hues picked by simulating protanopia, deuteranopia and tritanopia, so
    # every pair of card colours stays as different as ten colours allow for each.
    "colourblind": [
        ("cinnabar", "460c19"), ("copper", "3f2816"), ("amber", "37350a"), ("brass", "2a3422"), ("jade", "173a29"),
        ("lagoon", "222e39"), ("harbour", "26253a"), ("indigo", "23103f"), ("orchid", "4b0e36"), ("raspberry", "463b40"),
    ],
    # Only greens and woody browns.
    "forest": [
        ("bark", "371908"), ("fern", "1f2906"), ("acorn", "2c241c"), ("canopy", "142314"), ("lichen", "2d1f07"),
        ("pine", "062606"), ("moss", "201e06"), ("spruce", "08382b"), ("olive", "343723"), ("juniper", "182523"),
    ],
    # Only fire colours: reds, oranges and golds.
    "ember": [
        ("garnet", "290410"), ("sienna", "2e1d15"), ("cinder", "2f151e"), ("blaze", "2c1500"), ("ember", "4a2224"),
        ("amber", "2c1d00"), ("brick", "290304"), ("glow", "474020"), ("flame", "4a1909"), ("gold", "292301"),
    ],
    # Only northern-lights colours: greens, teals, blues and violets.
    "aurora": [
        ("verdant", "052e02"), ("ice", "0b2647"), ("borealis", "142b18"), ("polar", "03022d"), ("jade", "033b2f"),
        ("indigo", "181534"), ("spectre", "0b292d"), ("nebula", "22032b"), ("glacier", "152430"), ("violet", "462047"),
    ],
    # Only soft earth colours: sand, clay, terracotta and sage.
    "desert": [
        ("canyon", "261413"), ("sand", "2f2b18"), ("mesa", "2a1f1f"), ("dune", "212613"), ("terracotta", "3d291f"),
        ("wheat", "393e32"), ("clay", "261d13"), ("sage", "1a2814"), ("adobe", "423b31"), ("yucca", "31422c"),
    ],
    # Only berry colours: blues, purples, magentas and reds.
    "berry": [
        ("blueberry", "05182d"), ("elderberry", "2a0338"), ("bilberry", "121c26"), ("boysenberry", "300229"), ("blackberry", "04112e"),
        ("raspberry", "3c1c2d"), ("grape", "03032b"), ("cranberry", "261112"), ("plum", "311e3b"), ("currant", "280303"),
    ],
    # Only cool greys with a hint of blue or green.
    "nordic": [
        ("lichen", "1c2926"), ("harbour", "2e3447"), ("frost", "404443"), ("slate", "424347"), ("ice", "2d4246"),
        ("steel", "2b2b2e"), ("fjord", "303233"), ("storm", "272438"), ("mist", "1c252b"), ("heather", "232129"),
    ],
    # Only autumn leaves: maroon, rust, pumpkin, ochre and olive.
    "autumn": [
        ("maroon", "2a0505"), ("ochre", "211a05"), ("chestnut", "210e0d"), ("mustard", "3b341d"), ("rust", "3b231d"),
        ("harvest", "2d2d08"), ("pumpkin", "281205"), ("olive", "222714"), ("cider", "362310"), ("hazel", "212e06"),
    ],
    # Only bright synthwave colours: cyans, blues, violets and pinks.
    "neon": [
        ("radium", "003f30"), ("laser", "02023e"), ("cyber", "023c3d"), ("magenta", "32003d"), ("electric", "063c4f"),
        ("hot", "450537"), ("ultra", "04284d"), ("plasma", "4f0424"), ("violet", "081847"), ("pulse", "41000b"),
    ],
    # Only deep night-sky blues and violets.
    "galaxy": [
        ("comet", "0a2128"), ("quasar", "1c1827"), ("orion", "061626"), ("eclipse", "1c1228"), ("void", "12181f"),
        ("nebula", "1d0629"), ("sirius", "081329"), ("zenith", "2c1b2e"), ("cosmos", "070a27"), ("stardust", "200720"),
    ],
    # Only tropical colours: pinks, corals, mangos and lagoon blues.
    "tropical": [
        ("hibiscus", "4d0926"), ("pineapple", "003a0f"), ("flamingo", "47070c"), ("palm", "174d2e"), ("coral", "381a01"),
        ("reef", "023832"), ("papaya", "413413"), ("lagoon", "14494f"), ("mango", "40410a"), ("cove", "062a3a"),
    ],
    # The Dracula palette (as in the JetBrains Dracula theme), darkened for tab backgrounds.
    "dracula": [
        ("dracula", "21222c"), ("foreground", "292929"), ("comment", "23315c"), ("cyan", "054957"), ("green", "044915"),
        ("orange", "522d04"), ("pink", "61053a"), ("purple", "300868"), ("red", "550707"), ("yellow", "404508"),
    ],
    # The crew tractor meme: farm colours named after what gets yelled at the pond.
    "crewtractor": [
        ("state?!", "122154"), ("this?!", "552a02"), ("this ain't no", "30251d"), ("state property", "0f3d17"),
        ("private property", "500707"), ("lock em up", "2e1452"), ("crewe tractor", "2a3c07"), ("the pond", "0b3d3d"),
        ("hay bale", "473a06"), ("pickup truck", "49122f"),
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


def colour_key(name):
    """A colour name reduced to lowercase letters and digits, for matching typed names."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


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
        # -a: macOS pgrep skips its own ancestors by default, which would hide
        # the Claude session that runs this very command.
        pids = subprocess.check_output(["pgrep", "-a", "-x", "claude"], text=True).split()
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
        # Names can hold spaces and punctuation ("state?!"), which the shell mangles,
        # so match on letters and digits only: "set state property" or "set stateproperty".
        name = colour_key(" ".join(argv[1:]))
        pal = current_palette()
        mode = w.effective_mode()
        hexes = {colour_key(n): h for n, h in pal}
        for scheme in DARK:
            for n, h in palette(scheme, mode):
                hexes.setdefault(colour_key(n), h)
        if not name or name not in hexes:
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
