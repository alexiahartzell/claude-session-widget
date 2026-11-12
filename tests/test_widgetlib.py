import json, os, time
import widgetlib as w


def test_write_and_load_session(tmp_path):
    d = str(tmp_path / "sessions")
    w.write_session(d, {"session_id": "abc", "status": "idle"})
    assert w.load_session(d, "abc") == {"session_id": "abc", "status": "idle"}
    assert w.load_session(d, "nope") is None


def test_load_sessions_skips_malformed(tmp_path):
    d = tmp_path / "sessions"
    d.mkdir()
    (d / "good.json").write_text(json.dumps({"session_id": "good"}))
    (d / "bad.json").write_text("{not json")
    (d / "empty.json").write_text("")
    (d / "notes.txt").write_text("ignore me")
    got = w.load_sessions(str(d))
    assert [s["session_id"] for s in got] == ["good"]


def test_update_session_preserves_fields(tmp_path):
    d = str(tmp_path / "sessions")
    w.write_session(d, {"session_id": "abc", "label": "proj", "status": "idle", "updated": 1.0})
    old, new = w.update_session(d, "abc", status="working", task="hello")
    assert old["status"] == "idle"
    assert new["label"] == "proj"
    assert new["status"] == "working"
    assert new["task"] == "hello"
    assert new["updated"] > 1.0
    assert w.load_session(d, "abc") == new


def test_update_session_creates_when_missing(tmp_path):
    d = str(tmp_path / "sessions")
    old, new = w.update_session(d, "fresh", status="idle")
    assert old is None
    assert new["session_id"] == "fresh"
    assert new["status"] == "idle"


def test_delete_session(tmp_path):
    d = str(tmp_path / "sessions")
    w.write_session(d, {"session_id": "abc"})
    w.delete_session(d, "abc")
    w.delete_session(d, "abc")  # second delete is a no-op
    assert w.load_session(d, "abc") is None


def test_truncate_task_newlines():
    p = "fix the plot\n\nthen   rerun  the   fit " + "x" * 100
    out = w.truncate_task(p)
    assert "\n" not in out
    assert len(out) <= 60
    assert out.startswith("fix the plot then rerun the fit")


def test_truncate_task_unicode_and_empty():
    assert w.truncate_task("") == ""
    assert w.truncate_task("   ") == ""
    assert w.truncate_task("ψ-function σ") == "ψ-function σ"


def test_display_label_override_wins():
    assert w.display_label({"label": "proj"}) == "proj"
    assert w.display_label({"label": "proj", "label_override": "paper"}) == "paper"
    assert w.display_label({"label": "proj", "label_override": ""}) == "proj"
    assert w.display_label({}) == "?"
import subprocess, sys


def test_read_tint_found(tmp_path):
    (tmp_path / "_dev_ttys008.json").write_text(
        json.dumps({"orig": "000000", "tint": "1e1026", "name": "plum"}))
    assert w.read_tint(str(tmp_path), "/dev/ttys008") == ("1e1026", "plum")


def test_read_tint_missing(tmp_path):
    assert w.read_tint(str(tmp_path), "/dev/ttys999") == (w.GREY, "grey")
    assert w.read_tint(str(tmp_path), None) == (w.GREY, "grey")
    (tmp_path / "_dev_ttys001.json").write_text("garbage")
    assert w.read_tint(str(tmp_path), "/dev/ttys001") == (w.GREY, "grey")


def test_refresh_tints_follows_tab_colour_changes(tmp_path):
    sessions, tint = str(tmp_path / "sessions"), tmp_path / "tint"
    tint.mkdir()
    w.write_session(sessions, {"session_id": "s1", "tty": "/dev/ttys008", "color": w.GREY,
                               "color_name": "grey", "updated": 100.0})
    (tint / "_dev_ttys008.json").write_text(json.dumps({"tint": "1e1026", "name": "plum"}))
    w.refresh_tints(sessions, str(tint))
    s = w.load_session(sessions, "s1")
    assert (s["color"], s["color_name"]) == ("1e1026", "plum")
    assert s["updated"] == 100.0          # a colour change is not session activity


def test_cards_stay_readable_in_both_panel_modes():
    # Dark panel: light text, so every card must be dark, whatever the tab tint.
    # Light panel: dark text, so every card must be light and its accent dark.
    dark_bg, light_bg = w.PANEL_THEMES["dark"]["bg"], w.PANEL_THEMES["light"]["bg"]
    for tint in ("1e1026", "0c1f16", "efe6fb", "fbf3d5", w.GREY):
        assert not w.is_light(w.card_fill(tint, dark_bg, "dark")), tint
        assert w.is_light(w.card_fill(tint, light_bg, "light")), tint
        assert not w.is_light(w.accent(tint, "light")), tint


