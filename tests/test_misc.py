import json

import pytest

from horus_control import capabilities, settings, style


def test_unknown_capabilities_cannot_run():
    for cap in capabilities.CAPABILITIES:
        if cap.key in ("lighting", "lighting_colour"):
            assert cap.status == capabilities.Status.HARDWARE
            capabilities.require_usable(cap.key)
            continue
        assert cap.status == capabilities.Status.UNKNOWN
        with pytest.raises(capabilities.NotVerified):
            capabilities.require_usable(cap.key)


def test_lighting_writes_are_gated(monkeypatch):
    from horus_control import lighting
    unknown = capabilities.Capability("lighting", "x", capabilities.Status.UNKNOWN, "")
    monkeypatch.setattr(capabilities, "CAPABILITIES", (unknown,))
    with pytest.raises(capabilities.NotVerified):
        lighting.apply("/dev/never-opened", effect=1)


def test_settings_roundtrip_and_atomic(tmp_path):
    path = tmp_path / "horus-control" / "settings.json"
    assert not path.parent.exists()
    assert settings.load(str(path)) == settings.Settings()   # loading creates nothing
    assert not path.parent.exists()
    settings.save(settings.Settings("dark", "large", True), str(path))
    assert settings.load(str(path)) == settings.Settings("dark", "large", True)
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]


def test_settings_validation(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"version": 1, "theme": "neon", "size": "large", "reduce_motion": "yes", "x": 1}))
    assert settings.load(str(path)) == settings.Settings(size="large")
    path.write_text(json.dumps({"version": 99, "theme": "dark"}))
    assert settings.load(str(path)) == settings.Settings()
    path.write_text("{not json")
    assert settings.load(str(path)) == settings.Settings()


PAIRS_TEXT = [
    ("ON_SURFACE", "SURFACE_DIM"), ("ON_SURFACE", "SURFACE_CONTAINER"), ("ON_SURFACE", "SURFACE_CONTAINER_HIGH"),
    ("ON_SURFACE_VARIANT", "SURFACE_CONTAINER"), ("ON_SURFACE_VARIANT", "SURFACE_CONTAINER_HIGH"),
    ("ON_PRIMARY", "PRIMARY"), ("ON_PRIMARY_CONTAINER", "PRIMARY_CONTAINER"),
    ("ON_SECONDARY_CONTAINER", "SECONDARY_CONTAINER"), ("ON_SECONDARY_CONTAINER", "SECONDARY_CONTAINER_HOVER"),
    ("ON_TERTIARY_CONTAINER", "TERTIARY_CONTAINER"), ("ON_ERROR_CONTAINER", "ERROR_CONTAINER"),
    ("ERROR", "SURFACE_CONTAINER"), ("INVERSE_ON_SURFACE", "INVERSE_SURFACE"), ("PRIMARY", "SURFACE_CONTAINER"),
]
PAIRS_UI = [("PRIMARY", "SURFACE_DIM"), ("OUTLINE", "SURFACE_CONTAINER")]  # focus ring, switch border/faint text


@pytest.mark.parametrize("dark", [True, False])
def test_palette_contrast(dark):
    p = style.palette(dark)
    for fg, bg in PAIRS_TEXT:
        assert style.contrast(p[fg], p[bg]) >= 4.5, (fg, bg, dark)
    for fg, bg in PAIRS_UI:
        assert style.contrast(p[fg], p[bg]) >= 3.0, (fg, bg, dark)


def test_stylesheet_scales():
    large = style.stylesheet(True, "large")
    compact = style.stylesheet(True, "compact", reduce_motion=True)
    assert "border-radius: 28px" in large and "border-radius: 22px" in compact
    assert "px(" not in large and "fpx(" not in compact
    assert "transition: none" in compact
