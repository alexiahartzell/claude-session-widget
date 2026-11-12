"""Pure helpers shared by the session hook and the widget. No tkinter here."""
import fcntl, functools, json, os, re, subprocess, tempfile, time

HOME = os.path.expanduser("~")
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
# Runtime state lives apart from the code, so the code can sit in a read-only plugin cache.
WIDGET_DIR = os.environ.get("CLAUDE_WIDGET_HOME") or os.path.join(HOME, ".claude", "widget")
SESSIONS_DIR = os.path.join(WIDGET_DIR, "sessions")
TINT_DIR = os.path.join(HOME, ".claude", "tint-state")

ATTENTION = {"needs_input", "permission"}
GREY = "3c3c3c"
MAX_AGE_S = 12 * 3600


def session_path(sessions_dir, session_id):
    return os.path.join(sessions_dir, session_id + ".json")


def write_session(sessions_dir, data):
    os.makedirs(sessions_dir, exist_ok=True)
    path = session_path(sessions_dir, data["session_id"])
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".json.tmp", dir=sessions_dir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        try: os.remove(tmp)
        except OSError: pass
        raise


def _read_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def load_session(sessions_dir, session_id):
    return _read_json(session_path(sessions_dir, session_id))


def load_sessions(sessions_dir):
    out = []
    try:
        names = sorted(os.listdir(sessions_dir))
    except FileNotFoundError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        data = _read_json(os.path.join(sessions_dir, name))
        if data and data.get("session_id"):
            out.append(data)
    return out


def _lock(sessions_dir, session_id):
    os.makedirs(sessions_dir, exist_ok=True)
    f = open(os.path.join(sessions_dir, ".lock"), "a+")
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def update_session_fn(sessions_dir, session_id, fn, touch=True):
    """Locked read-modify-write: fn(current) -> fields to merge; a None value
    removes that field. Returns (old, new). touch=False keeps `updated` as is
    (for bookkeeping that is not session activity)."""
    lock = _lock(sessions_dir, session_id)
    try:
        old = load_session(sessions_dir, session_id)
        new = dict(old or {"session_id": session_id})
        new.update(fn(dict(new)) or {})
        new = {k: v for k, v in new.items() if v is not None}
        new["session_id"] = session_id
        now = time.time()
        if touch or "updated" not in new:
            new["updated"] = now
        if new.get("status") != (old or {}).get("status") or "status_since" not in new:
            new["status_since"] = now          # the waiting timer restarts on a new status
        write_session(sessions_dir, new)
    finally:
        lock.close()
    return old, new


def update_session(sessions_dir, session_id, **fields):
    return update_session_fn(sessions_dir, session_id, lambda cur: fields)


def delete_session(sessions_dir, session_id):
    try:
        os.remove(session_path(sessions_dir, session_id))
    except FileNotFoundError:
        pass


def truncate_task(prompt, n=60):
    text = re.sub(r"\s+", " ", prompt or "").strip()
    return text[:n]


def display_label(session):
    """Manual name, else the summary of what the session is doing now, else
    Claude Code's own title for the chat (from the transcript, or from the
    Terminal tab when no transcript is found), else the folder."""
    return (session.get("label_override") or session.get("summary") or session.get("title")
            or session.get("tab_title") or session.get("label") or "?")


def subtitle(session):
    """Second line of a card: what is happening right now. The step Claude is
    on while it works, what it waits on while watching, and nothing when it is
    your turn or idle. The title above says what the session is about."""
    status = session.get("status")
    waiting = session.get("armed") or session.get("background")
    if status == "watching" and waiting:
        # Both are true: you can reply, and Claude resumes on its own when it ends.
        return f"your turn · waiting on {waiting}"
    if status in ("working", "permission"):
        return session.get("activity") or (session.get("task") or "").strip()
    return ""


# ---- Claude's own spinner, read from the Terminal tab title ----
# Claude Code puts a spinning half-circle in front of the tab title while it
# works and a ✳ while it waits. That is the most direct busy signal there is,
# and it keeps working when a hook is missed (Escape, reloaded hooks).

TAB_BUSY = set("◐◓◑◒")
TAB_IDLE = "✳"
IDLE_HOLD_S = 4        # spinner gone this long before a working card flips
BUSY_HOLD_S = 2        # spinner running this long before a waiting card flips


