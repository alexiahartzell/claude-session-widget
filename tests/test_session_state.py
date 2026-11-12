import importlib.util, json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("session_state", os.path.join(HERE, "scripts", "session-state.py"))
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)
import widgetlib as w


def run(tmp_path, payload, tty="/dev/ttys008", calls=None, summarise=None):
    calls = calls if calls is not None else []
    return ss.handle(
        payload,
        sessions_dir=str(tmp_path / "sessions"),
        tint_dir=str(tmp_path / "tint"),
        pid=4242,
        tty=tty,
        notify=lambda title, msg: calls.append(("notify", title, msg)),
        launch=lambda: calls.append(("launch",)),
        summarise=summarise or (lambda sid: None),
    ), calls


def make_tint(tmp_path):
    t = tmp_path / "tint"
    t.mkdir(exist_ok=True)
    (t / "_dev_ttys008.json").write_text(json.dumps({"orig": "000000", "tint": "1e1026", "name": "plum"}))


def test_session_start_creates_file_and_launches(tmp_path):
    make_tint(tmp_path)
    new, calls = run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1",
                                "cwd": "/Users/me/spectra"})
    assert new["status"] == "idle"
    assert new["label"] == "spectra"
    assert new["color"] == "1e1026" and new["color_name"] == "plum"
    assert new["pid"] == 4242 and new["tty"] == "/dev/ttys008"
    assert new["task"] == ""
    assert ("launch",) in calls
    assert w.load_session(str(tmp_path / "sessions"), "s1") == new


def test_session_start_without_tint(tmp_path):
    new, _ = run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/y"}, tty=None)
    assert new["color"] == w.GREY and new["color_name"] == "grey"
    assert new.get("tty") is None


def test_prompt_sets_working_and_task(tmp_path):
    run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/y"})
    new, calls = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                                "prompt": "fix the\nbroadening plot " + "z" * 80})
    assert new["status"] == "working"
    assert new["task"].startswith("fix the broadening plot")
    assert len(new["task"]) <= 60
    assert not any(c[0] == "notify" for c in calls)


def test_stop_sets_needs_input_and_notifies_once(tmp_path):
    make_tint(tmp_path)
    run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj"})
    run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "go"})
    new, calls = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert new["status"] == "needs_input"
    assert calls == [("notify", "proj (plum)", "needs input: go")]
    # a second Stop while already needs_input does not notify again
    _, calls2 = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert calls2 == []


def test_notification_permission(tmp_path):
    run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj"})
    new, calls = run(tmp_path, {"hook_event_name": "Notification", "session_id": "s1",
                                "notification_type": "permission_prompt",
                                "message": "Claude needs your permission to use Bash"})
    assert new["status"] == "permission"
    assert calls[0][0] == "notify" and "permission" in calls[0][2]


def test_notification_idle(tmp_path):
    run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj"})
    new, _ = run(tmp_path, {"hook_event_name": "Notification", "session_id": "s1",
                            "notification_type": "idle_prompt", "message": "waiting"})
    assert new["status"] == "needs_input"


def test_notification_unknown_type_ignored(tmp_path):
    run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj"})
    run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "go"})
    new, calls = run(tmp_path, {"hook_event_name": "Notification", "session_id": "s1",
                                "message": "auth ok"})
    assert new is None
    assert w.load_session(str(tmp_path / "sessions"), "s1")["status"] == "working"
    assert calls == []


def test_session_end_deletes(tmp_path):
    run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj"})
    new, _ = run(tmp_path, {"hook_event_name": "SessionEnd", "session_id": "s1"})
    assert new is None
    assert w.load_session(str(tmp_path / "sessions"), "s1") is None


def test_event_without_session_id_is_ignored(tmp_path):
    new, calls = run(tmp_path, {"hook_event_name": "Stop"})
    assert new is None and calls == []


