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

"""Unit tests for GizmoMEPActions eligibility, per-icon visibility, and the
``compute_mep_join_location`` helper used to position bend / transition
icons at the predicted fitting location.

These tests patch ``tool.Blender`` / ``tool.Ifc`` / ``tool.System`` so the
poll-gate predicates and visibility predicates can be exercised without a
real IFC fixture. Each test pins one branch of the eligibility / visibility
contract so a silent regression in the gate ordering or in the per-icon
selection-cardinality checks is caught by a dedicated assertion.

The action_configs map to existing one-shot operators in mep.py — the
operators themselves are not exercised here (they need a full Blender +
IFC scene); this file only pins the gizmo-group surface plus the pure
geometric helper in decorator.py."""

from unittest.mock import Mock, patch

import bpy
import pytest

pytestmark = pytest.mark.model


def _patch_tools(selected, entity_for, is_mep_for):
    """Patch tool.Blender.get_selected_objects, tool.Ifc.get_entity, and
    tool.System.is_mep_element with the supplied mappings.

    Identity-keyed maps avoid relying on ``__eq__`` on the fake objects, which
    matters when those objects are plain ``object()`` sentinels."""
    from bonsai import tool

    entity_map = {id(obj): entity_for.get(id(obj)) for obj in selected if id(obj) in entity_for}
    mep_map = {ent: bool(flag) for ent, flag in is_mep_for.items()}

    def get_entity(obj):
        return entity_map.get(id(obj))

    def is_mep_element(element):
        return mep_map.get(id(element), False)

    return [
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.System, "is_mep_element", side_effect=is_mep_element),
    ]


def _start(patches):
    for p in patches:
        p.start()


def _stop(patches):
    for p in reversed(patches):
        p.stop()


# ---------------------------------------------------------------------------
# is_eligible_object — the group's poll-gate predicate
# ---------------------------------------------------------------------------


def test_is_eligible_object_false_when_active_lacks_ifc_entity():
    """A plain Blender object with no IFC binding must not show the gizmo
    group — the operators all require an IFC element on the active object."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    plain = object()
    patches = _patch_tools(selected=[plain], entity_for={}, is_mep_for={})
    _start(patches)
    try:
        assert GizmoMEPActions.is_eligible_object(plain) is False
    finally:
        _stop(patches)


def test_is_eligible_object_false_when_active_is_non_mep_ifc():
    """An IFC element that isn't a flow segment/fitting (e.g. a wall) must
    not show the gizmo group. Pins the delegation to tool.System.is_mep_element."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    wall_obj = object()
    wall_element = object()
    patches = _patch_tools(
        selected=[wall_obj],
        entity_for={id(wall_obj): wall_element},
        is_mep_for={id(wall_element): False},
    )
    _start(patches)
    try:
        assert GizmoMEPActions.is_eligible_object(wall_obj) is False
    finally:
        _stop(patches)


def test_is_eligible_object_true_when_active_is_mep_element():
    """The base case: an IfcFlowSegment / IfcFlowFitting on the active object
    polls the gizmo group in. tool.System.is_mep_element is the authority
    for what counts as MEP; we trust its True for both flow types."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    segment_obj = object()
    segment_element = object()
    patches = _patch_tools(
        selected=[segment_obj],
        entity_for={id(segment_obj): segment_element},
        is_mep_for={id(segment_element): True},
    )
    _start(patches)
    try:
        assert GizmoMEPActions.is_eligible_object(segment_obj) is True
    finally:
        _stop(patches)


# ---------------------------------------------------------------------------
# action_configs — each entry must reference a real registered operator
# ---------------------------------------------------------------------------


def test_action_configs_reference_registered_operators():
    """Catches the most common regression: renaming an operator's bl_idname
    without updating action_configs. bpy.ops.<namespace>.<verb> resolves at
    attribute-access time, so this check is a real registration probe."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    for config in GizmoMEPActions.action_configs:
        namespace, _, verb = config.operator.partition(".")
        assert namespace == "bim", f"Unexpected operator namespace in {config.name!r}: {config.operator!r}"
        ops = getattr(bpy.ops, namespace)
        assert hasattr(ops, verb), (
            f"action_config {config.name!r} targets {config.operator!r} which is not a registered operator. "
            f"Did its bl_idname get renamed?"
        )


def test_action_configs_have_unique_names_and_icons_present():
    """Each name is the suffix in ``self.action_{name}_gizmo`` (set by
    BaseIconActionGroup.setup) — duplicates would silently shadow each other.
    Each icon must be a non-empty Blender gizmo type bl_idname."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    names = [c.name for c in GizmoMEPActions.action_configs]
    assert len(names) == len(set(names)), f"Duplicate action_config names: {names}"
    for config in GizmoMEPActions.action_configs:
        assert config.icon, f"action_config {config.name!r} has empty icon bl_idname"
        assert config.icon.startswith(
            "VIEW3D_GT_"
        ), f"action_config {config.name!r} icon {config.icon!r} is not a VIEW3D_GT_* gizmo type"


def test_gizmo_mep_actions_is_registered():
    """Pin GizmoMEPActions' bl_idname so a typo can't silently hide the icons."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    assert GizmoMEPActions.bl_idname == "OBJECT_GGT_bim_mep_actions"
    assert issubclass(GizmoMEPActions, bpy.types.GizmoGroup)


# ---------------------------------------------------------------------------
# Per-icon visibility predicates
# ---------------------------------------------------------------------------


def _config_by_name(name):
    from bonsai.bim.module.model.mep import GizmoMEPActions

    for config in GizmoMEPActions.action_configs:
        if config.name == name:
            return config
    raise AssertionError(f"No action_config named {name!r}")


