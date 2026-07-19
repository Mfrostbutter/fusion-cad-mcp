"""Group 6 / visualize tools.

screenshot via fusion_mcp_read (Fusion handles the fit-view internally).
set_view via fusion_mcp_execute (no direct read tool; uses the active viewport).
"""

from __future__ import annotations

import json

from ..adapter import FusionAdapter
from ..envelope import Envelope, parse_stdout_json

VALID_DIRECTIONS = {
    "current", "front", "back", "bottom", "top", "left", "right",
    "iso-bottom-left", "iso-bottom-right", "iso-top-left", "iso-top-right",
}


def screenshot(
    adapter: FusionAdapter,
    direction: str = "iso-top-right",
    width: int | None = None,
    height: int | None = None,
    transparent: bool = True,
    anti_aliasing: bool = True,
) -> Envelope:
    """Capture a screenshot of the active viewport.

    Fusion's MCP returns PNG image content; the envelope carries it under .image.
    """
    if direction not in VALID_DIRECTIONS:
        return Envelope(
            ok=False,
            error="invalid_direction",
            message=f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {direction!r}",
        )
    kwargs: dict = {
        "direction": direction,
        "transparentBackground": transparent,
        "antiAliasing": anti_aliasing,
    }
    if width is not None:
        kwargs["width"] = width
    if height is not None:
        kwargs["height"] = height
    return adapter.read_query("screenshot", **kwargs)


def build_set_view(direction: str, fit: bool = True) -> str:
    """Generate a script that orients the viewport to a named direction.

    Uses ViewOrientations enum from adsk.core. 'current' is a no-op.
    """
    enum_map = {
        "top":              "TopViewOrientation",
        "bottom":           "BottomViewOrientation",
        "left":             "LeftViewOrientation",
        "right":            "RightViewOrientation",
        "front":            "FrontViewOrientation",
        "back":             "BackViewOrientation",
        "iso-top-right":    "IsoTopRightViewOrientation",
        "iso-top-left":     "IsoTopLeftViewOrientation",
        "iso-bottom-right": "IsoBottomRightViewOrientation",
        "iso-bottom-left":  "IsoBottomLeftViewOrientation",
    }
    if direction == "current":
        # Just fit, no orient
        orient_block = "# direction='current' — no orientation change"
    else:
        enum_name = enum_map.get(direction)
        if enum_name is None:
            # generator-time validation also; runtime fallthrough returns clean error
            orient_block = (
                f"print(json.dumps({{'ok': False, 'error': 'invalid_direction',"
                f" 'direction': {direction!r}}})); return"
            )
        else:
            orient_block = (
                f"vp.viewOrientation = adsk.core.ViewOrientations.{enum_name}"
            )
    fit_block = "vp.fit()" if fit else "# fit=False — leaving zoom alone"
    return f"""
import adsk.core
import adsk.fusion
import json

def run(_ctx):
    app = adsk.core.Application.get()
    vp = app.activeViewport
    if vp is None:
        print(json.dumps({{"ok": False, "error": "no_active_viewport"}}))
        return
    {orient_block}
    {fit_block}
    vp.refresh()
    print(json.dumps({{
        "ok": True,
        "direction": {direction!r},
        "fit": {fit!r},
    }}))
""".strip()


def set_view(adapter: FusionAdapter, direction: str = "iso-top-right", fit: bool = True) -> Envelope:
    if direction not in VALID_DIRECTIONS:
        return Envelope(
            ok=False,
            error="invalid_direction",
            message=f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {direction!r}",
        )
    env = adapter.execute_script(build_set_view(direction, fit))
    if not env.ok:
        return env
    parsed = parse_stdout_json(env)
    if parsed is None:
        return Envelope(ok=False, error="set_view_parse_failed", message=env.message)
    if parsed.get("ok") is False:
        return Envelope(ok=False, error=parsed.get("error", "set_view_failed"), message=env.message)
    return Envelope(ok=True, message=env.message, result=parsed)


def _get_marker_script() -> str:
    """Emit a script that prints {pos, count} of the active design's timeline."""
    return r"""
import adsk.core
import adsk.fusion
import json

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({"ok": False, "error": "no_active_design"}))
        return
    tl = design.timeline
    print(json.dumps({"ok": True, "pos": tl.markerPosition, "count": tl.count}))
""".strip()


