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

"""Unit tests for the single-wall unjoin gizmo (``GizmoWallUnjoinSingle``) and
the underlying ``UnjoinWallPathConnection`` operator.

Three sections:

- ``poll()`` gates — exclusively-one-wall selection, LAYER2-only, gizmo prefs
  toggle. The mutual-exclusion contract with the two-wall join gizmo (both
  groups never poll True for the same selection size) is pinned alongside the
  two-wall poll tests, not here.
- ``position_gizmos()`` — per-connection icon placement, including the T-junction
  (``ATPATH``) case and the per-icon ``other_wall_guid`` binding that keeps
  click dispatch surgical.
- ``UnjoinWallPathConnection._perform`` — bidirectional inverse-walk of
  ``ConnectedTo`` / ``ConnectedFrom``, post-mutation rebuild of both walls,
  recovery report when ``recreate_wall`` raises, and the missing-partner
  error path."""

from types import SimpleNamespace
from unittest.mock import patch

import bpy
import pytest

pytestmark = pytest.mark.wall


# ----------------------------------------------------------------------------
# GizmoWallUnjoinSingle.poll() — single-wall unjoin gizmo gates
# ----------------------------------------------------------------------------


def _run_unjoin_single_poll(*, prefs_on, selection_len, is_wall, usage_type, is_fillet_corner=False):
    """Drive ``GizmoWallUnjoinSingle.poll()`` against one stubbed selection state.

    ``is_wall`` here stands in for the looser ``is_path_connectable_wall`` gate
    the poll uses — True for LAYER2 walls and for fillet-corner walls. The
    ``is_fillet_corner`` flag distinguishes the two so non-LAYER2 + non-fillet
    rejection can still be pinned."""
    from bonsai import tool
    from bonsai.bim.module.model.wall import GizmoWallUnjoinSingle

    prefs = SimpleNamespace(gizmos=SimpleNamespace(draw_gizmos_in_3d_viewport=prefs_on))
    selected = [object() for _ in range(selection_len)]
    element = object() if selection_len else None

    def get_entity(obj):
        return element if (selected and obj is selected[0]) else None

    active_obj = selected[0] if selected else None
    patches = [
        patch.object(tool.Blender, "get_addon_preferences", return_value=prefs),
        patch.object(tool.Blender, "get_active_object", return_value=active_obj),
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.Parametric, "is_path_connectable_wall", return_value=is_wall or is_fillet_corner),
        patch.object(tool.Model, "get_usage_type", return_value=usage_type),
    ]
    for p in patches:
        p.start()
    try:
        return GizmoWallUnjoinSingle.poll(SimpleNamespace(scene=SimpleNamespace()))
    finally:
        for p in patches:
            p.stop()


def test_unjoin_single_poll_accepts_one_layer2_wall():
    assert _run_unjoin_single_poll(prefs_on=True, selection_len=1, is_wall=True, usage_type="LAYER2") is True


def test_unjoin_single_poll_rejects_zero_selection():
    # Mutual-exclusion sanity check: 0 selected → no gizmo.
    assert _run_unjoin_single_poll(prefs_on=True, selection_len=0, is_wall=True, usage_type="LAYER2") is False


def test_unjoin_single_poll_rejects_two_selection():
    # Critical: with 2 walls selected, `GizmoWallJoinIntersection` runs instead.
    # If both groups polled True on len==2 the user would see double-stacked icons.
    assert _run_unjoin_single_poll(prefs_on=True, selection_len=2, is_wall=True, usage_type="LAYER2") is False


def test_unjoin_single_poll_rejects_non_wall_element():
    assert _run_unjoin_single_poll(prefs_on=True, selection_len=1, is_wall=False, usage_type="LAYER2") is False


def test_unjoin_single_poll_rejects_non_layer2_wall():
    # LAYER2 filtering happens inside tool.Parametric.is_wall (it returns False for
    # non-LAYER2 walls), so the poll's reliance on is_wall is what enforces the contract.
    # Mock production-accurately: is_wall=False for LAYER3 — the poll then rejects.
    assert _run_unjoin_single_poll(prefs_on=True, selection_len=1, is_wall=False, usage_type="LAYER3") is False


