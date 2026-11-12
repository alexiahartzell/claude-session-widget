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
                            "tool_input": {"prompt": "go"}})
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


def test_tool_use_after_watching_means_claude_resumed(tmp_path):
    _armed_session(tmp_path)
    run(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Monitor", "tool_input": {}})
    run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    new, _ = run(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "Read", "tool_input": {}})
    assert new["status"] == "working" and "armed" not in new
    new, calls = run(tmp_path, {"hook_event_name": "Stop", "session_id": "s1"})
    assert new["status"] == "needs_input" and len(calls) == 1


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
