import importlib.util, itertools, json, os

import widgetlib as w

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("tint", os.path.join(HERE, "scripts", "tint.py"))
tint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tint)


def test_every_scheme_has_a_dark_and_a_light_version_of_the_same_size():
    for scheme in tint.DARK:
        assert len(tint.DARK[scheme]) == tint.PALETTE_SIZE, scheme
        dark, light = tint.palette(scheme, "dark"), tint.palette(scheme, "light")
        assert [n for n, _ in dark] == [n for n, _ in light]
        assert not any(w.is_light(h) for _, h in dark), scheme
        assert all(w.is_light(h) for _, h in light), scheme
        for pal in (dark, light):
            assert len({h for _, h in pal}) == len(pal), scheme


def test_light_version_keeps_the_hue():
    hue_dark = w._hsv("0d2547")[0]
    hue_light = w._hsv(tint.light_of("0d2547"))[0]
    assert abs(hue_dark - hue_light) < 0.02


def test_config_defaults_saving_and_old_pastel_choice(tmp_path):
    path = str(tmp_path / "scheme.json")
    assert w.load_config(path) == {"scheme": "muted", "mode": "auto"}
    w.save_config(path, scheme="jewel")
    w.save_config(path, mode="light")
    assert w.load_config(path) == {"scheme": "jewel", "mode": "light"}
    (tmp_path / "scheme.json").write_text(json.dumps({"scheme": "pastel"}))
    assert w.load_config(path) == {"scheme": "muted", "mode": "light"}
    (tmp_path / "scheme.json").write_text(json.dumps({"scheme": "nonsense", "mode": "sepia"}))
    assert w.load_config(path) == {"scheme": "muted", "mode": "auto"}


def test_pick_free_skips_colours_other_tabs_use(tmp_path, monkeypatch):
    monkeypatch.setattr(tint, "STATE_DIR", str(tmp_path))
    pal = tint.palette("jewel", "dark")
    tabs = {"/dev/ttys001": pal[0][1], "/dev/ttys002": "000000"}
    assert tint.pick_free("/dev/ttys002", tabs, palette=pal) == pal[1][1]


def _fake_terminal(tmp_path, monkeypatch, tabs, claude):
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    monkeypatch.setattr(tint, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr(w, "CONFIG_PATH", str(tmp_path / "scheme.json"))
    painted = {}
    monkeypatch.setattr(tint, "list_tabs", lambda: dict(tabs))
    monkeypatch.setattr(tint, "text_of", lambda tty: "ffffff")
    monkeypatch.setattr(tint, "claude_ttys", lambda: set(claude))
    monkeypatch.setattr(tint, "set_bg", lambda tty, h, text=None: painted.__setitem__(tty, (h, text)))
    return painted


def test_switching_scheme_recolours_every_claude_tab(tmp_path, monkeypatch, capsys):
    muted = tint.palette("muted", "dark")
    tabs = {"/dev/ttys001": muted[0][1], "/dev/ttys002": muted[1][1], "/dev/ttys003": "000000"}
    painted = _fake_terminal(tmp_path, monkeypatch, tabs, {"/dev/ttys001", "/dev/ttys002"})
    w.save_config(mode="dark")
    tint.main(["scheme", "dusk"])
    dusk = {h for _, h in tint.palette("dusk", "dark")}
    assert set(painted) == {"/dev/ttys001", "/dev/ttys002"}        # the non-claude tab is untouched
    assert {h for h, _ in painted.values()} <= dusk
    assert len({h for h, _ in painted.values()}) == 2
    assert all(text == tint.TEXT["dark"] for _, text in painted.values())
    assert w.load_config()["scheme"] == "dusk"
    assert "recoloured 2 tab(s)" in capsys.readouterr().out


def test_light_mode_uses_light_backgrounds_and_dark_text(tmp_path, monkeypatch):
    tabs = {"/dev/ttys001": "000000"}
    painted = _fake_terminal(tmp_path, monkeypatch, tabs, {"/dev/ttys001"})
    tint.main(["mode", "light"])
    bg, text = painted["/dev/ttys001"]
    assert w.is_light(bg) and text == tint.TEXT["light"]
    state = json.loads((tmp_path / "_dev_ttys001.json").read_text())
    assert (state["orig"], state["orig_text"]) == ("000000", "ffffff")


def test_restore_puts_back_background_and_text(tmp_path, monkeypatch):
    painted = _fake_terminal(tmp_path, monkeypatch, {"/dev/ttys001": "000000"}, {"/dev/ttys001"})
    tabs = {"/dev/ttys001": "000000"}
    tint.apply("/dev/ttys001", tabs, tint.palette("ocean", "light")[0][1])
    tint.restore("/dev/ttys001", tabs)
    assert painted["/dev/ttys001"] == ("000000", "ffffff")
    assert not (tmp_path / "_dev_ttys001.json").exists()


# ---- colour vision check for the colourblind scheme ----
# Machado et al. (2009) full-severity simulation matrices, applied in linear RGB.
CVD = {
    "protanopia": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216],
                   [-0.003882, -0.048116, 1.051998]],
    "deuteranopia": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413],
                     [-0.011820, 0.042940, 0.968881]],
    "tritanopia": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602],
                   [0.004733, 0.691367, 0.303900]],
}


def _lab(h, matrix):
    lin = [(c / 12.92) if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
           for c in (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))]
    lin = [min(1, max(0, sum(m * c for m, c in zip(row, lin)))) for row in matrix]
    xyz = [sum(m * c for m, c in zip(row, lin)) / n for row, n in zip(
        [[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]],
        (0.9505, 1.0, 1.089))]
    f = [t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in xyz]
    return (116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2]))


def test_colourblind_cards_stay_distinct_for_every_colour_vision_type():
    for mode in ("dark", "light"):
        accents = [w.accent(h, mode) for _, h in tint.palette("colourblind", mode)]
        for name, matrix in CVD.items():
            labs = [_lab(a, matrix) for a in accents]
            closest = min(sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5
                          for a, b in itertools.combinations(labs, 2))
            assert closest > 12, (mode, name)


def test_every_scheme_keeps_every_card_distinct_in_both_modes():
    """Light-mode cards differ only by hue, so a scheme's hues must stay spread out."""
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for scheme in tint.DARK:
        for mode in ("dark", "light"):
            labs = [_lab(w.accent(h, mode), identity) for _, h in tint.palette(scheme, mode)]
            closest = min(sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5
                          for a, b in itertools.combinations(labs, 2))
            assert closest > 14, (scheme, mode, closest)


def test_every_scheme_is_selectable():
    assert set(tint.DARK) == set(w.SCHEME_NAMES)


def test_claude_ttys_includes_the_calling_session(monkeypatch):
    calls = []
    def fake(cmd, text=True):
        calls.append(cmd)
        return "101\n"
    monkeypatch.setattr(tint.subprocess, "check_output", fake)
    monkeypatch.setattr(tint, "tty_of_pid", lambda p: "/dev/ttys000")
    assert tint.claude_ttys() == {"/dev/ttys000"}
    assert "-a" in calls[0]          # without it, the session running /tint is skipped