def test_brighten_keeps_hue_and_is_vivid():
    # plum 1e1026 is dark purple: blue > red > green. The swatch colour must
    # keep that ordering and be bright and saturated enough to tell apart.
    out = w.brighten("1e1026")
    r, g, b = (int(out[i:i + 2], 16) for i in (0, 2, 4))
    assert len(out) == 6
    assert b > r > g
    assert max(r, g, b) >= 180
    assert max(r, g, b) - min(r, g, b) >= 80
    # forest 0c1f16 stays green-dominant
    r2, g2, b2 = (int(w.brighten("0c1f16")[i:i + 2], 16) for i in (0, 2, 4))
    assert g2 > r2 and g2 > b2
    # pure grey stays grey (no hue to amplify) but gets lifted
    rg, gg, bg = (int(w.brighten(w.GREY)[i:i + 2], 16) for i in (0, 2, 4))
    assert abs(rg - gg) <= 12 and abs(gg - bg) <= 12 and rg >= 120
    assert w.brighten("ffffff") == "ffffff"
    # pastel mint e2f4e8 has little saturation but a clear green hue: keep it
    r3, g3, b3 = (int(w.brighten("e2f4e8")[i:i + 2], 16) for i in (0, 2, 4))
    assert g3 > r3 and g3 > b3 and max(r3, g3, b3) - min(r3, g3, b3) >= 80


def test_is_alive():
    assert w.is_alive(os.getpid())
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert not w.is_alive(p.pid)
    assert not w.is_alive(None)


def test_claude_pid_of_returns_none_when_no_claude_ancestor():
    # pytest run from a shell has no process named "claude" above it,
    # unless the tests are run from inside Claude Code; accept both.
    got = w.claude_pid_of(os.getpid())
    assert got is None or isinstance(got, int)


def test_sort_sessions_attention_first_then_recent():
    s = [
        {"session_id": "a", "status": "working", "updated": 30},
        {"session_id": "b", "status": "needs_input", "updated": 10},
        {"session_id": "c", "status": "idle", "updated": 20},
        {"session_id": "d", "status": "permission", "updated": 5},
    ]
    assert [x["session_id"] for x in w.sort_sessions(s)] == ["b", "d", "a", "c"]


def test_is_stale():
    now = 1_000_000.0
    live = {"pid": 1, "updated": now - 10}
    assert not w.is_stale(live, now, alive=lambda p: True)
    assert w.is_stale(live, now, alive=lambda p: False)
    old = {"pid": 1, "updated": now - w.MAX_AGE_S - 1}
    assert w.is_stale(old, now, alive=lambda p: True)
    assert w.is_stale({"updated": now}, now, alive=lambda p: True)  # no pid


def test_cleanup_deletes_stale_and_returns_sorted(tmp_path):
    d = str(tmp_path / "sessions")
    now = 1_000_000.0
    w.write_session(d, {"session_id": "dead", "pid": 2, "status": "working", "updated": now})
    w.write_session(d, {"session_id": "old", "pid": 1, "status": "working", "updated": now - 2 * w.MAX_AGE_S})
    w.write_session(d, {"session_id": "ok", "pid": 1, "status": "working", "updated": now - 5})
    w.write_session(d, {"session_id": "hot", "pid": 1, "status": "needs_input", "updated": now - 50})
    got = w.cleanup(d, now, alive=lambda p: p == 1)
    assert [s["session_id"] for s in got] == ["hot", "ok"]
    assert sorted(os.listdir(d)) == ["hot.json", "ok.json"]


def test_load_sessions_ignores_foreign_json(tmp_path):
    # Claude Code keeps its own <pid>.json files in ~/.claude/sessions with a
    # "sessionId" key; the widget must never treat those as its own.
    d = tmp_path / "sessions"
    d.mkdir()
    (d / "17282.json").write_text(json.dumps({"pid": 17282, "sessionId": "x", "status": "busy"}))
    assert w.load_sessions(str(d)) == []


# ---- mirroring Claude Code's own session records (for sessions that
# started before the hooks were installed, or have not fired a hook yet) ----

