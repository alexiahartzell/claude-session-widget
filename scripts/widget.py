#!/usr/bin/env python3
"""Always-on-top panel listing live Claude Code sessions. Reads <widget home>/sessions."""
import json, os, subprocess, sys, threading, time
import tkinter as tk
import tkinter.font as tkfont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import widgetlib as w

POLL_MS = 500
TAB_POLL_S = 1.5      # how often to read the Terminal tab titles
TAB_SCRIPT = '''set out to ""
tell application "Terminal"
repeat with wnd in windows
repeat with t in tabs of wnd
set out to out & (tty of t) & tab & (custom title of t) & linefeed
end repeat
end repeat
end tell
return out'''
PULSE_MS = 600
EMPTY_HIDE_S = 30
W_PX = 350            # panel width
PAD = 10              # inner padding
CARD_H = 58           # minimum card height
LINE_H = 18           # title line height
CARD_GAP = 8
RADIUS = 16
PILL_H = 20           # status pill height
PILL_PAD = 9          # space either side of the status word inside its pill
STATUS_WORD = {"working": "working", "needs_input": "needs you", "permission": "permission",
               "idle": "idle", "watching": "watching"}
STATE_FILE = os.path.join(w.WIDGET_DIR, "widget-state.json")
PID_FILE = os.path.join(w.WIDGET_DIR, "widget.pid")
CMD_FILE = os.path.join(w.WIDGET_DIR, "command")


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def focus_tab(tty):
    if not tty:
        return
    script = f'''tell application "Terminal"
repeat with wnd in windows
repeat with t in tabs of wnd
if tty of t is "{tty}" then
set selected tab of wnd to t
set index of wnd to 1
activate
return
end if
end repeat
end repeat
end tell'''
    subprocess.Popen(["osascript", "-e", script],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class TabWatcher(threading.Thread):
    """Reads every Terminal tab's title in the background, so a slow
    AppleScript call never freezes the panel. Remembers how long each tab's
    spinner state has held."""
    def __init__(self):
        super().__init__(daemon=True)
        self.lock = threading.Lock()
        self.tabs = {}                  # tty -> (state, title, since)

    def run(self):
        while True:
            try:
                if subprocess.run(["pgrep", "-x", "Terminal"], capture_output=True).returncode == 0:
                    out = subprocess.run(["osascript", "-e", TAB_SCRIPT], capture_output=True,
                                         text=True, timeout=5).stdout
                    self.update(w.parse_tab_titles(out))
            except Exception as e:
                log(f"tabs: {e!r}")
            time.sleep(TAB_POLL_S)

    def update(self, parsed):
        now = time.time()
        with self.lock:
            old = self.tabs
            self.tabs = {tty: (st, title, old[tty][2] if tty in old and old[tty][0] == st else now)
                         for tty, (st, title) in parsed.items()}

    def snapshot(self):
        with self.lock:
            return dict(self.tabs)


def rounded(canvas, x1, y1, x2, y2, r, **kw):
    """A rounded rectangle as a smoothed polygon."""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, splinesteps=12, **kw)


def mix(hex_a, hex_b, t):
    """Blend two '#rrggbb' colours; t=0 gives a, t=1 gives b."""
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(round(x + (y - x) * t)):02x}" for x, y in zip(a, b))


