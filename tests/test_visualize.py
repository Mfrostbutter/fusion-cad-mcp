"""Tests for screenshot + set_view wrappers."""

from __future__ import annotations

import ast
import json

from fusion_cad_mcp.envelope import Envelope
from fusion_cad_mcp.tools import visualize as viz


def test_screenshot_invalid_direction_short_circuits():
    class A:
        def read_query(self, *a, **kw):
            raise AssertionError("must not reach Fusion")

    env = viz.screenshot(A(), direction="diagonal")
    assert env.ok is False
    assert env.error == "invalid_direction"


def test_screenshot_passes_through_image_envelope():
    class A:
        def read_query(self, qt: str, **kw):
            assert qt == "screenshot"
            return Envelope(ok=True, image={"data": "AAAA", "mime_type": "image/png"})

    env = viz.screenshot(A(), direction="iso-top-right", width=400, height=300)
    assert env.ok is True
    assert env.image == {"data": "AAAA", "mime_type": "image/png"}


def test_screenshot_omits_width_height_when_none():
    captured: dict = {}

    class A:
        def read_query(self, qt: str, **kw):
            captured.update(kw)
            return Envelope(ok=True)

    viz.screenshot(A(), direction="front")
    assert "width" not in captured
    assert "height" not in captured
    assert captured["direction"] == "front"
    assert captured["transparentBackground"] is True
    assert captured["antiAliasing"] is True


def test_build_set_view_top_uses_enum():
    src = viz.build_set_view("top", fit=True)
    ast.parse(src)
    assert "TopViewOrientation" in src
    assert "vp.fit()" in src


def test_build_set_view_current_skips_orient():
    src = viz.build_set_view("current", fit=True)
    ast.parse(src)
    assert "ViewOrientations" not in src
    assert "vp.fit()" in src


def test_build_set_view_no_fit():
    src = viz.build_set_view("iso-top-right", fit=False)
    assert "vp.fit()" not in src


def test_set_view_invalid_direction_short_circuits():
    class A:
        def execute_script(self, s: str):
            raise AssertionError("must not reach Fusion")

    env = viz.set_view(A(), direction="bogus")
    assert env.ok is False
    assert env.error == "invalid_direction"


def test_set_view_parses_stdout_response():
    class A:
        def execute_script(self, s: str):
            return Envelope(
                ok=True, message=json.dumps({"ok": True, "direction": "top", "fit": True})
            )

    env = viz.set_view(A(), direction="top")
    assert env.ok is True
    assert env.result == {"ok": True, "direction": "top", "fit": True}


# ---------- screenshot_compare_with_marker ----------


class _CompareAdapter:
    """Records the call sequence and serves canned responses for the
    4 calls compare_with_marker makes: get-marker, set-marker, screenshot,
    set-marker, screenshot."""

    def __init__(
        self,
        current_pos: int,
        count: int,
        before_png: str,
        after_png: str,
        fail_at: str | None = None,
    ):
        self.calls: list[str] = []
        self._current_pos = current_pos
        self._count = count
        self._before_png = before_png
        self._after_png = after_png
        self._screenshot_idx = 0
        self._marker_set_idx = 0
        self.fail_at = fail_at

    def execute_script(self, script: str) -> Envelope:
        # First execute_script call reads the current marker
        if "tl.markerPosition" in script and "target =" not in script:
            self.calls.append("get_marker")
            if self.fail_at == "get_marker":
                return Envelope(ok=False, error="boom")
            return Envelope(
                ok=True,
                message=json.dumps({"ok": True, "pos": self._current_pos, "count": self._count}),
            )
        # Otherwise it's a set-marker call
        self._marker_set_idx += 1
        label = f"set_marker_{self._marker_set_idx}"
        self.calls.append(label)
        if self.fail_at == label:
            return Envelope(ok=False, error="boom")
        return Envelope(
            ok=True,
            message=json.dumps({"ok": True, "pos": self._current_pos, "count": self._count}),
        )

    def read_query(self, qt: str, **kw) -> Envelope:
        self._screenshot_idx += 1
        label = f"screenshot_{self._screenshot_idx}"
        self.calls.append(label)
        if self.fail_at == label:
            return Envelope(ok=False, error="boom")
        png = self._before_png if self._screenshot_idx == 1 else self._after_png
        return Envelope(ok=True, image={"data": png, "mime_type": "image/png"})


def test_compare_invalid_direction_short_circuits():
    a = _CompareAdapter(45, 50, "A", "B")
    env = viz.screenshot_compare_with_marker(a, 30, direction="diagonal")
    assert env.ok is False
    assert env.error == "invalid_direction"
    assert a.calls == []  # no adapter calls made


def test_compare_invalid_marker_position_short_circuits():
    a = _CompareAdapter(45, 50, "A", "B")
    env = viz.screenshot_compare_with_marker(a, 99, direction="iso-top-right")
    assert env.ok is False
    assert env.error == "invalid_marker_position"
    # get-marker happens before the position check (we need tl.count first)
    assert a.calls == ["get_marker"]


def test_compare_returns_both_images_and_marker_positions():
    a = _CompareAdapter(45, 50, "BEFORE_PNG", "AFTER_PNG")
    env = viz.screenshot_compare_with_marker(a, 30, direction="iso-top-right")
    assert env.ok is True
    assert env.result["before_marker"] == 30
    assert env.result["after_marker"] == 45
    assert env.result["direction"] == "iso-top-right"
    assert env.result["before_image"]["data"] == "BEFORE_PNG"
    assert env.result["after_image"]["data"] == "AFTER_PNG"
    # Verify call sequence: get -> set(before) -> shot -> set(after) -> shot
    assert a.calls == [
        "get_marker",
        "set_marker_1",
        "screenshot_1",
        "set_marker_2",
        "screenshot_2",
    ]


def test_compare_restores_marker_on_before_screenshot_failure():
    """If the before-shot fails, the marker is at the rolled-back position;
    the tool must attempt to restore it before returning."""
    a = _CompareAdapter(45, 50, "BEFORE_PNG", "AFTER_PNG", fail_at="screenshot_1")
    env = viz.screenshot_compare_with_marker(a, 30, direction="iso-top-right")
    assert env.ok is False
    assert env.error == "before_screenshot_failed"
    # set_marker_2 = the restore-on-failure call
    assert "set_marker_2" in a.calls


def test_compare_surfaces_restore_marker_failed_distinctly():
    """If the restore (forward roll) itself fails, the user needs to know
    the design may be left mid-rebuild."""
    a = _CompareAdapter(45, 50, "BEFORE_PNG", "AFTER_PNG", fail_at="set_marker_2")
    env = viz.screenshot_compare_with_marker(a, 30, direction="iso-top-right")
    assert env.ok is False
    assert env.error == "restore_marker_failed"


def test_compare_marker_position_zero_is_valid():
    """marker=0 (empty initial state) must be accepted, not rejected as falsy."""
    a = _CompareAdapter(45, 50, "BEFORE_PNG", "AFTER_PNG")
    env = viz.screenshot_compare_with_marker(a, 0, direction="iso-top-right")
    assert env.ok is True
    assert env.result["before_marker"] == 0
