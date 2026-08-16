"""Sketch additions (ellipse / arc / spline) tests."""

import ast

import pytest

from fusion_cad_mcp.tools import sketch as sk


def test_build_ellipse_parses():
    src = sk.build_add_ellipse("sk", [0, 0], [20, 0], [0, 10])
    ast.parse(src)
    assert "sketchEllipses.add" in src
    # mm -> cm: 20 -> 2.0
    assert "P(2.0, 0.0, 0)" in src


def test_build_ellipse_rejects_3d_points():
    with pytest.raises(ValueError):
        sk.build_add_ellipse("sk", [0, 0, 0], [20, 0], [0, 10])


def test_build_arc_3pt_parses():
    src = sk.build_add_arc("sk", "3pt", p1=[0, 0], p2=[5, 5], p3=[10, 0])
    ast.parse(src)
    assert "addByThreePoints" in src


def test_build_arc_center_start_end_parses():
    src = sk.build_add_arc("sk", "center_start_end", center=[0, 0], start=[10, 0], end=[0, 10])
    ast.parse(src)
    assert "addByCenterStartEnd" in src


def test_build_arc_center_start_sweep_parses():
    src = sk.build_add_arc(
        "sk", "center_start_sweep", center=[0, 0], start=[10, 0], sweep_radians=1.5708
    )
    ast.parse(src)
    assert "addByCenterStartSweep" in src
    assert "1.5708" in src


def test_build_arc_rejects_unknown_kind():
    with pytest.raises(ValueError):
        sk.build_add_arc("sk", "diagonal", p1=[0, 0], p2=[5, 5], p3=[10, 0])


def test_build_arc_rejects_missing_args():
    with pytest.raises(ValueError):
        sk.build_add_arc("sk", "3pt", p1=[0, 0])


def test_build_spline_parses_and_converts_mm():
    src = sk.build_add_spline("sk", [[0, 0], [10, 5], [20, 0]], closed=False)
    ast.parse(src)
    assert "sketchFittedSplines.add" in src
    assert "P(1.0, 0.5, 0)" in src
    assert "isClosed = False" in src


def test_build_spline_closed_flag():
    src = sk.build_add_spline("sk", [[0, 0], [10, 5]], closed=True)
    assert "isClosed = True" in src


def test_build_spline_rejects_one_point():
    with pytest.raises(ValueError):
        sk.build_add_spline("sk", [[0, 0]])
