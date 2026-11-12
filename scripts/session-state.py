#!/usr/bin/env python3
"""Claude Code hook: keep <widget home>/sessions/<id>.json in sync and launch the widget.

Hook use: stdin JSON from Claude Code (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop,
Notification, SessionEnd). Always exits 0.
CLI use:  session-state.py cmd show|hide|quit|name <text>
"""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import widgetlib as w

LOG = os.path.join(w.WIDGET_DIR, "hooks.log")
USAGE = "usage: /session-widget:widget [show | hide | quit | name <text> | summary on|off]"

def armed_by(payload):
    """What a PostToolUse event leaves Claude waiting on, or None."""
    return w.armed_by_tool(payload.get("tool_name"), payload.get("tool_input"))


def log(msg):
    try:
        os.makedirs(w.WIDGET_DIR, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except Exception:
        pass


def launch_widget():
    os.makedirs(w.WIDGET_DIR, exist_ok=True)
    out = open(os.path.join(w.WIDGET_DIR, "widget.log"), "a")
    subprocess.Popen([sys.executable, os.path.join(w.CODE_DIR, "widget.py")],
                     stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                     start_new_session=True, env=w.clean_env())


def ensure_widget_running(widget_dir, launch=launch_widget, alive=w.is_alive):
    try:
        with open(os.path.join(widget_dir, "widget.pid")) as f:
            pid = int(f.read().strip())
    except Exception:
        pid = None
    if alive(pid):
        return False
    launch()
    return True


def _base_fields(payload, pid, tty, tint_dir):
    color, name = w.read_tint(tint_dir, tty)
    cwd = payload.get("cwd") or os.getcwd()
    return {"pid": pid, "tty": tty, "color": color, "color_name": name,
            "cwd": cwd, "label": os.path.basename(cwd.rstrip("/")) or cwd}


def handle(payload, *, sessions_dir, tint_dir, pid, tty, notify, launch, summarise=lambda sid: None):
    event = payload.get("hook_event_name")
    sid = payload.get("session_id")
    if not sid or not event:
        return None

    if event == "SessionEnd":
        w.delete_session(sessions_dir, sid)
        return None

    fields = {}
    if event == "SessionStart":
        launch()
        fields = _base_fields(payload, pid, tty, tint_dir)
        existing = w.load_session(sessions_dir, sid)
        if payload.get("source", "startup") == "startup" or not existing:
            fields.update(status="idle", task="")
    elif event == "UserPromptSubmit":
        cur = w.load_session(sessions_dir, sid) or {}
        fields = {"status": "working", "task": w.truncate_task(payload.get("prompt", "")),
                  "armed": None, "activity": None,
                  "prompts": w.remember_prompt(cur.get("prompts"), payload.get("prompt", "")),
                  "prompt_count": int(cur.get("prompt_count") or 0) + 1}
    elif event == "PostToolUse":
        what = armed_by(payload)
        cur = w.load_session(sessions_dir, sid) or {}
        if cur.get("status") == "permission":
            fields = {"status": "working"}  # the tool ran, so the prompt was answered
        elif not what:
            return None
        if what:
            fields["armed"] = what
    elif event == "PreToolUse":
        cur = w.load_session(sessions_dir, sid)
        if cur is None:
            return None
        fields = {"activity": w.activity_text(payload.get("tool_name"), payload.get("tool_input"))}
        if payload.get("cwd"):
            fields["cwd_now"] = payload["cwd"]
        if cur.get("status") == "watching":
            fields.update(status="working", armed=None)   # the watcher fired, Claude resumed
        elif cur.get("status") in ("permission", "needs_input", "idle"):
            fields.update(status="working")               # a new step means Claude is busy again
        elif fields["activity"] == cur.get("activity") and fields.get("cwd_now") == cur.get("cwd_now"):
            return None                      # same step again: skip the write
        else:
            # Only the activity line changes. touch=False keeps the card order steady.
            _, new = w.update_session_fn(sessions_dir, sid, lambda c: fields, touch=False)
            return new
    elif event == "Stop":
        cur = w.load_session(sessions_dir, sid) or {}
        fields = {"status": "watching" if cur.get("armed") else "needs_input"}
    elif event == "Notification":
        kind = payload.get("notification_type")
        if kind == "permission_prompt":
            fields = {"status": "permission"}
        elif kind == "idle_prompt":
            cur = w.load_session(sessions_dir, sid) or {}
            if cur.get("status") == "watching":
                return None
            fields = {"status": "needs_input"}
        else:
            return None
    else:
        return None

    old = w.load_session(sessions_dir, sid)
    if old is None or "label" not in old or old.get("source") != "hook":
        fields = dict(_base_fields(payload, pid, tty, tint_dir), **fields)
        fields.setdefault("task", "")
    else:
        color, name = w.read_tint(tint_dir, tty)
        fields.update(color=color, color_name=name)
    fields["source"] = "hook"
    if payload.get("cwd"):
        fields["cwd_now"] = payload["cwd"]          # where the session is now, for the project tag
    old, new = w.update_session(sessions_dir, sid, **fields)

    was = (old or {}).get("status")
    if new["status"] in w.ATTENTION and was != new["status"]:
        notify(*w.attention_message(new))
    if event == "Stop" and w.summaries_enabled() and w.should_summarise(new):
        summarise(sid)
    return new


def start_summary(sid):
    """Run summarise.py in the background so the hook returns at once."""
    subprocess.Popen([sys.executable, os.path.join(w.CODE_DIR, "summarise.py"), sid],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True, env=w.clean_env())


def resolve_process(me, ps=None):
    """(claude pid or parent pid, tty, headless). Headless = a claude with no tty of its own."""
    cpid = w.claude_pid_of(me, ps=ps)
    if cpid:
        tty = w.direct_tty(cpid, ps=ps)
        return cpid, tty, tty is None
    out = (ps or w._ps)(me, "ppid=,tty=")
    parent = int(out[0]) if out else os.getppid()
    return parent, w.tty_of_pid(me, ps=ps), False


def cmd(args, *, sessions_dir, widget_dir, tty, pid=None):
    if not args:
        return USAGE
    word, rest = args[0], args[1:]
    if word in ("show", "hide", "quit"):
        os.makedirs(widget_dir, exist_ok=True)
        with open(os.path.join(widget_dir, "command"), "w") as f:
            f.write(word)
        return f"widget: {word}"
    if word == "summary" and rest[:1] in (["on"], ["off"]):
        w.set_summaries(rest[0] == "on")
        return f"widget: conversation summaries {rest[0]}"
    if word == "name":
        text = " ".join(rest).strip()
        sessions = w.load_sessions(sessions_dir)
        match = [s for s in sessions if pid and s.get("pid") == pid] or \
                [s for s in sessions if tty and s.get("tty") == tty]
        if match:
            w.update_session(sessions_dir, match[0]["session_id"], label_override=text)
            return f"widget: this session is now '{text}'" if text else "widget: name cleared"
        return "widget: could not find this session"
    return USAGE


def main(argv):
    me = os.getpid()
    pid, tty, headless = resolve_process(me)
    if argv[:1] == ["cmd"]:
        print(cmd(argv[1:], sessions_dir=w.SESSIONS_DIR, widget_dir=w.WIDGET_DIR, tty=tty, pid=pid))
        return
    if headless:
        return                      # `claude -p` runs are not terminals to watch
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    payload = json.loads(raw or "{}")
    handle(payload, sessions_dir=w.SESSIONS_DIR, tint_dir=w.TINT_DIR, pid=pid, tty=tty,
           notify=w.notify_mac,
           launch=lambda: ensure_widget_running(w.WIDGET_DIR), summarise=start_summary)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:
        log(f"error: {e!r}")
    sys.exit(0)
