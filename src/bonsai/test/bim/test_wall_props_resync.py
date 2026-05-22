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

"""Regression coverage for the wall gizmo non-edit-mode prop-sync helper.

The wall gizmos that stay visible outside edit mode (cursor-anchored extend /
split, rotate-90, pen, toggle-openings) read positions from a per-object
draft ``BIMWallProperties``. The draft is populated at edit-mode entry and
re-primed by each IFC-mutating wall operator after it commits, so the gizmos
land on the post-mutation coordinates immediately.

Crucially, the resync runs from operator ``_execute`` (where ID writes are
allowed), NOT from ``GizmoGroup.refresh`` (where Blender forbids writes to ID
data and would raise ``AttributeError: Writing to ID classes in this context
is not allowed``).

These tests pin two contracts:

- ``_maybe_resync_wall_props_from_ifc`` re-primes the draft from IFC exactly
  when the wall is parametrically editable and *not* in an active draft
  session, and stays quiet otherwise.
- The wall gizmo group does NOT override ``refresh`` — the broken call site
  cannot silently re-appear.
"""

from math import pi
from unittest import mock

import pytest

pytestmark = pytest.mark.model


def _patched_wall_module():
    """Return a context that patches the three callees on the wall module so
    tests can inspect the orchestration without standing up real IFC / props."""
    import bonsai.bim.module.model.wall as wall_module

    return wall_module


class TestMaybeResyncWallPropsFromIfc:
    """Pin the guard logic so future refactors of the gizmo refresh path do
    not silently re-introduce the stale-prop class of bug."""

    def test_no_op_when_obj_is_none(self):
        wall = _patched_wall_module()
        with mock.patch.object(wall, "_read_wall_state_into_props") as read_into:
            wall._maybe_resync_wall_props_from_ifc(None)
        read_into.assert_not_called()

    def test_no_op_when_wall_is_not_parametrically_editable(self):
        """A non-LAYER2 wall, a wall without a body extrusion, or a non-wall
        object must not trigger a read — ``_read_wall_state_into_props``
        asserts a valid geometry and would crash."""
        wall = _patched_wall_module()
        obj = mock.Mock(name="obj")
        with (
            mock.patch.object(wall.tool.Wall, "validate_for_parametric_edit", return_value="not a LAYER2 wall"),
            mock.patch.object(wall, "_read_wall_state_into_props") as read_into,
            mock.patch.object(wall.tool.Model, "get_wall_props") as get_props,
        ):
            wall._maybe_resync_wall_props_from_ifc(obj)
        read_into.assert_not_called()
        get_props.assert_not_called()

    def test_no_op_when_in_edit_mode(self):
        """During a draft session the draft IS the source of truth — pulling
        from IFC here would discard the user's in-progress dimension drags."""
        wall = _patched_wall_module()
        obj = mock.Mock(name="obj")
        props = mock.Mock(name="props")
        props.is_editing = True
        with (
            mock.patch.object(wall.tool.Wall, "validate_for_parametric_edit", return_value=None),
            mock.patch.object(wall.tool.Model, "get_wall_props", return_value=props),
            mock.patch.object(wall, "_read_wall_state_into_props") as read_into,
        ):
            wall._maybe_resync_wall_props_from_ifc(obj)
        read_into.assert_not_called()

    def test_resyncs_when_editable_and_not_editing(self):
        """The load-bearing case: this is what fixes the reported bug. Without
        this call, the pen / cursor / rotate gizmos lag the wall geometry."""
        wall = _patched_wall_module()
        obj = mock.Mock(name="obj")
        props = mock.Mock(name="props")
        props.is_editing = False
        with (
            mock.patch.object(wall.tool.Wall, "validate_for_parametric_edit", return_value=None),
            mock.patch.object(wall.tool.Model, "get_wall_props", return_value=props),
            mock.patch.object(wall, "_read_wall_state_into_props") as read_into,
        ):
            wall._maybe_resync_wall_props_from_ifc(obj)
        read_into.assert_called_once_with(obj, props)


