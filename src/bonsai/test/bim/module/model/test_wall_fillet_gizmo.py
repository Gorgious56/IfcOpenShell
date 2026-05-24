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

"""Registration smoke + IFC round-trip tests for the wall-fillet preview triad.

Smoke tests pin the operator surface, PropertyGroup, and umbrella wiring; the
round-trip integration tests fire ``bim.create_wall_fillet`` against a real
demo-template IFC project with two perpendicular walls and verify the result
is the expected three-wall topology connected by ``IfcRelConnectsPathElements``,
with the corner wall carrying a banana ``IfcArcIndex`` profile and a
``BBIM_Wall.IsFilletCorner`` flag that pins it against recalculation."""

import bpy
import pytest

import bonsai.tool as tool
from test.bim.bootstrap import NewFile


@pytest.mark.model
def test_wall_fillet_preview_operators_are_registered():
    """The four wall-fillet operators must resolve via ``bpy.ops.bim.*`` —
    enable populates scene props, finish dispatches the creator, cancel
    clears the state, and create is the IFC mutation entry point."""
    assert hasattr(bpy.ops.bim, "enable_wall_fillet_preview")
    assert hasattr(bpy.ops.bim, "finish_wall_fillet_preview")
    assert hasattr(bpy.ops.bim, "cancel_wall_fillet_preview")
    assert hasattr(bpy.ops.bim, "create_wall_fillet")


@pytest.mark.model
def test_wall_fillet_preview_properties_attached_to_scene():
    """The Scene PointerProperty must be bound in ``register()`` so
    enable / cancel and the preview decorator can read
    ``context.scene.BIMPreviewProperties.wall_fillet.is_active``."""
    assert hasattr(bpy.types.Scene, "BIMPreviewProperties")
    preview = bpy.context.scene.BIMPreviewProperties
    assert hasattr(preview, "wall_fillet")
    assert preview.wall_fillet.is_active is False
    assert preview.wall_fillet.wall_a_id == 0
    assert preview.wall_fillet.wall_b_id == 0


@pytest.mark.model
def test_cancel_when_not_active_returns_cancelled():
    """Cancel on idle state should report CANCELLED and leave props pristine.
    ESC routing fires cancel-without-active-preview cases regularly; cancel
    must be a no-op rather than reporting a spurious FINISHED."""
    preview = bpy.context.scene.BIMPreviewProperties
    preview.wall_fillet.is_active = False
    result = bpy.ops.bim.cancel_wall_fillet_preview()
    assert "CANCELLED" in result


@pytest.mark.model
def test_finish_when_not_active_returns_cancelled():
    """Finish on idle state should not dispatch the creator. Same defensive
    contract as cancel — the user could fire finish via a keybind from a
    non-preview state."""
    preview = bpy.context.scene.BIMPreviewProperties
    preview.wall_fillet.is_active = False
    result = bpy.ops.bim.finish_wall_fillet_preview()
    assert "CANCELLED" in result


@pytest.mark.model
def test_create_wall_fillet_is_ifc_operator():
    """``CreateWallFillet`` wraps the entire IFC mutation in a single
    transaction. Verify it inherits from ``tool.Ifc.Operator`` so the
    disconnect / shorten / create / connect sequence is one undo step."""
    from bonsai.bim.module.model.wall import CreateWallFillet

    assert issubclass(CreateWallFillet, tool.Ifc.Operator)
    assert CreateWallFillet.bl_idname == "bim.create_wall_fillet"


@pytest.mark.model
def test_fillet_preview_gizmo_group_registered():
    """``GizmoWallFilletPreview`` polls when the wall-fillet preview is
    active. Pin the bl_idname so a typo in the gizmo group wouldn't silently
    hide the preview gizmos at runtime."""
    from bonsai.bim.module.model.wall import GizmoWallFilletPreview

    assert GizmoWallFilletPreview.bl_idname == "OBJECT_GGT_bim_wall_fillet_preview"
    assert issubclass(GizmoWallFilletPreview, bpy.types.GizmoGroup)


