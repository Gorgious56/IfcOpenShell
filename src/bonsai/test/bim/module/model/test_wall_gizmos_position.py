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

"""Unit tests for wall gizmo positioning, cursor-anchored placement, and the
slope-aware Z routing that keeps icons on the wall's slanted top edge.

Three concerns, each pinned by its own helper + tests:

- ``GizmoWallJoinIntersection.position_gizmos`` — four-icon visibility and
  top-down vs perspective stacking.
- ``_position_cursor_anchored_gizmos`` — cursor-anchored extend / split
  icons; world-Z stacking that collapses to a screen-up offset in plan view;
  slope correction so the split icon lands on the slanted wall top.
- ``WallGizmoPreviewDecorator`` — ``_extended_wall_index`` hover-discrimination
  and ``_lookup_active_instance`` per-region routing.

Static AST guards on ``wall.py`` structural invariants (resync pairing, slope-
aware Z routing, predicate-call discipline) live in a separate file dedicated
to that concern."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.wall


# ----------------------------------------------------------------------------
# GizmoWallJoinIntersection.position_gizmos() — visibility regression tests
# ----------------------------------------------------------------------------
#
# These tests drive `position_gizmos()` directly with a stub `self` so the four
# icons' `.hide` state can be asserted without launching a full Blender editor.
# Two helper layers are mocked: the wall geometry/segment readers in
# `bonsai.bim.module.model.wall`, and the billboarding helpers in
# `bonsai.bim.module.drawing.gizmos`.


def _make_position_gizmos_self():
    """Build a stub instance for ``GizmoWallJoinIntersection.position_gizmos()``.

    Carries the four icon gizmos (each a namespace with writable ``hide``
    and ``matrix_basis``), the class-level tunables ``position_gizmos`` reads,
    and a ``_hide_all()`` helper bound to the stub."""
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    def _icon():
        return SimpleNamespace(hide=True, matrix_basis=None)

    stub = SimpleNamespace(
        unjoin_icon=_icon(),
        merge_icon=_icon(),
        join_icon=_icon(),
        extend_to_wall_icon=_icon(),
        fillet_icon=_icon(),
        ICON_STACK_OFFSET_Y=GizmoWallJoinIntersection.ICON_STACK_OFFSET_Y,
        ICON_TOP_LIFT=GizmoWallJoinIntersection.ICON_TOP_LIFT,
        TOP_DOWN_INTERSECTION_CLEARANCE=GizmoWallJoinIntersection.TOP_DOWN_INTERSECTION_CLEARANCE,
    )

    def _hide_all():
        stub.unjoin_icon.hide = True
        stub.merge_icon.hide = True
        stub.join_icon.hide = True
        stub.extend_to_wall_icon.hide = True
        stub.fillet_icon.hide = True

    stub._hide_all = _hide_all
    return stub


def _run_position_gizmos(seg_a, seg_b, top_down=False, screen_up=(0.0, 1.0, 0.0), height_a=3.0, height_b=3.0):
    """Invoke `position_gizmos()` with two world-space wall axis segments.

    `seg_a` / `seg_b` are pairs of 3-tuples (start, end). The two walls are
    treated as non-joined LAYER2 walls; whether the classifier returns
    ``"collinear"`` vs ``"intersect"`` vs ``"none"`` is decided by the
    segment geometry itself. ``height_a`` / ``height_b`` set the per-wall
    heights so callers can pin the ``max(wall_a_top, wall_b_top)`` math.
    ``top_down`` toggles the plan-view branch, and ``screen_up`` is the
    world-space screen-up vector callers can assert offsets against.
    Returns the stub ``self`` so the caller can assert on per-icon
    ``.hide`` / position state."""
    from mathutils import Matrix, Vector

    from bonsai import tool
    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model import wall as wall_module

    elem_a = object()
    elem_b = object()
    geom_a = {"height": height_a}
    geom_b = {"height": height_b}
    seg_a_vec = (Vector(seg_a[0]), Vector(seg_a[1]))
    seg_b_vec = (Vector(seg_b[0]), Vector(seg_b[1]))

    # Stand-ins for the two selected Blender objects. SimpleNamespace lets
    # `context.active_object in selected` use identity, and exposes a fake
    # `matrix_world.translation.z` for the extend icon's top-Z arithmetic.
    fake_matrix_world = SimpleNamespace(translation=SimpleNamespace(z=0.0))
    obj_a = SimpleNamespace(matrix_world=fake_matrix_world)
    obj_b = SimpleNamespace(matrix_world=fake_matrix_world)
    selected = [obj_a, obj_b]

    def get_entity(obj):
        return {id(obj_a): elem_a, id(obj_b): elem_b}.get(id(obj))

    def get_wall_geom_cached(group, obj):
        return {id(obj_a): geom_a, id(obj_b): geom_b}.get(id(obj))

    def axis_world_segment(obj, geom):
        return {id(obj_a): seg_a_vec, id(obj_b): seg_b_vec}[id(obj)]

    def read_wall_geometry(active):
        return geom_a if active is obj_a else geom_b

    context = SimpleNamespace(active_object=obj_a)

    patches = [
        patch.object(tool.Blender, "get_selected_objects", return_value=list(selected)),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(wall_module, "get_wall_geom_cached", side_effect=get_wall_geom_cached),
        patch.object(wall_module, "_wall_axis_world_segment_from_geom", side_effect=axis_world_segment),
        patch.object(wall_module, "_are_walls_joined", return_value=False),
        patch.object(wall_module, "_are_walls_collinear", return_value=False),
        patch.object(wall_module, "_is_fillet_corner_wall", return_value=False),
        patch.object(tool.Wall, "read_geometry", side_effect=read_wall_geometry),
        patch.object(tool.Blender, "is_view_top_down", return_value=top_down),
        patch.object(tool.Blender, "top_down_factor", return_value=1.0 if top_down else 0.0),
        patch.object(tool.Blender, "get_screen_up_world", return_value=Vector(screen_up)),
        patch.object(gizmo_module, "get_billboard_rotation", return_value=Matrix.Identity(4)),
        patch.object(gizmo_module, "billboarded_at", side_effect=lambda pos, rot, scale=0.5: Matrix.Translation(pos)),
    ]
    for p in patches:
        p.start()
    try:
        self_stub = _make_position_gizmos_self()
        wall_module.GizmoWallJoinIntersection.position_gizmos(self_stub, context)
        return self_stub
    finally:
        for p in patches:
            p.stop()


def test_position_gizmos_shows_join_and_extend_for_far_apart_walls():
    """Far-apart non-parallel wall axes must still display the join + extend icons.

    The two walls below are each 1 m long, placed so their axes meet ~50 m away
    from the nearest endpoint of either wall — far beyond any "near the corner"
    heuristic. The user has explicitly selected both walls; the gizmos exist
    precisely to let them join or extend in this situation. A previous
    endpoint-proximity gate hid all four icons whenever the intersection sat
    farther than a fraction of the wall length from the nearest endpoint, which
    is exactly the "user wants to extend distant walls" case.

    The parallel-axis guard already filters the genuine "intersection at
    infinity" case, so no other gate is needed for visibility here."""
    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        seg_b=((50.0, 50.0, 0.0), (50.0, 51.0, 0.0)),
    )
    assert self_stub.join_icon.hide is False
    assert self_stub.extend_to_wall_icon.hide is False
    assert self_stub.unjoin_icon.hide is True
    assert self_stub.merge_icon.hide is True


