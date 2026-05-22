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

"""Side-effect-free reads from ``IfcWall`` elements.

Lives in ``tool/`` (the bpy-permitted layer) so gizmo lambdas in ``bim/`` can
pull wall dimensions without the side effects of loading the wall's draft
``BIMWallProperties`` — the wall-edit pset loader mutates that PropertyGroup,
which would clobber the wall's own gizmo state if both the wall and a hosted
filling are selected. Reads exposed here only touch the IFC graph."""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.util.representation
import ifcopenshell.util.unit

import bonsai.core.model
import bonsai.core.tool
import bonsai.tool as tool


class Wall(bonsai.core.tool.Wall):
    @classmethod
    def get_length_and_height(cls, wall: ifcopenshell.entity_instance) -> tuple[float, float] | None:
        """SI length and vertical height of a LAYER2 extruded wall, or ``None``.

        Returns ``None`` for walls whose Body representation isn't an
        ``IfcExtrudedAreaSolid`` (or its boolean wrapper) — non-parametric
        walls, swept-disk walls, etc. Callers that need to display dimensions
        for those shapes need a different code path."""
        representation = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
        if not representation:
            return None
        extrusion = tool.Model.get_extrusion(representation)
        if not extrusion:
            return None
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        p1, p2 = ifcopenshell.util.representation.get_reference_line(wall)
        x_angle = tool.Model.get_existing_x_angle(extrusion)
        return bonsai.core.model.length_and_height_from_extrusion(
            extrusion_depth=extrusion.Depth,
            x_angle=x_angle,
            reference_line_x_extent=p2[0] - p1[0],
            unit_scale=unit_scale,
        )

    @classmethod
    def get_axis_local_extent(cls, wall: ifcopenshell.entity_instance) -> tuple[float, float] | None:
        """The wall's reference-line X extent in **SI metres**, wall-local frame.

        Returns ``(min_x, max_x)`` from the IFC axis polyline scaled to SI, or
        ``None`` for non-parametric walls. Pair with the wall's ``matrix_world``
        to anchor wall-edge gizmos at the IFC-authoritative ends — using
        ``obj.bound_box`` instead would drift on walls whose Blender mesh
        bounds don't coincide with the IFC axis (trimmed walls, openings at
        the end, etc.)."""
        representation = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
        if not representation:
            return None
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        p1, p2 = ifcopenshell.util.representation.get_reference_line(wall)
        x1, x2 = p1[0] * unit_scale, p2[0] * unit_scale
        return (min(x1, x2), max(x1, x2))

    @classmethod
    def get_x_angle(cls, wall: ifcopenshell.entity_instance) -> float | None:
        """Slanted-extrusion angle (radians) of a LAYER2 wall, or ``None``.

        Zero for the common vertical-wall case. Callers gate behaviour that
        assumes wall-local Z equals world vertical Z on this being zero —
        for tilted walls the wall's local Z runs along the slanted extrusion
        direction and that assumption breaks."""
        representation = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
        if not representation:
            return None
        extrusion = tool.Model.get_extrusion(representation)
        if not extrusion:
            return None
        return tool.Model.get_existing_x_angle(extrusion)