def test_prompt_before_start_still_creates_file(tmp_path):
    # hooks can be enabled mid-session; a late first event must still work
    make_tint(tmp_path)
    new, _ = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s9",
                            "cwd": "/x/late", "prompt": "hi"})
    assert new["label"] == "late" and new["color"] == "1e1026" and new["pid"] == 4242


def test_ensure_widget_running_uses_pidfile(tmp_path):
    calls = []
    wd = str(tmp_path)
    assert ss.ensure_widget_running(wd, launch=lambda: calls.append(1), alive=lambda p: False) is True
    assert calls == [1]
    (tmp_path / "widget.pid").write_text("123")
    assert ss.ensure_widget_running(wd, launch=lambda: calls.append(2), alive=lambda p: p == 123) is False
    assert calls == [1]
    (tmp_path / "widget.pid").write_text("junk")
    assert ss.ensure_widget_running(wd, launch=lambda: calls.append(3), alive=lambda p: False) is True
    assert calls == [1, 3]


def test_cmd_name_sets_override_by_tty(tmp_path):
    d = str(tmp_path / "sessions")
    w.write_session(d, {"session_id": "s1", "tty": "/dev/ttys008", "label": "proj", "pid": 1})
    w.write_session(d, {"session_id": "s2", "tty": "/dev/ttys009", "label": "other", "pid": 1})
    out = ss.cmd(["name", "paper", "draft"], sessions_dir=d, widget_dir=str(tmp_path), tty="/dev/ttys008")
    assert w.load_session(d, "s1")["label_override"] == "paper draft"
    assert "label_override" not in w.load_session(d, "s2")
    assert "paper draft" in out


def test_cmd_show_hide_quit_write_command_file(tmp_path):
    for word in ("show", "hide", "quit"):
        ss.cmd([word], sessions_dir=str(tmp_path / "s"), widget_dir=str(tmp_path), tty=None)
        assert (tmp_path / "command").read_text() == word


def test_cmd_unknown(tmp_path):
    out = ss.cmd(["dance"], sessions_dir=str(tmp_path / "s"), widget_dir=str(tmp_path), tty=None)
    assert "usage" in out.lower()


def test_hook_marks_source_and_refreshes_colour_each_event(tmp_path):
    # the tab can be re-tinted mid-session (/tint shuffle); every event re-reads it
    new, _ = run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj"})
    assert new["source"] == "hook" and new["color_name"] == "grey"
    make_tint(tmp_path)
    new, _ = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "go"})
    assert new["color"] == "1e1026" and new["color_name"] == "plum"


def test_hook_takes_over_a_mirrored_session(tmp_path):
    d = str(tmp_path / "sessions")
    w.write_session(d, {"session_id": "s1", "pid": 1, "status": "idle", "source": "mirror",
                        "label": "proj", "task": "", "updated": 1.0})
    new, _ = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "go"})
    assert new["source"] == "hook" and new["status"] == "working" and new["pid"] == 4242


def test_session_start_on_compact_or_resume_keeps_status_and_task(tmp_path):
    run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj", "source": "startup"})
    run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "long job"})
    new, calls = run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj", "source": "compact"})
    assert new["status"] == "working" and new["task"] == "long job"
    assert ("launch",) in calls          # still makes sure the widget is up
    new, _ = run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj", "source": "resume"})
    assert new["status"] == "working" and new["task"] == "long job"


def test_resolve_process_skips_headless_claude():
    fake = {"500": ["400", "??", "python3"], "400": ["300", "??", "claude"],
            "300": ["200", "ttys008", "python3"], "200": ["100", "ttys008", "claude"],
            "100": ["1", "ttys008", "zsh"]}

    def mk(table):
        def ps(pid, fields):
            row = table.get(str(pid))
            if not row:
                return []
            return [row[0], row[1]] if "tty" in fields else [row[0], row[2]]
        return ps
    ps = mk(fake)
    # hook run from a headless `claude -p` launched inside another session's Bash tool
    assert ss.resolve_process(500, ps=ps) == (400, None, True)
    # hook run from an interactive claude in a Terminal tab
    assert ss.resolve_process(300, ps=ps) == (200, "/dev/ttys008", False)
    # no claude ancestor at all (run by hand): use parent pid, walk for a tty, not headless
    fake2 = {"50": ["40", "ttys002", "python3"], "40": ["1", "ttys002", "zsh"]}
    ps2 = mk(fake2)
    assert ss.resolve_process(50, ps=ps2) == (40, "/dev/ttys002", False)


