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

"""Regression tests for wall-split array detachment.

Invariant: when a wall that participates in a ``BBIM_Array`` (as parent or as
child) is split, the resulting split-off half must end up fully detached from
the array system — the same end state as Shift+D-duplicating an array
parent/child via the duplicate-move override. Without the scrub, the IFC-copy
that produces the split-off wall propagates the source's ``BBIM_Array`` pset
verbatim, and the duplicate's ``Parent`` GlobalId still points at the source's
GlobalId, so the duplicate poses as an array child of the source — breaking
array UI/handlers and preventing the split-off wall from being edited as a
standalone element."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.wall


def test_duplicate_wall_detaches_split_off_from_array_system():
    """The split-off wall must not inherit the source's array participation.

    The duplicate helper that backs ``bim.split_wall`` must invoke the shared
    detach helper with ``array_data=None`` so the inherited array pset (and any
    CHILD_OF constraint copied along with the bpy object) is removed."""
    from bonsai.bim.module.model.wall import DumbWallJoiner

    wall1 = MagicMock(name="wall1")
    wall1.users_collection = []
    wall2 = MagicMock(name="wall2")
    wall1.copy.return_value = wall2
    wall2.data.copy.return_value = MagicMock(name="wall2_data")

    element2 = MagicMock(name="element2")

    with (
        patch("bonsai.core.root.copy_class"),
        patch("bonsai.tool.Ifc.get_entity", return_value=element2),
        patch("bonsai.tool.Model.handle_array_on_copied_element") as scrub,
    ):
        # Bypass __init__: it requires a live IFC file for unit-scale lookup,
        # and duplicate_wall does not use any instance state from __init__.
        result = DumbWallJoiner.__new__(DumbWallJoiner).duplicate_wall(wall1)

    assert result is wall2
    scrub.assert_called_once_with(element2, array_data=None)


def test_duplicate_wall_skips_detach_when_ifc_entity_missing():
    """Defensive: if the freshly-copied bpy object has no resolvable IFC entity
    (race during teardown / extension reload), the duplicate helper must not
    crash by passing ``None`` into the detach helper. It silently skips the
    scrub — there is nothing to detach."""
    from bonsai.bim.module.model.wall import DumbWallJoiner

    wall1 = MagicMock(name="wall1")
    wall1.users_collection = []
    wall2 = MagicMock(name="wall2")
    wall1.copy.return_value = wall2
    wall2.data.copy.return_value = MagicMock(name="wall2_data")

    with (
        patch("bonsai.core.root.copy_class"),
        patch("bonsai.tool.Ifc.get_entity", return_value=None),
        patch("bonsai.tool.Model.handle_array_on_copied_element") as scrub,
    ):
        result = DumbWallJoiner.__new__(DumbWallJoiner).duplicate_wall(wall1)

    assert result is wall2
    scrub.assert_not_called()