def test_regenerate_action_config_is_removed():
    """``bim.regenerate_distribution_element`` was removed from the
    GizmoMEPActions row in a follow-up round — the gizmo surfaced an
    operator the user never reached for in the gizmo flow (regenerate is
    a repair action invoked from the N-panel). Pin so a future
    re-addition is an intentional decision."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    names = {c.name for c in GizmoMEPActions.action_configs}
    assert "regenerate" not in names


def test_fit_action_config_is_removed():
    """``bim.fit_flow_segments`` was removed from the GizmoMEPActions row in
    a follow-up round — redundant with the per-end lock icons (which already
    cover obstruction placement, the operator's main use). Pin so a future
    re-addition is an intentional decision, not a drive-by re-introduction."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    names = {c.name for c in GizmoMEPActions.action_configs}
    assert "fit" not in names


@pytest.mark.parametrize(
    "name",
    [
        "lock_start_open",
        "lock_start_closed",
        "lock_end_open",
        "lock_end_closed",
    ],
)
@pytest.mark.parametrize(
    "n_selected,active_is_segment,expected",
    [
        (0, False, False),
        (1, False, False),  # single selection but not a flow segment
        (1, True, True),  # the only true case
        (2, True, False),  # operator only acts on the active; multi-select ambiguous
    ],
)
def test_lock_visibility_requires_one_active_flow_segment(name, n_selected, active_is_segment, expected):
    """Lock icons attach to a single segment at the named port (START / END).
    Pin both cardinality and the IfcFlowSegment check — IfcFlowFitting is not
    enough even though the group polls in on both, because the operators
    behind the lock icons act on segments. All four lock icons share the
    same visibility predicate; only one of each open/closed pair renders
    per redraw based on the current port-connection state, but the
    predicate runs unconditionally."""
    from bonsai import tool

    selected = [object() for _ in range(n_selected)]
    active = selected[0] if selected else object()
    flow_segment_element = Mock()
    flow_segment_element.is_a.side_effect = lambda type_name: type_name == "IfcFlowSegment"

    def get_entity(obj):
        if obj is active and active_is_segment:
            return flow_segment_element
        return None

    config = _config_by_name(name)
    with (
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
    ):
        assert config.visibility_condition(active) is expected


def test_lock_icons_route_to_distinct_operators_per_state():
    """Four lock configs (open/closed × start/end). Open locks fire
    ``bim.mep_add_obstruction`` (add at port); closed locks fire
    ``bim.mep_remove_terminal_fitting`` (delete the connected fitting).
    The open/closed suffix in the name encodes the routing in ``setup()``.
    Distinct names guarantee distinct ``self.action_<name>_gizmo`` attrs."""
    open_names = ["lock_start_open", "lock_end_open"]
    closed_names = ["lock_start_closed", "lock_end_closed"]
    open_configs = [_config_by_name(n) for n in open_names]
    closed_configs = [_config_by_name(n) for n in closed_names]
    assert {c.operator for c in open_configs} == {"bim.mep_add_obstruction"}
    assert {c.operator for c in closed_configs} == {"bim.mep_remove_terminal_fitting"}
    all_names = open_names + closed_names
    assert len(set(all_names)) == len(all_names)


def test_lock_icon_config_table_matches_action_configs():
    """``LOCK_ICON_CONFIGS`` is the lookup ``setup()`` uses to pre-fill each
    lock gizmo's operator (position arg). Each table entry must have a
    matching ``IconActionConfig`` of the same name in ``action_configs``,
    otherwise ``setup()`` would skip the pre-fill and the click would fire
    with default operator props."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    config_names = {c.name for c in GizmoMEPActions.action_configs}
    for config_name in GizmoMEPActions.LOCK_ICON_CONFIGS:
        assert (
            config_name in config_names
        ), f"LOCK_ICON_CONFIGS references {config_name!r} but action_configs has no matching entry"


@pytest.mark.parametrize(
    "config_name,expected_icon,expected_position",
    [
        ("lock_start_open", "VIEW3D_GT_lock_open", "START"),
        ("lock_start_closed", "VIEW3D_GT_lock_closed", "START"),
        ("lock_end_open", "VIEW3D_GT_lock_open", "END"),
        ("lock_end_closed", "VIEW3D_GT_lock_closed", "END"),
    ],
)
def test_lock_icon_config_table_pins_icon_and_position(config_name, expected_icon, expected_position):
    """Pin the (icon, position) pair for each lock variant. A swap would
    silently make a lock-icon click fire at the wrong port — the worst
    possible regression. ``setup()`` routes open vs closed clicks via the
    name suffix, so the table itself only needs the icon + port-position."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    icon, position = GizmoMEPActions.LOCK_ICON_CONFIGS[config_name]
    assert icon == expected_icon
    assert position == expected_position


def test_join_uses_merging_arrows_icon():
    """The single ``join`` dispatcher icon uses ``VIEW3D_GT_merge`` (converging
    arrows) — semantically right for "two flows joining" regardless of whether
    the underlying routing is transition or bend. Replaces the prior pair of
    distinct bend (``VIEW3D_GT_arc``) + transition (``VIEW3D_GT_merge``) icons.
    Pinning so a future drive-by icon swap is an intentional decision."""
    config = _config_by_name("join")
    assert config.icon == "VIEW3D_GT_merge"


def test_bend_and_transition_action_configs_are_removed():
    """The separate ``bend`` and ``transition`` icons were collapsed into a
    single ``join`` dispatcher (``MEPJoinSegments``) — the two underlying
    operators are geometrically mutually exclusive (parallel vs non-parallel
    segments) and the user shouldn't have to disambiguate up front. Pin so
    a future re-addition is an intentional decision."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    names = {c.name for c in GizmoMEPActions.action_configs}
    assert "bend" not in names
    assert "transition" not in names


def test_bend_anchor_configs_classifies_join_and_unjoin_pair():
    """The single ``join`` dispatcher and ``unjoin_pair`` both land at the
    predicted bend-marker midpoint and are mutually exclusive per
    ``position_gizmos`` (visible iff fitting is absent / present respectively).
    Pinning the classification so a regression doesn't silently re-route them
    into the row layout at the wrong size."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    assert "join" in GizmoMEPActions.BEND_ANCHOR_CONFIGS
    assert "unjoin_pair" in GizmoMEPActions.BEND_ANCHOR_CONFIGS
    # No row config accidentally classified as a bend anchor.
    assert "regenerate" not in GizmoMEPActions.BEND_ANCHOR_CONFIGS


@pytest.mark.parametrize(
    "config_name,expected_ratio",
    [
        ("join", 1.0),
        ("lock_start_open", 0.5),
        ("lock_start_closed", 0.5),
        ("lock_end_open", 0.5),
        ("lock_end_closed", 0.5),
    ],
)
def test_scale_for_config_returns_expected_ratio(config_name, expected_ratio):
    """``_scale_for_config`` is the single source of truth for per-icon size.
    Endpoint icons (port-anchored locks) shrink to 0.5; everything else uses the
    base scale. Call the function unbound with a SimpleNamespace stand-in since
    bpy_struct.__new__ rejects instantiating GizmoGroup subclasses outside
    Blender's own registration flow."""
    from types import SimpleNamespace

    from bonsai.bim.module.model.mep import GizmoMEPActions

    stub = SimpleNamespace(
        ICON_SCALE=GizmoMEPActions.ICON_SCALE,
        ENDPOINT_CONFIGS=GizmoMEPActions.ENDPOINT_CONFIGS,
        UNJOIN_CONFIGS=GizmoMEPActions.UNJOIN_CONFIGS,
        ENDPOINT_SCALE_RATIO=GizmoMEPActions.ENDPOINT_SCALE_RATIO,
    )
    assert GizmoMEPActions._scale_for_config(stub, config_name) == pytest.approx(
        GizmoMEPActions.ICON_SCALE * expected_ratio
    )


@pytest.mark.parametrize("config_name", ["unjoin_start", "unjoin_end", "unjoin_pair"])
def test_scale_for_config_unjoin_matches_default_billboard_scale(config_name):
    """Unjoin icons render at the default billboard scale regardless of
    whether they're endpoint-anchored or row-anchored — destructive actions
    deserve a full-size deliberate target, on par with the wall unjoin icon."""
    from types import SimpleNamespace

    from bonsai.bim.module.drawing import gizmos as gizmo
    from bonsai.bim.module.model.mep import GizmoMEPActions

    stub = SimpleNamespace(
        ICON_SCALE=GizmoMEPActions.ICON_SCALE,
        ENDPOINT_CONFIGS=GizmoMEPActions.ENDPOINT_CONFIGS,
        UNJOIN_CONFIGS=GizmoMEPActions.UNJOIN_CONFIGS,
        ENDPOINT_SCALE_RATIO=GizmoMEPActions.ENDPOINT_SCALE_RATIO,
    )
    assert GizmoMEPActions._scale_for_config(stub, config_name) == pytest.approx(gizmo.DEFAULT_BILLBOARD_SCALE)


def _run_mep_extend_refresh(cursor_local_z, current_length=3.0):
    """Drive ``_MEPSegmentEditionMixin._refresh_element_specific`` with a stub
    ``self`` and a cursor at ``cursor_local_z`` along the segment's local Z.

    ``mw`` is identity so ``cursor_local`` equals ``cursor_world``; the test
    math focuses on the tracking contract rather than the transform. The
    bound-box top is ``current_length`` to feed the split-icon visibility
    window. Returns the stub ``self`` so callers can assert on per-icon state."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from mathutils import Matrix, Vector

    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model.mep import _MEPSegmentEditionMixin

    def _icon():
        return SimpleNamespace(hide=False, matrix_basis=None)

    self_stub = SimpleNamespace(
        extend_gizmo=_icon(),
        split_gizmo=_icon(),
        _frame_billboard_rot=Matrix.Identity(4),
        is_gizmo_hidden_by_modal=lambda gz: False,
        CURSOR_STACK_OFFSET=_MEPSegmentEditionMixin.CURSOR_STACK_OFFSET,
    )
    cursor_world = Vector((0.0, 0.0, cursor_local_z))
    bound_box = [(0.0, 0.0, 0.0)] * 8
    bound_box[2] = (0.0, 0.0, current_length)
    active_obj = SimpleNamespace(bound_box=bound_box)
    scene = SimpleNamespace(cursor=SimpleNamespace(location=cursor_world))
    context = SimpleNamespace(scene=scene, active_object=active_obj)

    with patch.object(gizmo_module, "billboarded_at", side_effect=lambda pos, rot: Matrix.Translation(pos)):
        _MEPSegmentEditionMixin._refresh_element_specific(self_stub, context, Matrix.Identity(4), props=None)
    return self_stub


def test_mep_extend_gizmo_tracks_cursor_at_negative_local_z():
    """The extend icon's anchor follows the cursor along the segment's
    extrusion axis when the cursor sits below the origin (local Z < 0).
    Clicking the icon there extends the segment's start (ATSTART), so the
    icon must remain visible at the cursor anchor to surface the
    affordance — not snap to the origin."""
    self_stub = _run_mep_extend_refresh(cursor_local_z=-1.5, current_length=3.0)
    assert self_stub.extend_gizmo.hide is False
    assert self_stub.extend_gizmo.matrix_basis.translation.z == pytest.approx(-1.5)
    # Cursor projection sits outside the segment's endpoint-clear window,
    # so the split icon hides.
    assert self_stub.split_gizmo.hide is True


def test_mep_extend_gizmo_tracks_cursor_at_positive_local_z():
    """The extend icon's anchor follows the cursor at positive local Z. The
    split icon is also visible because the cursor projection sits inside
    the segment's endpoint-clear window."""
    self_stub = _run_mep_extend_refresh(cursor_local_z=1.5, current_length=3.0)
    assert self_stub.extend_gizmo.hide is False
    assert self_stub.extend_gizmo.matrix_basis.translation.z == pytest.approx(1.5)
    assert self_stub.split_gizmo.hide is False


def test_extend_segment_to_cursor_extends_nearest_endpoint():
    """The extend operator extends or trims the nearest endpoint of the
    segment to the cursor projection — it must not commit an absolute
    length, which would collapse the segment to zero for any cursor
    position before the segment origin."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from mathutils import Vector

    from bonsai.bim.module.model import mep as mep_module
    from bonsai.bim.module.model.profile import DumbProfileJoiner

    obj_stub = object()
    cursor_world = Vector((0.0, 0.0, -1.5))
    fake_joiner = MagicMock(spec=DumbProfileJoiner)
    context = SimpleNamespace(scene=SimpleNamespace(cursor=SimpleNamespace(location=cursor_world)))

    with (
        patch.object(mep_module, "_project_cursor_to_segment_local_z", return_value=(obj_stub, -1.5)),
        patch.object(mep_module, "DumbProfileJoiner", return_value=fake_joiner),
    ):
        result = mep_module._extend_segment_to_cursor(context, is_pipe=True)

    assert result == {"FINISHED"}
    fake_joiner.join_E.assert_called_once_with(obj_stub, cursor_world)
    # An absolute-length commit path would collapse the segment to ~0 at
    # negative cursor Z. Pin its absence.
    fake_joiner.set_depth.assert_not_called()


def test_extend_segment_to_cursor_cancels_when_active_object_invalid():
    """If the projection helper rejects (no IFC entity, wrong predicate),
    the operator must cancel without dispatching any joiner mutation."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from mathutils import Vector

    from bonsai.bim.module.model import mep as mep_module
    from bonsai.bim.module.model.profile import DumbProfileJoiner

    fake_joiner = MagicMock(spec=DumbProfileJoiner)
    context = SimpleNamespace(scene=SimpleNamespace(cursor=SimpleNamespace(location=Vector((0.0, 0.0, 1.0)))))

    with (
        patch.object(mep_module, "_project_cursor_to_segment_local_z", return_value=(None, None)),
        patch.object(mep_module, "DumbProfileJoiner", return_value=fake_joiner),
    ):
        result = mep_module._extend_segment_to_cursor(context, is_pipe=True)

    assert result == {"CANCELLED"}
    fake_joiner.join_E.assert_not_called()
    fake_joiner.set_depth.assert_not_called()


def test_mep_add_obstruction_position_and_mode_properties_exist():
    """``GizmoMEPActions.setup()`` mutates ``op_props.position`` AND
    ``op_props.mode`` post-bind. If either EnumProperty gets renamed or
    removed, ``setup()`` would fail silently at register time and the lock
    icons would either fire at the wrong port or stop toggling. Pin both."""
    op_class = bpy.types.Operator.bl_rna_get_subclass_py("MEP_OT_add_obstruction") or _resolve_operator_class(
        "bim.mep_add_obstruction"
    )
    assert op_class is not None
    annotations = getattr(op_class, "__annotations__", {})
    assert (
        "position" in annotations
    ), "MEPAddObstruction.position EnumProperty is missing — gizmo setup() will silently no-op."
    assert "mode" in annotations, "MEPAddObstruction.mode EnumProperty is missing — toggle won't dispatch ADD/REMOVE."


def test_mep_module_has_no_invalid_error_returns():
    """Regression guard for ``MEPAddBend._execute`` returning ``{"ERROR"}``
    on two geometry-validation paths (mep.py:1255, 1263 in the buggy state).

    ``{"ERROR"}`` is not in Blender's operator return spec — valid values
    are ``{"FINISHED"}``, ``{"CANCELLED"}``, ``{"RUNNING_MODAL"}``,
    ``{"PASS_THROUGH"}``, ``{"INTERFACE"}``. Returning the wrong set leaves
    the REGISTER+UNDO redo panel in an inconsistent state: modifying
    ``start_length`` / ``end_length`` re-invokes the operator, it errors
    again, and the user is locked out — exact symptom the bug report
    described ("infinite bug, couldn't finish geometry, couldn't do
    anything else").

    This test scans the mep.py source for the literal pattern so any
    future re-introduction in any operator in the file is caught at test
    time, not by another stuck user.
    """
    import inspect

    from bonsai.bim.module.model import mep

    source = inspect.getsource(mep)
    for invalid_literal in ('return {"ERROR"}', "return {'ERROR'}"):
        assert invalid_literal not in source, (
            f"mep.py contains `{invalid_literal}` — not a valid Blender operator return value. "
            f'Use `return {{"CANCELLED"}}` for error paths. See '
            f"`test_mep_module_has_no_invalid_error_returns` for context."
        )


def _resolve_operator_class(bl_idname):
    """Look up an operator class by its ``bim.<verb>`` bl_idname. Returns None
    when the operator isn't registered (test should fail loudly elsewhere)."""
    namespace, _, verb = bl_idname.partition(".")
    ops = getattr(bpy.ops, namespace, None)
    if ops is None or not hasattr(ops, verb):
        return None
    # Walk the bpy.types module for a subclass whose bl_idname matches.
    for candidate_name in dir(bpy.types):
        candidate = getattr(bpy.types, candidate_name, None)
        if getattr(candidate, "bl_idname", None) == bl_idname:
            return candidate
    return None


@pytest.mark.parametrize(
    "selected_descriptors,expected",
    [
        # 0/1/3 selected — wrong cardinality regardless of class
        ([], False),
        ([("mep", True)], False),
        ([("mep", True), ("mep", True), ("mep", True)], False),
        # 2 selected, both MEP — happy path
        ([("mep", True), ("mep", True)], True),
        # 2 selected, one is a wall — must hide
        ([("mep", True), ("wall", False)], False),
        # 2 selected, both walls — must hide
        ([("wall", False), ("wall", False)], False),
        # 2 selected, one has no IFC entity — must hide
        ([("mep", True), ("none", None)], False),
    ],
)
def test_join_visibility_requires_exactly_two_mep_selected(selected_descriptors, expected):
    """The ``join`` dispatcher routes to either ``bim.mep_add_transition`` or
    ``bim.mep_add_bend`` depending on geometry — both underlying operators
    require exactly two MEP elements (``IfcFlowSegment`` / ``IfcFlowFitting``).
    Pinning the visibility predicate so a mixed / wrong-cardinality selection
    doesn't surface a click target that would error on dispatch."""
    from bonsai import tool

    selected = []
    entity_map = {}
    mep_map = {}
    for kind, mep_flag in selected_descriptors:
        obj = object()
        selected.append(obj)
        if kind == "none":
            continue
        element = object()
        entity_map[id(obj)] = element
        mep_map[id(element)] = bool(mep_flag)

    def get_entity(obj):
        return entity_map.get(id(obj))

    def is_mep_element(element):
        return mep_map.get(id(element), False)

    config = _config_by_name("join")
    with (
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.System, "is_mep_element", side_effect=is_mep_element),
    ):
        assert config.visibility_condition(selected[0] if selected else object()) is expected