def test_unjoin_single_poll_rejects_when_gizmo_toggle_off():
    assert _run_unjoin_single_poll(prefs_on=False, selection_len=1, is_wall=True, usage_type="LAYER2") is False


def test_unjoin_single_poll_accepts_fillet_corner_wall():
    """A fillet-corner wall has no LAYER2 material usage by construction but
    still owns its two path connections to the straight neighbours. The poll
    must surface the unjoin gizmos for it; otherwise the user has no way to
    disconnect the fillet from either side."""
    assert (
        _run_unjoin_single_poll(
            prefs_on=True,
            selection_len=1,
            is_wall=False,
            usage_type=None,
            is_fillet_corner=True,
        )
        is True
    )


# ----------------------------------------------------------------------------
# GizmoWallUnjoinSingle.position_gizmos() — per-connection icon placement
# ----------------------------------------------------------------------------


def _run_unjoin_single_position(connections, *, pool_size=8, self_seg=((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))):
    """Drive ``GizmoWallUnjoinSingle.position_gizmos()`` with a stubbed connection set.

    ``connections`` is a list of ``(other_seg, self_conn_type, other_conn_type)``
    tuples — one per IfcRelConnectsPathElements the test wants to simulate. Returns
    the stub ``self`` so the caller can assert on each pool icon's ``hide`` and
    ``matrix_basis.translation`` state.
    """
    from mathutils import Matrix, Vector

    from bonsai import tool
    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model import wall as wall_module

    self_obj = SimpleNamespace()
    self_elem = object()

    # Each connection materialises one (other_obj, other_elem, other_seg) trio.
    other_objs = [SimpleNamespace() for _ in connections]
    other_elems = [SimpleNamespace(GlobalId=f"_test_other_guid_{i}") for i in range(len(connections))]
    other_segs = [(Vector(c[0][0]), Vector(c[0][1])) for c in connections]

    def get_entity(obj):
        if obj is self_obj:
            return self_elem
        for o, e in zip(other_objs, other_elems):
            if o is obj:
                return e
        return None

    def get_object(elem):
        for o, e in zip(other_objs, other_elems):
            if e is elem:
                return o
        return None

    def get_wall_geom_cached(group, obj):
        # Stub: return a non-None dict so `position_gizmos` proceeds past the guard.
        return {"placeholder": True}

    def axis_world_segment(obj, geom):
        if obj is self_obj:
            return (Vector(self_seg[0]), Vector(self_seg[1]))
        for o, s in zip(other_objs, other_segs):
            if o is obj:
                return s
        raise AssertionError("Unexpected obj in axis_world_segment stub")

    iter_returns = [(other_elems[i], c[1], c[2]) for i, c in enumerate(connections)]

    # `target_set_operator` is called ONCE per icon at setup-time, then the returned
    # OperatorProperties handles are stashed on the gizmo group. `position_gizmos`
    # only mutates the stashed handles' properties — it never re-calls
    # ``target_set_operator``. Tests inspect ``unjoin_op_props[i].other_wall_guid``
    # to verify the per-icon binding got the right partner.
    icons = [SimpleNamespace(hide=True, matrix_basis=None) for _ in range(pool_size)]
    op_props = [SimpleNamespace(other_wall_guid=None) for _ in range(pool_size)]
    self_stub = SimpleNamespace(unjoin_icons=icons, unjoin_op_props=op_props, POOL_SIZE=pool_size)

    patches = [
        patch.object(tool.Blender, "get_selected_objects", return_value=[self_obj]),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.Ifc, "get_object", side_effect=get_object),
        patch.object(wall_module, "get_wall_geom_cached", side_effect=get_wall_geom_cached),
        patch.object(wall_module, "_wall_axis_world_segment_from_geom", side_effect=axis_world_segment),
        patch.object(wall_module, "_iter_path_connections", return_value=iter_returns),
        patch.object(gizmo_module, "get_billboard_rotation", return_value=Matrix.Identity(4)),
        patch.object(gizmo_module, "billboarded_at", side_effect=lambda pos, rot, scale=0.5: Matrix.Translation(pos)),
    ]
    for p in patches:
        p.start()
    try:
        wall_module.GizmoWallUnjoinSingle.position_gizmos(self_stub, SimpleNamespace())
    finally:
        for p in patches:
            p.stop()
    return self_stub