def test_position_gizmos_hides_all_for_parallel_walls():
    """Two near-parallel walls must keep every icon hidden.

    Parallel axes have no meaningful intersection — the existing
    ``PARALLEL_DOT_THRESHOLD`` is what carries that guarantee, and removing the
    endpoint-distance gate must not weaken it. Two co-directional walls offset
    laterally should still produce a fully hidden gizmo group."""
    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        seg_b=((0.0, 5.0, 0.0), (1.0, 5.0, 0.0)),
    )
    assert self_stub.unjoin_icon.hide is True
    assert self_stub.merge_icon.hide is True
    assert self_stub.join_icon.hide is True
    assert self_stub.extend_to_wall_icon.hide is True


# ----------------------------------------------------------------------------
# Top-down view positioning — wall-Z lifts swap for screen-up offsets
# ----------------------------------------------------------------------------
#
# The wall gizmos lift icons along world-Z (above the wall top, at the slab
# elevation, …) for readable separation in 3D orbited views. In plan / top-down
# views that lift projects to zero on-screen and stacked icons collapse together;
# the positioning code swaps the Z-lift for a screen-up offset in those cases.
# Tests below pin both branches per gizmo group.


def test_position_gizmos_stacks_along_screen_up_in_top_down_view():
    """Plan view: join + extend share their XY anchor and separate along screen-up
    by the group's own ``ICON_STACK_OFFSET_Y``."""
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        seg_b=((50.0, 50.0, 0.0), (50.0, 51.0, 0.0)),
        top_down=True,
        screen_up=(0.0, 1.0, 0.0),
    )
    join_pos = self_stub.join_icon.matrix_basis.translation
    extend_pos = self_stub.extend_to_wall_icon.matrix_basis.translation
    assert join_pos.z == pytest.approx(extend_pos.z)
    delta = join_pos - extend_pos
    assert delta.y == pytest.approx(GizmoWallJoinIntersection.ICON_STACK_OFFSET_Y)
    assert delta.x == pytest.approx(0.0)


def test_position_gizmos_stacks_along_screen_up_in_perspective_view():
    """Non-top-down view: both icons anchor at the taller wall's top + ``ICON_TOP_LIFT``
    and separate along screen-up — the previous Z-stacking design (extend lifted by
    one wall-height above join) was replaced with uniform screen-up stacking so the
    icons read as a single XY column from any camera angle."""
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        seg_b=((50.0, 50.0, 0.0), (50.0, 51.0, 0.0)),
        top_down=False,
        screen_up=(0.0, 1.0, 0.0),
    )
    join_pos = self_stub.join_icon.matrix_basis.translation
    extend_pos = self_stub.extend_to_wall_icon.matrix_basis.translation
    # geom["height"] is 3.0, so both icons sit at 3.0 + ICON_TOP_LIFT.
    expected_z = 3.0 + GizmoWallJoinIntersection.ICON_TOP_LIFT
    assert join_pos.z == pytest.approx(expected_z)
    assert extend_pos.z == pytest.approx(expected_z)
    delta = join_pos - extend_pos
    assert delta.y == pytest.approx(GizmoWallJoinIntersection.ICON_STACK_OFFSET_Y)
    assert delta.x == pytest.approx(0.0)


def test_position_gizmos_lifts_stack_above_intersection_in_top_down_view():
    """Plan view: stack's lowest icon (extend) sits one
    ``TOP_DOWN_INTERSECTION_CLEARANCE`` *above* the intersection in screen-up,
    so the wall axes meeting underneath stay visible. Without this the icons
    land right on the intersection point and obscure the very feature the
    user is hovering."""
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        seg_b=((50.0, 50.0, 0.0), (50.0, 51.0, 0.0)),
        top_down=True,
        screen_up=(0.0, 1.0, 0.0),
    )
    extend_pos = self_stub.extend_to_wall_icon.matrix_basis.translation
    # Axes intersect at world (50.0, 0.0). The lowest icon (extend) sits at
    # intersection.y + TOP_DOWN_INTERSECTION_CLEARANCE along screen-up.
    assert extend_pos.x == pytest.approx(50.0)
    assert extend_pos.y == pytest.approx(GizmoWallJoinIntersection.TOP_DOWN_INTERSECTION_CLEARANCE)


def test_position_gizmos_no_extra_lift_in_perspective_view():
    """Perspective view: the wall-top Z lift already separates the icons from
    the wall body, so no screen-up shift applies. The lowest icon's XY
    matches the intersection."""
    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
        seg_b=((50.0, 50.0, 0.0), (50.0, 51.0, 0.0)),
        top_down=False,
        screen_up=(0.0, 1.0, 0.0),
    )
    extend_pos = self_stub.extend_to_wall_icon.matrix_basis.translation
    assert extend_pos.x == pytest.approx(50.0)
    assert extend_pos.y == pytest.approx(0.0)