def test_cmd_name_prefers_claude_pid_over_tty(tmp_path):
    d = str(tmp_path / "sessions")
    w.write_session(d, {"session_id": "old", "tty": "/dev/ttys008", "pid": 1, "label": "a"})
    w.write_session(d, {"session_id": "cur", "tty": "/dev/ttys008", "pid": 2, "label": "b"})
    ss.cmd(["name", "mine"], sessions_dir=d, widget_dir=str(tmp_path), tty="/dev/ttys008", pid=2)
    assert w.load_session(d, "cur")["label_override"] == "mine"
    assert "label_override" not in w.load_session(d, "old")


# ---- "watching": Claude armed a watcher / background job and ended its turn ----

def _armed_session(tmp_path):
    run(tmp_path, {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": "/x/proj"})
    run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "run the calc"})


def test_post_tool_use_arms_only_for_background_tools(tmp_path):
    _armed_session(tmp_path)
    new, _ = run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
                            "tool_input": {"command": "ls"}})
    assert new is None
    new, _ = run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
                            "tool_input": {"command": "python3 calc.py", "run_in_background": True}})
    assert new["armed"] == "a background job" and new["status"] == "working"
    new, _ = run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Monitor",
                            "tool_input": {"cmd": "until-loop"}})
    assert new["armed"] == "a watcher"
    new, _ = run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Agent",
                            "tool_input": {"prompt": "go", "run_in_background": True}})
    assert new["armed"] == "a subagent"
    new, _ = run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "ScheduleWakeup",
                            "tool_input": {"stop": True}})
    assert new is None                                   # stopping a loop does not arm


def test_stop_while_armed_is_watching_not_needs_input(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Monitor", "tool_input": {}})
    new, calls = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert new["status"] == "watching" and new["armed"] == "a watcher" and new["task"] == "run the calc"
    assert calls == []


def test_tool_use_after_watching_keeps_armed_until_a_new_prompt(tmp_path):
    # A Stop hook elsewhere blocks the stop, Claude resumes and runs a tool (issue 3).
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
                   "tool_input": {"command": "python3 calc.py", "run_in_background": True}})
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    new, _ = run(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Read", "tool_input": {}})
    assert new["status"] == "working" and new["armed"] == "a background job"
    new, calls = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert new["status"] == "watching" and calls == []
    new, _ = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                            "prompt": "<task-notification>done</task-notification>"})
    assert "armed" not in new
    new, calls = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert new["status"] == "needs_input" and len(calls) == 1


def test_blocked_stop_without_tools_stays_watching(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Monitor", "tool_input": {}})
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    d = str(tmp_path / "sessions")
    fix = w.reconcile(w.load_session(d, "s1"), "busy", held_s=3)   # tab spinner turns busy
    w.update_session(d, "s1", **fix)
    new, calls = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert new["status"] == "watching" and new["armed"] == "a watcher" and calls == []


def test_pre_tool_use_while_working_records_activity(tmp_path):
    _armed_session(tmp_path)
    new, calls = run(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Bash",
                                "tool_input": {"command": "pytest -q", "description": "Run the test suite"}})
    assert new["status"] == "working" and new["activity"] == "Run the test suite" and calls == []


def test_pre_tool_use_without_session_is_ignored(tmp_path):
    new, _ = run(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "ghost", "tool_name": "Read", "tool_input": {}})
    assert new is None