def test_unjoin_single_position_no_connections_hides_all_icons():
    self_stub = _run_unjoin_single_position(connections=[])
    for icon in self_stub.unjoin_icons:
        assert icon.hide is True


def test_unjoin_single_position_atstart_places_at_self_start():
    # Wall A from (0,0,0) to (5,0,0); partner ends at A's ATSTART endpoint.
    self_stub = _run_unjoin_single_position(
        connections=[(((0.0, 0.0, 0.0), (0.0, 3.0, 0.0)), "ATSTART", "ATSTART")],
    )
    visible = [icon for icon in self_stub.unjoin_icons if not icon.hide]
    assert len(visible) == 1
    pos = visible[0].matrix_basis.translation
    assert pos.x == pytest.approx(0.0)
    assert pos.y == pytest.approx(0.0)


def test_unjoin_single_position_atstart_and_atend_show_two_icons():
    # Classic "wall joined at both ends" — the 2-max claim's canonical case.
    self_stub = _run_unjoin_single_position(
        connections=[
            (((0.0, 0.0, 0.0), (0.0, 3.0, 0.0)), "ATSTART", "ATSTART"),
            (((5.0, 0.0, 0.0), (5.0, 3.0, 0.0)), "ATEND", "ATSTART"),
        ],
    )
    visible_positions = [icon.matrix_basis.translation for icon in self_stub.unjoin_icons if not icon.hide]
    assert len(visible_positions) == 2
    xs = sorted(p.x for p in visible_positions)
    assert xs[0] == pytest.approx(0.0)
    assert xs[1] == pytest.approx(5.0)


def test_unjoin_single_position_atpath_t_junction_places_at_partner_endpoint():
    # T-junction: selected wall is the through-wall (ATPATH); partner ends at
    # mid-path (2.5, 0, 0). The gizmo must sit at the T point, not at one of
    # self's endpoints — that's the failure mode of using
    # `closest_endpoint_midpoint` for ATPATH connections.
    self_stub = _run_unjoin_single_position(
        connections=[(((2.5, 0.0, 0.0), (2.5, 3.0, 0.0)), "ATPATH", "ATSTART")],
    )
    visible = [icon for icon in self_stub.unjoin_icons if not icon.hide]
    assert len(visible) == 1
    pos = visible[0].matrix_basis.translation
    assert pos.x == pytest.approx(2.5)
    assert pos.y == pytest.approx(0.0)