# Collinear-branch placement — Merge anchors above the taller wall's top so the
# icon clears the wall bodies in perspective views, parity with the joined and
# intersect branches.


def test_position_gizmos_merges_collinear_walls_above_taller_top_in_perspective_view():
    """Perspective view: Merge sits at the closest-endpoint XY midpoint and at
    ``max(wall_a_top, wall_b_top) + ICON_TOP_LIFT`` along Z, so the icon clears
    the wall bodies regardless of which of the two walls is taller."""
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        seg_b=((3.0, 0.0, 0.0), (5.0, 0.0, 0.0)),
        top_down=False,
        screen_up=(0.0, 1.0, 0.0),
        height_a=2.4,
        height_b=3.2,
    )
    assert self_stub.merge_icon.hide is False
    assert self_stub.unjoin_icon.hide is True
    assert self_stub.join_icon.hide is True
    assert self_stub.extend_to_wall_icon.hide is True
    assert self_stub.fillet_icon.hide is True
    merge_pos = self_stub.merge_icon.matrix_basis.translation
    assert merge_pos.x == pytest.approx(2.5)
    assert merge_pos.y == pytest.approx(0.0)
    assert merge_pos.z == pytest.approx(3.2 + GizmoWallJoinIntersection.ICON_TOP_LIFT)


def test_position_gizmos_lifts_merge_above_boundary_in_top_down_view():
    """Plan view: Merge keeps the wall-top Z anchor and additionally shifts along
    screen-up by ``TOP_DOWN_INTERSECTION_CLEARANCE`` so the boundary point stays
    visible below the icon — mirroring the joined / intersect branches."""
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        seg_b=((3.0, 0.0, 0.0), (5.0, 0.0, 0.0)),
        top_down=True,
        screen_up=(0.0, 1.0, 0.0),
        height_a=2.4,
        height_b=3.2,
    )
    merge_pos = self_stub.merge_icon.matrix_basis.translation
    assert merge_pos.x == pytest.approx(2.5)
    assert merge_pos.y == pytest.approx(GizmoWallJoinIntersection.TOP_DOWN_INTERSECTION_CLEARANCE)
    assert merge_pos.z == pytest.approx(3.2 + GizmoWallJoinIntersection.ICON_TOP_LIFT)


def test_position_gizmos_hides_non_merge_icons_for_collinear_walls():
    """Collinear branch shows Merge alone — the four sibling icons (Unjoin,
    Join, Extend, Fillet) must stay hidden so a future refactor that drops a
    hide flag fails loudly."""
    self_stub = _run_position_gizmos(
        seg_a=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        seg_b=((3.0, 0.0, 0.0), (5.0, 0.0, 0.0)),
        top_down=False,
        screen_up=(0.0, 1.0, 0.0),
        height_a=2.4,
        height_b=3.2,
    )
    assert self_stub.merge_icon.hide is False
    assert self_stub.unjoin_icon.hide is True
    assert self_stub.join_icon.hide is True
    assert self_stub.extend_to_wall_icon.hide is True
    assert self_stub.fillet_icon.hide is True


# GizmoWallExtendVertically position_gizmos is unconditional — the top-down
# case is rejected at poll() time, so position_gizmos never runs in plan view
# and needs no per-view branch test.


# ----------------------------------------------------------------------------
# Cursor-anchored gizmos on a single-wall selection — top-down stacking
# ----------------------------------------------------------------------------
#
# _position_cursor_anchored_gizmos stacks extend-X / extend-Z / split
# along world Z at the cursor's projected X. In plan view those Z slots collapse
# on-screen and every cursor icon lands on top of the others; the positioning
# code switches to a screen-up stack in that case.


def _run_cursor_gizmos(
    top_down,
    *,
    cursor_local=(0.5, 0.0, 1.5),
    screen_up=(0.0, 1.0, 0.0),
    billboard_rot=None,
    anchor_x=0.0,
    length=2.0,
):
    """Drive ``_position_cursor_anchored_gizmos`` with a stub ``self``.

    Returns the three icon stubs (extend_x, extend_z, split) so callers can
    inspect positions and visibility independently."""
    from mathutils import Matrix, Vector

    from bonsai import tool
    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model import wall as wall_module

    def _icon():
        return SimpleNamespace(hide=True, matrix_basis=None)

    extend_x = _icon()
    extend_z = _icon()
    split = _icon()

    props = SimpleNamespace(anchor_x=anchor_x, length=length, height=3.0, x_angle=0.0)

    self_stub = SimpleNamespace(
        extend_x_gizmo=extend_x,
        extend_z_gizmo=extend_z,
        split_gizmo=split,
        CURSOR_STACK_OFFSET=wall_module.GizmoWallEdition.CURSOR_STACK_OFFSET,
        _frame_billboard_rot=billboard_rot if billboard_rot is not None else Matrix.Identity(4),
        is_gizmo_hidden_by_modal=lambda gz: False,
    )
    cursor = SimpleNamespace(location=Vector(cursor_local))
    context = SimpleNamespace(scene=SimpleNamespace(cursor=cursor))

    patches = [
        patch.object(tool.Blender, "is_view_top_down", return_value=top_down),
        patch.object(tool.Blender, "get_screen_up_world", return_value=Vector(screen_up)),
        patch.object(gizmo_module, "billboarded_at", side_effect=lambda pos, rot, scale=0.5: Matrix.Translation(pos)),
    ]
    for p in patches:
        p.start()
    try:
        wall_module._position_cursor_anchored_gizmos(self_stub, context, Matrix.Identity(4), props)
    finally:
        for p in patches:
            p.stop()
    return extend_x, extend_z, split