def _claude_record(d, pid, sid, status, cwd="/Users/me/dynamics"):
    d.mkdir(exist_ok=True)
    (d / f"{pid}.json").write_text(json.dumps(
        {"pid": pid, "sessionId": sid, "cwd": cwd, "status": status, "name": "x"}))


def test_mirror_seeds_missing_sessions_with_colour(tmp_path):
    cl, se, ti = tmp_path / "claude", str(tmp_path / "sessions"), tmp_path / "tint"
    ti.mkdir()
    (ti / "_dev_ttys003.json").write_text(json.dumps({"orig": "000000", "tint": "0c1f16", "name": "forest"}))
    _claude_record(cl, 3989, "sid-a", "busy")
    _claude_record(cl, 5114, "sid-b", "idle")
    _claude_record(cl, 9999, "sid-dead", "busy")
    new_attention = w.mirror_claude_sessions(
        str(cl), se, tint_dir=str(ti),
        alive=lambda p: p in (3989, 5114),
        tty_of=lambda p: "/dev/ttys003" if p == 3989 else None)
    a, b = w.load_session(se, "sid-a"), w.load_session(se, "sid-b")
    assert a["status"] == "working" and a["source"] == "mirror"
    assert a["color"] == "0c1f16" and a["color_name"] == "forest" and a["tty"] == "/dev/ttys003"
    assert a["label"] == "dynamics" and a["pid"] == 3989
    assert b["status"] == "idle" and b["color"] == w.GREY     # idle at seed time: plain, no pulse
    assert w.load_session(se, "sid-dead") is None
    assert new_attention == []


def test_mirror_busy_to_idle_becomes_needs_input_once(tmp_path):
    cl, se = tmp_path / "claude", str(tmp_path / "sessions")
    _claude_record(cl, 3989, "sid-a", "busy")
    w.mirror_claude_sessions(str(cl), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None)
    _claude_record(cl, 3989, "sid-a", "idle")
    got = w.mirror_claude_sessions(str(cl), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None)
    assert [s["session_id"] for s in got] == ["sid-a"]
    assert w.load_session(se, "sid-a")["status"] == "needs_input"
    got2 = w.mirror_claude_sessions(str(cl), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None)
    assert got2 == []
    assert w.load_session(se, "sid-a")["status"] == "needs_input"
    _claude_record(cl, 3989, "sid-a", "busy")
    w.mirror_claude_sessions(str(cl), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None)
    assert w.load_session(se, "sid-a")["status"] == "working"


def test_mirror_leaves_hook_owned_sessions_alone(tmp_path):
    cl, se = tmp_path / "claude", str(tmp_path / "sessions")
    _claude_record(cl, 3989, "sid-a", "idle")
    w.write_session(se, {"session_id": "sid-a", "pid": 3989, "status": "working",
                         "source": "hook", "label": "proj", "updated": 5.0})
    w.mirror_claude_sessions(str(cl), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None)
    assert w.load_session(se, "sid-a")["status"] == "working"
    assert w.load_session(se, "sid-a")["updated"] == 5.0


def test_mirror_survives_bad_records(tmp_path):
    cl, se = tmp_path / "claude", str(tmp_path / "sessions")
    cl.mkdir()
    (cl / "1.json").write_text("junk")
    (cl / "2.json").write_text(json.dumps({"pid": 2}))          # no sessionId
    (cl / "3.key").write_text("secret")
    assert w.mirror_claude_sessions(str(cl), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None) == []
    assert w.mirror_claude_sessions(str(tmp_path / "missing"), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None) == []


def test_mirror_uses_claude_name_as_task(tmp_path):
    cl, se = tmp_path / "claude", str(tmp_path / "sessions")
    _claude_record(cl, 3989, "sid-a", "busy")
    w.mirror_claude_sessions(str(cl), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None)
    assert w.load_session(se, "sid-a")["task"] == "x"


def test_subtitle_falls_back_to_colour_name():
    assert w.subtitle({"task": "fix plot", "color_name": "plum"}) == ""     # idle: nothing happening now
    assert w.subtitle({}) == ""


# ---- review fixes ----