def test_unjoin_single_position_per_icon_operator_binding_uses_partner_guid():
    # Each visible icon must have its own ``other_wall_guid`` set so a click
    # disconnects only that pair. If the binding leaked across icons (e.g. all
    # ended up with the last partner's GlobalId) the surgical promise breaks.
    # GlobalId (not Blender object name) keeps the binding robust against
    # renames between dispatch and execute.
    from mathutils import Matrix, Vector

    from bonsai import tool
    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model import wall as wall_module

    self_obj = SimpleNamespace()
    self_elem = object()
    partner_objs = [SimpleNamespace(name="WallA"), SimpleNamespace(name="WallB")]
    partner_elems = [SimpleNamespace(GlobalId="_test_guid_A"), SimpleNamespace(GlobalId="_test_guid_B")]
    partner_segs = [
        (Vector((0.0, 0.0, 0.0)), Vector((0.0, 3.0, 0.0))),
        (Vector((5.0, 0.0, 0.0)), Vector((5.0, 3.0, 0.0))),
    ]

    def get_entity(obj):
        if obj is self_obj:
            return self_elem
        for o, e in zip(partner_objs, partner_elems):
            if o is obj:
                return e
        return None

    def get_object(elem):
        for o, e in zip(partner_objs, partner_elems):
            if e is elem:
                return o
        return None

    def axis_world_segment(obj, geom):
        if obj is self_obj:
            return (Vector((0.0, 0.0, 0.0)), Vector((5.0, 0.0, 0.0)))
        for o, s in zip(partner_objs, partner_segs):
            if o is obj:
                return s
        raise AssertionError("Unexpected obj")

    iter_returns = [
        (partner_elems[0], "ATSTART", "ATSTART"),
        (partner_elems[1], "ATEND", "ATSTART"),
    ]

    icons = [SimpleNamespace(hide=True, matrix_basis=None) for _ in range(8)]
    op_props_handles = [SimpleNamespace(other_wall_guid=None) for _ in range(8)]
    self_stub = SimpleNamespace(unjoin_icons=icons, unjoin_op_props=op_props_handles, POOL_SIZE=8)

    patches = [
        patch.object(tool.Blender, "get_selected_objects", return_value=[self_obj]),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.Ifc, "get_object", side_effect=get_object),
        patch.object(wall_module, "get_wall_geom_cached", return_value={"placeholder": True}),
        patch.object(wall_module, "_wall_axis_world_segment_from_geom", side_effect=axis_world_segment),
        patch.object(wall_module, "_iter_path_connections", return_value=iter_returns),
        patch.object(gizmo_module, "get_billboard_rotation", return_value=Matrix.Identity(4)),
        patch.object(gizmo_module, "billboarded_at", side_effect=lambda pos, rot, scale=0.5: Matrix.Translation(pos)),
    ]
    for p in patches:
        p.start()
    try:
        wall_module.GizmoWallUnjoinSingle.position_gizmos(self_stub, SimpleNamespace())
    finally:
        for p in patches:
            p.stop()

    bindings = sorted(p.other_wall_guid for p in self_stub.unjoin_op_props if p.other_wall_guid is not None)
    assert bindings == ["_test_guid_A", "_test_guid_B"]


# ----------------------------------------------------------------------------
# UnjoinWallPathConnection._execute — bidirectional disconnect_path discipline
# ----------------------------------------------------------------------------


@pytest.fixture
def _temp_partner_object():
    """Yield a real ``bpy.types.Object`` to stand in as the partner wall — the
    operator's ``tool.Ifc.get_object`` mock returns this object, and tests
    assert on it via identity. A real Blender object is preferable to a
    ``SimpleNamespace`` stub because the operator and its downstream callers
    treat the partner as a ``bpy.types.Object`` (matrix access, name printing
    in error reports) — surprises from accidental property access on a stub
    would surface here, not in production."""
    name = "_UnjoinWallPathConnectionTestPartner"
    obj = bpy.data.objects.new(name, None)
    try:
        yield obj
    finally:
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)


def _make_rel(relating, related, kind="IfcRelConnectsPathElements"):
    """Build a stub `IfcRelConnectsPathElements` exposing the inverse-walk
    contract the operator depends on: `is_a`, `RelatingElement`,
    `RelatedElement`. Tests build chains of these and hang them off
    `elem.ConnectedTo` / `elem.ConnectedFrom`."""
    return SimpleNamespace(
        is_a=lambda name, _kind=kind: name == _kind,
        RelatingElement=relating,
        RelatedElement=related,
    )