def test_cursor_gizmos_stack_along_screen_up_in_top_down_view():
    """Plan view: extend-Z is hidden entirely (no Z visual cue from above), and the
    remaining cursor gizmos stack along screen-up by CURSOR_STACK_OFFSET steps
    sharing the same projected world Z so on-screen positions never overlap."""
    from bonsai.bim.module.model.wall import GizmoWallEdition

    extend_x, extend_z, split = _run_cursor_gizmos(top_down=True, screen_up=(0.0, 1.0, 0.0))
    # extend-Z (wall-height extension) has no readable cue in plan view → hidden,
    # honouring the invariant that vertical-intent gizmos do not show in plan view.
    assert extend_z.hide is True
    assert extend_z.matrix_basis is None
    pos_x = extend_x.matrix_basis.translation
    pos_split = split.matrix_basis.translation
    # Remaining icons share the wall-axis world Z — stacking lives in screen space.
    assert pos_x.z == pytest.approx(pos_split.z)
    # split sits one CURSOR_STACK_OFFSET above extend-X along screen-up (+Y here).
    step = GizmoWallEdition.CURSOR_STACK_OFFSET
    assert pos_split.y - pos_x.y == pytest.approx(step)


def test_cursor_gizmos_keep_z_stacking_in_perspective_view():
    """3D view: cursor gizmos keep their world-Z slots — extend-X at 0, extend-Z at cursor Z,
    split at wall height, with the existing collision-resolution bump preserved."""
    extend_x, extend_z, split = _run_cursor_gizmos(top_down=False, cursor_local=(0.5, 0.0, 1.5))
    # All icons share the same screen-Y in 3D — only Z differs.
    assert extend_x.matrix_basis.translation.y == pytest.approx(0.0)
    assert extend_z.matrix_basis.translation.y == pytest.approx(0.0)
    assert split.matrix_basis.translation.y == pytest.approx(0.0)
    # extend-X at floor Z, extend-Z at cursor Z (1.5), split at wall height (3.0).
    assert extend_x.matrix_basis.translation.z == pytest.approx(0.0)
    assert extend_z.matrix_basis.translation.z == pytest.approx(1.5)
    assert split.matrix_basis.translation.z == pytest.approx(3.0)


# ----------------------------------------------------------------------------
# should_flip_extend_arrow — view-aware arrow mirroring for the horizontal extend
# ----------------------------------------------------------------------------


def test_should_flip_extend_arrow_returns_true_when_origin_is_screen_right():
    """Identity view, origin at +X of the gizmo → flip."""
    from mathutils import Matrix, Vector

    from bonsai.bim.module.drawing.gizmos import should_flip_extend_arrow

    assert (
        should_flip_extend_arrow(
            gizmo_world=Vector((1.0, 0.0, 0.0)),
            reference_world=Vector((2.0, 0.0, 0.0)),
            billboard_rot=Matrix.Identity(4),
        )
        is True
    )


def test_should_flip_extend_arrow_returns_false_when_origin_is_screen_left():
    """Identity view, origin at −X of the gizmo → no flip."""
    from mathutils import Matrix, Vector

    from bonsai.bim.module.drawing.gizmos import should_flip_extend_arrow

    assert (
        should_flip_extend_arrow(
            gizmo_world=Vector((2.0, 0.0, 0.0)),
            reference_world=Vector((0.0, 0.0, 0.0)),
            billboard_rot=Matrix.Identity(4),
        )
        is False
    )


def test_should_flip_extend_arrow_holds_canonical_in_epsilon_deadband():
    """Within ``EXTEND_FLIP_EPSILON`` the helper resolves to no-flip — anti-flicker."""
    from mathutils import Matrix, Vector

    from bonsai.bim.module.drawing.gizmos import (
        EXTEND_FLIP_EPSILON,
        should_flip_extend_arrow,
    )

    tiny = EXTEND_FLIP_EPSILON * 0.5
    assert (
        should_flip_extend_arrow(
            gizmo_world=Vector((1.0, 0.0, 0.0)),
            reference_world=Vector((1.0 + tiny, 0.0, 0.0)),
            billboard_rot=Matrix.Identity(4),
        )
        is False
    )


def test_should_flip_extend_arrow_responds_to_view_rotation():
    """Rotating the billboard 180° around world Z inverts the flip decision."""
    import math

    from mathutils import Matrix, Vector

    from bonsai.bim.module.drawing.gizmos import should_flip_extend_arrow

    args = dict(gizmo_world=Vector((2.0, 0.0, 0.0)), reference_world=Vector((0.0, 0.0, 0.0)))
    # Identity view: origin screen-left → no flip.
    assert should_flip_extend_arrow(billboard_rot=Matrix.Identity(4), **args) is False
    # Rotate the camera 180° about world-Z — origin now projects to screen-right.
    rot_180_z = Matrix.Rotation(math.pi, 4, "Z")
    assert should_flip_extend_arrow(billboard_rot=rot_180_z, **args) is True


def test_cursor_gizmos_extend_x_matrix_basis_mirrors_when_flip_required():
    """Extend-X mirrors on local X when the helper signals a screen-right origin;
    extend-Z and split keep their canonical orientation."""
    import math

    from mathutils import Matrix

    rot_180_z = Matrix.Rotation(math.pi, 4, "Z")
    extend_x, extend_z, split = _run_cursor_gizmos(
        top_down=False,
        cursor_local=(1.5, 0.0, 3.5),  # above height (3.0) so extend_z doesn't Y-flip
        billboard_rot=rot_180_z,
        anchor_x=0.0,
    )
    assert extend_x.matrix_basis.col[0].x == pytest.approx(-1.0)
    assert extend_z.matrix_basis.col[1].y == pytest.approx(1.0)
    assert split.matrix_basis.col[0].x == pytest.approx(1.0)


def test_cursor_gizmos_extend_z_matrix_basis_mirrors_y_when_below_wall_height():
    """Cursor below the wall top → extend-Z arrow flips so it points down."""
    extend_x, extend_z, split = _run_cursor_gizmos(
        top_down=False,
        cursor_local=(1.0, 0.0, 1.0),  # below height (3.0)
    )
    assert extend_z.matrix_basis.col[1].y == pytest.approx(-1.0)
    assert extend_z.matrix_basis.col[0].x == pytest.approx(1.0)


