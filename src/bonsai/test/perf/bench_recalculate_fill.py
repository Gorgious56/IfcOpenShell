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

"""Wall-clock benchmark for ``bim.recalculate_fill`` across array sizes.

Not collected by pytest (lives under ``test/perf/``, not ``test/bim/``);
invoke directly when re-validating the array-fillings perf fix or when
proposing further work on ``RecalculateFill`` / ``update_simple_openings``::

    blender -b -P src/bonsai/test/perf/bench_recalculate_fill.py

For each N in (1, 4, 8, 16) the script builds a fresh IFC project, creates
a cube wall and N cube doors, wires every door's ``FillsVoids`` to the
same wall via ``FilledOpeningGenerator``, then times
``bpy.ops.bim.recalculate_fill`` with all N doors selected (the dispatch
shape ``tool.Model.update_simple_openings`` produces when an array'd
window/door is finalised). 5 repeats per N; median + min + max reported.

The synthetic cube geometry keeps per-call CSG cost small, so absolute
numbers will be modest — what matters is the **scaling** across N. Pre-fix,
``RecalculateFill`` regenerated the host wall once per selected filling,
giving O(N²) total work; post-fix the regen is dedup'd to once per unique
host, so total time grows ~linearly with N (the per-filling
placement-commit work is what remains). The companion regression test
``test_recalculate_fill_scaling_stays_subquadratic`` pins the slope ratio."""

import statistics
import time
from unittest.mock import patch

import bpy
from mathutils import Vector

import bonsai.bim.handler
import bonsai.core.geometry
import bonsai.tool as tool
from bonsai.bim.ifc import IfcStore
from bonsai.bim.module.model.opening import FilledOpeningGenerator

_FAKE_AXIS2_LAYERS = {
    "layer_set_direction": "AXIS2",
    "offset": 0.0,
    "thickness": 0.05,
    "direction_sense": "POSITIVE",
    "thickness_si": 0.05,
}


def _reset_scene():
    """Fresh IFC project on an empty Blender scene — mirrors the ``NewIfc``
    bootstrap from the bim test lane so each N starts from a clean slate."""
    IfcStore.purge()
    bpy.ops.wm.read_homefile(app_template="")
    if bpy.data.objects:
        bpy.data.batch_remove(bpy.data.objects)
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    bonsai.bim.handler.load_post(None)
    bpy.ops.bim.create_project()


def _make_wall_with_n_doors(n: int):
    """Cube wall + ``n`` cube doors, each wired into the wall as a filling.
    Doors are spaced along local X so the per-door axis raycast succeeds."""
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
    wall_obj = bpy.context.active_object
    wall_obj.scale = (16.0, 0.1, 1.5)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    rprops = tool.Root.get_root_props()
    rprops.ifc_product = "IfcElement"
    bpy.ops.bim.assign_class(ifc_class="IfcWall")

    doors = []
    for i in range(n):
        x = -7.0 + i * 1.5
        bpy.ops.mesh.primitive_cube_add(size=0.4, location=(x, 0.0, 0.2))
        door_obj = bpy.context.active_object
        rprops.ifc_product = "IfcElement"
        bpy.ops.bim.assign_class(ifc_class="IfcDoor")
        bonsai.core.geometry.edit_object_placement(tool.Ifc, tool.Geometry, tool.Surveyor, obj=door_obj)
        target = Vector((x, 0.1, 1.0))
        with patch.object(tool.Model, "get_material_layer_parameters", return_value=_FAKE_AXIS2_LAYERS):
            err = FilledOpeningGenerator().generate(door_obj, wall_obj, target=target)
        assert err is None, f"generate failed at door {i}: {err}"
        doors.append(door_obj)
    return wall_obj, doors


def _time_recalculate_fill(doors, repeats: int):
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        with bpy.context.temp_override(selected_objects=doors):
            bpy.ops.bim.recalculate_fill()
        samples.append(time.perf_counter() - t0)
    return samples


def main():
    repeats = 5
    print("\n" + "=" * 72)
    print(f"bim.recalculate_fill benchmark — {repeats} repeats per N, ms")
    print("=" * 72)
    print(f"{'N':>4}  {'median':>9}  {'min':>9}  {'max':>9}  {'samples (ms)':<30}")
    print("-" * 72)
    for n in [1, 4, 8, 16]:
        _reset_scene()
        _wall, doors = _make_wall_with_n_doors(n=n)
        samples = _time_recalculate_fill(doors, repeats=repeats)
        samples_ms = [s * 1000 for s in samples]
        median_ms = statistics.median(samples_ms)
        print(
            f"{n:>4}  {median_ms:>8.2f}ms  {min(samples_ms):>8.2f}ms  {max(samples_ms):>8.2f}ms"
            f"  [{', '.join(f'{s:.2f}' for s in samples_ms)}]"
        )
    print("=" * 72 + "\n")


main()
