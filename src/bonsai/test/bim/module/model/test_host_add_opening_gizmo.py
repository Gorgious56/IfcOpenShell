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

"""Poll + positioning tests for ``GizmoHostAddOpening``.

The gizmo dispatches on element type: walls keep the existing axis-projection
math, while LAYER3 hosts (slabs, roofs) use a world-Z face bias derived from
the void object's elevation. Each branch is exercised independently with
mocks so the per-type contract is pinned without launching a full Blender
modelling session."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from mathutils import Matrix, Vector

pytestmark = pytest.mark.model


# ---------------------------------------------------------------------------
# poll() — entry gate per host type and per co-selection shape
# ---------------------------------------------------------------------------


def _make_context(active, selected):
    return SimpleNamespace(active_object=active, selected_objects=list(selected))


def _patch_for_poll(prefs_on, selected, active_kind, other_kind):
    """Build a stack of patches that simulates a single poll() invocation.

    ``active_kind`` / ``other_kind`` accept ``"wall"``, ``"slab"``, ``"roof"``,
    ``"plain"`` (non-host IFC element), ``"mesh"`` (no IFC entity), or
    ``None`` (object outside the selection set). The patches drive
    ``tool.Ifc.get_entity`` and the three host predicates accordingly."""
    from bonsai import tool

    # SimpleNamespace, not bare object(): the host sentinels need a settable
    # ``HasOpenings`` attribute so the poll's ``hasattr`` branch can hit.
    sentinels = {kind: SimpleNamespace() for kind in ("wall", "slab", "roof", "plain")}

    def entity_for(kind):
        if kind in (None, "mesh"):
            return None
        return sentinels[kind]

    entity_map = {}
    if len(selected) >= 1:
        entity_map[id(selected[0])] = entity_for(active_kind)
    if len(selected) >= 2:
        entity_map[id(selected[1])] = entity_for(other_kind)

    def get_entity(obj):
        return entity_map.get(id(obj))

    def is_wall(element):
        return element is sentinels["wall"]

    def is_slab(element):
        return element is sentinels["slab"]

    def is_roof(element):
        return element is sentinels["roof"]

    # ``HasOpenings`` must look real for the wall/slab/roof sentinels but be
    # absent on the "plain" sentinel so the corresponding poll branch can
    # reject it. SimpleNamespace doesn't have HasOpenings unless we set it.
    sentinels["wall"].HasOpenings = ()
    sentinels["slab"].HasOpenings = ()
    sentinels["roof"].HasOpenings = ()
    # sentinels["plain"] intentionally lacks HasOpenings

    return [
        patch.object(tool.Blender, "are_viewport_gizmos_enabled", return_value=prefs_on),
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.Blender.Modifier, "is_wall", side_effect=is_wall),
        patch.object(tool.Blender.Modifier, "is_slab", side_effect=is_slab),
        patch.object(tool.Blender.Modifier, "is_roof", side_effect=is_roof),
    ]


def _run_poll(prefs_on=True, n_selected=2, active_in_selected=True, active_kind="wall", other_kind="mesh"):
    from bonsai.bim.module.model.host_add_opening_gizmo import GizmoHostAddOpening

    selected = [object() for _ in range(n_selected)]
    active = selected[0] if (active_in_selected and selected) else object()

    patches = _patch_for_poll(prefs_on, selected, active_kind, other_kind)
    for p in patches:
        p.start()
    try:
        return GizmoHostAddOpening.poll(_make_context(active, selected))
    finally:
        for p in patches:
            p.stop()


@pytest.mark.parametrize("host_kind", ["wall", "slab", "roof"])
def test_poll_accepts_each_host_with_a_plain_mesh_void(host_kind):
    assert _run_poll(active_kind=host_kind, other_kind="mesh") is True


def test_poll_rejects_when_gizmo_toggle_off():
    assert _run_poll(prefs_on=False) is False


def test_poll_rejects_when_selection_count_is_not_two():
    assert _run_poll(n_selected=1) is False
    assert _run_poll(n_selected=3) is False


def test_poll_rejects_when_active_is_not_in_selection():
    assert _run_poll(active_in_selected=False) is False


def test_poll_rejects_when_active_has_no_ifc_entity():
    assert _run_poll(active_kind="mesh") is False


def test_poll_rejects_when_active_is_not_a_host():
    # "plain" sentinel is recognised as an IFC entity but is none of wall/slab/roof.
    assert _run_poll(active_kind="plain") is False


@pytest.mark.parametrize(
    "active_kind,other_kind",
    [
        ("wall", "wall"),  # wall-join gizmo owns this
        ("slab", "slab"),  # future slab-edit gizmo
        ("roof", "roof"),
        ("wall", "slab"),  # extend-vertically gizmo overlaps with this
        ("slab", "wall"),
        ("roof", "wall"),
    ],
)
def test_poll_rejects_host_host_pairs(active_kind, other_kind):
    """Host + host pairings must be suppressed so the icon never stacks with
    the wall-join / extend-vertical / future slab-edit gizmos."""
    assert _run_poll(active_kind=active_kind, other_kind=other_kind) is False


def test_poll_rejects_active_host_without_has_openings():
    # Real-world equivalent: an IFC class that the active schema strips
    # ``HasOpenings`` from (e.g., a non-element subtype). The active sentinel
    # is set up to be ``is_wall``-true but with no HasOpenings attribute.
    from bonsai import tool
    from bonsai.bim.module.model.host_add_opening_gizmo import GizmoHostAddOpening

    selected = [object(), object()]
    active = selected[0]
    host_sentinel = object()  # No HasOpenings attribute
    other_sentinel = None

    patches = [
        patch.object(tool.Blender, "are_viewport_gizmos_enabled", return_value=True),
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(
            tool.Ifc, "get_entity", side_effect=lambda o: host_sentinel if o is selected[0] else other_sentinel
        ),
        patch.object(tool.Blender.Modifier, "is_wall", side_effect=lambda e: e is host_sentinel),
        patch.object(tool.Blender.Modifier, "is_slab", return_value=False),
        patch.object(tool.Blender.Modifier, "is_roof", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        assert GizmoHostAddOpening.poll(_make_context(active, selected)) is False
    finally:
        for p in patches:
            p.stop()


# ---------------------------------------------------------------------------
# position_gizmos() — branch dispatch and per-branch anchor math
# ---------------------------------------------------------------------------


def _run_position_wall_branch(*, other_translation=(0.5, 0.0, 0.0), top_down=True):
    """Drive the wall branch with stub IFC reads, returning the icon's
    matrix_basis translation."""
    from bonsai import tool
    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model import host_add_opening_gizmo as host_mod
    from bonsai.bim.module.model.host_add_opening_gizmo import GizmoHostAddOpening

    geom = {"anchor_x": 0.0, "length": 2.0, "height": 3.0, "offset": 0.0, "thickness": 0.2}
    wall_element = object()
    active = SimpleNamespace(matrix_world=Matrix.Identity(4))
    other = SimpleNamespace(matrix_world=Matrix.Translation(Vector(other_translation)))
    selected = [active, other]
    context = SimpleNamespace(active_object=active)
    icon = SimpleNamespace(matrix_basis=None, hide=True)
    self_stub = SimpleNamespace(add_opening_icon=icon)

    patches = [
        patch.object(tool.Blender, "get_selected_objects", return_value=selected),
        patch.object(tool.Ifc, "get_entity", return_value=wall_element),
        patch.object(tool.Blender.Modifier, "is_wall", return_value=True),
        patch.object(host_mod, "get_wall_geom_cached", return_value=geom),
        patch.object(host_mod, "wall_camera_facing_icon_y", return_value=0.0),
        patch.object(tool.Blender, "is_view_top_down", return_value=top_down),
        patch.object(tool.Blender, "get_screen_up_world", return_value=Vector((0.0, 1.0, 0.0))),
        patch.object(gizmo_module, "get_billboard_rotation", return_value=Matrix.Identity(4)),
        patch.object(gizmo_module, "billboarded_at", side_effect=lambda pos, rot, scale=0.5: Matrix.Translation(pos)),
    ]
    for p in patches:
        p.start()
    try:
        GizmoHostAddOpening.position_gizmos(self_stub, context)
    finally:
        for p in patches:
            p.stop()
    return icon.matrix_basis.translation


def test_wall_branch_drops_height_lift_in_top_down_view():
    """Regression: in plan view the wall branch must collapse the wall-top
    Z lift and offset along screen-up instead — pin from the prior
    GizmoWallAddOpening behaviour so the refactor preserves it."""
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    pos = _run_position_wall_branch(top_down=True)
    assert pos.z == pytest.approx(0.0)
    assert pos.y == pytest.approx(BaseParametricGizmoGroup.SCREEN_STACK_OFFSET)


def _run_position_layer3_branch(*, host_world_z_range=(0.0, 0.2), other_z=1.0, other_xy=(0.7, 0.4), is_wall=False):
    """Drive the LAYER3 (slab/roof) branch and return the icon translation.

    ``host_world_z_range`` sets the world-Z extents of the host's bounding box
    (the gizmo picks top vs bottom by comparing the void's Z to the box
    midpoint). ``is_wall`` keeps a single helper for both branches by
    flipping the dispatch predicate."""
    from bonsai import tool
    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model.host_add_opening_gizmo import GizmoHostAddOpening

    z_min, z_max = host_world_z_range
    # bound_box returns 8 corners in local space; we only need their world-Z
    # range to drive the branch, so fix XY at zero and vary Z.
    local_corners = [(0.0, 0.0, z_min), (0.0, 0.0, z_max)] * 4
    host_obj = SimpleNamespace(matrix_world=Matrix.Identity(4), bound_box=local_corners)
    other = SimpleNamespace(matrix_world=Matrix.Translation(Vector((other_xy[0], other_xy[1], other_z))))
    selected = [host_obj, other]
    context = SimpleNamespace(active_object=host_obj)
    icon = SimpleNamespace(matrix_basis=None, hide=True)
    self_stub = SimpleNamespace(add_opening_icon=icon)

    host_element = object()
    patches = [
        patch.object(tool.Blender, "get_selected_objects", return_value=selected),
        patch.object(tool.Ifc, "get_entity", return_value=host_element),
        patch.object(tool.Blender.Modifier, "is_wall", return_value=is_wall),
        patch.object(gizmo_module, "get_billboard_rotation", return_value=Matrix.Identity(4)),
        patch.object(gizmo_module, "billboarded_at", side_effect=lambda pos, rot, scale=0.5: Matrix.Translation(pos)),
    ]
    for p in patches:
        p.start()
    try:
        GizmoHostAddOpening.position_gizmos(self_stub, context)
    finally:
        for p in patches:
            p.stop()
    return icon.matrix_basis.translation


def test_layer3_branch_places_icon_above_when_void_is_above():
    """Void above the slab midplane → icon sits above the top face (with the
    ICON_Z_OFFSET lift) at the void's world XY."""
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    pos = _run_position_layer3_branch(host_world_z_range=(0.0, 0.2), other_z=1.0, other_xy=(0.7, 0.4))
    assert pos.x == pytest.approx(0.7)
    assert pos.y == pytest.approx(0.4)
    assert pos.z == pytest.approx(0.2 + BaseParametricGizmoGroup.ICON_Z_OFFSET)


def test_layer3_branch_places_icon_below_when_void_is_below():
    """Void below the slab midplane → icon sits below the bottom face."""
    from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup

    pos = _run_position_layer3_branch(host_world_z_range=(0.0, 0.2), other_z=-1.0, other_xy=(0.7, 0.4))
    assert pos.x == pytest.approx(0.7)
    assert pos.y == pytest.approx(0.4)
    assert pos.z == pytest.approx(0.0 - BaseParametricGizmoGroup.ICON_Z_OFFSET)


# ---------------------------------------------------------------------------
# is_supported_host() — predicate totality
# ---------------------------------------------------------------------------


def test_is_supported_host_returns_false_for_none():
    """Total predicate: ``None`` short-circuits to False without raising."""
    from bonsai.bim.module.model.host_add_opening_gizmo import is_supported_host

    assert is_supported_host(None) is False