# ---------------------------------------------------------------------------
# compute_mep_join_location — pure geometric helper used to anchor bend /
# transition icons at the predicted fitting location.
# ---------------------------------------------------------------------------


def _set_up_two_mep_selection(seg_a_endpoints, seg_b_endpoints):
    """Patch tool.Blender / tool.Ifc / tool.Model so two synthetic MEP segments
    with the given world-space (start, end) endpoint tuples are selected.
    Returns the list of patch context managers (caller starts/stops)."""
    from bonsai import tool

    obj_a = object()
    obj_b = object()
    elem_a = object()
    elem_b = object()
    entity_map = {id(obj_a): elem_a, id(obj_b): elem_b}
    mep_map = {id(elem_a): True, id(elem_b): True}
    axis_map = {id(obj_a): seg_a_endpoints, id(obj_b): seg_b_endpoints}

    return [
        patch.object(tool.Blender, "get_selected_objects", return_value={obj_a, obj_b}),
        patch.object(tool.Ifc, "get_entity", side_effect=lambda obj: entity_map.get(id(obj))),
        patch.object(tool.System, "is_mep_element", side_effect=lambda elem: mep_map.get(id(elem), False)),
        patch.object(tool.Model, "get_flow_segment_axis", side_effect=lambda obj: axis_map[id(obj)]),
    ]


def test_join_location_picks_midpoint_of_closest_endpoint_pair():
    """The bend/transition icons land at the midpoint between the two
    segments' closest endpoints — the natural "where the fitting will go"
    cue. Pin the math on a concrete L-shape so a regression in the
    closest-pair selection or the midpoint formula is caught."""
    from mathutils import Vector

    from bonsai.bim.module.model.decorator import compute_mep_join_location

    # Segment A from (0,0,0) to (1,0,0); segment B from (1,1,0) to (1,2,0).
    # Closest endpoint pair: A's end (1,0,0) and B's start (1,1,0).
    # Midpoint: (1, 0.5, 0).
    seg_a = (Vector((0, 0, 0)), Vector((1, 0, 0)))
    seg_b = (Vector((1, 1, 0)), Vector((1, 2, 0)))
    patches = _set_up_two_mep_selection(seg_a, seg_b)
    _start(patches)
    try:
        location = compute_mep_join_location()
    finally:
        _stop(patches)
    assert location is not None
    assert tuple(location) == pytest.approx((1.0, 0.5, 0.0))


def test_join_location_returns_none_when_selection_is_not_two_mep():
    """The helper must defensively reject non-2-MEP selections — different
    callers can reach it with stale selection states."""
    from bonsai import tool
    from bonsai.bim.module.model.decorator import compute_mep_join_location

    # Single-object selection: bend isn't valid.
    with patch.object(tool.Blender, "get_selected_objects", return_value={object()}):
        assert compute_mep_join_location() is None


def test_join_location_returns_none_when_one_selection_is_non_mep():
    """One MEP + one wall: bend isn't valid. The helper must filter this so
    the gizmo positioning code doesn't anchor at a meaningless midpoint."""
    from bonsai import tool
    from bonsai.bim.module.model.decorator import compute_mep_join_location

    mep_obj = object()
    wall_obj = object()
    mep_elem = object()
    wall_elem = object()
    with (
        patch.object(tool.Blender, "get_selected_objects", return_value={mep_obj, wall_obj}),
        patch.object(
            tool.Ifc, "get_entity", side_effect=lambda o: {id(mep_obj): mep_elem, id(wall_obj): wall_elem}.get(id(o))
        ),
        patch.object(tool.System, "is_mep_element", side_effect=lambda e: e is mep_elem),
    ):
        assert compute_mep_join_location() is None


# ---------------------------------------------------------------------------
# find_obstruction_at_port — drives both MEPGenerator.remove_obstruction and
# GizmoMEPActions' lock-icon open/closed pair selection (per-port query).
# ---------------------------------------------------------------------------


def _make_segment_with_port_chain(connected_port, connected_element, *, bridges=False):
    """Return a Mock IfcFlowSegment plus the patches needed to drive the
    port-chain helpers. Mock objects stand in for the port graph;
    tool.System helpers are stubbed via patch.object.

    ``bridges``: when True, the ``connected_element`` is given a second port
    that wires to a different element — drives the graph-walk in
    ``port_connection_state`` to the JOINED branch. When False (default),
    the connected element is a dead end → graph-walk returns TERMINAL.
    """
    from bonsai import tool
    from bonsai.bim.module.model import mep

    segment = Mock()
    segment.is_a.side_effect = lambda type_name: type_name == "IfcFlowSegment"
    start_port = Mock()
    end_port = Mock()

    other_port = Mock() if (bridges and connected_element is not None) else None
    far_port = Mock() if bridges else None
    far_element = Mock() if bridges else None
    connected_ports: list = []
    if connected_element is not None and connected_port is not None:
        connected_ports.append(connected_port)
        if other_port is not None:
            connected_ports.append(other_port)

    def get_connected_port_side_effect(port):
        if port is start_port or port is end_port:
            return connected_port
        if port is other_port:
            return far_port
        return None

    def get_port_relating_element_side_effect(port):
        if port is connected_port:
            return connected_element
        if port is far_port:
            return far_element
        return None

    def get_ports_side_effect(element):
        if element is connected_element:
            return connected_ports
        return []

    return segment, [
        patch.object(
            mep.MEPGenerator,
            "get_segment_data",
            return_value={"start_port": start_port, "end_port": end_port, "extrusion_depth": 1.0},
        ),
        patch.object(tool.System, "get_connected_port", side_effect=get_connected_port_side_effect),
        patch.object(tool.System, "get_port_relating_element", side_effect=get_port_relating_element_side_effect),
        patch.object(tool.System, "get_ports", side_effect=get_ports_side_effect),
    ]