def parse_tab_titles(text):
    """'tty<TAB>title' lines -> {tty: (state, title)}; state is busy, idle or None."""
    out = {}
    for line in (text or "").splitlines():
        tty, _, title = line.partition("\t")
        if not tty.startswith("/dev/"):
            continue
        title = title.strip()
        head = title[:1]
        if head in TAB_BUSY:
            out[tty] = ("busy", title[1:].strip())
        elif head == TAB_IDLE:
            out[tty] = ("idle", title[1:].strip())
        else:
            out[tty] = (None, "")
    return out


def reconcile(session, state, held_s):
    """Fields that bring a card in line with the tab's spinner, or None."""
    status = session.get("status")
    if state == "idle" and held_s >= IDLE_HOLD_S and status == "working":
        waiting = session.get("armed") or session.get("background")
        return {"status": "watching"} if waiting else {"status": "needs_input"}
    if state == "busy" and held_s >= BUSY_HOLD_S:
        if status in ("idle", "needs_input", "watching"):
            # Keep "armed": a busy tab while watching can be a blocked Stop resuming the
            # turn, not the job ending. Only a new prompt clears it.
            return {"status": "working"}
    return None


# ---- a short summary of the conversation, written by a small model ----

PROMPT_MEMORY = 6
SUMMARY_RETRY_S = 120


def remember_prompt(prompts, prompt):
    text = re.sub(r"\s+", " ", prompt or "").strip()[:300]
    out = list(prompts or [])
    if text:
        out.append(text)
    return out[-PROMPT_MEMORY:]


def should_summarise(session, now=None):
    now = time.time() if now is None else now
    if not session.get("prompts"):
        return False
    if session.get("summary_for") == session.get("prompt_count"):
        return False
    started = session.get("summary_started")
    return not started or now - _num(started) > SUMMARY_RETRY_S


def summary_request(session):
    lines = [
        "Below are the most recent requests a user typed into a coding assistant session, oldest first.",
        "Write a title of at most five words (under 30 characters) naming the overall piece of work the session is on now.",
        "Weigh the latest requests most. Name the goal, not a single small step.",
        "Start with a verb ending in -ing. No quotes, no final full stop. Reply with the line only.",
        "",
    ]
    for i, p in enumerate(session.get("prompts") or [], 1):
        lines.append(f"Request {i}: {p}")
    return "\n".join(lines)


WIDGET_CONFIG = os.path.join(WIDGET_DIR, "config.json")


def summaries_enabled(path=None):
    return (_read_json(path or WIDGET_CONFIG) or {}).get("summaries", True)


def set_summaries(on, path=None):
    path = path or WIDGET_CONFIG
    cfg = _read_json(path) or {}
    cfg["summaries"] = bool(on)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f)


def _config(path):
    return _read_json(path or WIDGET_CONFIG) or {}


def _save_config_field(path, **fields):
    path = path or WIDGET_CONFIG
    cfg = dict(_config(path), **fields)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f)


def mute_banners(minutes, path=None, now=None):
    """Silence macOS banners for this many minutes; 0 unmutes. Cards still pulse."""
    now = time.time() if now is None else now
    _save_config_field(path, mute_until=now + minutes * 60 if minutes > 0 else 0)


def mute_until(path=None):
    return _num(_config(path).get("mute_until"))


def banners_muted(path=None, now=None):
    return mute_until(path) > (time.time() if now is None else now)


# ---- subagents ----

AGENT_TOOLS = ("Agent", "Task")
AGENT_MAX_AGE_S = 2 * 3600


def agent_started(agents, tool_use_id, inp, now=None):
    inp = inp if isinstance(inp, dict) else {}
    out = [a for a in (agents or []) if a.get("id") != tool_use_id]
    out.append({"id": tool_use_id or f"agent-{time.time()}", "desc": _short(inp.get("description") or "working", 50),
                "type": inp.get("subagent_type") or "", "bg": bool(inp.get("run_in_background")),
                "started": time.time() if now is None else now})
    return out


def agent_returned(agents, tool_use_id):
    return [a for a in (agents or []) if a.get("id") != tool_use_id]