def test_new_prompt_clears_activity(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Read",
                   "tool_input": {"file_path": "/a/b/notes.md"}})
    new, _ = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "next thing"})
    assert "activity" not in new


def test_idle_notification_ignored_while_watching(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Monitor", "tool_input": {}})
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    new, calls = run(tmp_path, {"hook_event_name": "Notification", "session_id": "s1",
                                "notification_type": "idle_prompt", "message": "waiting"})
    assert new is None and calls == []
    assert w.load_session(str(tmp_path / "sessions"), "s1")["status"] == "watching"


def test_prompt_clears_armed(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Monitor", "tool_input": {}})
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    new, _ = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "next"})
    assert new["status"] == "working" and "armed" not in new


def test_prompts_are_remembered_for_the_summary(tmp_path):
    _armed_session(tmp_path)
    new, _ = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "second thing"})
    assert new["prompts"] == ["run the calc", "second thing"] and new["prompt_count"] == 2


def test_tool_call_after_permission_means_working_again(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "Notification", "session_id": "s1", "notification_type": "permission_prompt"})
    new, _ = run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
                            "tool_input": {"command": "ls"}})
    assert new["status"] == "working"


def test_stop_starts_a_summary(tmp_path):
    started = []
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"}, summarise=started.append)
    assert started == ["s1"]


def test_hooks_record_the_current_folder(tmp_path):
    _armed_session(tmp_path)
    new, _ = run(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": "/x/proj/sub",
                            "tool_name": "Read", "tool_input": {"file_path": "/a/b.md"}})
    assert new["cwd_now"] == "/x/proj/sub" and new["cwd"] == "/x/proj"


# ---- subagents ----

def _agent(tmp_path, tid, desc, bg=False, kind="Explore"):
    return run(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Agent",
                          "tool_use_id": tid, "tool_input": {"description": desc, "subagent_type": kind,
                                                             "run_in_background": bg}})


def test_foreground_agent_listed_then_cleared_when_it_returns(tmp_path):
    _armed_session(tmp_path)
    new, _ = _agent(tmp_path, "t1", "Review the diff")
    assert [a["desc"] for a in new["agents"]] == ["Review the diff"]
    new, _ = run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Agent",
                            "tool_use_id": "t1", "tool_input": {"description": "Review the diff"}})
    assert not new.get("agents") and "armed" not in new        # a finished foreground agent arms nothing


def test_background_agents_stay_until_subagent_stop(tmp_path):
    _armed_session(tmp_path)
    _agent(tmp_path, "t1", "Search the docs", bg=True)
    _agent(tmp_path, "t2", "Run the benchmarks", bg=True, kind="general-purpose")
    new, _ = run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Agent",
                            "tool_use_id": "t1", "tool_input": {"description": "Search the docs", "run_in_background": True}})
    assert len(new["agents"]) == 2 and new["armed"] == "a subagent"
    new, _ = run(tmp_path, {"hook_event_name": "SubagentStop", "session_id": "s1", "agent_type": "general-purpose"})
    assert [a["desc"] for a in new["agents"]] == ["Search the docs"]
    new, _ = run(tmp_path, {"hook_event_name": "SubagentStop", "session_id": "s1"})
    assert not new.get("agents")


def test_stop_clears_foreground_agents_only(tmp_path):
    _armed_session(tmp_path)
    _agent(tmp_path, "t1", "Quick look")
    _agent(tmp_path, "t2", "Long job", bg=True)
    new, _ = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert [a["desc"] for a in new["agents"]] == ["Long job"]


def test_mute_command(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "WIDGET_CONFIG", str(tmp_path / "config.json"))
    kw = dict(sessions_dir=str(tmp_path / "s"), widget_dir=str(tmp_path), tty=None)
    assert ss.cmd(["mute", "20"], **kw) == "widget: banners muted for 20 min"
    assert w.banners_muted()
    assert ss.cmd(["unmute"], **kw) == "widget: banners on"
    assert not w.banners_muted()
    assert ss.cmd(["mute", "soon"], **kw).startswith("usage")