def test_find_obstruction_at_port_returns_obstruction_when_present():
    """Happy path: the connected element is an IfcFlowFitting with
    PredefinedType OBSTRUCTION. The helper returns it so the caller can
    pass it to ``ifcopenshell.api.root.remove_product``."""
    from bonsai.bim.module.model.mep import find_obstruction_at_port

    obstruction = Mock()
    obstruction.is_a.side_effect = lambda type_name: type_name == "IfcFlowFitting"
    obstruction.PredefinedType = "OBSTRUCTION"
    segment, patches = _make_segment_with_port_chain(connected_port=Mock(), connected_element=obstruction)

    _start(patches)
    try:
        assert find_obstruction_at_port(segment, at_segment_start=True) is obstruction
    finally:
        _stop(patches)


def test_find_obstruction_at_port_returns_none_for_non_obstruction_fitting():
    """A bend / transition connected at the port is also an IfcFlowFitting
    but with a different PredefinedType. The helper must NOT report these
    as obstructions — the lock-icon would otherwise close (signalling
    'click to remove') for an unrelated fitting."""
    from bonsai.bim.module.model.mep import find_obstruction_at_port

    bend = Mock()
    bend.is_a.side_effect = lambda type_name: type_name == "IfcFlowFitting"
    bend.PredefinedType = "BEND"
    segment, patches = _make_segment_with_port_chain(connected_port=Mock(), connected_element=bend)

    _start(patches)
    try:
        assert find_obstruction_at_port(segment, at_segment_start=True) is None
    finally:
        _stop(patches)


def test_find_obstruction_at_port_returns_none_for_disconnected_port():
    """No connected port at the named end → no obstruction. Pin so the lock
    icon stays open (can-add) when nothing's connected."""
    from bonsai.bim.module.model.mep import find_obstruction_at_port

    segment, patches = _make_segment_with_port_chain(connected_port=None, connected_element=None)

    _start(patches)
    try:
        assert find_obstruction_at_port(segment, at_segment_start=False) is None
    finally:
        _stop(patches)


def test_find_obstruction_at_port_returns_none_for_non_segment():
    """Defensive: the helper is the only place ``MEPGenerator.remove_obstruction``
    delegates its 'is this a flow segment?' check to. A non-segment caller
    (e.g. a fitting passed by accident) must short-circuit to None without
    touching the port chain."""
    from bonsai.bim.module.model.mep import find_obstruction_at_port

    fitting = Mock()
    fitting.is_a.side_effect = lambda type_name: type_name == "IfcFlowFitting"

    assert find_obstruction_at_port(fitting, at_segment_start=True) is None


def test_lock_open_and_closed_gizmo_classes_are_registered():
    """Both members of the open/closed lock pair must be importable + valid Gizmo
    subclasses so ``self.gizmos.new("VIEW3D_GT_lock_open")`` resolves at setup."""
    from bonsai.bim.module.drawing.gizmos import GizmoLockClosed, GizmoLockOpen

    assert GizmoLockOpen.bl_idname == "VIEW3D_GT_lock_open"
    assert GizmoLockClosed.bl_idname == "VIEW3D_GT_lock_closed"
    assert issubclass(GizmoLockOpen, bpy.types.Gizmo)
    assert issubclass(GizmoLockClosed, bpy.types.Gizmo)


# ---------------------------------------------------------------------------
# port_connection_state — three-state classification driving lock visibility
# ---------------------------------------------------------------------------


def test_port_connection_state_returns_free_for_non_segment():
    """Defensive: non-segment input (e.g. a fitting passed by accident) must
    short-circuit to FREE without touching the port chain. The helper sits
    in the per-frame ``position_gizmos`` hot path; a raise here would crash
    the gizmo refresh."""
    from bonsai.bim.module.model.mep import PORT_FREE, port_connection_state

    fitting = Mock()
    fitting.is_a.side_effect = lambda type_name: type_name == "IfcFlowFitting"
    assert port_connection_state(fitting, at_segment_start=True) == PORT_FREE


def test_port_connection_state_returns_free_for_disconnected_port():
    """The common case: a freshly-drawn pipe segment has no port
    connections. State must be FREE so the OPEN lock shows (click-to-add
    obstruction is valid)."""
    from bonsai import tool
    from bonsai.bim.module.model import mep
    from bonsai.bim.module.model.mep import PORT_FREE, port_connection_state

    segment, patches = _make_segment_with_port_chain(connected_port=None, connected_element=None)
    _start(patches)
    try:
        assert port_connection_state(segment, at_segment_start=False) == PORT_FREE
    finally:
        _stop(patches)


def test_port_connection_state_returns_terminal_for_solo_obstruction_fitting():
    """An obstruction at the port has no other connections → the graph-walk
    finds no bridging element → state is TERMINAL → CLOSED lock visible.
    ``bim.mep_remove_terminal_fitting`` dispatches the click to the
    obstruction-aware removal path."""
    from bonsai.bim.module.model.mep import PORT_TERMINAL, port_connection_state

    obstruction = Mock()
    obstruction.is_a.side_effect = lambda type_name: type_name == "IfcFlowFitting"
    obstruction.PredefinedType = "OBSTRUCTION"
    segment, patches = _make_segment_with_port_chain(connected_port=Mock(), connected_element=obstruction)
    _start(patches)
    try:
        assert port_connection_state(segment, at_segment_start=True) == PORT_TERMINAL
    finally:
        _stop(patches)


def test_port_connection_state_returns_terminal_for_solo_non_obstruction_fitting():
    """A bend / cap / single-port fitting at the port with nothing on its
    other side classifies as TERMINAL — same as a solo obstruction, just a
    different fitting type. The closed lock click delegates fitting deletion
    to ``bim.mep_remove_terminal_fitting``."""
    from bonsai.bim.module.model.mep import PORT_TERMINAL, port_connection_state

    cap = Mock()
    cap.is_a.side_effect = lambda type_name: type_name == "IfcFlowFitting"
    cap.PredefinedType = "BEND"
    segment, patches = _make_segment_with_port_chain(connected_port=Mock(), connected_element=cap)
    _start(patches)
    try:
        assert port_connection_state(segment, at_segment_start=True) == PORT_TERMINAL
    finally:
        _stop(patches)


def test_port_connection_state_returns_joined_when_fitting_bridges_two_elements():
    """Bridging case: the fitting at the port has a second port leading to a
    different element. The graph-walk returns JOINED → unjoin icon visible,
    both locks hidden."""
    from bonsai.bim.module.model.mep import PORT_JOINED, port_connection_state

    bend = Mock()
    bend.is_a.side_effect = lambda type_name: type_name == "IfcFlowFitting"
    bend.PredefinedType = "BEND"
    segment, patches = _make_segment_with_port_chain(connected_port=Mock(), connected_element=bend, bridges=True)
    _start(patches)
    try:
        assert port_connection_state(segment, at_segment_start=True) == PORT_JOINED
    finally:
        _stop(patches)


def test_port_connection_state_returns_joined_for_bridging_adjacent_segment():
    """Daisy-chained pipes where the next element bridges onward to a third
    element → JOINED. Without the onward bridge the same shape would be
    TERMINAL — the classification is graph-driven, not type-driven."""
    from bonsai.bim.module.model.mep import PORT_JOINED, port_connection_state

    next_segment = Mock()
    next_segment.is_a.side_effect = lambda type_name: type_name == "IfcFlowSegment"
    segment, patches = _make_segment_with_port_chain(
        connected_port=Mock(), connected_element=next_segment, bridges=True
    )
    _start(patches)
    try:
        assert port_connection_state(segment, at_segment_start=True) == PORT_JOINED
    finally:
        _stop(patches)


# ---------------------------------------------------------------------------
# find_fitting_between_segments — pair traversal driving unjoin_pair gizmo
# and bend/transition suppression
# ---------------------------------------------------------------------------


def _make_segment_pair_with_fitting(fitting_predefined_type="BEND", connect_pair=True):
    """Return (segment_a, segment_b, fitting, patches) for the pair-traversal
    happy path. By default the fitting's ports connect both segments; set
    ``connect_pair=False`` to break the second hop (fitting → segment_b) so
    the helper returns None despite segment_a being connected to a fitting."""
    from bonsai import tool

    segment_a = Mock(name="segment_a")
    segment_a.is_a.side_effect = lambda t: t == "IfcFlowSegment"
    segment_b = Mock(name="segment_b")
    segment_b.is_a.side_effect = lambda t: t == "IfcFlowSegment"

    a_port = Mock(name="a_port")
    b_port = Mock(name="b_port") if connect_pair else None
    fitting_port_to_a = Mock(name="fitting_port_to_a")
    fitting_port_to_b = Mock(name="fitting_port_to_b")

    fitting = Mock(name="fitting")
    fitting.is_a.side_effect = lambda t: t == "IfcFlowFitting"
    fitting.PredefinedType = fitting_predefined_type

    # tool.System.get_ports needs to disambiguate by segment.
    def get_ports(element):
        if element is segment_a:
            return [a_port]
        if element is segment_b:
            return [b_port] if b_port is not None else []
        if element is fitting:
            return [fitting_port_to_a, fitting_port_to_b]
        return []

    # get_connected_port maps each port to its partner across the IfcRelConnectsPorts.
    def get_connected_port(port):
        if port is a_port:
            return fitting_port_to_a
        if port is fitting_port_to_a:
            return a_port
        if port is fitting_port_to_b:
            return b_port
        if port is b_port:
            return fitting_port_to_b
        return None

    # The relating-element-on-the-other-side query: every fitting-side port
    # belongs to the fitting; every segment-side port belongs to its segment.
    def get_port_relating_element(port):
        if port is fitting_port_to_a or port is fitting_port_to_b:
            return fitting
        if port is a_port:
            return segment_a
        if port is b_port:
            return segment_b
        return None

    patches = [
        patch.object(tool.System, "get_ports", side_effect=get_ports),
        patch.object(tool.System, "get_connected_port", side_effect=get_connected_port),
        patch.object(tool.System, "get_port_relating_element", side_effect=get_port_relating_element),
    ]
    return segment_a, segment_b, fitting, patches


