import importlib.util, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("tint", os.path.join(HERE, "scripts", "tint.py"))
tint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tint)


def test_scheme_colours_are_unique_and_match_their_brightness():
    hexes = [h for pal in tint.SCHEMES.values() for _, h in pal]
    assert len(hexes) == len(set(hexes))
    for name, pal in tint.SCHEMES.items():
        assert all(tint.is_light(h) == (name == "pastel") for _, h in pal)


def test_auto_scheme_follows_the_tab_background():
    assert tint.palette_for("ffffff", "auto") is tint.SCHEMES["pastel"]
    assert tint.palette_for("000000", "auto") is tint.SCHEMES["muted"]
    assert tint.palette_for("ffffff", "jewel") is tint.SCHEMES["jewel"]


def test_scheme_choice_is_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(tint, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tint, "CONFIG_PATH", str(tmp_path / "scheme.json"))
    assert tint.load_scheme() == "auto"
    tint.save_scheme("colourblind")
    assert tint.load_scheme() == "colourblind"
    (tmp_path / "scheme.json").write_text('{"scheme": "nonsense"}')
    assert tint.load_scheme() == "auto"


def test_pick_free_skips_colours_other_tabs_use(tmp_path, monkeypatch):
    monkeypatch.setattr(tint, "STATE_DIR", str(tmp_path))
    pal = tint.SCHEMES["jewel"]
    tabs = {"/dev/ttys001": pal[0][1], "/dev/ttys002": "000000"}
    assert tint.pick_free("/dev/ttys002", tabs, palette=pal) == pal[1][1]


def test_switching_scheme_recolours_every_claude_tab(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    monkeypatch.setattr(tint, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(tint, "CONFIG_PATH", str(tmp_path / "scheme.json"))
    muted = tint.SCHEMES["muted"]
    tabs = {"/dev/ttys001": muted[0][1], "/dev/ttys002": muted[1][1], "/dev/ttys003": "ffffff"}
    painted = {}
    monkeypatch.setattr(tint, "list_tabs", lambda: dict(tabs))
    monkeypatch.setattr(tint, "claude_ttys", lambda: {"/dev/ttys001", "/dev/ttys002"})
    monkeypatch.setattr(tint, "set_bg", lambda tty, h: painted.__setitem__(tty, h))
    tint.main(["scheme", "jewel"])
    jewel = {h for _, h in tint.SCHEMES["jewel"]}
    assert set(painted) == {"/dev/ttys001", "/dev/ttys002"}        # the non-claude tab is untouched
    assert set(painted.values()) <= jewel and len(set(painted.values())) == 2
    assert tint.load_scheme() == "jewel"
    assert "recoloured 2 tab(s)" in capsys.readouterr().out