def test_cursor_gizmos_extend_z_no_mirror_when_above_wall_height():
    """Cursor above the wall top → extend-Z keeps its canonical upward arrow."""
    extend_x, extend_z, split = _run_cursor_gizmos(
        top_down=False,
        cursor_local=(1.0, 0.0, 4.0),  # above height (3.0)
    )
    assert extend_z.matrix_basis.col[1].y == pytest.approx(1.0)


def test_cursor_gizmos_extend_x_points_to_origin_when_cursor_in_first_half():
    """Cursor in the wall's first half → click moves the start → arrow points at the origin."""
    extend_x, _, _ = _run_cursor_gizmos(
        top_down=False,
        cursor_local=(0.5, 0.0, 3.5),
    )
    assert extend_x.matrix_basis.col[0].x == pytest.approx(-1.0)


def test_cursor_gizmos_extend_x_points_to_end_when_cursor_in_second_half():
    """Cursor in the wall's second half → click moves the end → arrow keeps the canonical
    orientation pointing at the end."""
    extend_x, _, _ = _run_cursor_gizmos(
        top_down=False,
        cursor_local=(1.5, 0.0, 3.5),
    )
    assert extend_x.matrix_basis.col[0].x == pytest.approx(1.0)


def test_cursor_gizmos_extend_x_midpoint_matches_operator_dispatch():
    """At the exact midpoint the click moves the origin, so the arrow points at the origin too —
    pinning the visual to the operator's strict-inequality threshold."""
    extend_x, _, _ = _run_cursor_gizmos(
        top_down=False,
        cursor_local=(1.0, 0.0, 3.5),
    )
    assert extend_x.matrix_basis.col[0].x == pytest.approx(-1.0)


def test_cursor_gizmos_extend_x_cursor_side_independent_of_view_rotation():
    """Cursor-side reference selection and view-aware flip compose: same cursor side as the
    first-half scenario but with a 180° view rotation flips the arrow back to canonical."""
    import math

    from mathutils import Matrix

    extend_x, _, _ = _run_cursor_gizmos(
        top_down=False,
        cursor_local=(0.5, 0.0, 3.5),
        billboard_rot=Matrix.Rotation(math.pi, 4, "Z"),
    )
    assert extend_x.matrix_basis.col[0].x == pytest.approx(1.0)


def test_cursor_gizmos_extend_x_falls_back_to_origin_reference_when_length_zero():
    """Degenerate wall (non-positive length) keeps the historical origin reference rather than
    routing through the new cursor-side branch."""
    extend_x, _, _ = _run_cursor_gizmos(
        top_down=False,
        cursor_local=(0.0, 0.0, 3.5),
        length=0.0,
    )
    assert extend_x.matrix_basis.col[0].x == pytest.approx(1.0)


# ----------------------------------------------------------------------------
# WallGizmoPreviewDecorator._draw_cursor_split_preview — vertical cut line
# ----------------------------------------------------------------------------


_SPLIT_PREVIEW_RED = (1.0, 0.0, 0.0, 1.0)


def _run_split_preview(
    hovered,
    *,
    anchor_x=0.0,
    length=2.0,
    height=3.0,
    cursor_local=(1.0, 0.0, 0.5),
    matrix_world=None,
):
    """Drive ``_draw_cursor_split_preview`` and return ``(segments, color)``.
    Returns ``([], None)`` when no line was drawn."""
    from mathutils import Matrix, Vector

    from bonsai import tool
    from bonsai.bim.module.model import decorator as decorator_module

    mw = matrix_world if matrix_world is not None else Matrix.Identity(4)
    active_obj = SimpleNamespace(matrix_world=mw)
    geom = {"anchor_x": anchor_x, "length": length, "height": height}
    cursor = SimpleNamespace(location=mw @ Vector(cursor_local))
    context = SimpleNamespace(scene=SimpleNamespace(cursor=cursor))
    prefs = SimpleNamespace(
        decorator_color_selected=(0.0, 1.0, 0.0, 1.0),
        decorator_color_error=_SPLIT_PREVIEW_RED,
    )

    decorator = decorator_module.WallGizmoPreviewDecorator()
    captured: dict = {"segments": [], "color": None}

    def _capture_stroke(self_, ctx, segments, color):
        captured["segments"].extend(segments)
        captured["color"] = color

    patches = [
        patch.object(
            decorator_module.WallGizmoPreviewDecorator,
            "_active_layer2_wall_for_gizmo_preview",
            return_value=active_obj,
        ),
        patch.object(
            decorator_module.WallGizmoPreviewDecorator,
            "_cursor_icon_hovered",
            return_value=hovered,
        ),
        patch.object(tool.Wall, "read_geometry", return_value=geom),
        patch.object(decorator_module.WallGizmoPreviewDecorator, "_stroke", _capture_stroke),
    ]
    for p in patches:
        p.start()
    try:
        decorator._draw_cursor_split_preview(context, prefs)
    finally:
        for p in reversed(patches):
            p.stop()
    return captured["segments"], captured["color"]


def test_split_preview_draws_red_line_at_cursor_x_when_hovered():
    """In-range cursor + hovered split → one segment from base (Z=0) to top (Z=3),
    coloured with the destructive-action warning red."""
    segments, color = _run_split_preview(hovered=True, length=2.0, height=3.0, cursor_local=(1.0, 0.0, 0.5))
    assert len(segments) == 1
    bottom, top = segments[0]
    assert bottom[0] == pytest.approx(1.0)
    assert bottom[1] == pytest.approx(0.0)
    assert bottom[2] == pytest.approx(0.0)
    assert top[0] == pytest.approx(1.0)
    assert top[1] == pytest.approx(0.0)
    assert top[2] == pytest.approx(3.0)
    assert color == pytest.approx(_SPLIT_PREVIEW_RED[:3])