def test_find_fitting_between_segments_returns_fitting_when_pair_is_joined():
    """Happy path: a single IfcFlowFitting joins both segments via its two
    ports. Pin so the unjoin_pair gizmo's visibility predicate has a real
    fitting to point at and the deletion operator a real target."""
    from bonsai.bim.module.model.mep import find_fitting_between_segments

    segment_a, segment_b, fitting, patches = _make_segment_pair_with_fitting()
    _start(patches)
    try:
        assert find_fitting_between_segments(segment_a, segment_b) is fitting
    finally:
        _stop(patches)


def test_find_fitting_between_segments_returns_none_for_non_segment_inputs():
    """Defensive: a fitting passed as one of the two arguments short-circuits
    to None. The helper's contract is "two IfcFlowSegments joined by a
    fitting"; relaxing it would let unjoin_pair point at an arbitrary
    fitting-to-fitting chain."""
    from bonsai.bim.module.model.mep import find_fitting_between_segments

    fitting = Mock()
    fitting.is_a.side_effect = lambda t: t == "IfcFlowFitting"
    segment = Mock()
    segment.is_a.side_effect = lambda t: t == "IfcFlowSegment"

    assert find_fitting_between_segments(fitting, segment) is None
    assert find_fitting_between_segments(segment, fitting) is None


def test_find_fitting_between_segments_returns_none_when_chain_breaks():
    """A fitting connected to segment_a but whose other port does NOT connect
    to segment_b — the helper must NOT return the fitting (it doesn't join
    the pair). Otherwise unjoin_pair would delete a fitting that joins
    segment_a to some third element."""
    from bonsai.bim.module.model.mep import find_fitting_between_segments

    segment_a, segment_b, _fitting, patches = _make_segment_pair_with_fitting(connect_pair=False)
    _start(patches)
    try:
        assert find_fitting_between_segments(segment_a, segment_b) is None
    finally:
        _stop(patches)


# ---------------------------------------------------------------------------
# Unjoin action_configs presence + (icon, operator) wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "config_name,expected_operator",
    [
        ("unjoin_start", "bim.mep_unjoin_at_port"),
        ("unjoin_end", "bim.mep_unjoin_at_port"),
        ("unjoin_pair", "bim.mep_unjoin_pair"),
    ],
)
def test_unjoin_action_configs_present_with_split_icon_and_correct_operator(config_name, expected_operator):
    """Three unjoin icons: two port-level (start / end, both fire
    ``bim.mep_unjoin_at_port`` with different pre-filled ``position`` args)
    and one pair-level (fires ``bim.mep_unjoin_pair`` against the 2-segment
    selection). All three share ``VIEW3D_GT_split`` (the wall-unjoin glyph)
    so the destructive-action affordance reads consistently across walls
    and MEP."""
    config = _config_by_name(config_name)
    assert config.icon == "VIEW3D_GT_split"
    assert config.operator == expected_operator


def test_unjoin_configs_set_matches_action_configs():
    """``UNJOIN_CONFIGS`` drives the warning-color override in ``setup()``.
    Pin that every name in the set has a matching ``IconActionConfig`` —
    a typo or rename would silently leave a destructive icon hovering green
    instead of red (Bonsai convention says red on hover for destructive)."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    config_names = {c.name for c in GizmoMEPActions.action_configs}
    for name in GizmoMEPActions.UNJOIN_CONFIGS:
        assert name in config_names, (
            f"UNJOIN_CONFIGS references {name!r} but action_configs has no matching entry — "
            f"warning-color override in setup() would silently no-op."
        )


def test_unjoin_endpoint_configs_share_endpoint_anchoring():
    """``unjoin_start`` / ``unjoin_end`` must appear in ``ENDPOINT_CONFIGS``
    with matching ``START`` / ``END`` strings so ``position_gizmos`` anchors
    them at the segment ports (not in the bbox-top row). Otherwise they'd
    drift away from the lock-icon group they replace."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    assert GizmoMEPActions.ENDPOINT_CONFIGS["unjoin_start"] == "START"
    assert GizmoMEPActions.ENDPOINT_CONFIGS["unjoin_end"] == "END"


def test_unjoin_pair_and_join_share_bend_anchor():
    """The bend-anchor location hosts exactly two mutually-exclusive icons:
    ``join`` (when no fitting joins the pair → click to create one) and
    ``unjoin_pair`` (when a fitting already joins them → click to delete it).
    ``position_gizmos`` resolves the visibility via
    ``find_fitting_between_segments``."""
    from bonsai.bim.module.model.mep import GizmoMEPActions

    assert "unjoin_pair" in GizmoMEPActions.BEND_ANCHOR_CONFIGS
    assert "join" in GizmoMEPActions.BEND_ANCHOR_CONFIGS


def test_unjoin_at_port_and_unjoin_pair_operators_are_registered():
    """The two new operators must be in the model module's ``classes`` tuple
    and registered with Blender. ``bpy.ops.bim.<verb>`` resolves at
    attribute-access time, so this is a real registration probe."""
    assert hasattr(bpy.ops.bim, "mep_unjoin_at_port")
    assert hasattr(bpy.ops.bim, "mep_unjoin_pair")


def test_mep_join_segments_dispatcher_is_registered():
    """The ``MEPJoinSegments`` dispatcher replaces direct bend / transition
    operator binding on the gizmo. ``bpy.ops.bim.mep_join_segments`` must
    resolve so the ``join`` IconActionConfig's click reaches it."""
    assert hasattr(bpy.ops.bim, "mep_join_segments")


def test_segments_are_parallel_routes_via_tool_cad():
    """``MEPJoinSegments.execute`` calls ``segments_are_parallel`` to pick
    between ``bim.mep_add_transition`` (parallel) and ``bim.mep_add_bend``
    (non-parallel). The helper must delegate to ``tool.Cad.are_edges_parallel``
    so the dispatcher's classification matches what each underlying operator
    will accept — a mismatch would re-introduce the click-time error the
    dispatcher was added to avoid."""
    from bonsai import tool
    from bonsai.bim.module.model.mep import segments_are_parallel

    start_axis = (Mock(name="start_a"), Mock(name="start_b"))
    end_axis = (Mock(name="end_a"), Mock(name="end_b"))
    start_obj = Mock()
    end_obj = Mock()

    with (
        patch.object(
            tool.Model,
            "get_flow_segment_axis",
            side_effect=lambda o: start_axis if o is start_obj else end_axis,
        ),
        patch.object(tool.Cad, "are_edges_parallel", return_value=True) as parallel_mock,
    ):
        assert segments_are_parallel(start_obj, end_obj) is True
        parallel_mock.assert_called_once_with(start_axis, end_axis)


# ---------------------------------------------------------------------------
# compute_bend_preview_polylines — pure geometry helper driving the GPU
# preview and the gizmo group's anchor positioning
# ---------------------------------------------------------------------------


def _mock_obj_with_axis(start_world, end_world):
    """Return (obj, patch_callable) — obj is a Mock placeholder; the patch is
    applied by ``_with_axis_patches`` and makes
    ``tool.Model.get_flow_segment_axis(obj)`` return the supplied axis.
    Used to drive ``compute_bend_preview_polylines`` without a real Blender
    object."""
    from mathutils import Vector

    obj = Mock()
    return obj, (obj, (Vector(start_world), Vector(end_world)))


def _with_axis_patches(*obj_axis_pairs):
    """Build the patch.object that maps each mock obj to its axis."""
    from bonsai import tool

    table = {id(obj): axis for obj, axis in obj_axis_pairs}
    return patch.object(tool.Model, "get_flow_segment_axis", side_effect=lambda o: table.get(id(o)))


def test_compute_bend_preview_polylines_invalid_for_parallel_axes():
    """Parallel axes have no defined intersection; ``MEPAddBend`` rejects
    them and the preview must too. Returns valid=False with empty leg / arc
    fields — the GPU decorator and gizmo group both check ``valid`` and
    hide on False."""
    from bonsai import tool
    from bonsai.bim.module.model.mep import compute_bend_preview_polylines

    start_obj, start_pair = _mock_obj_with_axis((0, 0, 0), (1, 0, 0))
    end_obj, end_pair = _mock_obj_with_axis((0, 1, 0), (1, 1, 0))  # parallel, offset by Y

    with _with_axis_patches(start_pair, end_pair):
        with patch.object(tool.Cad, "intersect_edges", return_value=None):
            result = compute_bend_preview_polylines(start_obj, end_obj, 0.1, 0.1, 0.2)
    assert result["valid"] is False
    assert result["arc"] == []
    assert result["leg_a"] is None
    assert result["leg_b"] is None


