# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2026
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.
#
# This file was generated with the assistance of an AI coding tool.

"""Regression tests for wall-split opening assignment when the cut passes
through an opening.

Bug repro before the fix: when ``bpy.ops.bim.split_wall`` (Shift+K) cut a wall
through an opening, ``DumbWallJoiner.split`` decided opening assignment using
the opening's centre-point projected onto the wall axis. Any opening whose
extent straddled the cut was therefore assigned to whichever side its centre
sat on, leaving the neighbour wall with no void where the opening overlapped.

The fix replaces the single-point test with an axis-projected extent
(``_opening_axis_extent``): an opening is removed from a wall only when its
extent lies *entirely* outside that wall's portion of the axis. Straddling
openings stay on both walls."""

from unittest.mock import MagicMock, patch

import bpy
import pytest

pytestmark = pytest.mark.wall


def _fake_shape(verts_local, matrix_world_4x4):
    """Build a stand-in for the ``shape`` object returned by
    ``ifcopenshell.geom.create_shape``. ``get_vertices`` and
    ``get_shape_matrix`` are mocked separately to read off this stand-in."""
    import numpy as np

    shape = MagicMock(name="shape")
    shape.geometry = MagicMock(name="geometry")
    shape._verts = np.asarray(verts_local, dtype=np.float64)
    shape._matrix = np.asarray(matrix_world_4x4, dtype=np.float64)
    return shape


