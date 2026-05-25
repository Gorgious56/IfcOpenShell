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

"""Regression guard against per-filling host-wall regeneration in
``RecalculateFill``.

``RecalculateFill`` is the operator that ``update_simple_openings`` dispatches
with every array sibling of an edited window/door in its selection. The
expensive step inside it is ``switch_representation`` on each voided host —
an IfcOpenShell CSG opening-subtraction. For an array of N windows on one
wall the host must be regenerated **once**, not N times; otherwise the
geometry stage scales linearly with the array size.

The test invokes ``bim.recalculate_fill`` with all N siblings selected and
counts the calls to the operator's module-local ``bonsai.core.geometry.
switch_representation``. Both the N=1 (independent ``workspace.py`` caller)
and the N=8 (array commit) shapes must converge to a single host regen."""

from unittest.mock import patch

import bpy
import pytest
from mathutils import Vector

import bonsai.core.geometry
import bonsai.tool as tool
from test.bim.bootstrap import NewIfc

pytestmark = pytest.mark.model


def _fake_axis2_layers():
    """``MaterialLayerParameters`` shape for a 0.1m AXIS2 wall — minimal enough
    to keep ``FilledOpeningGenerator.generate``'s wall-axis math happy when the
    wall is a plain cube rather than a parametric LAYER2 wall."""
    return {
        "layer_set_direction": "AXIS2",
        "offset": 0.0,
        "thickness": 0.05,
        "direction_sense": "POSITIVE",
        "thickness_si": 0.05,
    }


class TestRecalculateFillDedupesHostRegen(NewIfc):
    def _make_wall_with_n_doors(self, n: int):
        """Build a cube wall + ``n`` cube doors, each wired into the wall via
        ``FilledOpeningGenerator.generate`` so every door's ``FillsVoids``
        points at the same host. Doors are spaced along the wall's local X
        axis so the per-door ``closest_point_on_mesh`` raycast succeeds.

        Returns ``(wall_obj, doors)``."""
        from bonsai.bim.module.model.opening import FilledOpeningGenerator

        bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
        wall_obj = bpy.context.active_object
        assert wall_obj
        wall_obj.scale = (10.0, 0.1, 1.5)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        rprops = tool.Root.get_root_props()
        rprops.ifc_product = "IfcElement"
        bpy.ops.bim.assign_class(ifc_class="IfcWall")

        doors = []
        layers = _fake_axis2_layers()
        for i in range(n):
            x = -7.0 + i * 1.5
            bpy.ops.mesh.primitive_cube_add(size=0.4, location=(x, 0.0, 0.2))
            door_obj = bpy.context.active_object
            assert door_obj
            rprops.ifc_product = "IfcElement"
            bpy.ops.bim.assign_class(ifc_class="IfcDoor")
            bonsai.core.geometry.edit_object_placement(tool.Ifc, tool.Geometry, tool.Surveyor, obj=door_obj)

            target = Vector((x, 0.1, 1.0))
            with patch.object(tool.Model, "get_material_layer_parameters", return_value=layers):
                err = FilledOpeningGenerator().generate(door_obj, wall_obj, target=target)
            assert err is None, f"FilledOpeningGenerator.generate failed for door {i}: {err}"
            doors.append(door_obj)
        return wall_obj, doors

    def _count_wall_regens(self, wall_obj, doors):
        """Invoke ``bim.recalculate_fill`` with ``doors`` selected and count
        how many times ``switch_representation`` was invoked with ``wall_obj``
        as the target.

        The host wall is the expensive regen target (a CSG opening-subtraction
        per call); openings in the decomposition are cheap. Counting just the
        wall-targeted calls isolates the contract without depending on how
        many decomposed children ``get_decomposition`` returns.

        Patches the ``opening`` module's local ``bonsai`` reference (the
        railing-test idiom) rather than the dotted-string form, which is
        fragile when ``bonsai.bim`` has not been pre-imported."""
        from bonsai.bim.module.model import opening as opening_module

        with patch.object(opening_module, "bonsai") as mock_bonsai:
            with bpy.context.temp_override(selected_objects=doors):
                bpy.ops.bim.recalculate_fill()
            sr = mock_bonsai.core.geometry.switch_representation
            return sum(1 for call in sr.call_args_list if call.kwargs.get("obj") is wall_obj)

    def test_n_siblings_on_one_wall_regenerate_host_once(self):
        """The contract this file exists to pin: the host wall is regenerated
        once across the whole operation, not once per selected filling. With
        8 siblings sharing one wall the pre-fix path called the wall's
        ``switch_representation`` 8 times; post-fix it must be exactly 1."""
        wall, doors = self._make_wall_with_n_doors(n=8)
        wall_regens = self._count_wall_regens(wall, doors)
        assert wall_regens == 1, (
            f"RecalculateFill regenerated the host wall {wall_regens}× for "
            f"8 fillings — expected 1 (one regen per unique host)."
        )

    def test_single_filling_still_regenerates_host_once(self):
        """Independent-caller invariant: ``workspace.py``'s single-filling
        dispatch must keep its existing behaviour. N=1 produces one host
        regen — no regression in the common case."""
        wall, doors = self._make_wall_with_n_doors(n=1)
        wall_regens = self._count_wall_regens(wall, doors)
        assert wall_regens == 1, (
            f"RecalculateFill regenerated the host wall {wall_regens}× for a " f"single filling — expected 1."
        )