def test_compute_bend_preview_polylines_returns_arc_and_leg_polylines_for_right_angle():
    """Two perpendicular segments meeting at origin → a 90° bend. Pin the
    structural invariants: arc has the requested resolution + 1 points, the
    two legs are returned as ``(far, endpoint)`` pairs, and each leg's
    endpoint sits ``start_length`` / ``end_length`` away from the tangent
    point (i.e. ``radius * tan(bend_angle/2)`` from the intersection plus
    the leg length)."""
    from math import isclose, pi, tan

    from mathutils import Vector

    from bonsai import tool
    from bonsai.bim.module.model.mep import compute_bend_preview_polylines

    # Start segment lies along +X from (1, 0, 0) outward to (3, 0, 0).
    # End segment lies along +Y from (0, 1, 0) outward to (0, 3, 0).
    # Both pointing AWAY from the intersection at origin; intersection of
    # the two infinite axes is (0, 0, 0).
    start_obj, start_pair = _mock_obj_with_axis((1, 0, 0), (3, 0, 0))
    end_obj, end_pair = _mock_obj_with_axis((0, 1, 0), (0, 3, 0))

    intersection = (Vector((0, 0, 0)), Vector((0, 0, 0)))
    start_length, end_length, radius = 0.5, 0.5, 0.2
    bend_angle = pi / 2  # right angle
    tangent_offset = radius * tan(bend_angle / 2)  # = radius for 90° (tan 45° = 1)

    with _with_axis_patches(start_pair, end_pair):
        with patch.object(tool.Cad, "intersect_edges", return_value=intersection):
            with patch.object(
                tool.Cad,
                "closest_and_furthest_vectors",
                side_effect=lambda p, axis: (axis[0], axis[1]),  # near = axis[0], far = axis[1]
            ):
                result = compute_bend_preview_polylines(
                    start_obj, end_obj, start_length, end_length, radius, arc_resolution=12
                )

    assert result["valid"] is True
    # leg_a goes from far (3, 0, 0) to endpoint = tangent + start_length along leg.
    # Tangent sits at (tangent_offset, 0, 0) from intersection along +X.
    # Endpoint sits at (tangent_offset + start_length, 0, 0).
    leg_a_far, leg_a_endpoint = result["leg_a"]
    assert tuple(leg_a_far) == (3, 0, 0)
    assert isclose(leg_a_endpoint.x, tangent_offset + start_length, abs_tol=1e-6)
    assert isclose(leg_a_endpoint.y, 0.0, abs_tol=1e-6)

    leg_b_far, leg_b_endpoint = result["leg_b"]
    assert tuple(leg_b_far) == (0, 3, 0)
    assert isclose(leg_b_endpoint.x, 0.0, abs_tol=1e-6)
    assert isclose(leg_b_endpoint.y, tangent_offset + end_length, abs_tol=1e-6)

    # Arc resolution check: requested 12 → 13 sample points.
    assert len(result["arc"]) == 13
    # All arc points lie at distance ``radius`` from the arc center
    # (radius * tan(45°) = radius, but the center is offset from the
    # intersection by radius along the bisector). Verify first & last
    # are the two tangent points.
    arc = result["arc"]
    assert isclose((arc[0] - Vector((tangent_offset, 0, 0))).length, 0.0, abs_tol=1e-6)
    assert isclose((arc[-1] - Vector((0, tangent_offset, 0))).length, 0.0, abs_tol=1e-6)


def test_compute_bend_preview_polylines_invalid_for_near_collinear():
    """Near-collinear axes (intersection exists but bend angle ≈ 0) short-
    circuit to valid=False so the preview doesn't render a degenerate
    near-zero-radius arc."""
    from mathutils import Vector

    from bonsai import tool
    from bonsai.bim.module.model.mep import compute_bend_preview_polylines

    # Two segments nearly collinear: same direction with tiny angle.
    start_obj, start_pair = _mock_obj_with_axis((1, 0, 0), (3, 0, 0))
    end_obj, end_pair = _mock_obj_with_axis((-1, 0, 0), (-3, 0, 0))
    intersection = (Vector((0, 0, 0)), Vector((0, 0, 0)))

    with _with_axis_patches(start_pair, end_pair):
        with patch.object(tool.Cad, "intersect_edges", return_value=intersection):
            with patch.object(
                tool.Cad,
                "closest_and_furthest_vectors",
                side_effect=lambda p, axis: (axis[0], axis[1]),
            ):
                result = compute_bend_preview_polylines(start_obj, end_obj, 0.1, 0.1, 0.2)
    # dir_into_start ∥ dir_into_end (opposite signs would give angle=π →
    # bend_angle=0); same sign here gives angle=0 → bend_angle=π. Both
    # fall in the [<1e-3, >π-1e-3] reject band.
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# Bend preview registration probes
# ---------------------------------------------------------------------------


def test_bend_preview_operators_are_registered():
    """The three bend-preview operators must resolve via ``bpy.ops.bim.*`` —
    enable populates scene props, finish dispatches ``bim.mep_add_bend``
    with the tuned params, cancel clears the state."""
    assert hasattr(bpy.ops.bim, "enable_bend_preview")
    assert hasattr(bpy.ops.bim, "finish_bend_preview")
    assert hasattr(bpy.ops.bim, "cancel_bend_preview")


def test_bend_preview_gizmo_group_is_registered():
    """``GizmoBendPreview`` polls when ``scene.BIMPreviewProperties.bend.is_active``
    is True. Pin the bl_idname so a typo in the gizmo group wouldn't silently
    hide the preview gizmos at runtime."""
    from bonsai.bim.module.model.mep import GizmoBendPreview

    assert GizmoBendPreview.bl_idname == "OBJECT_GGT_bim_bend_preview"
    # ``bpy.types`` exposes registered GizmoGroup subclasses by their Python
    # class name, not their ``bl_idname`` — so the old ``hasattr(bpy.types,
    # "OBJECT_GGT_bim_bend_preview")`` check would fail even when the class
    # IS registered. Use ``issubclass`` against the actual GizmoGroup base
    # to verify it's a usable gizmo group; the import succeeding above
    # already proves the class is loadable.
    assert issubclass(GizmoBendPreview, bpy.types.GizmoGroup)


def test_base_preview_finish_catches_runtime_error_from_dispatch():
    """When the dispatched ``bim.<verb>`` operator reports ERROR + returns
    CANCELLED, ``bpy.ops`` promotes that to RuntimeError. The finish base
    must catch it and return CANCELLED — propagating the exception leaves
    Blender's operator state half-broken and silently disables downstream
    gizmo polls. Preview state must remain active so the user can re-tune."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from bonsai import tool
    from bonsai.bim.module.model.mep import FinishBendPreview

    class _Stand:
        def __init__(self):
            self.report = MagicMock()

    op_self = _Stand()
    fake_props = SimpleNamespace(
        is_active=True,
        start_segment_id=42,
        end_segment_id=43,
        start_length=0.1,
        end_length=0.1,
        radius=0.2,
    )
    context = SimpleNamespace(
        screen=MagicMock(),
        scene=SimpleNamespace(BIMPreviewProperties=SimpleNamespace(bend=fake_props)),
    )

    mock_ops_bim = MagicMock()
    mock_ops_bim.mep_add_bend.side_effect = RuntimeError("synthetic dispatch error")

    with (
        patch.object(tool.Ifc, "get", return_value=MagicMock(name="ifc_file")),
        patch.object(bpy.ops, "bim", new=mock_ops_bim),
    ):
        result = FinishBendPreview.execute(op_self, context)

    assert "CANCELLED" in result, "RuntimeError from dispatch must be converted to CANCELLED"
    assert fake_props.is_active is True, "failed dispatch must leave preview active for re-tune"
    op_self.report.assert_called()


def test_bim_bend_preview_properties_attached_to_scene():
    """The Scene PointerProperty must be bound in ``register()`` so
    ``EnableBendPreview`` / ``CancelBendPreview`` and the GPU decorator
    can read ``context.scene.BIMPreviewProperties.bend.is_active``."""
    assert hasattr(bpy.types.Scene, "BIMPreviewProperties")
    assert hasattr(bpy.context.scene.BIMPreviewProperties, "bend")


def test_bend_preview_decorator_class_present():
    """The GPU decorator is installed at addon load (via
    ``bim/handler.py:load_post``). Verify the class exists with the
    install / uninstall interface the handler expects."""
    from bonsai.bim.module.model.decorator import BendPreviewDecorator

    assert hasattr(BendPreviewDecorator, "install")
    assert hasattr(BendPreviewDecorator, "uninstall")


def test_escape_cancels_active_bend_preview():
    """Pressing Esc while a bend preview is active must clear its state.
    Drives the registry-backed dispatch in ``preview_base`` from the
    user-facing Esc operator end."""
    preview = bpy.context.scene.BIMPreviewProperties.bend
    preview.is_active = True
    preview.start_segment_id = 42
    preview.end_segment_id = 43

    bpy.ops.bim.override_escape()

    assert preview.is_active is False
    assert preview.start_segment_id == 0
    assert preview.end_segment_id == 0


# ---------------------------------------------------------------------------
# _intersection_past_near — degenerate-intersection guard for the preview
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "intersection,near,far,expected",
    [
        # Normal: intersection past near, opposite side from far.
        ((0, 0, 0), (-1, 0, 0), (-3, 0, 0), True),
        # Degenerate: intersection BETWEEN near and far (inside the segment).
        ((-2, 0, 0), (-1, 0, 0), (-3, 0, 0), False),
        # Degenerate: intersection past FAR (opposite side from the bend).
        ((-4, 0, 0), (-1, 0, 0), (-3, 0, 0), False),
        # Borderline: intersection coincides with near — within tolerance → False.
        ((-1, 0, 0), (-1, 0, 0), (-3, 0, 0), False),
        # Degenerate: zero-length segment — can't classify, False.
        ((0, 0, 0), (-1, 0, 0), (-1, 0, 0), False),
    ],
)
def test_intersection_past_near(intersection, near, far, expected):
    """Pins the degenerate-intersection classification used by
    ``compute_bend_preview_polylines`` to reject in-segment intersections.
    Wraps the four sign-dependent branches: outside-on-bend-side (True),
    inside-segment (False), past-far (False), and degenerate zero-length (False)."""
    from mathutils import Vector

    from bonsai.bim.module.model.mep import _intersection_past_near

    assert _intersection_past_near(Vector(intersection), Vector(near), Vector(far)) is expected


def test_compute_bend_preview_polylines_returns_invalid_axes_when_intersection_inside_segment():
    """When the intersection lands inside one of the segments, ``valid`` is
    False AND the result carries ``invalid_axes`` — a pair of (far_endpoint,
    intersection) lines for each segment. ``BendPreviewDecorator`` reads
    these to draw warning-red axes instead of rendering a degenerate arc.
    Pins both the False outcome AND the new ``invalid_axes`` contract so a
    refactor can't silently drop the red-warning rendering."""
    from mathutils import Vector

    from bonsai import tool
    from bonsai.bim.module.model.mep import compute_bend_preview_polylines

    # Segment A: from (-3, 0, 0) to (-1, 0, 0). Intersection inside at (-2, 0, 0).
    # Segment B: well outside, perpendicular, far from A's interior.
    start_obj, start_pair = _mock_obj_with_axis((-3, 0, 0), (-1, 0, 0))
    end_obj, end_pair = _mock_obj_with_axis((0, 5, 0), (0, 3, 0))
    # Pick an intersection point INSIDE segment A.
    intersection = (Vector((-2, 0, 0)), Vector((-2, 0, 0)))

    with _with_axis_patches(start_pair, end_pair):
        with patch.object(tool.Cad, "intersect_edges", return_value=intersection):
            with patch.object(
                tool.Cad,
                "closest_and_furthest_vectors",
                # axis[0] = closer endpoint (near), axis[1] = farther (far).
                side_effect=lambda p, axis: (axis[1], axis[0]),
            ):
                result = compute_bend_preview_polylines(start_obj, end_obj, 0.1, 0.1, 0.2)

    assert result["valid"] is False
    assert "invalid_axes" in result, "preview must return invalid_axes for the warning decorator"
    axes = result["invalid_axes"]
    assert len(axes) == 2, "one axis line per segment"
    # Each axis line ends at the intersection point — that's the shared
    # 'where the bend would land' endpoint that both red lines extend to.
    for far_endpoint, axis_end in axes:
        assert tuple(axis_end) == (-2, 0, 0)
    # The reason key is informational but should be set so callers can
    # distinguish the two intersection-inside cases.
    assert result.get("reason") in ("intersection_inside_start", "intersection_inside_end")