def test_split_preview_endpoints_follow_wall_slope():
    """Sloped wall (rotated about X): the line endpoints must ride the wall's
    local Z axis, not strict world Z. With a 90° X-rotation the wall's local Z
    aligns with world Y, so the top endpoint lands at Y=height (not Z=height)."""
    import math

    from mathutils import Matrix

    rot_x_90 = Matrix.Rotation(math.pi / 2, 4, "X")
    segments, _color = _run_split_preview(
        hovered=True,
        length=2.0,
        height=3.0,
        cursor_local=(1.0, 0.0, 0.0),
        matrix_world=rot_x_90,
    )
    assert len(segments) == 1
    bottom, top = segments[0]
    assert tuple(bottom) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert tuple(top) == pytest.approx((1.0, -3.0, 0.0), abs=1e-6)


def test_split_preview_skips_draw_when_icon_not_hovered():
    """No hover, no line."""
    segments, _color = _run_split_preview(hovered=False)
    assert segments == []


def test_split_preview_skips_draw_when_cursor_outside_wall_span():
    """Cursor outside ``[anchor_x, anchor_x + length]`` → no preview."""
    segments, _color = _run_split_preview(hovered=True, length=2.0, cursor_local=(3.5, 0.0, 0.5))
    assert segments == []


# ----------------------------------------------------------------------------
# WallGizmoPreviewDecorator._draw_cursor_extend_z_preview — new height line
# ----------------------------------------------------------------------------


def _run_extend_z_preview(
    hovered,
    *,
    anchor_x=0.0,
    length=2.0,
    height=3.0,
    cursor_local=(1.0, 0.0, 5.0),
):
    """Drive ``_draw_cursor_extend_z_preview`` and return the captured stroke
    segments. ``mw`` is Identity, so ``cursor_local`` doubles as world coords."""
    from mathutils import Matrix, Vector

    from bonsai import tool
    from bonsai.bim.module.model import decorator as decorator_module

    active_obj = SimpleNamespace(matrix_world=Matrix.Identity(4))
    geom = {"anchor_x": anchor_x, "length": length, "height": height}
    cursor = SimpleNamespace(location=Vector(cursor_local))
    context = SimpleNamespace(scene=SimpleNamespace(cursor=cursor))
    prefs = SimpleNamespace(decorator_color_selected=(0.0, 1.0, 0.0, 1.0))

    decorator = decorator_module.WallGizmoPreviewDecorator()
    captured_segments: list = []

    def _capture_stroke(self_, ctx, segments, color):
        captured_segments.extend(segments)

    patches = [
        patch.object(
            decorator_module.WallGizmoPreviewDecorator,
            "_active_layer2_wall_for_gizmo_preview",
            return_value=active_obj,
        ),
        patch.object(
            decorator_module.WallGizmoPreviewDecorator,
            "_cursor_icon_hovered",
            return_value=hovered,
        ),
        patch.object(tool.Wall, "read_geometry", return_value=geom),
        patch.object(decorator_module.WallGizmoPreviewDecorator, "_stroke", _capture_stroke),
    ]
    for p in patches:
        p.start()
    try:
        decorator._draw_cursor_extend_z_preview(context, prefs)
    finally:
        for p in reversed(patches):
            p.stop()
    return captured_segments


def test_extend_z_preview_draws_one_line_from_base_to_gizmo_when_hovered():
    """Identity matrix, gizmo at local Z=5 → segment from base (Z=0) to gizmo (Z=5)."""
    segments = _run_extend_z_preview(hovered=True, length=2.0, height=3.0, cursor_local=(1.5, 0.0, 5.0))
    assert len(segments) == 1
    bottom, top = segments[0]
    assert tuple(bottom) == pytest.approx((1.5, 0.0, 0.0))
    assert tuple(top) == pytest.approx((1.5, 0.0, 5.0))


def test_extend_z_preview_skips_draw_when_icon_not_hovered():
    segments = _run_extend_z_preview(hovered=False)
    assert segments == []


def test_extend_z_preview_skips_draw_when_cursor_below_wall_base():
    """Operator gate: new height must be > 0."""
    segments = _run_extend_z_preview(hovered=True, cursor_local=(1.5, 0.0, 0.0))
    assert segments == []


# ----------------------------------------------------------------------------
# WallGizmoPreviewDecorator._extended_wall_index — hover-discrimination map
# ----------------------------------------------------------------------------
#
# These tests pin the floor-line index returned for the wall the default-
# direction Extend operator would actually move. The decorator uses this to
# light up only one of the two floor-plane preview strokes on Extend hover
# (the other stays at the default color), giving the user a clear "this is
# the wall I'm about to extend" cue without a separate label.


def test_extended_wall_index_returns_other_when_active_is_first_selected():
    from bonsai.bim.module.model.decorator import WallGizmoPreviewDecorator

    wall_a = SimpleNamespace()
    wall_b = SimpleNamespace()
    context = SimpleNamespace(active_object=wall_a)
    # selected[0] = wall_a is active → the OTHER wall (selected[1]) is the one
    # the default-direction operator would extend → index 1.
    assert WallGizmoPreviewDecorator._extended_wall_index(context, [wall_a, wall_b]) == 1


def test_extended_wall_index_returns_other_when_active_is_second_selected():
    from bonsai.bim.module.model.decorator import WallGizmoPreviewDecorator

    wall_a = SimpleNamespace()
    wall_b = SimpleNamespace()
    context = SimpleNamespace(active_object=wall_b)
    # Symmetric: active = selected[1] → extend target = selected[0] → index 0.
    assert WallGizmoPreviewDecorator._extended_wall_index(context, [wall_a, wall_b]) == 0


def test_extended_wall_index_returns_none_when_active_is_not_in_selection():
    """Edge case: an external object is active while two walls are selected.
    The decorator can't tell which wall would be "extended", so the helper
    returns ``None`` and the caller falls back to drawing both lines in the
    default colour — no spurious highlight."""
    from bonsai.bim.module.model.decorator import WallGizmoPreviewDecorator

    wall_a = SimpleNamespace()
    wall_b = SimpleNamespace()
    other = SimpleNamespace()
    context = SimpleNamespace(active_object=other)
    assert WallGizmoPreviewDecorator._extended_wall_index(context, [wall_a, wall_b]) is None