class Widget:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparent", True)
            self.root.config(bg="systemTransparent")
            canvas_bg = "systemTransparent"
        except Exception:
            canvas_bg = "#" + w.PANEL_THEMES["dark"]["bg"]
        self.alive = True
        self.hidden = False
        self.seen_attention = set()
        self.empty_since = None
        self.pulse_on = False
        self.last_key = None
        self.sessions = []
        self.pulse_items = []       # (item id, bright colour, dim colour)
        self.drag = None
        self.mode = "dark"

        def font(size, bold=False, family="Avenir Next"):
            return tkfont.Font(family=family, size=size, weight="bold" if bold else "normal")
        self.f_title = font(11, False)
        self.f_label = font(13, True)
        self.f_sub = font(10)
        self.f_status = font(10, True)
        self.f_time = font(9)
        self.f_tag = font(10, True)
        self.f_close = font(13, False)
        # Every title gets the same width, set by the widest possible pill.
        self.pill_w = max(self.f_status.measure(t) for t in STATUS_WORD.values()) + 2 * PILL_PAD

        self.c = tk.Canvas(self.root, width=W_PX, height=100, bg=canvas_bg,
                           highlightthickness=0, bd=0)
        self.c.pack()
        self.c.bind("<Button-1>", self.on_click)
        self.c.bind("<B1-Motion>", self.drag_move)
        self.c.bind("<ButtonRelease-1>", self.on_release)

        self.restore_pos()
        self.write_pid()
        self.tabs = TabWatcher()
        self.tabs.start()
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.after(100, self.tick)
        self.root.after(PULSE_MS, self.pulse)

    # ---- window position ----
    def restore_pos(self):
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        try:
            with open(STATE_FILE) as f:
                st = json.load(f)
            self.anchor = (int(st["x"]), int(st["bottom"]))
        except Exception:
            self.anchor = (sw - W_PX - 24, sh - 110)
        self.place()

    def place(self):
        self.root.update_idletasks()
        x, bottom = self.anchor
        y = max(0, bottom - int(self.c.cget("height")))
        self.root.geometry(f"{W_PX}x{int(self.c.cget('height'))}+{x}+{y}")

    def save_pos(self):
        self.anchor = (self.root.winfo_x(), self.root.winfo_y() + self.root.winfo_height())
        try:
            os.makedirs(w.WIDGET_DIR, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump({"x": self.anchor[0], "bottom": self.anchor[1]}, f)
        except Exception as e:
            log(f"save_pos: {e!r}")

    # ---- mouse ----
    def on_click(self, e):
        tags = self.c.gettags("current")
        if "close" in tags:
            self.hide()
            return
        for t in tags:
            if t.startswith("card:"):
                self.clicked_card = t[5:]
                break
        else:
            self.clicked_card = None
        self.drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y(), e.x_root, e.y_root)

    def drag_move(self, e):
        if self.drag:
            self.root.geometry(f"+{e.x_root - self.drag[0]}+{e.y_root - self.drag[1]}")

    def on_release(self, e):
        if not self.drag:
            return
        moved = abs(e.x_root - self.drag[2]) + abs(e.y_root - self.drag[3])
        self.drag = None
        if moved > 4:
            self.save_pos()
        elif self.clicked_card:
            for s in self.sessions:
                if s["session_id"] == self.clicked_card:
                    focus_tab(s.get("tty"))

    # ---- lifecycle ----
    def write_pid(self):
        self.pid_lock = w.acquire_single_instance(PID_FILE)
        if self.pid_lock is None:
            log("another widget is already running; exiting")
            sys.exit(0)

    def quit(self):
        try:
            os.remove(PID_FILE)
            self.pid_lock.close()
        except (FileNotFoundError, AttributeError):
            pass
        self.alive = False
        self.root.destroy()

    def show(self):
        self.hidden = False
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()

    def hide(self):
        self.hidden = True
        self.root.withdraw()

    def read_command(self):
        try:
            with open(CMD_FILE) as f:
                word = f.read().strip()
            os.remove(CMD_FILE)
        except FileNotFoundError:
            return
        except Exception as e:
            log(f"command: {e!r}")
            return
        {"show": self.show, "hide": self.hide, "quit": self.quit}.get(word, lambda: None)()

    # ---- polling ----
    def tick(self):
        try:
            self.read_command()
            if not self.alive:
                return
            for s in w.mirror_claude_sessions(w.CLAUDE_SESSIONS_DIR, w.SESSIONS_DIR):
                w.notify_mac(*w.attention_message(s))
            w.refresh_titles(w.SESSIONS_DIR)
            w.refresh_tints(w.SESSIONS_DIR)
            self.apply_tabs()
            sessions = w.cleanup(w.SESSIONS_DIR)
            self.handle_attention(sessions)
            self.handle_empty(sessions)
            self.mode = w.effective_mode()
            key = [self.mode] + [(s["session_id"], s.get("status"), s.get("armed"), w.display_label(s),
                                  s.get("title"), s.get("task"), s.get("activity"), s.get("color"),
                                  w.project_tag(s), w.elapsed_text(s)) for s in sessions]
            if key != self.last_key:
                self.last_key = key
                self.redraw(sessions)
        except Exception as e:
            log(f"tick: {e!r}")
        self.root.after(POLL_MS, self.tick)

    def apply_tabs(self):
        """Correct statuses from Claude's spinner in each tab, and fill in titles."""
        tabs = self.tabs.snapshot()
        if not tabs:
            return
        now = time.time()
        for s in w.load_sessions(w.SESSIONS_DIR):
            tab = tabs.get(s.get("tty"))
            if not tab:
                continue
            state, title, since = tab
            # Count only the time since the card last changed, so a prompt you just
            # sent is not flipped back by a spinner that has not started yet.
            held = now - max(since, w._num(s.get("status_since") or s.get("updated")))
            fix = w.reconcile(s, state, held)
            if title and title != s.get("tab_title"):
                w.update_session_fn(w.SESSIONS_DIR, s["session_id"],
                                    lambda cur: {"tab_title": title}, touch=False)
            if fix:
                log(f"tab says {state}: {s['session_id'][:8]} {s.get('status')} -> {fix['status']}")
                _, new = w.update_session(w.SESSIONS_DIR, s["session_id"], **fix)
                if new.get("status") in w.ATTENTION:
                    w.notify_mac(*w.attention_message(new))

    def handle_attention(self, sessions):
        current = {(s["session_id"], s.get("updated")) for s in sessions
                   if s.get("status") in w.ATTENTION}
        new = current - self.seen_attention
        self.seen_attention = current
        if new and self.hidden:
            self.show()

    def handle_empty(self, sessions):
        if sessions:
            self.empty_since = None
            if self.hidden is False and self.root.state() == "withdrawn":
                self.show()
            return
        if self.empty_since is None:
            self.empty_since = time.time()
        elif time.time() - self.empty_since > EMPTY_HIDE_S and not self.hidden:
            self.root.withdraw()

    # ---- drawing ----
    def theme(self):
        """Panel colours for the current light or dark mode, as '#rrggbb'."""
        return {k: "#" + v for k, v in w.PANEL_THEMES[self.mode].items()}

    def redraw(self, sessions):
        c = self.c
        th = self.theme()
        c.delete("all")
        self.sessions = sessions
        self.pulse_items = []
        head_h = 34
        y = head_h + PAD
        if not sessions:
            c.create_text(W_PX / 2, y + CARD_H / 2, text="nothing running", fill=th["dim"], font=self.f_sub)
            y += CARD_H
        for s in sessions:
            y += self.draw_card(s, y) + CARD_GAP
        height = y - (CARD_GAP if sessions else 0) + PAD
        c.config(height=height)
        rounded(c, 0, 0, W_PX, height, RADIUS + 4, fill=th["bg"], outline=th["outline"], tags=("panel",))
        c.tag_lower("panel")
        c.create_text(PAD + 8, head_h / 2, text="claude", anchor="w", fill=th["dim"], font=self.f_title)
        c.create_text(W_PX - PAD - 8, head_h / 2, text="×", anchor="e", fill=th["dim"],
                      font=self.f_close, tags=("close",))
        self.place()
        if not self.hidden and self.root.state() == "withdrawn" and sessions:
            self.show()

    @staticmethod
    def fit(text, font, max_px):
        """Shorten text with an ellipsis so it fits in max_px."""
        if font.measure(text) <= max_px:
            return text
        while text and font.measure(text + "…") > max_px:
            text = text[:-1]
        return text.rstrip() + "…"

    def title_lines(self, text, max_px):
        """Wrap a title onto at most two lines at word boundaries, no ellipsis."""
        words = text.split()
        lines, cur = [], ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if self.f_label.measure(trial) <= max_px or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        return lines[:2]

    def draw_card(self, s, y):
        """Draw one session card at y; returns its height."""
        c = self.c
        th = self.theme()
        tag = "card:" + s["session_id"]
        color = s.get("color") or w.GREY
        vivid = "#" + w.accent(color, self.mode)
        status = s.get("status") or "idle"
        attention = status in w.ATTENTION
        x1, x2 = PAD, W_PX - PAD
        pill_x2 = x2 - 14
        text_x = x1 + 18
        text_w = (pill_x2 - self.pill_w - 12) - text_x
        lines = self.title_lines(w.display_label(s), text_w)
        h = CARD_H + LINE_H * (len(lines) - 1)
        card_fill = "#" + w.card_fill(color, th["bg"][1:], self.mode)
        glow = rounded(c, x1 - 2, y - 2, x2 + 2, y + h + 2, RADIUS + 2,
                       fill="", outline=vivid if attention else "", width=3, tags=(tag,))
        rounded(c, x1, y, x2, y + h, RADIUS, fill=card_fill, outline="", tags=(tag,))

        ty = y + 19
        for line in lines:
            c.create_text(text_x, ty, text=line, anchor="w",
                          fill=th["fg"] if attention else mix(th["fg"], th["dim"], 0.4), font=self.f_label, tags=(tag,))
            ty += LINE_H
        self.draw_subtitle(s, text_x, ty + 3, text_w, vivid, th, tag)
        self.draw_status(s, status, attention, pill_x2, y, h, vivid, card_fill, th, tag)
        if attention:
            self.pulse_items.append((glow, vivid, mix(vivid, card_fill, 0.7)))
        return h

    def draw_subtitle(self, s, x, y, width, vivid, th, tag):
        """Project name in the card's accent colour, then the activity or task."""
        c = self.c
        project = w.project_tag(s)
        if project:
            project = self.fit(project, self.f_tag, width * 0.45)
            c.create_text(x, y, text=project, anchor="w", fill=vivid, font=self.f_tag, tags=(tag,))
            x += self.f_tag.measure(project) + 4
            width -= self.f_tag.measure(project) + 4
            c.create_text(x, y, text="·", anchor="w", fill=th["dim"], font=self.f_sub, tags=(tag,))
            x += self.f_sub.measure("· ")
            width -= self.f_sub.measure("· ")
        sub = self.fit(w.subtitle(s), self.f_sub, max(width, 0))
        c.create_text(x, y, text=sub, anchor="w", fill=th["dim"], font=self.f_sub, tags=(tag,))

    def pill(self, x1, y1, x2, y2, fill, tag):
        """A crisp capsule: two circles joined by a rectangle. A smoothed polygon
        looks lumpy at this size."""
        c, d = self.c, y2 - y1
        c.create_oval(x1, y1, x1 + d, y2, fill=fill, outline=fill, tags=(tag,))
        c.create_oval(x2 - d, y1, x2, y2, fill=fill, outline=fill, tags=(tag,))
        c.create_rectangle(x1 + d / 2, y1, x2 - d / 2, y2, fill=fill, outline=fill, tags=(tag,))

    def draw_status(self, s, status, attention, right, y, h, vivid, card_fill, th, tag):
        """A rounded pill holding the status word, with the time in that status below it."""
        c = self.c
        word = STATUS_WORD.get(status, status)
        since = w.elapsed_text(s)
        pw = self.f_status.measure(word) + 2 * PILL_PAD
        block_h = PILL_H + (15 if since else 0)
        py = y + (h - block_h) / 2
        if attention:
            fill, ink = mix(vivid, card_fill, 0.35), th["fg"]
        else:
            fill, ink = mix(card_fill, th["fg"], 0.10), mix(th["fg"], th["dim"], 0.25)
        self.pill(right - pw, py, right, py + PILL_H, fill, tag)
        c.create_text(right - pw / 2, py + PILL_H / 2, text=word, fill=ink, font=self.f_status, tags=(tag,))
        if since:
            c.create_text(right - pw / 2, py + PILL_H + 9, text=since, fill=th["dim"],
                          font=self.f_time, tags=(tag,))

    def pulse(self):
        if not self.alive:
            return
        try:
            self.pulse_on = not self.pulse_on
            for item, bright, dim in self.pulse_items:
                self.c.itemconfigure(item, outline=bright if self.pulse_on else dim)
        except Exception as e:
            log(f"pulse: {e!r}")
        self.root.after(PULSE_MS, self.pulse)


def main():
    # Drop macOS malloc debugging switches so osascript children stay quiet in the log.
    for k in [k for k in os.environ if k.startswith("Malloc")]:
        del os.environ[k]
    app = Widget()
    app.root.mainloop()


if __name__ == "__main__":
    main()
