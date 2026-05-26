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

"""Wall-merge contract: the resync targets the surviving wall.

The merge primitive deletes its second argument's Blender datablock — the
``bpy.data.objects.remove`` call invalidates the Python ``bpy_struct`` and
any subsequent attribute access on the deleted object raises
``ReferenceError``. The merge operator must therefore route its
post-mutation resync to the surviving (non-active) wall and promote that
wall to active so the selection retains a usable target."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.model


class _DeadableObj:
    """Test double for a Blender Object whose ``bpy_struct`` can be invalidated.

    Mirrors the Blender contract: once ``invalidate()`` runs, any attribute
    access raises ``ReferenceError`` — the exact exception type
    ``bpy.data.objects.remove`` causes downstream attribute lookups to raise.
    Comparison falls back to identity, matching Blender Object semantics for
    identity-based selection filtering."""

    def __init__(self, name: str) -> None:
        self._alive = True
        self._label = name

    def invalidate(self) -> None:
        self._alive = False

    def __getattr__(self, attr: str):
        if not self._alive:
            raise ReferenceError("StructRNA of type Object has been removed")
        return MagicMock(name=f"{self._label}.{attr}")

    def __repr__(self) -> str:
        return f"<_DeadableObj {self._label!r}>"


def test_merge_wall_resyncs_surviving_wall_not_active_object():
    """The resync helper must receive the non-active selected wall. The active
    wall is the deletion target of the merge primitive; resyncing it would
    touch a removed ``bpy_struct`` and raise ``ReferenceError``."""
    from bonsai.bim.module.model import wall as wall_module

    wall_active = MagicMock(name="wall_active")
    wall_other = MagicMock(name="wall_other")
    context = MagicMock(name="context")
    context.active_object = wall_active
    op_self = MagicMock(name="self")

    # The joiner's ``__init__`` needs a live IFC for unit-scale lookup; replace
    # the class wholesale so the test stays Blender / IFC-free.
    with (
        patch.object(
            wall_module.tool.Model,
            "get_selected_mesh_objects",
            return_value=[wall_active, wall_other],
        ),
        patch.object(wall_module, "DumbWallJoiner") as joiner_cls,
        patch.object(wall_module, "_maybe_resync_wall_props_from_ifc") as resync,
    ):
        result = wall_module.MergeWall._perform(op_self, context)

    assert result == {"FINISHED"}
    joiner_cls.return_value.merge.assert_called_once_with(wall_other, wall_active)
    resync.assert_called_once_with(wall_other)


def test_merge_wall_promotes_surviving_wall_to_active():
    """The merge deletes the previously active wall, so the selection loses
    its active object. The operator must promote the survivor so the user's
    downstream actions (gizmos, panels, follow-up operators) have a wall to
    target."""
    from bonsai.bim.module.model import wall as wall_module

    wall_active = MagicMock(name="wall_active")
    wall_other = MagicMock(name="wall_other")
    context = MagicMock(name="context")
    context.active_object = wall_active
    op_self = MagicMock(name="self")

    with (
        patch.object(
            wall_module.tool.Model,
            "get_selected_mesh_objects",
            return_value=[wall_active, wall_other],
        ),
        patch.object(wall_module, "DumbWallJoiner"),
        patch.object(wall_module, "_maybe_resync_wall_props_from_ifc"),
    ):
        result = wall_module.MergeWall._perform(op_self, context)

    assert result == {"FINISHED"}
    assert context.view_layer.objects.active is wall_other


def test_merge_wall_completes_when_merge_invalidates_active_object():
    """The merge primitive invalidates its second argument's ``bpy_struct``
    (matching ``bpy.data.objects.remove``'s real behaviour). The operator must
    complete without touching the dead object — the survivor is the only safe
    target for post-mutation work."""
    from bonsai.bim.module.model import wall as wall_module

    wall_active = _DeadableObj("wall_active")
    wall_other = _DeadableObj("wall_other")
    context = MagicMock(name="context")
    context.active_object = wall_active
    op_self = MagicMock(name="self")

    def merge_invalidates_second(_wall1, wall2):
        wall2.invalidate()
        return True

    def resync_touches_obj(obj):
        # The real resync helper reads ``obj.BIMObjectProperties`` to validate
        # the IFC entity. Reproducing that one attribute access is enough to
        # fail-fast on a removed ``bpy_struct``.
        _ = obj.BIMObjectProperties

    with (
        patch.object(
            wall_module.tool.Model,
            "get_selected_mesh_objects",
            return_value=[wall_active, wall_other],
        ),
        patch.object(wall_module, "DumbWallJoiner") as joiner_cls,
        patch.object(
            wall_module,
            "_maybe_resync_wall_props_from_ifc",
            side_effect=resync_touches_obj,
        ) as resync,
    ):
        joiner_cls.return_value.merge.side_effect = merge_invalidates_second
        result = wall_module.MergeWall._perform(op_self, context)

    assert result == {"FINISHED"}
    resync.assert_called_once_with(wall_other)


def test_merge_wall_reports_and_cancels_when_merge_no_ops():
    """When the merge primitive declines (walls not collinear), the operator
    must surface a user-visible warning, cancel, and leave the active object
    untouched. Silently swapping active on a no-op would be a confusing UX —
    the user clicked merge, saw nothing happen, yet their selection changed."""
    from bonsai.bim.module.model import wall as wall_module

    wall_active = MagicMock(name="wall_active")
    wall_other = MagicMock(name="wall_other")
    context = MagicMock(name="context")
    context.active_object = wall_active
    original_active = context.view_layer.objects.active
    op_self = MagicMock(name="self")

    with (
        patch.object(
            wall_module.tool.Model,
            "get_selected_mesh_objects",
            return_value=[wall_active, wall_other],
        ),
        patch.object(wall_module, "DumbWallJoiner") as joiner_cls,
        patch.object(wall_module, "_maybe_resync_wall_props_from_ifc") as resync,
    ):
        joiner_cls.return_value.merge.return_value = False
        result = wall_module.MergeWall._perform(op_self, context)

    assert result == {"CANCELLED"}
    op_self.report.assert_called_once_with({"WARNING"}, "Walls are not collinear — nothing merged.")
    resync.assert_not_called()
    assert context.view_layer.objects.active is original_active