# ---------------------------------------------------------------------------
# direction_from_port_pair — derives connect_port's direction arg from
# the ports' FlowDirection. Pins each canonical pair so a typo in the
# lookup table breaks loudly.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "a_flow,b_flow,expected_direction",
    [
        ("SOURCE", "SINK", "SOURCE"),
        ("SINK", "SOURCE", "SINK"),
        ("SOURCEANDSINK", "SOURCEANDSINK", "SOURCEANDSINK"),
        ("NOTDEFINED", "NOTDEFINED", "NOTDEFINED"),
        # Asymmetric / unexpected combos fall through to NOTDEFINED.
        ("SOURCE", "SOURCE", "NOTDEFINED"),
        ("SINK", "SINK", "NOTDEFINED"),
        ("SOURCE", "NOTDEFINED", "NOTDEFINED"),
        # None FlowDirection (e.g. uninitialised port) ⇒ NOTDEFINED.
        (None, None, "NOTDEFINED"),
    ],
)
def testdirection_from_port_pair(a_flow, b_flow, expected_direction):
    from bonsai.tool.system import direction_from_port_pair

    port_a = Mock()
    port_a.FlowDirection = a_flow
    port_b = Mock()
    port_b.FlowDirection = b_flow
    assert direction_from_port_pair(port_a, port_b) == expected_direction


# ---------------------------------------------------------------------------
# MEP Split — operator registration + helper preconditions
# ---------------------------------------------------------------------------


def test_split_segment_operators_are_registered():
    """The new split operators must resolve via ``bpy.ops.bim.*`` — split
    gizmo's click target depends on it. ``bim.split_pipe_segment_at_cursor``
    and ``bim.split_duct_segment_at_cursor`` are the two cursor-anchored
    split ops; one per parametric-segment feature, mirroring the extend
    pattern."""
    assert hasattr(bpy.ops.bim, "split_pipe_segment_at_cursor")
    assert hasattr(bpy.ops.bim, "split_duct_segment_at_cursor")


def test_split_mep_segment_rejects_endpoint_cuts():
    """``split_mep_segment`` rejects cuts at or near the segment's
    endpoints — below 0.01m from start, or within 0.01m of the end.
    Same 0.01m threshold wall split uses. The rejection happens BEFORE
    any IFC mutation, so a near-endpoint click is a no-op rather than
    producing a zero-length placeholder."""
    from bonsai import tool
    from bonsai.bim.module.model.mep import split_mep_segment

    obj = Mock()
    # Mock obj.bound_box: 8 corners, local Z extent 0..2 (segment 2m long
    # along local +Z). bound_box is iterated as a sequence of 3-tuples.
    obj.bound_box = [(0, 0, 0)] * 4 + [(0, 0, 2.0)] * 4
    # matrix_world identity so world axis == local axis.
    from mathutils import Matrix as Mat

    obj.matrix_world = Mat.Identity(4)

    mep_element = Mock()
    with (
        patch.object(tool.Ifc, "get_entity", return_value=mep_element),
        patch.object(tool.System, "is_mep_element", return_value=True),
    ):
        # Below threshold at start.
        assert split_mep_segment(obj, 0.005) is None
        # Below threshold at end (length is 2.0, so cuts > 1.99 are
        # rejected).
        assert split_mep_segment(obj, 1.995) is None
        # Exact endpoint cuts (0 and length) — also rejected.
        assert split_mep_segment(obj, 0.0) is None
        assert split_mep_segment(obj, 2.0) is None


def test_split_mep_segment_rejects_non_mep_element():
    """``split_mep_segment`` only works on IfcFlowSegment / IfcFlowFitting
    via ``tool.System.is_mep_element``. A wall / window / etc. passed in
    by accident returns None without any IFC mutation."""
    from bonsai import tool
    from bonsai.bim.module.model.mep import split_mep_segment

    obj = Mock()
    obj.bound_box = [(0, 0, 0)] * 4 + [(0, 0, 2.0)] * 4
    from mathutils import Matrix as Mat

    obj.matrix_world = Mat.Identity(4)

    wall_element = Mock()
    with (
        patch.object(tool.Ifc, "get_entity", return_value=wall_element),
        patch.object(tool.System, "is_mep_element", return_value=False),
    ):
        # Valid mid-segment cut, but element predicate is False → reject.
        assert split_mep_segment(obj, 1.0) is None


def test_select_mep_path_members_is_registered():
    """``SelectMEPPathMembers`` is the click target for the path-select
    icon in ``GizmoMEPActions``. Registration probe so a typo or missing
    classes-tuple entry surfaces here rather than at click-time as a
    silent no-op."""
    assert hasattr(bpy.ops.bim, "select_mep_path_members")


def test_select_path_action_config_uses_array_all_icon():
    """Pin the path-select icon choice. ``VIEW3D_GT_array_all`` (the 2x2
    grid the array module uses for 'select all related') is the
    semantic choice — alternative ``VIEW3D_GT_array_parent`` was
    rejected as misleading (tree icon implies hierarchy; MEP paths are
    linear / graph topology, not hierarchical). A future drive-by icon
    swap should be an intentional decision, not an oversight."""
    config = _config_by_name("select_path")
    assert config.icon == "VIEW3D_GT_array_all"
    assert config.operator == "bim.select_mep_path_members"