def test_concurrent_updates_lose_nothing(tmp_path):
    import multiprocessing as mp
    d = str(tmp_path / "sessions")
    w.write_session(d, {"session_id": "s", "n_a": 0, "n_b": 0, "status": "idle"})

    def worker(field):
        for _ in range(150):
            w.update_session_fn(d, "s", lambda cur, f=field: {f: cur.get(f, 0) + 1})

    ctx = mp.get_context("fork")
    ps = [ctx.Process(target=worker, args=(f,)) for f in ("n_a", "n_b")]
    [p.start() for p in ps]; [p.join() for p in ps]
    got = w.load_session(d, "s")
    assert got["n_a"] == 150 and got["n_b"] == 150
    assert got["status"] == "idle"
    assert [n for n in os.listdir(d) if n.endswith(".tmp")] == []


def test_update_session_fn_creates_when_missing(tmp_path):
    d = str(tmp_path / "sessions")
    old, new = w.update_session_fn(d, "x", lambda cur: {"status": "working"})
    assert old is None and new["status"] == "working" and new["session_id"] == "x"


def test_cleanup_removes_stale_temp_files(tmp_path):
    d = tmp_path / "sessions"
    d.mkdir()
    (d / "abc.json.tmp").write_text("{")
    os.utime(d / "abc.json.tmp", (1, 1))
    (d / "fresh.json.tmp").write_text("{")
    w.cleanup(str(d), now=1_000_000.0)
    assert sorted(os.listdir(d)) == ["fresh.json.tmp"]


def test_sort_and_stale_survive_junk_updated():
    s = [{"session_id": "a", "status": "idle", "updated": "junk"},
         {"session_id": "b", "status": "idle", "updated": None}]
    assert [x["session_id"] for x in w.sort_sessions(s)] == ["a", "b"]
    assert w.is_stale({"pid": 1, "updated": "junk"}, 1_000_000.0, alive=lambda p: True)


def test_direct_tty_and_headless_detection():
    fake = {"17282": ["1", "ttys008", "claude"], "23185": ["1", "??", "claude"]}
    ps = lambda pid, fields: fake.get(str(pid), [])
    assert w.direct_tty(17282, ps=ps) == "/dev/ttys008"
    assert w.direct_tty(23185, ps=ps) is None
    assert w.direct_tty(1, ps=ps) is None


def test_single_instance_lock(tmp_path):
    p = str(tmp_path / "widget.pid")
    h1 = w.acquire_single_instance(p)
    assert h1 is not None
    assert open(p).read().strip() == str(os.getpid())
    assert w.acquire_single_instance(p) is None
    h1.close()
    h2 = w.acquire_single_instance(p)
    assert h2 is not None
    h2.close()


def test_subtitle_while_watching_names_what_it_waits_on():
    assert w.subtitle({"status": "watching", "armed": "a watcher", "task": "run the calc"}) == "waiting on a watcher"
    assert w.subtitle({"status": "watching", "armed": "a subagent", "task": ""}) == "waiting on a subagent"


# ---- reading armed watchers out of a mirrored session's transcript ----

def _jl(*msgs):
    return "\n".join(json.dumps(m) for m in msgs) + "\n"


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _tool_result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


def _assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def _tool(name, **inp):
    return {"type": "tool_use", "name": name, "input": inp}