# ----------------------------------------------------------------------------
# WallGizmoPreviewDecorator._lookup_active_instance — per-region routing
# ----------------------------------------------------------------------------
#
# The decorator stores a weakref to each region's live ``GizmoGroup`` instance
# keyed by ``region.as_pointer()``. The lookup helper is what routes hover-
# state reads to the right viewport when the user has multiple 3D viewports
# open. These tests pin the four observable branches: hit-in-region, miss-in-
# region (different pointer), no region on the context, dead weakref.
#
# Stubbed: the gizmo class is a bare namespace with a populated
# ``_active_instances`` dict — the helper doesn't care about the class identity
# beyond that attribute, so the stub keeps the test independent of any future
# refactor of GizmoWallJoinIntersection or GizmoWallEdition.


def _make_region(pointer_value):
    return SimpleNamespace(as_pointer=lambda v=pointer_value: v)


class _StubGizmoInstance:
    """Stub stand-in for a registered ``GizmoGroup`` instance. A bare class
    (not ``SimpleNamespace``) because ``weakref.ref`` rejects namespace
    objects but accepts any class that doesn't define ``__slots__`` without
    ``__weakref__``."""


def test_lookup_active_instance_returns_instance_for_matching_region():
    import weakref

    from bonsai.bim.module.model.decorator import WallGizmoPreviewDecorator

    instance = _StubGizmoInstance()
    gizmo_cls = SimpleNamespace(_active_instances={42: weakref.ref(instance)})
    context = SimpleNamespace(region=_make_region(42))
    assert WallGizmoPreviewDecorator._lookup_active_instance(gizmo_cls, context) is instance


def test_lookup_active_instance_returns_none_for_unknown_region():
    """Multi-viewport routing: hovering in viewport B must not surface the
    weakref registered for viewport A. Pinned by pointing the context at a
    region pointer the dict doesn't have."""
    import weakref

    from bonsai.bim.module.model.decorator import WallGizmoPreviewDecorator

    instance = _StubGizmoInstance()
    gizmo_cls = SimpleNamespace(_active_instances={42: weakref.ref(instance)})
    context = SimpleNamespace(region=_make_region(99))
    assert WallGizmoPreviewDecorator._lookup_active_instance(gizmo_cls, context) is None


def test_lookup_active_instance_returns_none_when_context_has_no_region():
    """``context.region`` can be missing or ``None`` outside of an active
    redraw (e.g. when the install context was a restricted Blender context).
    The helper must degrade quietly rather than raise ``AttributeError``."""
    from bonsai.bim.module.model.decorator import WallGizmoPreviewDecorator

    gizmo_cls = SimpleNamespace(_active_instances={})
    context = SimpleNamespace(region=None)
    assert WallGizmoPreviewDecorator._lookup_active_instance(gizmo_cls, context) is None


def test_lookup_active_instance_returns_none_for_dead_weakref():
    """When Blender destroys a GizmoGroup (poll → False), its weakref's
    referent becomes ``None`` but the dict entry stays. The helper must treat
    a dead weakref the same as a missing entry — otherwise the decorator
    would try to read ``is_highlight`` off a freed instance and crash."""
    import gc
    import weakref

    from bonsai.bim.module.model.decorator import WallGizmoPreviewDecorator

    # Build a weakref that resolves to None: create the instance inside a
    # nested scope, return only the weakref, and force a collection cycle so
    # the referent is reaped before the assertion.
    def _dead_ref():
        return weakref.ref(_StubGizmoInstance())

    dead = _dead_ref()
    gc.collect()
    assert dead() is None  # precondition: the weakref is actually dead
    gizmo_cls = SimpleNamespace(_active_instances={42: dead})
    context = SimpleNamespace(region=_make_region(42))
    assert WallGizmoPreviewDecorator._lookup_active_instance(gizmo_cls, context) is None


# ----------------------------------------------------------------------------
# _position_cursor_anchored_gizmos — split-gizmo slope correction
# ----------------------------------------------------------------------------
#
# ``props.height`` is the *vertical* (world-Z) wall height. When the wall is
# tilted around its local X axis by ``props.x_angle``, feeding ``props.height``
# directly as a wall-local Z and rotating by ``mw`` lands the split icon at
# world Z = cos(x_angle) * props.height — visibly below the slanted top edge.
# The cursor-gizmo code routes through ``core.extrusion_depth_from_vertical_height``
# so the world Z of the icon matches ``props.height`` regardless of slope.


def _drive_update_cursor_gizmos(*, x_angle, height):
    """Invoke ``_position_cursor_anchored_gizmos`` with the minimal stub
    and a single-candidate (scissors-only) gizmo prefs config, so the assertion
    isolates split-gizmo placement from the cursor-stack bumping cascade."""
    from mathutils import Matrix, Vector

    from bonsai import tool
    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model import wall as wall_module

    split_gizmo = SimpleNamespace(hide=True, matrix_basis=None)
    extend_x_gizmo = SimpleNamespace(hide=True, matrix_basis=None)
    extend_z_gizmo = SimpleNamespace(hide=True, matrix_basis=None)
    self_stub = SimpleNamespace(
        split_gizmo=split_gizmo,
        extend_x_gizmo=extend_x_gizmo,
        extend_z_gizmo=extend_z_gizmo,
        _frame_billboard_rot=Matrix.Identity(4),
        CURSOR_STACK_OFFSET=wall_module.GizmoWallEdition.CURSOR_STACK_OFFSET,
        is_gizmo_hidden_by_modal=lambda gz: False,
    )

    props = SimpleNamespace(anchor_x=0.0, length=4.0, height=height, x_angle=x_angle)
    mw = Matrix.Rotation(x_angle, 4, "X")  # wall at origin, tilted around local X
    cursor_world = Vector((2.0, 0.0, 0.0))  # mid-wall along its length, on the ground
    context = SimpleNamespace(scene=SimpleNamespace(cursor=SimpleNamespace(location=cursor_world)))

    patches = [
        patch.object(tool.Blender, "is_view_top_down", return_value=False),
        patch.object(
            gizmo_module,
            "billboarded_at",
            side_effect=lambda pos, rot, scale=0.5: Matrix.Translation(pos),
        ),
    ]
    for p in patches:
        p.start()
    try:
        wall_module._position_cursor_anchored_gizmos(self_stub, context, mw, props)
    finally:
        for p in patches:
            p.stop()
    return split_gizmo