def agent_stopped(agents, agent_type):
    """SubagentStop does not say which call it was. Drop the oldest agent of the
    same type, else the oldest foreground one, else the oldest of all."""
    agents = list(agents or [])
    pick = ([a for a in agents if agent_type and a.get("type") == agent_type]
            or [a for a in agents if not a.get("bg")] or agents)
    if pick:
        agents.remove(pick[0])
    return agents


def prune_agents(agents, now=None):
    now = time.time() if now is None else now
    return [a for a in (agents or []) if now - _num(a.get("started")) < AGENT_MAX_AGE_S]


def agents_text(agents):
    agents = agents or []
    if not agents:
        return ""
    n = len(agents)
    return f"{n} agent{'s' if n > 1 else ''} · " + ", ".join(a.get("desc", "") for a in agents)


def clean_summary(text):
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    line = line.strip().strip('"\'`').rstrip(".").strip()
    return _short(line, 40)


def _short(text, n=60):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def activity_text(tool_name, tool_input):
    """A short plain-words line for the tool call Claude is about to make."""
    if not tool_name:
        return ""
    inp = tool_input if isinstance(tool_input, dict) else {}
    base = lambda key: os.path.basename(str(inp.get(key) or "").rstrip("/"))
    if tool_name == "Bash":
        if inp.get("description"):
            return _short(inp["description"])
        return _short("Running " + str(inp.get("command") or "a command"))
    if tool_name in ("Edit", "MultiEdit", "NotebookEdit"):
        return _short("Editing " + (base("file_path") or base("notebook_path") or "a file"))
    if tool_name == "Write":
        return _short("Writing " + (base("file_path") or "a file"))
    if tool_name == "Read":
        return _short("Reading " + (base("file_path") or "a file"))
    if tool_name in ("Grep", "Glob"):
        return "Searching the code"
    if tool_name == "WebSearch":
        return _short("Searching the web: " + str(inp.get("query") or ""))
    if tool_name == "WebFetch":
        host = re.sub(r"^[a-z]+://", "", str(inp.get("url") or "")).split("/")[0]
        return _short("Reading " + (host or "a web page"))
    if tool_name in ("Agent", "Task"):
        return _short("Agent: " + str(inp.get("description") or "working"))
    if tool_name == "Skill":
        return _short("Using skill " + str(inp.get("skill") or ""))
    if tool_name.startswith("mcp__"):
        return _short("Using " + tool_name.split("__")[1])
    return _short("Using " + tool_name)