def test_opening_axis_extent_uses_geometry_kernel_vertices():
    """``_opening_axis_extent`` drives ``ifcopenshell.geom.create_shape`` to
    get the opening's real geometry vertices and ``get_shape_matrix`` to get
    its world placement, then projects the world-space corners onto the wall
    axis. This is the production path — works for every representation type
    Bonsai may produce (mapped representation, swept area, brep, boolean).

    A unit cube centred at world X=5 on a 10m wall axis projects to
    t ∈ [0.45, 0.55] (the cube spans 0.5m on each axis around the centre)."""
    from bonsai.bim.module.model.wall import _opening_axis_extent

    # Unit cube in local coords, centred at (0,0,0), extent ±0.5.
    verts_local = [
        (-0.5, -0.5, -0.5),
        (0.5, -0.5, -0.5),
        (0.5, 0.5, -0.5),
        (-0.5, 0.5, -0.5),
        (-0.5, -0.5, 0.5),
        (0.5, -0.5, 0.5),
        (0.5, 0.5, 0.5),
        (-0.5, 0.5, 0.5),
    ]
    matrix_world = [
        [1.0, 0.0, 0.0, 5.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    fake_shape = _fake_shape(verts_local, matrix_world)
    opening = MagicMock(name="opening")
    axis_reference = (
        __import__("mathutils").Vector((0.0, 0.0)),
        __import__("mathutils").Vector((10.0, 0.0)),
    )

    with (
        patch("ifcopenshell.geom.create_shape", return_value=fake_shape),
        patch("ifcopenshell.util.shape.get_vertices", return_value=fake_shape._verts),
        patch("ifcopenshell.util.shape.get_shape_matrix", return_value=fake_shape._matrix),
    ):
        min_t, max_t = _opening_axis_extent(opening, axis_reference, unit_scale=1.0)

    # Cube spans world X ∈ [4.5, 5.5] → t ∈ [0.45, 0.55].
    assert min_t == pytest.approx(0.45)
    assert max_t == pytest.approx(0.55)


def test_opening_axis_extent_falls_back_to_placement_when_geometry_kernel_fails():
    """When ``ifcopenshell.geom.create_shape`` raises (representation it
    can't process), the helper falls back to a degenerate single-point range
    at the opening's composed placement origin. This is the safety net — it
    matches the pre-fix center-only semantics rather than dropping the
    opening entirely."""
    from bonsai.bim.module.model.wall import _opening_axis_extent

    opening = MagicMock(name="opening")
    placement_matrix = [
        [1.0, 0.0, 0.0, 5.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    axis_reference = (
        __import__("mathutils").Vector((0.0, 0.0)),
        __import__("mathutils").Vector((10.0, 0.0)),
    )

    with (
        patch("ifcopenshell.geom.create_shape", side_effect=RuntimeError("kernel failure")),
        patch("ifcopenshell.util.placement.get_local_placement") as mock_get_placement,
    ):
        mock_get_placement.return_value = type("FakeArr", (), {"tolist": lambda self: placement_matrix})()
        min_t, max_t = _opening_axis_extent(opening, axis_reference, unit_scale=1.0)

    assert min_t == max_t == pytest.approx(0.5)


def test_opening_axis_extent_offset_cursor_inside_extent_returns_straddling_range():
    """The regression guard for the user-reported bug across two fix attempts:
    when the cursor is placed *inside* the opening but not at its exact
    centre, the helper must still return a range that straddles the cursor
    position so the side test keeps the opening on both walls.

    Pre-fix v2/v3 collapsed to a degenerate range whenever the production
    representation type wasn't recognised (Blender bound_box absent in v2;
    mapped representation not walked in v3). The current implementation uses
    ``ifcopenshell.geom.create_shape``, which handles every representation
    Bonsai may produce."""
    from bonsai.bim.module.model.wall import _opening_axis_extent

    # 2m-wide opening centred at world X=5 → world X ∈ [4.0, 6.0] → t ∈ [0.4, 0.6].
    verts_local = [(-1.0, -0.5, -0.5), (1.0, 0.5, 0.5)]
    matrix_world = [
        [1.0, 0.0, 0.0, 5.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    fake_shape = _fake_shape(verts_local, matrix_world)
    opening = MagicMock(name="opening")
    axis_reference = (
        __import__("mathutils").Vector((0.0, 0.0)),
        __import__("mathutils").Vector((10.0, 0.0)),
    )

    with (
        patch("ifcopenshell.geom.create_shape", return_value=fake_shape),
        patch("ifcopenshell.util.shape.get_vertices", return_value=fake_shape._verts),
        patch("ifcopenshell.util.shape.get_shape_matrix", return_value=fake_shape._matrix),
    ):
        min_t, max_t = _opening_axis_extent(opening, axis_reference, unit_scale=1.0)

    # Cursor at world X=4.7 → t=0.47 (inside the opening, not centred on it).
    cut_percentage = 0.47
    assert (
        min_t < cut_percentage < max_t
    ), f"opening [t={min_t}, t={max_t}] must straddle off-centre cursor at t={cut_percentage}"


# The three cut-decision predicates ``opening_is_past_cut`` /
# ``opening_is_before_cut`` / ``opening_straddles_cut`` are pure floats-in,
# bool-out functions in ``bonsai.core.model`` and are tested in
# ``test/core/test_model.py``'s ``TestOpeningSplitPredicates`` /
# ``TestOpeningPredicateNaNHandling``. The forward-compat guard that
# production calls them (rather than re-inlining the inequalities) lives
# alongside the other wall.py structural AST guards.


# ---------------------------------------------------------------------------
# Filled-opening void-straddle behaviour
#
# When a wall split passes through a door/window, the filling (the door
# element itself) belongs to whichever wall contains its centre — but the
# void cut by the IfcOpeningElement may still straddle the cut, in which
# case the neighbour wall's body must also be cut. The helper that adds the
# pure-void copy is ``_add_void_copy``; the decision is taken in
# ``DumbWallJoiner.split``'s filled-opening loop.
# ---------------------------------------------------------------------------


def _make_void_copy_mock(has_filling_rel=True):
    """Build the ``void_copy`` MagicMock returned by ``copy_class`` shaped
    like the IfcOpeningElement ``_add_void_copy`` consumes — ``HasFillings``
    populated when the source carried a filling rel, ``VoidsElements`` and
    ``ObjectPlacement`` shaped so the production code can inspect them."""
    copy_placement = MagicMock(name="copy_placement")
    copy_placement.is_a = lambda klass: klass == "IfcLocalPlacement"
    void_relation = MagicMock(name="VoidsRelation")
    void_copy = MagicMock(name="void_copy")
    void_copy.HasFillings = (MagicMock(name="copy_filling_rel"),) if has_filling_rel else ()
    void_copy.VoidsElements = (void_relation,)
    void_copy.ObjectPlacement = copy_placement
    return void_copy, void_relation, copy_placement


def test_add_void_copy_strips_fillings_and_reparents_via_feature_api():
    """``_add_void_copy`` must create a pure-void IfcOpeningElement attached
    to the target wall via ``ifcopenshell.api.feature.add_feature``. The
    carried filling rel must be removed first; the void-rel rewiring and
    placement re-parent both go through the API so owner history rotates
    and the world matrix is preserved."""
    from bonsai.bim.module.model.wall import _add_void_copy

    source_opening = MagicMock(name="source_opening")
    source_opening.Representation = MagicMock(name="source_representation")

    void_copy, _void_relation, _copy_placement = _make_void_copy_mock()
    carried_filling_rel = void_copy.HasFillings[0]

    target_wall = MagicMock(name="target_wall")
    target_wall.ObjectPlacement = MagicMock(name="target_placement")

    ifc_file = MagicMock(name="ifc_file")
    deep_copy_result = MagicMock(name="copied_representation")

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("ifcopenshell.api.root.copy_class", return_value=void_copy) as mock_copy_class,
        patch("ifcopenshell.api.feature.add_feature") as mock_add_feature,
        patch("ifcopenshell.util.element.copy_deep", return_value=deep_copy_result),
    ):
        _add_void_copy(target_wall, source_opening)

    mock_copy_class.assert_called_once_with(ifc_file, product=source_opening)
    ifc_file.remove.assert_called_once_with(carried_filling_rel)
    mock_add_feature.assert_called_once_with(ifc_file, feature=void_copy, element=target_wall)
    assert void_copy.Representation is deep_copy_result


def test_add_void_copy_handles_source_with_no_fillings():
    """A source with no carried filling rel must skip the ``remove`` loop;
    relationship rewiring still goes through ``add_feature``."""
    from bonsai.bim.module.model.wall import _add_void_copy

    source_opening = MagicMock(name="source_opening")
    source_opening.Representation = MagicMock(name="rep")

    void_copy, _void_relation, _copy_placement = _make_void_copy_mock(has_filling_rel=False)
    target_wall = MagicMock(name="target_wall")

    ifc_file = MagicMock(name="ifc_file")

    with (
        patch("bonsai.tool.Ifc.get", return_value=ifc_file),
        patch("ifcopenshell.api.root.copy_class", return_value=void_copy),
        patch("ifcopenshell.api.feature.add_feature") as mock_add_feature,
        patch("ifcopenshell.util.element.copy_deep", return_value=MagicMock()),
    ):
        _add_void_copy(target_wall, source_opening)

    ifc_file.remove.assert_not_called()
    mock_add_feature.assert_called_once_with(ifc_file, feature=void_copy, element=target_wall)