class TestOperatorPostMutationResync:
    """Pin that the IFC-mutating wall operators call
    ``_maybe_resync_wall_props_from_ifc`` after their mutation. Without this
    the always-visible gizmos lag the wall geometry by one operator
    invocation. Representative operator only — exhaustive coverage of all
    ten ops would be repetitive without catching independent bugs."""

    def test_extend_wall_height_to_cursor_resyncs_after_mutation(self):
        wall = _patched_wall_module()
        obj = mock.Mock(name="obj")
        obj.matrix_world.translation.z = 0.0
        context = mock.MagicMock(name="context")
        context.scene.cursor.location.z = 3.0
        # ``bpy.types.Operator`` subclasses can't be instantiated via ``__new__``
        # outside Blender's registration flow (bpy_struct guards it). Call
        # ``_execute`` as an unbound function with a plain mock for ``self`` so
        # the test only exercises the pure-Python orchestration. ``bpy.context``
        # is a read-only bpy_struct so the whole ``wall.bpy`` symbol is replaced
        # with a ``MagicMock`` instead of patching individual attributes.
        op_self = mock.Mock(name="self")
        fake_bpy = mock.MagicMock(name="bpy")

        with (
            mock.patch.object(wall, "_commit_active_wall_edit_if_any", return_value=obj),
            mock.patch.object(wall, "_maybe_resync_wall_props_from_ifc") as resync,
            mock.patch.object(wall, "bpy", fake_bpy),
        ):
            result = wall.ExtendWallHeightToCursor._execute(op_self, context)

        assert result == {"FINISHED"}
        resync.assert_called_once_with(obj)
        fake_bpy.ops.bim.change_extrusion_depth.assert_called_once_with(depth=3.0)


class TestWallGizmoGroupRefreshIsBase:
    """Regression guard: writing to ``BIMWallProperties`` from
    ``GizmoGroup.refresh`` is forbidden by Blender (ID write inside the
    refresh / depsgraph context). Resync must run from each IFC-mutating
    operator's ``_execute`` instead. Pinning that the wall gizmo group does
    not introduce its own ``refresh`` makes the broken call site impossible
    to silently re-add."""

    def test_wall_gizmo_group_does_not_override_refresh(self):
        from bonsai.bim.module.drawing.gizmos import BaseParametricGizmoGroup
        from bonsai.bim.module.model.wall import GizmoWallEdition

        assert GizmoWallEdition.refresh is BaseParametricGizmoGroup.refresh


class TestRotateWall90InvokeModifierMapping:
    """Pin the gizmo-click contract: a plain click rotates +90° (counter-clockwise
    around Z), Shift inverts to -90° (clockwise), Ctrl jumps to 180°. Ctrl wins
    over Shift if both are held. The mapping lives in ``RotateWall90.invoke``;
    callers that drive the operator directly (workspace shortcut, BDD scenario)
    skip ``invoke`` and pick up the property default."""

    def _invoke_with(self, *, ctrl: bool, shift: bool) -> float:
        # ``bpy.types.Operator`` subclasses can't be instantiated via ``__new__``
        # outside Blender's registration flow (bpy_struct guards it). Call
        # ``invoke`` as an unbound function with a plain mock for ``self`` so the
        # test only exercises the pure-Python modifier-key dispatch.
        wall = _patched_wall_module()
        op_self = mock.Mock(name="self")
        op_self.execute.return_value = {"FINISHED"}
        event = mock.Mock(name="event", ctrl=ctrl, shift=shift)
        context = mock.MagicMock(name="context")
        result = wall.RotateWall90.invoke(op_self, context, event)
        assert result == {"FINISHED"}
        op_self.execute.assert_called_once_with(context)
        return op_self.angle

    def test_plain_click_rotates_counter_clockwise_90(self):
        assert self._invoke_with(ctrl=False, shift=False) == pi / 2

    def test_shift_click_rotates_clockwise_90(self):
        assert self._invoke_with(ctrl=False, shift=True) == -pi / 2

    def test_ctrl_click_rotates_180(self):
        assert self._invoke_with(ctrl=True, shift=False) == pi

    def test_ctrl_wins_over_shift(self):
        assert self._invoke_with(ctrl=True, shift=True) == pi


class TestRotateWall90ExecuteForwardsAngle:
    """Pin the second half of the gizmo-click contract: whatever angle ``invoke``
    set, ``_execute`` must forward it as the ``angle=`` kwarg to ``bim.rotate_90``
    (the layer that actually rotates the matrix). Without this guard, a future
    edit could drop the kwarg and silently degrade every modifier-click back to
    the +90° default while ``TestRotateWall90InvokeModifierMapping`` still passes."""

    def test_execute_forwards_angle_to_rotate_90(self):
        # Same constraint as TestOperatorPostMutationResync: instantiate via a
        # plain ``Mock`` for ``self`` and replace the whole ``wall.bpy`` symbol
        # because ``bpy.context`` is a read-only bpy_struct.
        wall = _patched_wall_module()
        obj = mock.Mock(name="obj")
        context = mock.MagicMock(name="context")

        op_self = mock.Mock(name="self")
        op_self.angle = pi  # the Ctrl-click value; any non-default works

        fake_bpy = mock.MagicMock(name="bpy")

        with (
            mock.patch.object(wall, "_commit_active_wall_edit_if_any", return_value=obj),
            mock.patch.object(wall, "bpy", fake_bpy),
        ):
            result = wall.RotateWall90._execute(op_self, context)

        assert result == {"FINISHED"}
        fake_bpy.ops.bim.rotate_90.assert_called_once_with(axis="Z", angle=pi)