def elapsed_text(session, now=None):
    """How long the session has been in its current status, in plain words."""
    since = session.get("status_since") or session.get("updated")
    if not since:
        return ""
    secs = max(0, (time.time() if now is None else now) - _num(since))
    mins = int(secs // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min"
    h, m = divmod(mins, 60)
    return f"{h} h {m} min" if m else f"{h} h"


@functools.lru_cache(maxsize=256)
def project_name(cwd, home=HOME):
    """The project a folder belongs to: the nearest enclosing git checkout
    (a .git folder or worktree file), else the folder's own name. A repo at
    home itself, such as dotfiles, does not count."""
    if not cwd:
        return ""
    path = os.path.abspath(cwd)
    home = os.path.abspath(home)
    cur = path
    while True:
        if cur == home or cur == os.path.dirname(cur):
            break
        if os.path.exists(os.path.join(cur, ".git")):
            return os.path.basename(cur)
        cur = os.path.dirname(cur)
    return os.path.basename(path.rstrip("/")) or path


def project_tag(session, name=None):
    """Project name for the card, or '' when the card's title already is that name."""
    tag = (name or project_name)(session.get("cwd_now") or session.get("cwd") or "")
    return "" if not tag or tag == display_label(session) else tag


def clean_env(env=None):
    """A copy of the environment without macOS malloc debugging switches,
    which make every child Python print a harmless warning into the log."""
    env = dict(os.environ if env is None else env)
    return {k: v for k, v in env.items() if not k.startswith("Malloc")}


def read_tint(tint_dir, tty):
    if not tty:
        return GREY, "grey"
    path = os.path.join(tint_dir, tty.replace("/", "_") + ".json")
    data = _read_json(path)
    if not data or not data.get("tint"):
        return GREY, "grey"
    return data["tint"], data.get("name", "tint")


def refresh_tints(sessions_dir, tint_dir=None):
    """Pick up tab colour changes, such as /tint shuffle, without waiting for a hook."""
    tint_dir = tint_dir or TINT_DIR
    for s in load_sessions(sessions_dir):
        color, name = read_tint(tint_dir, s.get("tty"))
        if (color, name) != (s.get("color"), s.get("color_name")):
            update_session_fn(sessions_dir, s["session_id"],
                              lambda cur: {"color": color, "color_name": name}, touch=False)


def brighten(h, value=0.82, min_sat=0.55):
    """Lift a dark muted tab tint to a vivid swatch colour with the same hue."""
    import colorsys
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
    if sat < 0.03:                                 # no hue to amplify
        if val >= 0.95:
            return h                               # already light, leave it
        return "".join(f"{int(max(val, 0.5) * 255):02x}" for _ in range(3))
    sat = max(sat, min_sat)
    val = max(val, value)
    return "".join(f"{int(round(c * 255)):02x}" for c in colorsys.hsv_to_rgb(hue, sat, val))


def _mix(a, b, t):
    """Blend two 'rrggbb' colours; t=0 gives a, t=1 gives b."""
    pa = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    pb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "".join(f"{int(round(x + (y - x) * t)):02x}" for x, y in zip(pa, pb))


def is_light(h):
    """True when a hex colour is light enough to need dark text."""
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b > 140


# ---- colour scheme and light/dark mode, shared with tint.py ----

CONFIG_PATH = os.path.join(TINT_DIR, "scheme.json")
SCHEME_NAMES = ("muted", "jewel", "dusk", "ocean", "colourblind",
                "forest", "ember", "aurora", "desert", "berry",
                "nordic", "autumn", "neon", "galaxy", "tropical")
MODES = ("auto", "dark", "light")

# Panel colours per mode: background, outline, text, secondary text.
PANEL_THEMES = {
    "dark":  {"bg": "15171e", "outline": "2a2d3a", "fg": "f2f0f7", "dim": "9a9db0"},
    "light": {"bg": "f6f5f9", "outline": "d9d7e2", "fg": "1d1f27", "dim": "6a6d7e"},
}


def load_config(path=None):
    """{"scheme", "mode"} from the saved choice, with defaults for anything missing."""
    data = _read_json(path or CONFIG_PATH) or {}
    scheme, mode = data.get("scheme"), data.get("mode")
    if scheme == "pastel":                         # pastel became the light mode of muted
        scheme, mode = "muted", mode or "light"
    return {"scheme": scheme if scheme in SCHEME_NAMES else "muted",
            "mode": mode if mode in MODES else "auto"}


def save_config(path=None, **fields):
    path = path or CONFIG_PATH
    cfg = dict(load_config(path), **fields)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f)
    return cfg


_system_mode_cache = [0.0, "dark"]


def system_mode(max_age=5.0):
    """'dark' or 'light' from the macOS appearance setting, checked at most every few seconds."""
    now = time.time()
    if now - _system_mode_cache[0] > max_age:
        try:
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                                 capture_output=True, text=True).stdout
            _system_mode_cache[1] = "dark" if "Dark" in out else "light"
        except Exception:
            pass
        _system_mode_cache[0] = now
    return _system_mode_cache[1]


def effective_mode(cfg=None):
    mode = (cfg or load_config())["mode"]
    return system_mode() if mode == "auto" else mode


def _hsv(h):
    import colorsys
    return colorsys.rgb_to_hsv(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def _hex(hue, sat, val):
    import colorsys
    return "".join(f"{int(round(c * 255)):02x}" for c in colorsys.hsv_to_rgb(hue, sat, val))


def _dark_of(h):
    """Undo tint.py's light_of: the dark tab colour a light-mode tab colour came from,
    so a scheme's character reads the same in both modes."""
    import colorsys
    hue, light, sat = colorsys.rgb_to_hls(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)))
    r, g, b = colorsys.hls_to_rgb(hue, min(1.0, max(0.0, (1 - light) / 0.55)), sat)
    return "".join(f"{int(round(c * 255)):02x}" for c in (r, g, b))


def _character(tint):
    """(hue, saturation, value) of the dark version of a tab colour."""
    return _hsv(_dark_of(tint) if is_light(tint) else tint)


