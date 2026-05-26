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

"""Unit tests for ``GizmoWallExtendVertically.poll()`` and the gizmo-group
mutual-exclusion contract.

These tests patch ``tool.Blender`` / ``tool.Ifc`` / ``tool.Model`` so the poll
logic can be exercised without a real IFC fixture. Each test pins one of the
gates ``poll()`` walks, so any silent regression in the gate order or in the
LAYER3-active / LAYER2-other contract is caught by a dedicated assertion.

The trailing parametrized test pins the selection-count partition between
``GizmoWallJoinIntersection`` (requires 2) and ``GizmoWallUnjoinSingle``
(requires 1). It belongs in this file because it is a poll-time guard for
the cross-group invariant — there is no way for both groups to be active at
once and have the user see stacked icons."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test.bim.module.model.conftest import make_context

pytestmark = pytest.mark.wall


def _patch_tools(prefs_on, selected, active_element, other_element, active_usage, other_usage):
    """Return a stack of patches that simulate one selection / IFC state for poll().

    ``prefs.gizmos.draw_gizmos_in_3d_viewport`` is the top-level toggle. The
    selection set, the IFC entity lookup, and the usage-type lookup are stubbed
    so the test only depends on the predicate ordering in poll()."""
    prefs = SimpleNamespace(gizmos=SimpleNamespace(draw_gizmos_in_3d_viewport=prefs_on))

    entity_map = {}
    usage_map = {}
    # active_element/other_element are matched by object identity from the selected set
    if len(selected) == 2:
        entity_map[id(selected[0])] = active_element
        entity_map[id(selected[1])] = other_element
        usage_map[id(active_element)] = active_usage
        usage_map[id(other_element)] = other_usage

    def get_entity(obj):
        return entity_map.get(id(obj))

    def get_usage_type(element):
        return usage_map.get(id(element))

    from bonsai import tool

    return [
        patch.object(tool.Blender, "get_addon_preferences", return_value=prefs),
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.Model, "get_usage_type", side_effect=get_usage_type),
    ]


def _run_poll(
    prefs_on, active_is_in_selected, len_override, active_usage, other_usage, active_has_entity=True, top_down=False
):
    from bonsai import tool
    from bonsai.bim.module.model.wall import GizmoWallExtendVertically

    slab_obj = object()
    wall_obj = object()
    active = slab_obj if active_is_in_selected else object()
    if len_override is None:
        selected = [slab_obj, wall_obj]
    else:
        selected = [object() for _ in range(len_override)]
        if active_is_in_selected and selected:
            active = selected[0]

    slab_element = object() if active_has_entity else None
    wall_element = object()

    patches = _patch_tools(prefs_on, selected, slab_element, wall_element, active_usage, other_usage)
    patches.append(patch.object(tool.Blender, "is_view_top_down", return_value=top_down))
    patches.append(patch("bonsai.bim.module.model.wall._is_fillet_corner_wall", return_value=False))
    for p in patches:
        p.start()
    try:
        return GizmoWallExtendVertically.poll(make_context(active=active, selected=selected))
    finally:
        for p in patches:
            p.stop()


def test_poll_accepts_layer3_active_with_layer2_other():
    assert (
        _run_poll(
            prefs_on=True, active_is_in_selected=True, len_override=None, active_usage="LAYER3", other_usage="LAYER2"
        )
        is True
    )


def test_poll_rejects_when_gizmo_toggle_off():
    assert (
        _run_poll(
            prefs_on=False, active_is_in_selected=True, len_override=None, active_usage="LAYER3", other_usage="LAYER2"
        )
        is False
    )


def test_poll_rejects_when_selection_count_is_not_two():
    assert (
        _run_poll(
            prefs_on=True, active_is_in_selected=True, len_override=3, active_usage="LAYER3", other_usage="LAYER2"
        )
        is False
    )
    assert (
        _run_poll(
            prefs_on=True, active_is_in_selected=True, len_override=1, active_usage="LAYER3", other_usage="LAYER2"
        )
        is False
    )


def test_poll_rejects_when_active_has_no_ifc_entity():
    assert (
        _run_poll(
            prefs_on=True,
            active_is_in_selected=True,
            len_override=None,
            active_usage="LAYER3",
            other_usage="LAYER2",
            active_has_entity=False,
        )
        is False
    )


def test_poll_rejects_when_active_is_not_layer3():
    # A LAYER2 active (wall) must NOT trigger this gizmo — the wall-join gizmo
    # owns that case, and extend_walls_to_underside expects the slab to be active.
    assert (
        _run_poll(
            prefs_on=True, active_is_in_selected=True, len_override=None, active_usage="LAYER2", other_usage="LAYER2"
        )
        is False
    )
    # Active with no usage at all (generic mesh, e.g. an opening blocker) is also rejected.
    assert (
        _run_poll(prefs_on=True, active_is_in_selected=True, len_override=None, active_usage=None, other_usage="LAYER2")
        is False
    )


def test_poll_rejects_when_other_is_not_layer2_wall():
    assert (
        _run_poll(
            prefs_on=True, active_is_in_selected=True, len_override=None, active_usage="LAYER3", other_usage="LAYER3"
        )
        is False
    )
    assert (
        _run_poll(prefs_on=True, active_is_in_selected=True, len_override=None, active_usage="LAYER3", other_usage=None)
        is False
    )


def test_poll_rejects_in_top_down_view():
    """Plan / top-down view has no meaningful vertical direction — the gizmo
    must hide entirely so the user falls back to the N-panel button."""
    assert (
        _run_poll(
            prefs_on=True,
            active_is_in_selected=True,
            len_override=None,
            active_usage="LAYER3",
            other_usage="LAYER2",
            top_down=True,
        )
        is False
    )


# ----------------------------------------------------------------------------
# Gizmo-group mutual exclusion — pins the len(selected) contract between
# GizmoWallJoinIntersection (requires 2) and GizmoWallUnjoinSingle (requires 1).
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("selection_len", [0, 1, 2, 3])
def test_gizmo_groups_never_poll_simultaneously(selection_len):
    """``GizmoWallJoinIntersection`` (2 walls) and ``GizmoWallUnjoinSingle`` (1
    wall) coexist only because their poll() gates partition the selection-count
    space — if both were to poll True for the same selection, Blender would
    activate both groups and stack icons. Pin the contract: for any
    selection length, at most ONE of the two groups returns True from poll().

    This is the regression guard. If a future edit relaxes either group's
    `len(selected)` check, this test catches the conflict before it ships."""
    from bonsai import tool
    from bonsai.bim.module.model.wall import (
        GizmoWallJoinIntersection,
        GizmoWallUnjoinSingle,
    )

    prefs = SimpleNamespace(gizmos=SimpleNamespace(draw_gizmos_in_3d_viewport=True))
    selected = [object() for _ in range(selection_len)]
    walls_element = object()

    patches = [
        patch.object(tool.Blender, "get_addon_preferences", return_value=prefs),
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(tool.Ifc, "get_entity", return_value=walls_element),
        patch.object(tool.Parametric, "is_path_connectable_wall", return_value=True),
        patch.object(tool.Model, "get_usage_type", return_value="LAYER2"),
    ]
    for p in patches:
        p.start()
    try:
        join_polls = GizmoWallJoinIntersection.poll(make_context())
        unjoin_polls = GizmoWallUnjoinSingle.poll(make_context())
    finally:
        for p in patches:
            p.stop()

    assert not (join_polls and unjoin_polls), (
        f"len(selected)={selection_len}: both gizmo groups polled True — "
        f"join={join_polls}, unjoin={unjoin_polls}. They must partition the space."
    )


def test_join_intersection_poll_accepts_layer2_plus_fillet_corner_pair():
    """A LAYER2 wall + fillet-corner two-wall selection must surface join-state
    icons. Per-icon gating inside the group's draw step keeps the fillet-only
    icon hidden for this pair, but the group itself must poll True so the
    unjoin icon at the existing junction remains clickable."""
    from bonsai import tool
    from bonsai.bim.module.model.wall import GizmoWallJoinIntersection

    prefs = SimpleNamespace(gizmos=SimpleNamespace(draw_gizmos_in_3d_viewport=True))
    layer2_obj = object()
    fillet_obj = object()
    selected = [layer2_obj, fillet_obj]
    entities = {id(layer2_obj): object(), id(fillet_obj): object()}

    def get_entity(obj):
        return entities.get(id(obj))

    patches = [
        patch.object(tool.Blender, "get_addon_preferences", return_value=prefs),
        patch.object(tool.Blender, "get_selected_objects", return_value=set(selected)),
        patch.object(tool.Ifc, "get_entity", side_effect=get_entity),
        patch.object(tool.Parametric, "is_path_connectable_wall", return_value=True),
        patch("bonsai.bim.module.model.wall._wall_fillet_preview_active", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        assert GizmoWallJoinIntersection.poll(make_context(active=layer2_obj, selected=selected)) is True
    finally:
        for p in patches:
            p.stop()