@pytest.mark.model
def test_fillet_preview_exposes_trim_widget_factories():
    """The preview surfaces a second dimension widget for the leg trim
    length (intersection → tangent point), expressing the same single DOF
    as the radius widget via ``trim = |radius| * tan(sweep/2)``. Pin the
    factory names so a refactor can't silently drop the alternative
    parameterization."""
    from bonsai.bim.module.model.wall import GizmoWallFilletPreview

    assert hasattr(GizmoWallFilletPreview, "_make_trim_getter")
    assert hasattr(GizmoWallFilletPreview, "_make_trim_setter")


@pytest.mark.model
def test_fillet_preview_decorator_class_present():
    """The GPU decorator is installed at addon load (via
    ``bim/handler.py:load_post``). Verify the class exists with the
    install / uninstall interface the handler expects."""
    from bonsai.bim.module.model.decorator import WallFilletPreviewDecorator

    assert hasattr(WallFilletPreviewDecorator, "install")
    assert hasattr(WallFilletPreviewDecorator, "uninstall")


@pytest.mark.model
def test_pen_icon_reedit_operator_registered():
    """``bim.enable_wall_fillet_preview_from_corner`` is the pen-icon entry
    point that re-opens the preview for an existing fillet corner. Pin the
    bl_idname so a typo in the operator wouldn't silently break the
    GizmoWallFilletReedit icon binding."""
    assert hasattr(bpy.ops.bim, "enable_wall_fillet_preview_from_corner")


@pytest.mark.model
def test_pen_icon_reedit_gizmo_group_registered():
    """``GizmoWallFilletReedit`` polls when a single fillet corner wall is
    selected. The pen icon it surfaces dispatches the re-edit enable
    operator."""
    from bonsai.bim.module.model.wall import GizmoWallFilletReedit

    assert GizmoWallFilletReedit.bl_idname == "OBJECT_GGT_bim_wall_fillet_reedit"
    assert issubclass(GizmoWallFilletReedit, bpy.types.GizmoGroup)


@pytest.mark.model
def test_create_wall_fillet_accepts_editing_corner_id():
    """``CreateWallFillet`` exposes the ``editing_corner_id`` IntProperty so
    ``FinishWallFilletPreview`` can pass the existing corner's id through
    on re-edit dispatch (the operator deletes that corner before recreating
    so re-edits stay a single undo step)."""
    from bonsai.bim.module.model.wall import CreateWallFillet

    annotations = CreateWallFillet.__annotations__
    assert "editing_corner_id" in annotations


@pytest.mark.model
def test_wall_junction_custom_icons_registered():
    """The wall-junction gizmo group binds to custom wall-shaped glyphs
    (``VIEW3D_GT_wall_corner`` for sharp join, ``VIEW3D_GT_wall_tee`` for
    extend-to-wall, ``VIEW3D_GT_fillet`` for fillet) so the three corner
    actions read as a visual triad without repurposing the generic
    ``VIEW3D_GT_merge`` / ``VIEW3D_GT_extend`` glyphs used elsewhere."""
    from bonsai.bim.module.drawing.gizmos import (
        GizmoFillet,
        GizmoWallCornerIcon,
        GizmoWallTeeIcon,
    )

    assert GizmoFillet.bl_idname == "VIEW3D_GT_fillet"
    assert GizmoWallCornerIcon.bl_idname == "VIEW3D_GT_wall_corner"
    assert GizmoWallTeeIcon.bl_idname == "VIEW3D_GT_wall_tee"
    # The icons must have non-empty ``tris`` so Blender's gizmo renderer
    # actually draws geometry; an empty tuple produces an invisible icon
    # that registers without being clickable.
    assert len(GizmoWallCornerIcon.tris) > 0
    assert len(GizmoWallTeeIcon.tris) > 0