def card_fill(tint, panel_bg, mode="dark"):
    """Card background for a tab tint, readable with the panel's text in this mode.
    A richer tab colour gives a richer card, so schemes keep their character."""
    if mode == "light":
        hue, sat, _ = _character(tint)
        if sat < 0.03:
            return _mix("e9e9ee", panel_bg, 0.3)
        return _mix(_hex(hue, 0.05 + 0.28 * min(sat, 1.0), 0.96), panel_bg, 0.2)
    if is_light(tint):
        return _mix(brighten(tint), panel_bg, 0.78)
    return _mix(tint, panel_bg, 0.25)


def accent(tint, mode="dark"):
    """Outline and status colour for a card. It keeps the tab colour's own
    saturation and depth: quiet schemes get soft accents, bright ones vivid ones."""
    hue, sat, val = _character(tint)
    if sat < 0.03:
        return "707070" if mode == "light" else brighten(tint)
    s = min(1.0, max(0.2, 0.15 + 0.9 * sat))
    if mode == "light":
        v = min(0.68, max(0.42, 0.75 - 1.2 * (val - 0.1)))
        out = _hex(hue, s, v)
        while is_light(out) and v > 0.2:          # bright yellows need darkening to read
            v -= 0.03
            out = _hex(hue, s, v)
        return out
    return _hex(hue, s, min(1.0, max(0.62, 0.45 + 2.0 * val)))


def _ps(pid, fields):
    try:
        return subprocess.check_output(
            ["ps", "-o", fields, "-p", str(pid)], text=True).split(None, 2)
    except Exception:
        return []


def tty_of_pid(pid, ps=None):
    ps = ps or _ps
    for _ in range(12):
        out = ps(pid, "ppid=,tty=")
        if len(out) < 2:
            return None
        ppid, tty = out[0], out[1]
        if tty.startswith("ttys"):
            return "/dev/" + tty
        if ppid in ("0", "1"):
            return None
        pid = ppid
    return None


def direct_tty(pid, ps=None):
    """The tty of this exact process (no walking up), or None for '??'."""
    out = (ps or _ps)(pid, "ppid=,tty=")
    if len(out) < 2 or not out[1].startswith("ttys"):
        return None
    return "/dev/" + out[1]