def test_unjoin_wall_path_connection_removes_rel_via_inverse_walk(_temp_partner_object):
    """The operator must find the single `IfcRelConnectsPathElements` between the
    two walls by walking BOTH inverses (`ConnectedTo` and `ConnectedFrom`) and
    remove only that rel — without depending on which wall is the rel's
    `RelatingElement`. This pins both orientations.

    Also pins the post-mutation rebuild: `tool.Model.recreate_wall` must run on
    BOTH walls, otherwise the disconnected mitre stays in the mesh."""
    from bonsai import tool
    from bonsai.bim.module.model import wall as wall_module

    other_obj = _temp_partner_object
    active_obj = SimpleNamespace(name="ActiveWall")

    # Two scenarios collapse into one test case via parametrisation across the
    # rel's orientation: when the rel sits on `active.ConnectedTo` and when it
    # sits on `active.ConnectedFrom`. Both must be discovered and removed.
    for orientation in ("ConnectedTo", "ConnectedFrom"):
        removed_rels: list[object] = []
        recreate_calls: list[tuple[object, object]] = []

        def fake_remove_connection(_geom_tool, *, connection):
            removed_rels.append(connection)

        def fake_recreate(elem, obj):
            recreate_calls.append((elem, obj))

        elem_active = SimpleNamespace(name="ActiveElem", ConnectedTo=[], ConnectedFrom=[])
        elem_other = SimpleNamespace(name="OtherElem", ConnectedTo=[], ConnectedFrom=[])
        if orientation == "ConnectedTo":
            rel = _make_rel(relating=elem_active, related=elem_other)
            elem_active.ConnectedTo = [rel]
        else:
            rel = _make_rel(relating=elem_other, related=elem_active)
            elem_active.ConnectedFrom = [rel]

        def get_entity(obj, _ea=elem_active, _ao=active_obj):
            return _ea if obj is _ao else None

        def by_guid(g, _eo=elem_other):
            if g == "_test_partner_guid":
                return _eo
            raise RuntimeError(f"Instance with GlobalId {g} not in file")

        def get_object(elem, _eo=elem_other, _oo=other_obj):
            return _oo if elem is _eo else None

        self_stub = SimpleNamespace(other_wall_guid="_test_partner_guid", report=lambda level, msg: None)

        patches = [
            patch.object(tool.Blender, "get_active_object", return_value=active_obj),
            patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
            patch.object(tool.Ifc, "get", return_value=SimpleNamespace(by_guid=by_guid)),
            patch.object(tool.Ifc, "get_object", side_effect=get_object),
            patch.object(tool.Model, "recreate_wall", side_effect=fake_recreate),
            patch.object(wall_module, "_resync_walls_after_mutation"),
            patch.object(wall_module.bonsai.core.geometry, "remove_connection", side_effect=fake_remove_connection),
        ]
        for p in patches:
            p.start()
        try:
            wall_module.UnjoinWallPathConnection._perform(self_stub, SimpleNamespace())
        finally:
            for p in patches:
                p.stop()

        # Exactly the one rel for this orientation must have been removed.
        assert removed_rels == [rel], f"orientation={orientation}: removed_rels={removed_rels}"
        # Both walls' meshes must be rebuilt — skipping either leaves stale geometry.
        assert (elem_active, active_obj) in recreate_calls
        assert (elem_other, other_obj) in recreate_calls
        assert len(recreate_calls) == 2


def test_unjoin_wall_path_connection_reports_recovery_when_recreate_wall_raises(_temp_partner_object):
    """When ``recreate_wall`` raises after the IFC connection has already been
    removed, the operator must (a) surface a clear ``{'ERROR'}`` report telling
    the user how to recover (Ctrl+Z), (b) re-raise so Blender's normal operator
    error flow logs the traceback, and (c) NOT call ``_resync_walls_after_mutation``
    (rebuilding draft props off a partial-mesh state would just propagate the
    inconsistency to the gizmos)."""
    from bonsai import tool
    from bonsai.bim.module.model import wall as wall_module

    other_obj = _temp_partner_object
    active_obj = SimpleNamespace(name="ActiveWall")
    elem_active = SimpleNamespace(name="ActiveElem", ConnectedTo=[], ConnectedFrom=[])
    elem_other = SimpleNamespace(name="OtherElem", ConnectedTo=[], ConnectedFrom=[])
    rel = _make_rel(relating=elem_active, related=elem_other)
    elem_active.ConnectedTo = [rel]

    def get_entity(obj):
        return elem_active if obj is active_obj else None

    def by_guid(g):
        if g == "_test_partner_guid":
            return elem_other
        raise RuntimeError(f"Instance with GlobalId {g} not in file")

    def get_object(elem):
        return other_obj if elem is elem_other else None

    reports: list[tuple[set[str], str]] = []
    resync_calls: list[object] = []
    self_stub = SimpleNamespace(
        other_wall_guid="_test_partner_guid",
        report=lambda level, msg: reports.append((level, msg)),
    )

    patches = [
        patch.object(tool.Blender, "get_active_object", return_value=active_obj),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.Ifc, "get", return_value=SimpleNamespace(by_guid=by_guid)),
        patch.object(tool.Ifc, "get_object", side_effect=get_object),
        patch.object(tool.Model, "recreate_wall", side_effect=RuntimeError("kernel failure")),
        patch.object(wall_module, "_resync_walls_after_mutation", side_effect=lambda objs: resync_calls.append(objs)),
        patch.object(wall_module.bonsai.core.geometry, "remove_connection"),
    ]
    for p in patches:
        p.start()
    try:
        with pytest.raises(RuntimeError, match="kernel failure"):
            wall_module.UnjoinWallPathConnection._perform(self_stub, SimpleNamespace())
    finally:
        for p in patches:
            p.stop()

    # Report named the partial state and the recovery action.
    assert reports, "operator must self.report when recreate_wall raises"
    level, msg = reports[0]
    assert "ERROR" in level
    assert "Ctrl+Z" in msg or "undo" in msg.lower()
    # Resync MUST be skipped — running it after a failed rebuild would re-prime
    # gizmo draft props off the half-mutated state.
    assert resync_calls == [], "resync must not run when recreate_wall failed"


