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

import math
import types
from types import SimpleNamespace

import bmesh
import bpy
import pytest
from mathutils import Matrix, Vector

from bonsai import tool
from bonsai.bim.module.drawing.gizmos import (
    BaseSchematicGizmoGroup,
    DimensionGizmoConfig,
)

pytestmark = pytest.mark.drawing


@pytest.fixture(autouse=True)
def _require_real_bpy():
    if not isinstance(bpy, types.ModuleType) or hasattr(bpy, "_mock_name"):
        pytest.skip("requires real Blender (bpy is mocked or absent)")


# ── compute_schematic_anchor ─────────────────────────────────────────────────


def test_compute_anchor_at_identity():
    """Identity world matrix + identity billboard + zero schematic offset → icon-row position."""
    anchor = BaseSchematicGizmoGroup.compute_schematic_anchor(
        mw=Matrix.Identity(4),
        element_height=2.0,
        icon_x=0.0,
        icon_z_offset=0.5,
        billboard_rot=Matrix.Identity(4),
        schematic_offset=Vector((0.0, 0.0, 0.0)),
    )
    assert anchor == Vector((0.0, 0.0, 2.5))


def test_compute_anchor_lifts_by_schematic_offset():
    """The schematic offset rides on billboard_rot @ offset, not raw world."""
    anchor = BaseSchematicGizmoGroup.compute_schematic_anchor(
        mw=Matrix.Identity(4),
        element_height=1.0,
        icon_x=0.0,
        icon_z_offset=0.5,
        billboard_rot=Matrix.Identity(4),
        schematic_offset=Vector((0.0, 0.0, 0.6)),
    )
    assert anchor == Vector((0.0, 0.0, 2.1))


def test_compute_anchor_translates_with_world_matrix():
    """Moving the object moves the anchor by the same vector."""
    mw = Matrix.Translation((5.0, -3.0, 1.0))
    anchor = BaseSchematicGizmoGroup.compute_schematic_anchor(
        mw=mw,
        element_height=1.0,
        icon_x=0.0,
        icon_z_offset=0.5,
        billboard_rot=Matrix.Identity(4),
        schematic_offset=Vector((0.0, 0.0, 0.0)),
    )
    assert anchor == Vector((5.0, -3.0, 2.5))


# ── _schematic_world_matrix ─────────────────────────────────────────────────


def test_schematic_matrix_translation_is_anchor_plus_offset():
    """matrix_basis.translation = anchor + billboard_rot @ local_position."""
    anchor = Vector((1.0, 2.0, 3.0))
    matrix = BaseSchematicGizmoGroup._schematic_world_matrix(
        anchor=anchor,
        billboard_rot=Matrix.Identity(4),
        axis=(1, 0, 0),
        local_position=(0.1, -0.2, 0.05),
    )
    assert matrix.translation == Vector((1.1, 1.8, 3.05))


def test_schematic_matrix_rotates_with_billboard():
    """With a 90° Z-rotation billboard, schematic-local +X maps to world +Y."""
    billboard_rot = Matrix.Rotation(math.pi / 2, 4, "Z")
    matrix = BaseSchematicGizmoGroup._schematic_world_matrix(
        anchor=Vector((0.0, 0.0, 0.0)),
        billboard_rot=billboard_rot,
        axis=(1, 0, 0),
        local_position=(0.0, 0.0, 0.0),
    )
    bar_x_world = matrix.col[0].xyz  # local +X expressed in world
    assert bar_x_world.y == pytest.approx(1.0)
    assert bar_x_world.x == pytest.approx(0.0, abs=1e-6)
    assert bar_x_world.z == pytest.approx(0.0, abs=1e-6)


def test_schematic_matrix_aligns_bar_with_schematic_axis():
    """A Z-axis dimension points along world +Z under identity billboard."""
    matrix = BaseSchematicGizmoGroup._schematic_world_matrix(
        anchor=Vector((0.0, 0.0, 0.0)),
        billboard_rot=Matrix.Identity(4),
        axis=(0, 0, 1),
        local_position=(0.0, 0.0, 0.0),
    )
    bar_x_world = matrix.col[0].xyz
    assert bar_x_world.z == pytest.approx(1.0)


# ── Draw-handler lifecycle ───────────────────────────────────────────────────