def test_armed_in_transcript_sees_background_job_in_last_turn(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(_jl(
        _user("run the calc"),
        _assistant(_tool("Bash", command="ls")), _tool_result(),
        _assistant(_tool("Bash", command="python3 calc.py", run_in_background=True)), _tool_result(),
        _assistant({"type": "text", "text": "I'll wait for it."}),
        {"type": "system", "content": "x"}))
    assert w.armed_in_transcript(str(f)) == "a background job"


def test_armed_in_transcript_cleared_once_the_watcher_fired(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(_jl(
        _user("run the calc"),
        _assistant(_tool("Bash", command="python3 calc.py", run_in_background=True)), _tool_result(),
        _user("<task-notification>done</task-notification>"),
        _assistant(_tool("Read", file_path="/x")), _tool_result(),
        _assistant({"type": "text", "text": "Finished."})))
    assert w.armed_in_transcript(str(f)) is None


def test_armed_in_transcript_rearmed_after_notification(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(_jl(
        _user("run the calc"),
        _assistant(_tool("Bash", command="python3 calc.py", run_in_background=True)), _tool_result(),
        _user("<task-notification>done</task-notification>"),
        _assistant(_tool("Agent", prompt="review", run_in_background=True)), _tool_result()))
    assert w.armed_in_transcript(str(f)) == "a subagent"


def test_armed_in_transcript_handles_missing_and_junk(tmp_path):
    assert w.armed_in_transcript(str(tmp_path / "nope.jsonl")) is None
    f = tmp_path / "s.jsonl"
    f.write_text("not json\n{\"type\": \"user\"}\n")
    assert w.armed_in_transcript(str(f)) is None


def test_armed_in_transcript_only_reads_the_tail(tmp_path):
    f = tmp_path / "s.jsonl"
    filler = [_assistant({"type": "text", "text": "x" * 500})] * 300
    f.write_text(_jl(_user("old"), *filler, _user("go"),
                     _assistant(_tool("ScheduleWakeup", delaySeconds=600)), _tool_result()))
    assert w.armed_in_transcript(str(f), tail_bytes=20000) == "a timer"


def test_find_transcript(tmp_path):
    proj = tmp_path / "projects" / "-Users-me-dynamics"
    proj.mkdir(parents=True)
    (proj / "sid-a.jsonl").write_text("")
    assert w.find_transcript("sid-a", str(tmp_path / "projects")) == str(proj / "sid-a.jsonl")
    assert w.find_transcript("sid-zzz", str(tmp_path / "projects")) is None


def test_mirror_marks_watching_from_transcript_and_alerts_when_done(tmp_path):
    cl, se = tmp_path / "claude", str(tmp_path / "sessions")
    proj = tmp_path / "projects" / "-x-proj"
    proj.mkdir(parents=True)
    tr = proj / "sid-a.jsonl"
    tr.write_text(_jl(_user("run it"),
                      _assistant(_tool("Bash", command="calc", run_in_background=True)), _tool_result(),
                      _assistant({"type": "text", "text": "waiting"})))
    _claude_record(cl, 3989, "sid-a", "shell", cwd="/x/proj")
    kw = dict(tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None,
              projects_dir=str(tmp_path / "projects"))
    assert w.mirror_claude_sessions(str(cl), se, **kw) == []
    s = w.load_session(se, "sid-a")
    assert s["status"] == "watching" and s["armed"] == "a background job"
    # the job finishes, Claude resumes, finishes its turn with no new watcher
    import time as _t; _t.sleep(0.01)
    with open(tr, "a") as fh:
        fh.write(_jl(_user("<task-notification>done</task-notification>"),
                     _assistant({"type": "text", "text": "All done."})))
    os.utime(tr, None)
    _claude_record(cl, 3989, "sid-a", "idle", cwd="/x/proj")
    got = w.mirror_claude_sessions(str(cl), se, **kw)
    assert [x["session_id"] for x in got] == ["sid-a"]
    s = w.load_session(se, "sid-a")
    assert s["status"] == "needs_input" and "armed" not in s
    # steady state: no repeat alert
    assert w.mirror_claude_sessions(str(cl), se, **kw) == []


# ---- session titles: Claude Code writes {"type":"ai-title","aiTitle":...} records ----

def test_title_in_transcript_returns_latest_ai_title(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(_jl({"type": "ai-title", "aiTitle": "Old title", "sessionId": "s"},
                     _user("go"), _assistant({"type": "text", "text": "ok"}),
                     {"type": "ai-title", "aiTitle": "Spectroscopy tasks", "sessionId": "s"},
                     {"type": "last-prompt", "lastPrompt": "x"}))
    assert w.title_in_transcript(str(f)) == "Spectroscopy tasks"


def test_title_in_transcript_searches_back_through_a_long_file(tmp_path):
    f = tmp_path / "s.jsonl"
    filler = [_assistant({"type": "text", "text": "x" * 500})] * 800      # ~400 KB after the title
    f.write_text(_jl({"type": "ai-title", "aiTitle": "Buried title"}, *filler))
    assert w.title_in_transcript(str(f), chunk=65536) == "Buried title"


def test_title_in_transcript_missing_or_untitled(tmp_path):
    assert w.title_in_transcript(str(tmp_path / "nope.jsonl")) is None
    f = tmp_path / "s.jsonl"
    f.write_text(_jl(_user("go"), {"type": "ai-title", "aiTitle": ""}))
    assert w.title_in_transcript(str(f)) is None


def test_display_label_prefers_override_then_title_then_folder():
    assert w.display_label({"label": "dynamics", "title": "Spectroscopy tasks"}) == "Spectroscopy tasks"
    assert w.display_label({"label": "dynamics", "title": "Spectra", "label_override": "paper"}) == "paper"
    assert w.display_label({"label": "dynamics", "title": ""}) == "dynamics"


def test_refresh_titles_updates_only_when_transcript_changed(tmp_path):
    se = str(tmp_path / "sessions")
    proj = tmp_path / "projects" / "-x"
    proj.mkdir(parents=True)
    tr = proj / "sid-a.jsonl"
    tr.write_text(_jl({"type": "ai-title", "aiTitle": "First"}))
    w.write_session(se, {"session_id": "sid-a", "pid": 1, "label": "x", "status": "idle", "updated": 5.0})
    w.write_session(se, {"session_id": "sid-none", "pid": 1, "label": "y", "status": "idle", "updated": 5.0})
    w.refresh_titles(se, projects_dir=str(tmp_path / "projects"))
    a = w.load_session(se, "sid-a")
    assert a["title"] == "First" and a["updated"] == 5.0        # a title refresh is not activity
    assert "title" not in w.load_session(se, "sid-none")
    # unchanged transcript: nothing rewritten
    os.utime(tr, (1, 1))
    w.refresh_titles(se, projects_dir=str(tmp_path / "projects"))
    os.utime(tr, (1, 1))
    first_mtime = w.load_session(se, "sid-a")["title_mtime"]
    w.refresh_titles(se, projects_dir=str(tmp_path / "projects"))
    assert w.load_session(se, "sid-a")["title_mtime"] == first_mtime
    # changed transcript: new title picked up
    with open(tr, "a") as fh:
        fh.write(_jl({"type": "ai-title", "aiTitle": "Second"}))
    os.utime(tr, (2, 2))
    w.refresh_titles(se, projects_dir=str(tmp_path / "projects"))
    assert w.load_session(se, "sid-a")["title"] == "Second"


# ---- waiting timer ----

def test_status_since_set_on_first_status_and_on_change(tmp_path):
    d = str(tmp_path / "sessions")
    _, a = w.update_session(d, "s", status="working")
    assert a["status_since"] == a["updated"]
    time.sleep(0.01)
    _, b = w.update_session(d, "s", status="working", task="more")
    assert b["status_since"] == a["status_since"]           # same status: clock keeps running
    time.sleep(0.01)
    _, c = w.update_session(d, "s", status="needs_input")
    assert c["status_since"] > a["status_since"]


def test_status_since_untouched_by_non_status_updates(tmp_path):
    d = str(tmp_path / "sessions")
    _, a = w.update_session(d, "s", status="idle")
    _, b = w.update_session_fn(d, "s", lambda cur: {"color": "112233"}, touch=False)
    assert b["status_since"] == a["status_since"]


def test_mirror_seed_records_status_since(tmp_path):
    cl, se = tmp_path / "claude", str(tmp_path / "sessions")
    _claude_record(cl, 3989, "sid-a", "busy")
    w.mirror_claude_sessions(str(cl), se, tint_dir=str(tmp_path), alive=lambda p: True, tty_of=lambda p: None)
    s = w.load_session(se, "sid-a")
    assert s["status_since"] == s["updated"]


def test_elapsed_text():
    assert w.elapsed_text({"status_since": 1000.0}, now=1030.0) == "just now"
    assert w.elapsed_text({"status_since": 1000.0}, now=1000.0 + 5 * 60 + 10) == "5 min"
    assert w.elapsed_text({"status_since": 1000.0}, now=1000.0 + 2 * 3600 + 7 * 60) == "2 h 7 min"
    assert w.elapsed_text({"status_since": 1000.0}, now=1000.0 + 3 * 3600) == "3 h"
    assert w.elapsed_text({"updated": 1000.0}, now=1000.0 + 120) == "2 min"   # older files
    assert w.elapsed_text({}, now=5.0) == ""


# ---- project name ----

def test_project_name_uses_nearest_repo_root(tmp_path):
    repo = tmp_path / "home" / "work" / "dynamics"
    (repo / ".git").mkdir(parents=True)
    deep = repo / "src" / "solver"
    deep.mkdir(parents=True)
    w.project_name.cache_clear()
    assert w.project_name(str(deep), home=str(tmp_path / "home")) == "dynamics"


def test_project_name_accepts_worktree_git_file(tmp_path):
    wt = tmp_path / "home" / "wt-feature"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /elsewhere\n")
    w.project_name.cache_clear()
    assert w.project_name(str(wt / "a"), home=str(tmp_path / "home")) == "wt-feature"


def test_project_name_without_repo_is_folder_name(tmp_path):
    home = tmp_path / "home"
    d = home / "notes" / "today"
    d.mkdir(parents=True)
    (home / ".git").mkdir()                      # a dotfiles repo at home must not win
    w.project_name.cache_clear()
    assert w.project_name(str(d), home=str(home)) == "today"
    assert w.project_name("", home=str(home)) == ""


def test_project_tag_hidden_when_label_already_shows_it():
    s = {"cwd": "/x/dynamics", "label": "dynamics"}
    assert w.project_tag(s, name=lambda cwd: "dynamics") == ""
    s["title"] = "Fit the spectrum"
    assert w.project_tag(s, name=lambda cwd: "dynamics") == "dynamics"


# ---- log noise ----

def test_clean_env_drops_malloc_debug_vars():
    env = {"PATH": "/bin", "MallocStackLogging": "0", "MallocStackLoggingNoCompact": "1", "HOME": "/h"}
    assert w.clean_env(env) == {"PATH": "/bin", "HOME": "/h"}


# ---- live activity line ----

def test_activity_text_per_tool():
    a = w.activity_text
    assert a("Bash", {"command": "pytest -q", "description": "Run the test suite"}) == "Run the test suite"
    assert a("Bash", {"command": "pytest -q"}) == "Running pytest -q"
    assert a("Edit", {"file_path": "/x/y/widget.py"}) == "Editing widget.py"
    assert a("Write", {"file_path": "/x/notes.md"}) == "Writing notes.md"
    assert a("Read", {"file_path": "/x/README.md"}) == "Reading README.md"
    assert a("Grep", {"pattern": "foo"}) == "Searching the code"
    assert a("WebSearch", {"query": "exciton transport"}) == "Searching the web: exciton transport"
    assert a("WebFetch", {"url": "https://arxiv.org/abs/1"}) == "Reading arxiv.org"
    assert a("Agent", {"description": "Review the diff"}) == "Agent: Review the diff"
    assert a("mcp__zotero__search", {}) == "Using zotero"
    assert a("Mystery", {}) == "Using Mystery"
    assert len(a("Bash", {"description": "x" * 200})) <= 60
    assert a(None, None) == ""


def test_subtitle_shows_live_activity_while_working_or_asking():
    s = {"status": "working", "task": "fix the plot", "activity": "Editing plot.py"}
    assert w.subtitle(s) == "Editing plot.py"
    s["status"] = "permission"
    assert w.subtitle(s) == "Editing plot.py"
    s["status"] = "needs_input"
    assert w.subtitle(s) == ""                   # your turn: the pill says so, no stale step
    assert w.subtitle({"status": "working", "task": "fix the plot"}) == "fix the plot"


# ---- reading Claude's own spinner from the Terminal tab title ----

def test_parse_tab_titles():
    text = "/dev/ttys000\t◐ Lib-drop PDF import\n/dev/ttys001\t✳ Widget work\n/dev/ttys002\tuser@host:~\n\n"
    got = w.parse_tab_titles(text)
    assert got["/dev/ttys000"] == ("busy", "Lib-drop PDF import")
    assert got["/dev/ttys001"] == ("idle", "Widget work")
    assert got["/dev/ttys002"] == (None, "")


def test_reconcile_stuck_working_becomes_needs_input():
    s = {"status": "working"}
    assert w.reconcile(s, "idle", held_s=1) is None              # a blink between steps
    assert w.reconcile(s, "idle", held_s=5) == {"status": "needs_input"}
    assert w.reconcile(dict(s, armed="a timer"), "idle", held_s=5) == {"status": "watching"}


def test_reconcile_spinner_means_working():
    assert w.reconcile({"status": "needs_input"}, "busy", held_s=3) == {"status": "working"}
    assert w.reconcile({"status": "idle"}, "busy", held_s=3) == {"status": "working"}
    assert w.reconcile({"status": "watching", "armed": "a timer"}, "busy", held_s=3) == {"status": "working", "armed": None}
    assert w.reconcile({"status": "permission"}, "busy", held_s=30) is None   # never hide a permission prompt
    assert w.reconcile({"status": "working"}, "busy", held_s=30) is None
    assert w.reconcile({"status": "working"}, None, held_s=30) is None        # not a Claude tab, or not Terminal


def test_tab_title_is_a_label_fallback():
    assert w.display_label({"label": "work", "tab_title": "Widget polish"}) == "Widget polish"
    assert w.display_label({"label": "work", "tab_title": "Widget polish", "title": "AI title"}) == "AI title"


# ---- conversation summary ----

def test_remember_prompt_keeps_the_last_few():
    got = []
    for i in range(10):
        got = w.remember_prompt(got, f"prompt {i} " + "x" * 400)
    assert len(got) == w.PROMPT_MEMORY and got[-1].startswith("prompt 9")
    assert all(len(p) <= 300 for p in got)
    assert w.remember_prompt(None, "   ") == []


def test_should_summarise():
    s = {"prompts": ["a", "b"], "prompt_count": 2}
    assert w.should_summarise(s, now=100.0)
    assert not w.should_summarise(dict(s, summary_for=2), now=100.0)            # already up to date
    assert not w.should_summarise(dict(s, summary_started=80.0), now=100.0)     # one is running
    assert w.should_summarise(dict(s, summary_started=10.0), now=200.0)         # that one died
    assert not w.should_summarise({"prompts": []}, now=100.0)


def test_summary_request_mentions_prompts_and_title():
    req = w.summary_request({"title": "Widget polish", "prompts": ["add a timer", "fix the status"],
                             "activity": "Editing widget.py"})
    assert "add a timer" in req and "fix the status" in req
    assert "Editing widget.py" not in req          # one step would pull the summary off course


def test_clean_summary():
    assert w.clean_summary('"Fixing stuck widget statuses."\n') == "Fixing stuck widget statuses"
    assert w.clean_summary("") == ""
    assert len(w.clean_summary("word " * 40)) <= 40


def test_summary_becomes_the_headline():
    s = {"label": "work", "title": "Lib-drop PDF import", "summary": "Fixing stuck widget statuses"}
    assert w.display_label(s) == "Fixing stuck widget statuses"
    assert w.display_label(dict(s, label_override="paper")) == "paper"


def test_subtitle_is_empty_when_it_is_your_turn():
    s = {"status": "needs_input", "title": "Lib-drop PDF import", "summary": "Fixing stuck widget statuses",
         "task": "last prompt"}
    assert w.subtitle(s) == ""
    assert w.subtitle({"status": "needs_input", "title": "Lib-drop PDF import", "task": "last prompt"}) == ""


def test_project_follows_where_the_session_is_now():
    s = {"cwd": "/x/work", "cwd_now": "/x/work/tools/widget", "title": "T"}
    seen = []
    w.project_tag(s, name=lambda cwd: seen.append(cwd) or "widget")
    assert seen == ["/x/work/tools/widget"]


# ---- subagent list ----

def test_agents_text():
    assert w.agents_text([]) == ""
    assert w.agents_text([{"desc": "Review the diff"}]) == "1 agent · Review the diff"
    assert w.agents_text([{"desc": "A"}, {"desc": "B"}]) == "2 agents · A, B"


def test_prune_agents_drops_old_ones():
    agents = [{"id": "a", "started": 0.0}, {"id": "b", "started": 9000.0}]
    assert [a["id"] for a in w.prune_agents(agents, now=10000.0)] == ["b"]


def test_agent_stopped_prefers_matching_type_then_foreground():
    agents = [{"id": "1", "type": "Explore", "bg": True}, {"id": "2", "type": "Plan", "bg": False},
              {"id": "3", "type": "Explore", "bg": False}]
    assert [a["id"] for a in w.agent_stopped(agents, "Explore")] == ["2", "3"]
    assert [a["id"] for a in w.agent_stopped(agents, None)] == ["1", "3"]


# ---- muting banners ----

def test_mute_and_unmute(tmp_path):
    cfg = str(tmp_path / "config.json")
    assert not w.banners_muted(path=cfg, now=100.0)
    w.mute_banners(30, path=cfg, now=100.0)
    assert w.banners_muted(path=cfg, now=100.0 + 29 * 60)
    assert not w.banners_muted(path=cfg, now=100.0 + 31 * 60)
    w.mute_banners(0, path=cfg, now=100.0)
    assert not w.banners_muted(path=cfg, now=101.0)


def test_notify_mac_stays_quiet_while_muted(monkeypatch, tmp_path):
    cfg = str(tmp_path / "config.json")
    monkeypatch.setattr(w, "WIDGET_CONFIG", cfg)
    calls = []
    monkeypatch.setattr(w.subprocess, "Popen", lambda *a, **k: calls.append(a))
    w.mute_banners(10, path=cfg)
    w.notify_mac("t", "m")
    assert calls == []
    w.mute_banners(0, path=cfg)
    w.notify_mac("t", "m")
    assert len(calls) == 1
