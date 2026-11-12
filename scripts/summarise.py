#!/usr/bin/env python3
"""Write a one-line summary of a session's conversation into its card.

Started in the background by the Stop hook. Asks a small model through the
`claude` command already installed, with hooks off so it does not trigger
this plugin or anything else. Usage: summarise.py <session id>
"""
import json, os, shutil, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import widgetlib as w

MODEL = os.environ.get("CLAUDE_WIDGET_SUMMARY_MODEL", "haiku")
TIMEOUT_S = 60


def ask(prompt):
    exe = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    out = subprocess.run(
        [exe, "-p", "--model", MODEL, "--no-session-persistence", "--tools", "",
         "--settings", json.dumps({"disableAllHooks": True}), "--output-format", "json"],
        input=prompt, capture_output=True, text=True, timeout=TIMEOUT_S,
        cwd=w.WIDGET_DIR, env=w.clean_env())
    return json.loads(out.stdout or "{}").get("result") or ""


def main(sid):
    now = time.time()
    if w.load_session(w.SESSIONS_DIR, sid) is None:
        return
    claimed = []

    def claim(cur):
        if not w.should_summarise(cur, now):
            return {}
        claimed.append(dict(cur))
        return {"summary_started": now}
    w.update_session_fn(w.SESSIONS_DIR, sid, claim, touch=False)
    if not claimed:
        return                                   # up to date, or another run has it
    snapshot = claimed[0]
    line = w.clean_summary(ask(w.summary_request(snapshot)))
    if not line or w.load_session(w.SESSIONS_DIR, sid) is None:
        return
    w.update_session_fn(w.SESSIONS_DIR, sid,
                        lambda cur: {"summary": line, "summary_for": snapshot.get("prompt_count")},
                        touch=False)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 2:
            main(sys.argv[1])
    except Exception:
        pass