class _StubSchematic(BaseSchematicGizmoGroup):
    """Concrete subclass used only by the draw-handler tests.

    Lives in the test file (not the production tree) so its lifecycle is
    bounded by the test fixture — no production dead-weight from a stub
    that ships with the addon.
    """

    bl_idname = "OBJECT_GGT_test_schematic_stub"
    props_getter = tool.Model.get_railing_props
    gizmo_pref_name = "railing"
    schematic_dimension_props = [
        DimensionGizmoConfig(attr_name="height", axis=(0, 0, 1)),
    ]

    @classmethod
    def build_schematic_mesh(cls, _props):
        # The draw-handler lifecycle tests don't actually invoke the draw
        # callback, but the abstract hook must be implementable. Return an
        # empty bmesh so the cache path in ``_get_schematic_local_edges``
        # works if a future test exercises it.
        return bmesh.new()


def test_install_draw_handler_is_idempotent():
    """Calling install twice doesn't register two handlers."""
    _StubSchematic._draw_handler_installed = None
    try:
        _StubSchematic._install_draw_handler()
        first = _StubSchematic._draw_handler_installed
        assert first is not None
        _StubSchematic._install_draw_handler()
        assert _StubSchematic._draw_handler_installed is first
    finally:
        _StubSchematic._uninstall_draw_handler()


def test_uninstall_draw_handler_clears_state():
    _StubSchematic._draw_handler_installed = None
    _StubSchematic._install_draw_handler()
    assert _StubSchematic._draw_handler_installed is not None
    _StubSchematic._uninstall_draw_handler()
    assert _StubSchematic._draw_handler_installed is None


def test_uninstall_is_idempotent_when_not_installed():
    """Calling uninstall without a prior install must not raise."""
    _StubSchematic._draw_handler_installed = None
    _StubSchematic._uninstall_draw_handler()
    assert _StubSchematic._draw_handler_installed is None


def test_subclass_handlers_do_not_collide():
    """Two consumer subclasses keep independent draw handles."""

    class _OtherStub(BaseSchematicGizmoGroup):
        bl_idname = "OBJECT_GGT_test_schematic_other"
        props_getter = tool.Model.get_railing_props
        gizmo_pref_name = "railing"

    _StubSchematic._draw_handler_installed = None
    _OtherStub._draw_handler_installed = None
    try:
        _StubSchematic._install_draw_handler()
        _OtherStub._install_draw_handler()
        assert _StubSchematic._draw_handler_installed is not None
        assert _OtherStub._draw_handler_installed is not None
        assert _StubSchematic._draw_handler_installed is not _OtherStub._draw_handler_installed
    finally:
        _StubSchematic._uninstall_draw_handler()
        _OtherStub._uninstall_draw_handler()


# ── Class shape / contract ───────────────────────────────────────────────────


def test_dimension_props_default_empty():
    """Schematic groups don't ship in-place dimensions — the inherited
    parent setup_dimension_gizmos becomes a no-op."""
    assert BaseSchematicGizmoGroup.dimension_gizmo_props == []


def test_build_schematic_mesh_is_abstract():
    """Subclasses without an override must raise so they fail loudly at first draw."""

    class _NoBuild(BaseSchematicGizmoGroup):
        bl_idname = "OBJECT_GGT_test_schematic_no_build"

    with pytest.raises(NotImplementedError, match="build_schematic_mesh"):
        _NoBuild.build_schematic_mesh(SimpleNamespace())


def test_schematic_should_show_class_matches_is_editing():
    """Class-level visibility gate reads props.is_editing — used by the
    draw handler which has no group instance to call the instance method."""
    assert BaseSchematicGizmoGroup.schematic_should_show_class(SimpleNamespace(is_editing=True)) is True
    assert BaseSchematicGizmoGroup.schematic_should_show_class(SimpleNamespace(is_editing=False)) is False


def test_get_element_height_class_prefers_overall_height():
    """Door/window/stair-style elements expose overall_height; railing/wall expose height."""
    assert BaseSchematicGizmoGroup._get_element_height_class(SimpleNamespace(overall_height=2.4, height=99.0)) == 2.4
    assert BaseSchematicGizmoGroup._get_element_height_class(SimpleNamespace(height=1.1)) == 1.1
    # Fallback when neither attribute exists.
    assert BaseSchematicGizmoGroup._get_element_height_class(SimpleNamespace()) == 1.0
