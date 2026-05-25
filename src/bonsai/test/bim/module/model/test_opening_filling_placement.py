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

"""Regression guard for the filling-placement commit at the end of
``FilledOpeningGenerator.generate``.

Contract: after ``generate`` mutates ``filling_obj.matrix_world`` to land the
filling on the wall axis, the filling's IFC ``ObjectPlacement`` must be
committed in lockstep. Without that commit, a later parametric-edit cancel
restores from the stale (spawn-time) placement and snaps the door to a
visually wrong position — most pronounced on slanted walls where the
spawn-time Z and the wall-axis Z differ sharply."""

from unittest.mock import patch

import bpy
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import numpy as np
import pytest
from mathutils import Vector

import bonsai.core.geometry
import bonsai.tool as tool
from test.bim.bootstrap import NewIfc

pytestmark = pytest.mark.model


def _fake_axis2_layers():
    """``MaterialLayerParameters`` shape for a 0.1m AXIS2 wall — minimal
    enough to keep ``get_wall_axis`` happy in the AXIS2 branch of
    ``FilledOpeningGenerator.generate``."""
    return {
        "layer_set_direction": "AXIS2",
        "offset": 0.0,
        "thickness": 0.05,
        "direction_sense": "POSITIVE",
        "thickness_si": 0.05,
    }


class TestGenerateCommitsFillingPlacement(NewIfc):
    def _make_cube_wall_and_door(self):
        """Create a plain-mesh wall + door pair on top of ``NewIfc``'s
        fresh-project fixture.

        The wall is a long, thin cube serving as the voided element; the door
        is a small cube spawned at a different location so the generate-time
        ``matrix_world`` re-positioning produces a visible delta from the spawn
        placement. Returns ``(wall_obj, door_obj)``."""
        bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
        wall_obj = bpy.context.active_object
        assert wall_obj
        wall_obj.scale = (5.0, 0.1, 1.5)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        rprops = tool.Root.get_root_props()
        rprops.ifc_product = "IfcElement"
        bpy.ops.bim.assign_class(ifc_class="IfcWall")

        bpy.ops.mesh.primitive_cube_add(size=0.4, location=(3.0, 0.0, 0.2))
        door_obj = bpy.context.active_object
        assert door_obj
        rprops.ifc_product = "IfcElement"
        bpy.ops.bim.assign_class(ifc_class="IfcDoor")

        bonsai.core.geometry.edit_object_placement(tool.Ifc, tool.Geometry, tool.Surveyor, obj=door_obj)
        return wall_obj, door_obj

    def test_generate_commits_filling_placement_to_ifc(self):
        """After ``FilledOpeningGenerator.generate`` returns, the filling's IFC
        ``ObjectPlacement`` must match its post-generate ``matrix_world``.

        Without this contract, the parametric-edit cancel path would read a
        stale placement on restore and snap the filling away from its visible
        position."""
        from bonsai.bim.module.model.opening import FilledOpeningGenerator

        wall_obj, door_obj = self._make_cube_wall_and_door()
        door_element = tool.Ifc.get_entity(door_obj)
        assert door_element is not None

        # Spawn placement was at (3.0, 0, 0.2). Pick a target that lands on the
        # wall's +Y face (Y ≈ 0.1 in the wall's local frame) so the initial
        # ``closest_point_on_mesh(distance=0.01)`` raycast succeeds — otherwise
        # the fallback re-uses the filling's spawn translation as the target and
        # ``new_matrix`` collapses back to the spawn position, leaving
        # ``is_moved`` False trivially regardless of whether the commit happens.
        target = Vector((-2.0, 0.1, 1.4))

        layers = _fake_axis2_layers()
        with patch.object(tool.Model, "get_material_layer_parameters", return_value=layers):
            FilledOpeningGenerator().generate(door_obj, wall_obj, target=target)

        # Sanity: generate actually moved the door — otherwise the contract below
        # is vacuously satisfied and the test wouldn't catch a missing commit.
        spawn_xyz = Vector((3.0, 0.0, 0.2))
        assert (door_obj.matrix_world.translation - spawn_xyz).length > 0.1, (
            "test scaffold is broken: generate() didn't measurably move the door, "
            "so the placement-commit assertion below would pass trivially."
        )

        # is_moved compares matrix_world to a recorded checksum; False means the
        # IFC placement was committed in sync with the visible matrix.
        assert not tool.Ifc.is_moved(door_obj), (
            "FilledOpeningGenerator.generate left door_obj.matrix_world out of sync "
            "with its IFC ObjectPlacement — a parametric-edit cancel would snap "
            "the door to the stale (spawn-time) position."
        )

        # Stronger pin: the committed placement must reproduce the visible matrix.
        matrix_np = ifcopenshell.util.placement.get_local_placement(door_element.ObjectPlacement).copy()
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        matrix_np[:3, 3] *= unit_scale
        committed = tool.Loader.apply_blender_offset_to_matrix_world(door_obj, matrix_np)
        visible = np.array(door_obj.matrix_world)
        assert np.allclose(committed, visible, atol=1e-6), (
            f"committed placement does not match visible matrix_world:\n" f"committed={committed}\nvisible={visible}"
        )