def acquire_single_instance(pid_file):
    """Lock the pid file for this process. Returns the open handle (keep it), or None if taken."""
    os.makedirs(os.path.dirname(pid_file), exist_ok=True)
    f = open(pid_file, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    f.seek(0); f.truncate(); f.write(str(os.getpid())); f.flush()
    return f


PLUGIN_REGISTRY = os.path.join(HOME, ".claude", "plugins", "installed_plugins.json")


def newer_install(registry=PLUGIN_REGISTRY, code_dir=CODE_DIR):
    """The scripts folder of a different installed copy of this plugin, or None.
    Only a copy running from the plugin cache restarts itself; a development
    checkout is left alone."""
    if os.sep + "cache" + os.sep not in code_dir:
        return None
    data = _read_json(registry) or {}
    for key, entries in (data.get("plugins") or {}).items():
        if not key.startswith("session-widget@") or not entries:
            continue
        path = os.path.join(entries[0].get("installPath") or "", "scripts")
        if (os.path.isfile(os.path.join(path, "widget.py"))
                and os.path.realpath(path) != os.path.realpath(code_dir)):
            return path
    return None


def claude_pid_of(pid, ps=None):
    ps = ps or _ps
    for _ in range(12):
        out = ps(pid, "ppid=,comm=")
        if len(out) < 2:
            return None
        ppid, comm = out[0], out[1]
        if os.path.basename(comm) == "claude":
            return int(pid)
        if ppid in ("0", "1"):
            return None
        pid = ppid
    return None


def notify_mac(title, msg):
    """Post a macOS banner, unless banners are muted. Fire and forget."""
    if banners_muted():
        return
    q = lambda t: t.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.Popen(["osascript", "-e",
                      f'display notification "{q(msg)}" with title "{q(title)}"'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def attention_message(session):
    """(title, body) for a banner about a session that needs attention."""
    title = f"{display_label(session)} ({session.get('color_name', 'grey')})"
    word = "needs permission" if session.get("status") == "permission" else "needs input"
    return title, f"{word}: {session.get('task') or ''}".rstrip(": ")


def is_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def sort_sessions(sessions):
    return sorted(
        sessions,
        key=lambda s: (0 if s.get("status") in ATTENTION else 1, -_num(s.get("updated"))))


def is_stale(session, now, alive=is_alive):
    if not session.get("pid") or not alive(session.get("pid")):
        return True
    return now - _num(session.get("updated")) > MAX_AGE_S


def _sweep_temp_files(sessions_dir, now):
    try:
        names = os.listdir(sessions_dir)
    except FileNotFoundError:
        return
    for n in names:
        if n.endswith(".tmp"):
            p = os.path.join(sessions_dir, n)
            try:
                if now - os.path.getmtime(p) > 60:
                    os.remove(p)
            except OSError:
                pass


def cleanup(sessions_dir, now=None, alive=is_alive):
    now = time.time() if now is None else now
    _sweep_temp_files(sessions_dir, now)
    keep = []
    for s in load_sessions(sessions_dir):
        if is_stale(s, now, alive):
            delete_session(sessions_dir, s["session_id"])
        else:
            keep.append(s)
    return sort_sessions(keep)


# ---- mirroring Claude Code's own session records ----
# Claude Code keeps ~/.claude/sessions/<pid>.json with {pid, sessionId, cwd,
# status: busy|idle|shell}. Sessions that have not fired one of our hooks yet
# (started before the hooks were installed, or idle since) are mirrored from
# there so the widget still shows every terminal. A hook-written file
# (source == "hook") always wins.

CLAUDE_SESSIONS_DIR = os.path.join(HOME, ".claude", "sessions")
CLAUDE_PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
MIRROR_STATUS = {"busy": "working", "idle": "idle", "shell": "idle"}

# Tools that leave Claude waiting on something other than the user.
ARMING_TOOLS = {"Monitor": "a watcher", "ScheduleWakeup": "a timer", "CronCreate": "a timer",
                "Agent": "a subagent", "Workflow": "a workflow", "Bash": "a background job"}


def armed_by_tool(name, inp):
    """What a tool use leaves Claude waiting on, or None."""
    inp = inp or {}
    if name not in ARMING_TOOLS:
        return None
    if name in ("Bash", "Agent") and not inp.get("run_in_background"):
        return None                     # it finished before Claude stopped
    if name == "ScheduleWakeup" and inp.get("stop"):
        return None
    return ARMING_TOOLS[name]


# Stop payloads list in-flight background work and scheduled wakeups. That
# covers work from earlier turns too, which "armed" (this turn only) misses.
TASK_TYPES = {"shell": ("a background job", "background jobs"), "subagent": ("a subagent", "subagents"),
              "monitor": ("a watcher", "watchers"), "workflow": ("a workflow", "workflows")}


def waiting_from_stop(payload):
    """(known, label). known is False when the payload has no background lists
    (older Claude Code). label names what Claude waits on, or is None."""
    if "background_tasks" not in payload and "session_crons" not in payload:
        return False, None
    tasks = [t for t in payload.get("background_tasks") or [] if isinstance(t, dict)]
    crons = payload.get("session_crons") or []
    if tasks:
        kinds = {t.get("type") for t in tasks}
        one, many = (TASK_TYPES.get(kinds.pop(), ("background work", "background tasks"))
                     if len(kinds) == 1 else ("background work", "background tasks"))
        return True, one if len(tasks) == 1 else f"{len(tasks)} {many}"
    if crons:
        return True, "a timer"
    return True, None


def find_transcript(session_id, projects_dir=CLAUDE_PROJECTS_DIR):
    import glob
    hits = glob.glob(os.path.join(projects_dir, "*", session_id + ".jsonl"))
    return hits[0] if hits else None


def title_in_transcript(path, chunk=262144, max_bytes=8 * 1024 * 1024):
    """Latest {"type":"ai-title","aiTitle":...} record, searching back from the end."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            end = size
            while end > 0 and size - end < max_bytes:
                start = max(0, end - chunk)
                f.seek(start)
                data = f.read(end - start)
                lines = data.decode("utf-8", "replace").splitlines()
                if start > 0:
                    lines = lines[1:]
                for line in reversed(lines):
                    if '"ai-title"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") == "ai-title":
                        t = (d.get("aiTitle") or "").strip()
                        if t:
                            return t
                        return None
                end = start
    except OSError:
        return None
    return None


def refresh_titles(sessions_dir, projects_dir=CLAUDE_PROJECTS_DIR):
    """Pull each session's AI title from its transcript when the transcript changed."""
    for s in load_sessions(sessions_dir):
        tr = find_transcript(s["session_id"], projects_dir)
        if not tr:
            continue
        try:
            mtime = os.path.getmtime(tr)
        except OSError:
            continue
        if s.get("title_mtime") == mtime:
            continue
        title = title_in_transcript(tr)
        update_session_fn(sessions_dir, s["session_id"],
                          lambda cur: {"title": title, "title_mtime": mtime}, touch=False)


def armed_in_transcript(path, tail_bytes=262144):
    """Scan the last turn of a transcript. Returns what Claude is waiting on, or None.
    A turn starts at any user message that is not just tool results (a prompt,
    or the notification that a watcher fired)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            data = f.read()
    except OSError:
        return None
    lines = data.decode("utf-8", "replace").splitlines()
    if size > tail_bytes:
        lines = lines[1:]                     # drop the partial first line
    armed = None
    for line in lines:
        try:
            d = json.loads(line)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        content = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
        if d.get("type") == "user":
            if isinstance(content, list) and content and all(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                continue
            armed = None                      # a new turn begins
        elif d.get("type") == "assistant" and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    armed = armed_by_tool(b.get("name"), b.get("input")) or armed
    return armed


def _mirror_status(rec_status, sid, ours, projects_dir):
    """(status, armed, transcript_mtime) for a mirrored session."""
    status = MIRROR_STATUS.get(rec_status, "idle")
    if status == "working":
        return status, None, None
    tr = find_transcript(sid, projects_dir)
    try:
        mtime = os.path.getmtime(tr) if tr else None
    except OSError:
        mtime = None
    if ours and ours.get("transcript_mtime") == mtime and mtime is not None:
        armed = ours.get("armed")
    else:
        armed = armed_in_transcript(tr) if tr else None
    return ("watching" if armed else "idle"), armed, mtime


def mirror_claude_sessions(claude_dir, sessions_dir, tint_dir=TINT_DIR,
                           alive=is_alive, tty_of=tty_of_pid, projects_dir=CLAUDE_PROJECTS_DIR):
    """Seed/update mirror sessions. Returns sessions that just became needs_input."""
    newly_attention = []
    try:
        names = os.listdir(claude_dir)
    except FileNotFoundError:
        return newly_attention
    for name in names:
        if not name.endswith(".json"):
            continue
        rec = _read_json(os.path.join(claude_dir, name))
        if not rec or not rec.get("sessionId") or not rec.get("pid"):
            continue
        pid, sid = rec["pid"], rec["sessionId"]
        if not alive(pid):
            continue
        ours = load_session(sessions_dir, sid)
        if ours is not None and ours.get("source") != "mirror":
            continue
        status, armed, mtime = _mirror_status(rec.get("status"), sid, ours, projects_dir)
        if ours is None:
            tty = tty_of(pid)
            color, cname = read_tint(tint_dir, tty)
            cwd = rec.get("cwd") or ""
            data = {
                "session_id": sid, "pid": pid, "tty": tty, "color": color,
                "color_name": cname, "cwd": cwd,
                "label": os.path.basename(cwd.rstrip("/")) or cwd or "?",
                "task": rec.get("name") or "", "status": status, "source": "mirror",
                "armed": armed, "transcript_mtime": mtime, "updated": time.time()}
            data["status_since"] = data["updated"]
            write_session(sessions_dir, {k: v for k, v in data.items() if v is not None})
            continue
        was = ours.get("status")
        if status == "idle" and was in ("working", "watching", "needs_input"):
            status = "needs_input"            # it was doing something and has now stopped
        changed = (status != was or armed != ours.get("armed")
                   or mtime != ours.get("transcript_mtime"))
        if changed:
            _, new = update_session(sessions_dir, sid, status=status, armed=armed,
                                    transcript_mtime=mtime)
            if status == "needs_input" and was != "needs_input":
                newly_attention.append(new)
    return newly_attention