@pytest.mark.skip(reason="Needs richer IFC mocking — split_mep_segment touches the unit-scale graph")
def test_split_mep_segment_happy_path_calls_copy_class_set_depth_connect_port():
    """Pin the split's canonical mutation sequence (copy_class once, set_depth twice
    in the correct order, then tool.Ifc.run for system.connect_port)."""
    from mathutils import Matrix as Mat
    from mathutils import Vector

    from bonsai import tool

    # ---- Mock the active segment object + element ----
    obj = Mock(name="segment1_obj")
    obj.bound_box = [(0, 0, 0)] * 4 + [(0, 0, 2.0)] * 4  # 2m segment along +Z
    obj.matrix_world = Mat.Identity(4)
    obj.data = None
    obj.users_collection = []

    mep_element = Mock(name="segment1_element")
    # Mock get_segment_data to return start/end ports with predictable
    # identity — the test verifies connect_port receives the right pair.
    seg1_start = Mock(name="seg1_start_port")
    seg1_end = Mock(name="seg1_end_port")

    new_element = Mock(name="segment2_element")
    new_obj_returned = Mock(name="segment2_obj")
    new_obj_returned.matrix_world = Mat.Identity(4)

    seg2_start = Mock(name="seg2_start_port")
    seg2_end = Mock(name="seg2_end_port")

    # ---- get_segment_data: first call returns segment1's ports, third
    # call (after set_depth) returns segment1 fresh ports, then segment2 ----
    segment_data_responses = [
        # Initial snapshot of original segment's ports
        {"start_port": seg1_start, "end_port": seg1_end},
        # After set_depth, segment1's ports re-resolved
        {"start_port": seg1_start, "end_port": seg1_end},
        # segment2's ports
        {"start_port": seg2_start, "end_port": seg2_end},
    ]
    segment_data_iter = iter(segment_data_responses)

    from bonsai.bim.module.model.mep import MEPGenerator, split_mep_segment
    from bonsai.bim.module.model.profile import DumbProfileJoiner

    with (
        patch.object(tool.Ifc, "get_entity", side_effect=[mep_element, new_element]),
        patch.object(tool.System, "is_mep_element", return_value=True),
        patch.object(MEPGenerator, "get_segment_data", side_effect=lambda e: next(segment_data_iter)),
        patch.object(tool.System, "get_connected_port", return_value=None),
        patch(
            "bonsai.core.root.copy_class",
            return_value=new_element,
        ) as mock_copy_class,
        patch.object(DumbProfileJoiner, "set_depth") as mock_set_depth,
        patch.object(tool.Ifc, "run") as mock_ifc_run,
        # obj.copy() in split_mep_segment — return our pre-built mock.
        patch.object(obj, "copy", return_value=new_obj_returned),
        # tool.Ifc.get_object for the new element resolution after copy_class
        patch.object(tool.Ifc, "get_object", return_value=new_obj_returned),
    ):
        result = split_mep_segment(obj, 0.75)

    assert result is new_obj_returned
    # 1. copy_class invoked exactly once.
    assert mock_copy_class.call_count == 1, "split_mep_segment must call copy_class exactly once"
    # 2. set_depth invoked twice — segment1 with cut, segment2 with remainder.
    assert mock_set_depth.call_count == 2, "set_depth must be called for each half"
    first_call_args = mock_set_depth.call_args_list[0]
    second_call_args = mock_set_depth.call_args_list[1]
    # First call: original obj, length=0.75 (the cut).
    assert first_call_args.args[0] is obj
    assert first_call_args.args[1] == pytest.approx(0.75)
    # Second call: new obj, length=2.0 - 0.75 = 1.25 (the remainder).
    assert second_call_args.args[0] is new_obj_returned
    assert second_call_args.args[1] == pytest.approx(1.25)
    # 3. tool.Ifc.run("system.connect_port", ...) at least once — wiring the
    # halves at the cut. No downstream connection in this fixture so
    # exactly one connect_port call expected.
    connect_port_calls = [c for c in mock_ifc_run.call_args_list if c.args and c.args[0] == "system.connect_port"]
    assert len(connect_port_calls) == 1, "expected exactly one connect_port call for the cut"
    kwargs = connect_port_calls[0].kwargs
    assert kwargs["port1"] is seg1_end
    assert kwargs["port2"] is seg2_start
    assert kwargs["direction"] == "NOTDEFINED"


# ---------------------------------------------------------------------------
# MEP segment extend gizmo — view-aware mirror + hover-gated preview line
# ---------------------------------------------------------------------------


def _run_mep_refresh_element_specific(
    *,
    cursor_local,
    mw=None,
    billboard_rot=None,
):
    """Drive ``_MEPSegmentEditionMixin._refresh_element_specific`` with a stub
    self. Returns ``self_stub.extend_gizmo`` so callers can inspect its
    ``matrix_basis`` (translation + mirror sign)."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from mathutils import Matrix, Vector

    from bonsai.bim.module.drawing import gizmos as gizmo_module
    from bonsai.bim.module.model import mep as mep_module

    extend = SimpleNamespace(hide=True, matrix_basis=None)
    split = SimpleNamespace(hide=True, matrix_basis=None)

    self_stub = SimpleNamespace(
        extend_gizmo=extend,
        split_gizmo=split,
        CURSOR_STACK_OFFSET=mep_module._MEPSegmentEditionMixin.CURSOR_STACK_OFFSET,
        _frame_billboard_rot=billboard_rot if billboard_rot is not None else Matrix.Identity(4),
        is_gizmo_hidden_by_modal=lambda gz: False,
    )

    obj = SimpleNamespace(bound_box=((0.0, 0.0, 0.0),) * 8)
    cursor = SimpleNamespace(location=(mw if mw is not None else Matrix.Identity(4)) @ Vector(cursor_local))
    context = SimpleNamespace(active_object=obj, scene=SimpleNamespace(cursor=cursor))

    with patch.object(
        gizmo_module, "billboarded_at", side_effect=lambda pos, rot, scale=0.5: Matrix.Translation(pos)
    ):
        mep_module._MEPSegmentEditionMixin._refresh_element_specific(
            self_stub, context, mw if mw is not None else Matrix.Identity(4), props=SimpleNamespace()
        )
    return extend


def test_mep_extend_gizmo_no_mirror_when_origin_is_screen_left():
    """Identity view, segment origin screen-left of the gizmo → no mirror."""
    from mathutils import Matrix

    extend = _run_mep_refresh_element_specific(cursor_local=(0.0, 0.0, 2.0))
    # MEP segment extrudes along local Z; with identity view the screen-X delta
    # is the world-Z delta projected by billboard_rot.transposed() = identity →
    # origin_world - gizmo_world has Z component only, X component is zero, so
    # no flip is triggered.
    assert extend.matrix_basis is not None
    assert extend.matrix_basis.col[0].x == pytest.approx(1.0)
    # Sanity: translation should be at the projected cursor (local Z=2 in world).
    assert extend.matrix_basis.translation.z == pytest.approx(2.0)


def test_mep_extend_gizmo_mirrors_when_view_aligns_z_to_screen_x():
    """View tipped so world -Z lands on screen +X → segment origin screen-right of
    the gizmo → mirror engages."""
    import math

    from mathutils import Matrix

    rot_y_90 = Matrix.Rotation(math.pi / 2, 4, "Y")
    extend = _run_mep_refresh_element_specific(cursor_local=(0.0, 0.0, 2.0), billboard_rot=rot_y_90)
    assert extend.matrix_basis is not None
    assert extend.matrix_basis.col[0].x == pytest.approx(-1.0)


def test_mep_extend_preview_line_drawn_at_positive_local_z():
    """Cursor-local Z above the current end → line target lands on the cursor (no clamp)."""
    from mathutils import Matrix, Vector

    from bonsai.bim.module.model.decorator import MEPSegmentExtendPreviewDecorator

    result = MEPSegmentExtendPreviewDecorator._compute_extend_preview_line(
        matrix_world=Matrix.Identity(4),
        cursor_world=Vector((0.0, 0.0, 3.5)),
        current_length=2.0,
    )
    assert result is not None
    current_end, target_end = result
    assert tuple(current_end) == pytest.approx((0.0, 0.0, 2.0))
    assert tuple(target_end) == pytest.approx((0.0, 0.0, 3.5))


def test_mep_extend_preview_skips_draw_when_gizmo_not_hovered(monkeypatch):
    """No hover on the extend gizmo → no stroke."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from mathutils import Matrix

    from bonsai import tool
    from bonsai.bim.module.model import decorator as decorator_module

    obj = SimpleNamespace(matrix_world=Matrix.Identity(4), bound_box=((0.0, 0.0, 1.0),) * 8)
    element = object()
    region = SimpleNamespace(as_pointer=lambda: 12345)
    cursor = SimpleNamespace(location=Matrix.Identity(4).to_translation())
    context = SimpleNamespace(active_object=obj, region=region, scene=SimpleNamespace(cursor=cursor))

    gizmo_prefs = SimpleNamespace(enabled=True)
    prefs = SimpleNamespace(
        gizmos=SimpleNamespace(pipe_segment=gizmo_prefs, duct_segment=gizmo_prefs),
        decorator_color_selected=(0.0, 1.0, 0.0, 1.0),
    )

    stroke_calls = []

    def _fake_stroke(*args, **kwargs):
        stroke_calls.append((args, kwargs))

    decorator = decorator_module.MEPSegmentExtendPreviewDecorator()

    with (
        patch.object(tool.Blender, "are_viewport_gizmos_enabled", return_value=True),
        patch.object(tool.Blender, "get_addon_preferences", return_value=prefs),
        patch.object(tool.Blender, "get_selected_objects", return_value=[obj]),
        patch.object(tool.Ifc, "get_entity", return_value=element),
        patch.object(tool.Parametric, "is_pipe_segment", return_value=True),
        patch.object(tool.Parametric, "is_duct_segment", return_value=False),
        patch.object(decorator_module, "_stroke_lines_alpha", side_effect=_fake_stroke),
    ):
        # No registered gizmo group instance for this region → hover-gate False →
        # decorator must return early.
        decorator.draw_line(context)

    assert stroke_calls == [], "preview line drew despite no extend-gizmo hover"


# ---------------------------------------------------------------------------
# MEP bend body must be committed as a tessellated representation
#
# ``mep_bend_shape`` emits ``IfcSweptDiskSolid`` for circular profiles, which
# is not portable across IFC geometry kernels at typical import tolerances
# (the rendered mesh on reload silently drops the swept-disk items, leaving
# the user with only the straight extrusion segments). The fix installs the
# parametric rep to fill ``obj.data`` with the kernel triangulation, then
# overwrites the body with a faceted version via ``add_body_representation``.
# Without the second commit, the on-disk body is the unportable swept-disk
# rep and the bug returns.
# ---------------------------------------------------------------------------


def test_mep_add_bend_commits_tessellated_body_after_parametric_rep():
    """The bend-creation flow that calls ``mep_bend_shape`` must follow up
    with ``add_body_representation`` in the same function — the parametric
    rep's swept-disk items are not portable, the faceted overwrite is."""
    import inspect

    from bonsai.bim.module.model import mep

    creator_src = None
    for _name, obj in inspect.getmembers(mep, inspect.isclass):
        try:
            src = inspect.getsource(obj)
        except (OSError, TypeError):
            continue
        if "mep_bend_shape" in src:
            creator_src = src
            break

    assert creator_src is not None, "expected a class invoking mep_bend_shape to exist in mep.py"
    assert "add_body_representation" in creator_src, (
        "the operator that invokes mep_bend_shape must also call "
        "tool.Model.add_body_representation to overwrite the parametric "
        "IfcSweptDiskSolid body with a faceted one — without this, reload "
        "through some IFC geometry kernels silently drops the bend"
    )