def _set_marker_script(target_pos: int) -> str:
    """Emit a script that sets the timeline marker. Clamps to [0, tl.count]."""
    return f"""
import adsk.core
import adsk.fusion
import json

def run(_ctx):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if design is None:
        print(json.dumps({{"ok": False, "error": "no_active_design"}}))
        return
    tl = design.timeline
    target = max(0, min({target_pos}, tl.count))
    tl.markerPosition = target
    app.activeViewport.refresh()
    print(json.dumps({{"ok": True, "pos": tl.markerPosition, "count": tl.count}}))
""".strip()


def screenshot_compare_with_marker(
    adapter: FusionAdapter,
    before_marker_position: int,
    direction: str = "iso-top-right",
    width: int | None = None,
    height: int | None = None,
    transparent: bool = True,
    anti_aliasing: bool = True,
) -> Envelope:
    """Capture before/after screenshots from the same camera by rolling the
    timeline marker to `before_marker_position`, screenshotting, then rolling
    forward to the original position and screenshotting again.

    Restore-on-error semantics: if anything fails after we've moved the marker,
    we attempt to restore it before returning. Result envelope carries both
    base64-encoded PNGs so the agent can render or save either independently.

    Returns envelope.result = {
        before_image: {data, mime_type},
        after_image:  {data, mime_type},
        before_marker: int,
        after_marker:  int,
        direction:     str,
    }
    """
    if direction not in VALID_DIRECTIONS:
        return Envelope(
            ok=False,
            error="invalid_direction",
            message=f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {direction!r}",
        )

    # Step 1: capture current marker position (= the "after" state)
    cur_env = adapter.execute_script(_get_marker_script())
    if not cur_env.ok:
        return cur_env
    cur_parsed = parse_stdout_json(cur_env)
    if cur_parsed is None or cur_parsed.get("ok") is False:
        return Envelope(
            ok=False, error="marker_read_failed",
            message=cur_env.message,
            result=cur_parsed,
        )
    after_pos = cur_parsed["pos"]
    tl_count = cur_parsed["count"]

    def _restore():
        adapter.execute_script(_set_marker_script(after_pos))

    # Step 2: roll back to the "before" position
    if before_marker_position < 0 or before_marker_position > tl_count:
        return Envelope(
            ok=False, error="invalid_marker_position",
            message=f"before_marker_position must be in [0, {tl_count}], got {before_marker_position}",
        )
    roll_back_env = adapter.execute_script(_set_marker_script(before_marker_position))
    if not roll_back_env.ok:
        _restore()
        return roll_back_env

    # Step 3: before screenshot
    before_env = screenshot(adapter, direction, width, height, transparent, anti_aliasing)
    if not before_env.ok or before_env.image is None:
        _restore()
        return Envelope(
            ok=False, error="before_screenshot_failed",
            message=before_env.message, result=before_env.to_dict(),
        )

    # Step 4: roll forward to the original position
    roll_fwd_env = adapter.execute_script(_set_marker_script(after_pos))
    if not roll_fwd_env.ok:
        # The marker may be stuck mid-rebuild; surface clearly
        return Envelope(
            ok=False, error="restore_marker_failed",
            message=roll_fwd_env.message,
            result={"before_marker": before_marker_position, "after_marker_target": after_pos},
        )

    # Step 5: after screenshot
    after_env = screenshot(adapter, direction, width, height, transparent, anti_aliasing)
    if not after_env.ok or after_env.image is None:
        return Envelope(
            ok=False, error="after_screenshot_failed",
            message=after_env.message, result=after_env.to_dict(),
        )

    return Envelope(
        ok=True,
        result={
            "before_image": before_env.image,
            "after_image": after_env.image,
            "before_marker": before_marker_position,
            "after_marker": after_pos,
            "direction": direction,
        },
    )


__all__ = [
    "VALID_DIRECTIONS",
    "build_set_view",
    "screenshot",
    "screenshot_compare_with_marker",
    "set_view",
]