def test_unjoin_wall_path_connection_reports_when_partner_missing():
    """If the partner can't be resolved by GlobalId (entity removed from the IFC
    file between gizmo render and click), the operator must surface an explicit
    error rather than silently returning — that silent return was the original
    M2 review finding."""
    from bonsai import tool
    from bonsai.bim.module.model import wall as wall_module

    active_obj = SimpleNamespace()
    elem_active = SimpleNamespace(name="ActiveElem")
    reports: list[tuple[set[str], str]] = []

    def by_guid_not_found(g):
        raise RuntimeError(f"Instance with GlobalId {g} not in file")

    # A GUID that ``by_guid`` raises on → operator falls into the not-resolved
    # branch and must report the error.
    self_stub = SimpleNamespace(
        other_wall_guid="_test_vanished_guid",
        report=lambda level, msg: reports.append((level, msg)),
    )

    patches = [
        patch.object(tool.Blender, "get_active_object", return_value=active_obj),
        patch.object(tool.Ifc, "get_entity", return_value=elem_active),
        patch.object(tool.Ifc, "get", return_value=SimpleNamespace(by_guid=by_guid_not_found)),
        patch.object(wall_module.bonsai.core.geometry, "remove_connection"),
    ]
    for p in patches:
        p.start()
    try:
        wall_module.UnjoinWallPathConnection._perform(self_stub, SimpleNamespace())
    finally:
        for p in patches:
            p.stop()

    assert reports, "operator must self.report({'ERROR'}, ...) on missing partner"
    level, _ = reports[0]
    assert "ERROR" in level


# ----------------------------------------------------------------------------
# _iter_path_connections — partner enumeration must surface fillet corners
# ----------------------------------------------------------------------------


def test_iter_path_connections_surfaces_fillet_corner_partner():
    """When a normal LAYER2 wall is connected to a fillet-corner wall, the
    partner-enumeration walk must yield the fillet partner so the per-rel
    unjoin gizmo can sit at the fillet-side junction. Filtering with the
    strict LAYER2-only predicate would drop fillet corners from the partner
    list even though their path connections remain authoritative."""
    from bonsai import tool
    from bonsai.bim.module.model.wall import _iter_path_connections

    normal_wall = SimpleNamespace()
    fillet_corner = SimpleNamespace()
    rel = SimpleNamespace(
        RelatedElement=fillet_corner,
        RelatingConnectionType="ATEND",
        RelatedConnectionType="NOTDEFINED",
        is_a=lambda t: t == "IfcRelConnectsPathElements",
    )
    normal_wall.ConnectedTo = [rel]
    normal_wall.ConnectedFrom = []

    def is_path_connectable(element):
        return element is fillet_corner

    with patch.object(tool.Parametric, "is_path_connectable_wall", side_effect=is_path_connectable):
        out = _iter_path_connections(normal_wall)

    assert out == [(fillet_corner, "ATEND", "NOTDEFINED")]