# ---- Stop payloads list background work from every turn (issue 5) ----

def _bg(type_="shell", **kw):
    return dict({"id": "b1", "type": type_, "status": "running", "description": "wait on cluster"}, **kw)


def test_stop_watches_background_job_from_an_earlier_turn(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
                   "tool_input": {"command": "squeue-wait", "run_in_background": True}})
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1", "background_tasks": [_bg()], "session_crons": []})
    new, _ = run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "something else"})
    assert "armed" not in new
    new, calls = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1",
                                "background_tasks": [_bg()], "session_crons": []})
    assert new["status"] == "watching" and new["background"] == "a background job" and calls == []
    assert w.subtitle(new) == "your turn · waiting on a background job"


def test_stop_with_empty_lists_needs_you_even_if_armed(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
                   "tool_input": {"command": "sleep 1", "run_in_background": True}})
    new, calls = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1",
                                "background_tasks": [], "session_crons": []})
    assert new["status"] == "needs_input" and "armed" not in new and "background" not in new
    assert len(calls) == 1


def test_stop_watches_a_scheduled_wakeup(tmp_path):
    _armed_session(tmp_path)
    new, _ = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1", "background_tasks": [],
                            "session_crons": [{"id": "c1", "schedule": "5 * * * *", "recurring": False, "prompt": "go"}]})
    assert new["status"] == "watching" and new["background"] == "a timer"


def test_stop_without_lists_falls_back_to_armed(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Monitor", "tool_input": {}})
    new, _ = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert new["status"] == "watching" and new["armed"] == "a watcher"


def test_background_survives_new_prompts_and_feeds_reconcile(tmp_path):
    # A Stop hook is missed (Escape), so only the tab spinner says Claude went idle.
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1", "background_tasks": [_bg()], "session_crons": []})
    run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "other thing"})
    d = str(tmp_path / "sessions")
    s = w.load_session(d, "s1")
    assert s["status"] == "working" and s["background"] == "a background job"
    assert w.reconcile(s, "idle", held_s=10) == {"status": "watching"}


def test_subagent_stop_refreshes_background(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1", "background_tasks": [_bg()], "session_crons": []})
    new, _ = run(tmp_path, {"hook_event_name": "SubagentStop", "session_id": "s1", "agent_type": "x",
                            "background_tasks": [], "session_crons": []})
    assert "background" not in new
    new, _ = run(tmp_path, {"hook_event_name": "SubagentStop", "session_id": "s1", "agent_type": "x",
                            "background_tasks": [_bg("subagent")], "session_crons": []})
    assert new["background"] == "a subagent"


def test_prompts_are_counted_for_daily_stats(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "next"})
    run(tmp_path, {"hook_event_name": "UserPromptSubmit", "session_id": "s1",
                   "prompt": "<task-notification>x</task-notification>"})
    day = w.today_stats(str(tmp_path / "stats.json"))
    assert day["prompts"] == 2 and day["by_session"]["s1"]["prompts"] == 2


def test_cmd_pet_choose_list_and_off(tmp_path, monkeypatch):
    cfg = str(tmp_path / "config.json")
    monkeypatch.setattr(w, "WIDGET_CONFIG", cfg)
    c = lambda *a: ss.cmd(["pet", *a], sessions_dir=str(tmp_path), widget_dir=str(tmp_path), tty=None)
    assert "pebble" in c() and "kit" in c() and "sprout" in c()
    assert c("kit") == "widget: your pet is now kit, a fire kit" and w.pet_kind(cfg) == "kit"
    assert c("off") == "widget: pets off" and w.pet_kind(cfg) is None
    c("on")
    assert w.pet_kind(cfg) == "pebble"