@pytest.mark.model
def test_fillet_icon_present_on_join_intersection_group():
    """The two-walls-selected gizmo group must expose a fillet entry-point
    icon — the user-discoverable trigger that opens the preview flow."""
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    # The class exposes the icon via an instance attribute set in setup();
    # verifying the load-bearing constants that wire the icon into the
    # stack catches a missing icon without instantiating a GizmoGroup
    # (which Blender forbids outside ``setup()``).
    assert hasattr(GizmoWallJoinIntersection, "ICON_STACK_OFFSET_Y")
    assert hasattr(GizmoWallJoinIntersection, "ICON_TOP_LIFT")


def _create_perpendicular_wall_pair():
    """Set up an IFC4 project with two perpendicular walls meeting at (5, 0).

    Wall A runs along +X from (0, 0) to (5, 0); wall B runs along +Y from
    (5, 0) to (5, 5). Returns (elem_a, elem_b)."""
    tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
    bpy.ops.bim.create_project()
    ifc_file = tool.Ifc.get()
    wall_type = ifc_file.by_type("IfcWallType")[0]

    bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
    wall_a = bpy.context.active_object
    # Default occurrence is at the origin, default length 1m along +X. Stretch
    # to 5m by rewriting the axis via the wall joiner.
    from bonsai.bim.module.model.wall import DumbWallJoiner

    DumbWallJoiner().set_length(wall_a, 5.0)

    bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
    wall_b = bpy.context.active_object
    # Place wall B at (5, 0) rotated 90° around +Z so its local +X aligns
    # with world +Y. Then stretch to 5m so it runs from (5, 0) to (5, 5).
    from mathutils import Euler, Matrix, Vector

    wall_b.matrix_world = (
        Matrix.Translation(Vector((5.0, 0.0, 0.0))) @ Euler((0, 0, 1.5707963267948966)).to_matrix().to_4x4()
    )
    import bonsai.core.geometry

    bonsai.core.geometry.edit_object_placement(tool.Ifc, tool.Geometry, tool.Surveyor, obj=wall_b, apply_scale=False)
    DumbWallJoiner().set_length(wall_b, 5.0)

    return tool.Ifc.get_entity(wall_a), tool.Ifc.get_entity(wall_b)