def test_update_cursor_gizmos_split_world_z_matches_height_for_vertical_wall():
    """Baseline: vertical wall (x_angle=0) — slope correction is the identity,
    so the icon's world Z must still equal props.height."""
    import math

    split = _drive_update_cursor_gizmos(x_angle=0.0, height=3.0)
    assert split.hide is False
    assert split.matrix_basis.translation.z == pytest.approx(3.0)
    # No lean for a vertical wall — the icon sits on the wall plane (Y=0).
    assert split.matrix_basis.translation.y == pytest.approx(0.0)
    # Sanity check on the local-Z conversion: at x_angle=0, cos=1 → identity.
    assert math.isclose(math.cos(0.0), 1.0)


def test_update_cursor_gizmos_split_world_z_matches_height_for_sloped_wall():
    """For a sloped wall, the icon's world Z must equal props.height (the
    vertical height), not cos(x_angle) * props.height (the pre-fix value)."""
    import math

    x_angle = math.radians(28)
    split = _drive_update_cursor_gizmos(x_angle=x_angle, height=3.0)
    assert split.hide is False
    # World Z lands at the actual slanted-top elevation == props.height.
    assert split.matrix_basis.translation.z == pytest.approx(3.0)
    # Pre-fix value (the regression we are guarding against):
    assert split.matrix_basis.translation.z != pytest.approx(3.0 * math.cos(x_angle), rel=1e-3)


# ----------------------------------------------------------------------------
# Hit-shape vs stack-spacing invariant — bbox hitboxes can't overlap siblings
# ----------------------------------------------------------------------------
#
# The icons stacked vertically in GizmoWallJoinIntersection (fillet / wall-corner /
# wall-tee) sit ICON_STACK_OFFSET_Y apart. Their glyph tris extend across a Y range
# that exceeds that spacing, so a 2D-bounding-box hit shape would overlap the
# next icon's hit area and let Blender's reverse-iter hit-test route clicks to
# the wrong icon. This test pins the resolution: those classes opt out of the
# bbox hit shape AND, defensively, if anyone flips them back, the bbox extent
# must fit inside the stack spacing budget.


def test_wall_junction_icons_opt_out_of_bbox_hit_shape():
    """The three wall-junction icons must keep ``hit_uses_bbox = False`` because
    their stack spacing in ``GizmoWallJoinIntersection`` is smaller than their
    glyph bbox; the full-bbox hit would let the topmost-iter icon steal clicks
    from the icons below it."""
    from bonsai.bim.module.drawing.gizmos import (
        GizmoFillet,
        GizmoWallCornerIcon,
        GizmoWallTeeIcon,
    )

    for cls in (GizmoFillet, GizmoWallCornerIcon, GizmoWallTeeIcon):
        assert cls.hit_uses_bbox is False, (
            f"{cls.__name__} sits in the wall-junction stack at ICON_STACK_OFFSET_Y "
            f"spacing; flipping hit_uses_bbox to True would let sibling bboxes overlap "
            f"and misroute clicks. Either keep the opt-out or bump ICON_STACK_OFFSET_Y "
            f"to fit the glyph bbox + outline padding."
        )


def test_wall_tee_icon_branching_bar_is_centered_not_bottom_anchored():
    """The side-T (⊣) orientation places the branching (horizontal) bar at the
    icon's midline so the vertical 'through' bar extends equally above and
    below it. Asserts the left-edge vertices (where the branching bar
    reaches) sit above the icon's midpoint."""
    from bonsai.bim.module.drawing.gizmos import WALL_TEE_TRIS_DEFAULT

    # Left edge of the branching bar reaches the icon's left bbox edge (x ≈ -0.45).
    left_edge_ys = [v[1] for v in WALL_TEE_TRIS_DEFAULT if v[0] <= -0.40]
    assert left_edge_ys, "no tris reach the left edge — icon has no branching bar"
    assert min(left_edge_ys) > 0.0, "branching bar must sit above the icon midline (y=0) for the ⊣ orientation"


def test_wall_junction_icon_glyph_bbox_exceeds_stack_offset():
    """Documents the geometry that motivates the opt-out: each wall-junction icon's
    glyph extends >0.6 local units in Y (asymmetric: bars reach to +0.45 and -0.28),
    while ICON_STACK_OFFSET_Y is 0.4 — so bbox+pad hit shapes would overlap each
    other by ~0.3 local units. If either side of this inequality changes, the
    opt-out decision needs re-evaluation."""
    from bonsai.bim.module.drawing.gizmos import (
        _OUTLINE_DEFAULT_WIDTH,
        FILLET_TRIS_DEFAULT,
        WALL_CORNER_TRIS_DEFAULT,
        WALL_TEE_TRIS_DEFAULT,
    )
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    stack_offset = GizmoWallJoinIntersection.ICON_STACK_OFFSET_Y
    for tris in (FILLET_TRIS_DEFAULT, WALL_CORNER_TRIS_DEFAULT, WALL_TEE_TRIS_DEFAULT):
        ys = [v[1] for v in tris]
        bbox_height_with_pad = (max(ys) - min(ys)) + 2 * _OUTLINE_DEFAULT_WIDTH
        assert bbox_height_with_pad > stack_offset, (
            f"bbox+pad height ({bbox_height_with_pad}) fits inside stack offset "
            f"({stack_offset}) — the wall-junction icons no longer need to opt out "
            f"of hit_uses_bbox; the opt-out can be removed."
        )