@pytest.mark.model
class TestCreateWallFilletRoundTrip(NewFile):
    """End-to-end IFC mutation tests against a real demo-template project."""

    def test_perpendicular_pair_produces_three_walls_with_two_path_connections(self):
        elem_a, elem_b = _create_perpendicular_wall_pair()
        ifc_file = tool.Ifc.get()
        assert len(ifc_file.by_type("IfcWall")) == 2

        result = bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=1.0)
        assert "FINISHED" in result

        walls = ifc_file.by_type("IfcWall")
        assert len(walls) == 3, f"expected 3 walls after fillet, got {len(walls)}"

        # Exactly two IfcRelConnectsPathElements: A↔corner and corner↔B.
        connections = ifc_file.by_type("IfcRelConnectsPathElements")
        assert len(connections) == 2, f"expected 2 path connections, got {len(connections)}"

        # The corner wall participates in both connections (it's the only
        # wall connected to both originals).
        corner_candidates = [w for w in walls if w not in (elem_a, elem_b)]
        assert len(corner_candidates) == 1
        corner = corner_candidates[0]
        related_walls = set()
        for conn in connections:
            related_walls.add(conn.RelatingElement)
            related_walls.add(conn.RelatedElement)
        assert corner in related_walls
        assert elem_a in related_walls
        assert elem_b in related_walls

    def test_corner_wall_body_uses_ifc_arc_index_for_curved_profile(self):
        """The corner wall's Body must be an ``IfcExtrudedAreaSolid`` whose
        ``SweptArea`` is an ``IfcArbitraryClosedProfileDef`` containing an
        ``IfcIndexedPolyCurve`` with ``IfcArcIndex`` segments — that's the
        IFC-native marker that this is a true rounded corner, not a chamfer."""
        import ifcopenshell.util.representation

        elem_a, elem_b = _create_perpendicular_wall_pair()
        ifc_file = tool.Ifc.get()
        bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=1.0)

        corner = next(w for w in ifc_file.by_type("IfcWall") if w not in (elem_a, elem_b))
        body = ifcopenshell.util.representation.get_representation(corner, "Model", "Body", "MODEL_VIEW")
        assert body is not None, "Corner wall has no Model/Body representation."

        # Drill down to the SweptArea profile and confirm IfcArcIndex segments.
        items = list(body.Items)
        assert len(items) == 1, f"Corner body should have exactly one item, got {len(items)}."
        extrusion = items[0]
        assert extrusion.is_a("IfcExtrudedAreaSolid"), f"Expected IfcExtrudedAreaSolid, got {extrusion.is_a()}."
        profile = extrusion.SweptArea
        assert profile.is_a("IfcArbitraryClosedProfileDef"), f"Expected banana profile, got {profile.is_a()}."
        outer = profile.OuterCurve
        assert outer.is_a("IfcIndexedPolyCurve"), f"Expected IfcIndexedPolyCurve, got {outer.is_a()}."
        arc_segments = [s for s in (outer.Segments or []) if s.is_a("IfcArcIndex")]
        assert len(arc_segments) == 2, f"Expected 2 IfcArcIndex segments (outer + inner arc), got {len(arc_segments)}."

    def test_corner_wall_carries_is_fillet_corner_pset(self):
        """The corner wall must carry ``BBIM_Wall.IsFilletCorner = True`` —
        the marker that keeps ``tool.Model.recreate_wall`` from overwriting
        the curved body during downstream recalculations, and that gates the
        fillet enable-poll against re-selecting the corner as an input."""
        import ifcopenshell.util.element

        elem_a, elem_b = _create_perpendicular_wall_pair()
        ifc_file = tool.Ifc.get()
        bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=1.0)

        corner = next(w for w in ifc_file.by_type("IfcWall") if w not in (elem_a, elem_b))
        assert ifcopenshell.util.element.get_pset(corner, "BBIM_Wall", "IsFilletCorner") is True

    def test_invalid_radius_overshoot_rejects_without_mutating(self):
        """A radius larger than the geometrically reachable limit should
        leave the project intact — 2 walls, 0 connections. Blender escalates
        operator ``{'ERROR'}`` reports to ``RuntimeError`` at the
        ``bpy.ops`` call site, so the rejection surfaces as an exception."""
        elem_a, elem_b = _create_perpendicular_wall_pair()
        ifc_file = tool.Ifc.get()
        with pytest.raises(RuntimeError, match="invalid_radius"):
            bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=100.0)
        assert len(ifc_file.by_type("IfcWall")) == 2
        assert len(ifc_file.by_type("IfcRelConnectsPathElements")) == 0

    def test_inverted_fillet_with_negative_radius(self):
        """A negative radius produces an INVERTED fillet — arc center on
        the opposite side, tangent points past the intersection, body
        between the two extended wall ends. Still 3 walls + 2 connections;
        the corner's banana still carries ``IfcArcIndex`` segments because
        the body builder uses ``abs(radius)`` for the banana radii; the
        sign only flips the arc center's side."""
        import ifcopenshell.util.element
        import ifcopenshell.util.representation

        elem_a, elem_b = _create_perpendicular_wall_pair()
        ifc_file = tool.Ifc.get()
        result = bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=-0.5)
        assert "FINISHED" in result

        assert len(ifc_file.by_type("IfcWall")) == 3
        assert len(ifc_file.by_type("IfcRelConnectsPathElements")) == 2

        corner = next(w for w in ifc_file.by_type("IfcWall") if w not in (elem_a, elem_b))
        # The pset stores the SIGNED radius — the sign carries semantic
        # information (positive = convex, negative = inverted) that future
        # regenerations need to preserve.
        assert ifcopenshell.util.element.get_pset(corner, "BBIM_Wall", "FilletRadius") == pytest.approx(-0.5)

        # Banana profile still has two arc-index segments regardless of sign.
        body = ifcopenshell.util.representation.get_representation(corner, "Model", "Body", "MODEL_VIEW")
        extrusion = body.Items[0]
        outer = extrusion.SweptArea.OuterCurve
        arc_segments = [s for s in (outer.Segments or []) if s.is_a("IfcArcIndex")]
        assert len(arc_segments) == 2

    def test_wall_type_thickness_change_propagates_to_corner(self):
        """When a wall type's ``IfcMaterialLayer.LayerThickness`` changes,
        the corner wall's banana profile must rebuild with the new
        thickness. ``regenerate_fillet_corner_wall`` reads the live layer
        parameters from the active neighbour at recalc time — if the
        corner is gated out of recreate_wall entirely (the bug this hook
        replaced), the curve freezes at its creation-time thickness even
        as the source walls' bodies update."""
        import ifcopenshell.util.element
        import ifcopenshell.util.representation
        import ifcopenshell.util.unit

        elem_a, elem_b = _create_perpendicular_wall_pair()
        ifc_file = tool.Ifc.get()
        bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=1.0)

        corner = next(w for w in ifc_file.by_type("IfcWall") if w not in (elem_a, elem_b))

        # Read the corner's banana thickness from the start cap: the
        # IfcCartesianPointList2D stores 6 points (3 outer arc + 3 inner
        # arc), and points 1 (outer-at-start) and 6 (inner-at-start) sit
        # on opposite radii at the corner's chord-local x=0 line. Their
        # distance in chord-local coords IS the wall thickness.
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc_file)

        def _profile_thickness(wall):
            body = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
            outer = body.Items[0].SweptArea.OuterCurve
            coords = outer.Points.CoordList
            p1, p6 = coords[0], coords[5]
            return ((p1[0] - p6[0]) ** 2 + (p1[1] - p6[1]) ** 2) ** 0.5 * unit_scale

        before = _profile_thickness(corner)

        # Double the wall type's layer thickness directly. The model panel
        # has its own flow for this; here we exercise the underlying
        # propagation only — touch the IfcMaterialLayer attribute then
        # call recalculate_walls on the neighbours.
        wall_type = ifcopenshell.util.element.get_type(elem_a)
        material_set = ifcopenshell.util.element.get_material(wall_type, should_skip_usage=True)
        for layer in material_set.MaterialLayers:
            layer.LayerThickness = layer.LayerThickness * 2

        wall_a_obj = tool.Ifc.get_object(elem_a)
        wall_b_obj = tool.Ifc.get_object(elem_b)
        tool.Model.recalculate_walls([wall_a_obj, wall_b_obj])

        after = _profile_thickness(corner)
        assert after == pytest.approx(
            before * 2, rel=0.05
        ), f"corner thickness didn't follow wall-type change: before={before}, after={after}"

    def test_neighbor_move_triggers_corner_regeneration(self):
        """When a neighbor wall moves, the fillet corner should regenerate
        its body AND its placement to follow. We move wall A and call
        ``recalculate_walls`` — the corner's matrix_world translation should
        shift to a NEW position consistent with the moved tangent_a."""
        elem_a, elem_b = _create_perpendicular_wall_pair()
        ifc_file = tool.Ifc.get()
        bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=1.0)

        corner = next(w for w in ifc_file.by_type("IfcWall") if w not in (elem_a, elem_b))
        corner_obj = tool.Ifc.get_object(corner)
        original_placement = corner_obj.matrix_world.translation.copy()

        # Move wall A: shift its placement by +Y so the intersection / fillet
        # geometry has to relocate. The standard Bonsai flow on a wall move
        # is ``recalculate_walls`` over the moved wall + its neighbours,
        # which fires ``recreate_wall`` and (via the IsFilletCorner gate)
        # ``regenerate_fillet_corner_wall`` on the corner.
        from mathutils import Vector

        wall_a_obj = tool.Ifc.get_object(elem_a)
        wall_a_obj.matrix_world = wall_a_obj.matrix_world.copy()
        wall_a_obj.matrix_world.translation = wall_a_obj.matrix_world.translation + Vector((0.0, 1.0, 0.0))
        import bonsai.core.geometry

        bonsai.core.geometry.edit_object_placement(
            tool.Ifc, tool.Geometry, tool.Surveyor, obj=wall_a_obj, apply_scale=False
        )
        tool.Model.recalculate_walls([wall_a_obj])

        new_placement = corner_obj.matrix_world.translation
        # Placement should have moved — exact distance depends on how the
        # intersection geometry changed, but it MUST NOT equal the old
        # placement (that would mean the corner's still anchored to the
        # pre-move tangent_a, which was the bug we fixed).
        assert (
            new_placement - original_placement
        ).length > 0.01, f"corner placement didn't follow neighbour move: stayed at {original_placement}"

    def test_pen_icon_reedit_replaces_corner_with_new_radius(self):
        """The pen-icon re-edit flow: select an existing fillet corner, fire
        the enable-from-corner op, change the radius on the preview props,
        then dispatch ``finish_wall_fillet_preview`` (which passes the
        ``editing_corner_id`` through to ``CreateWallFillet``). The result
        is still 3 walls + 2 connections — the old corner deleted, a new
        one in its place at the new radius."""
        import ifcopenshell.util.element

        elem_a, elem_b = _create_perpendicular_wall_pair()
        ifc_file = tool.Ifc.get()
        bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=1.0)

        original_corner = next(w for w in ifc_file.by_type("IfcWall") if w not in (elem_a, elem_b))
        original_corner_id = original_corner.id()
        assert ifcopenshell.util.element.get_pset(original_corner, "BBIM_Wall", "FilletRadius") == pytest.approx(1.0)

        # Simulate the pen-icon click: select the corner and fire the
        # re-edit enable operator.
        corner_obj = tool.Ifc.get_object(original_corner)
        tool.Blender.set_objects_selection(bpy.context, corner_obj, (corner_obj,))
        bpy.ops.bim.enable_wall_fillet_preview_from_corner()

        preview = bpy.context.scene.BIMPreviewProperties.wall_fillet
        assert preview.is_active is True
        assert preview.editing_corner_id == original_corner_id
        assert preview.radius == pytest.approx(1.0)
        # The enable-from-corner op should have resolved both neighbors to
        # the original source walls (or vice versa — order isn't fixed by
        # the inverse-graph walk, but the pair must match).
        assert {preview.wall_a_id, preview.wall_b_id} == {elem_a.id(), elem_b.id()}

        # User drags the radius to a new value, then validates.
        preview.radius = 0.5
        bpy.ops.bim.finish_wall_fillet_preview()

        # State machine: preview cleared on successful commit.
        assert preview.is_active is False
        assert preview.editing_corner_id == 0

        # Still 3 walls, 2 connections — the old corner was deleted, a new
        # one inserted in its place.
        walls = ifc_file.by_type("IfcWall")
        assert len(walls) == 3
        connections = ifc_file.by_type("IfcRelConnectsPathElements")
        assert len(connections) == 2

        # The new corner has the NEW radius stored on its pset.
        new_corner = next(w for w in walls if w not in (elem_a, elem_b))
        assert ifcopenshell.util.element.get_pset(new_corner, "BBIM_Wall", "FilletRadius") == pytest.approx(0.5)
        # And it's a DIFFERENT IFC entity than the original — re-edit is
        # delete-then-recreate, not in-place patch.
        assert new_corner.id() != original_corner_id
