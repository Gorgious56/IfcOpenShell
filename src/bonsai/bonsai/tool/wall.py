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

"""Side-effect-free wall helpers — IFC reads and wall-axis geometry, callable from
gizmo lambdas without loading the wall's draft props. The world-space geometry helpers
are pure-math wrappers over ``bonsai.core.model``."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import ifcopenshell
import ifcopenshell.util.representation
import ifcopenshell.util.unit
from mathutils import Vector

import bonsai.core.model
import bonsai.core.tool
import bonsai.tool as tool

if TYPE_CHECKING:
    import bpy


class WallGeometry(TypedDict):
    anchor_x: float
    length: float
    height: float
    x_angle: float
    thickness: float
    offset: float


class Wall(bonsai.core.tool.Wall):
    @classmethod
    def get_length_and_height(cls, wall: ifcopenshell.entity_instance) -> tuple[float, float] | None:
        """SI length and vertical height of a LAYER2 extruded wall, or ``None`` for
        non-parametric bodies (sweeps, brep, non-extrusion booleans)."""
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
        """``(min_x, max_x)`` of the wall's IFC reference line in wall-local SI metres,
        or ``None``. Anchors wall-edge gizmos at IFC-authoritative ends — ``obj.bound_box``
        would drift on trimmed walls or walls with end openings."""
        representation = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
        if not representation:
            return None
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        p1, p2 = ifcopenshell.util.representation.get_reference_line(wall)
        x1, x2 = p1[0] * unit_scale, p2[0] * unit_scale
        return (min(x1, x2), max(x1, x2))

    @classmethod
    def get_x_angle(cls, wall: ifcopenshell.entity_instance) -> float | None:
        """Slanted-extrusion angle (radians) of a LAYER2 wall, zero for vertical walls,
        ``None`` for non-parametric bodies. Callers that assume wall-local Z == world Z
        must gate on this being zero."""
        representation = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
        if not representation:
            return None
        extrusion = tool.Model.get_extrusion(representation)
        if not extrusion:
            return None
        return tool.Model.get_existing_x_angle(extrusion)

    @classmethod
    def read_geometry(cls, obj: bpy.types.Object) -> WallGeometry | None:
        """Live wall geometry from IFC in SI metres/radians, or ``None`` for
        non-LAYER2-extruded walls. Shared by gizmo positioning and draft initialisation."""
        element = tool.Ifc.get_entity(obj)
        if not element or not tool.Blender.Modifier.is_wall(element):
            return None
        representation = ifcopenshell.util.representation.get_representation(element, "Model", "Body", "MODEL_VIEW")
        if not representation:
            return None
        extrusion = tool.Model.get_extrusion(representation)
        if not extrusion:
            return None
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        p1, p2 = ifcopenshell.util.representation.get_reference_line(element)
        layer_params = tool.Model.get_material_layer_parameters(element)
        x_angle = tool.Model.get_existing_x_angle(extrusion)
        return {
            "anchor_x": p1[0] * unit_scale,
            "length": (p2[0] - p1[0]) * unit_scale,
            "height": bonsai.core.model.vertical_height_from_extrusion_depth(extrusion.Depth * unit_scale, x_angle),
            "x_angle": x_angle,
            "thickness": layer_params["thickness"],
            "offset": layer_params["offset"],
        }

    @classmethod
    def collinear_boundary_world(cls, seg_a: tuple[Vector, Vector], seg_b: tuple[Vector, Vector]) -> Vector:
        """World-space midpoint of the closest endpoint pair across two wall axis segments —
        the anchor for Merge/Unjoin gizmos on collinear or already-joined walls."""
        return Vector(
            bonsai.core.model.closest_endpoint_midpoint(
                (tuple(seg_a[0]), tuple(seg_a[1])),
                (tuple(seg_b[0]), tuple(seg_b[1])),
            )
        )

    @classmethod
    def path_connection_location_world(
        cls,
        seg_self: tuple[Vector, Vector],
        self_conn_type: str,
        seg_other: tuple[Vector, Vector],
        other_conn_type: str,
        parallel_threshold: float = 0.9994,
    ) -> Vector:
        """World-space physical join point of an ``IfcRelConnectsPathElements`` — an
        endpoint for end-connected walls, the axis intersection for ATPATH junctions."""
        return Vector(
            bonsai.core.model.compute_path_connection_location(
                (tuple(seg_self[0]), tuple(seg_self[1])),
                self_conn_type,
                (tuple(seg_other[0]), tuple(seg_other[1])),
                other_conn_type,
                parallel_threshold,
            )
        )

    @classmethod
    def validate_for_parametric_edit(cls, obj: bpy.types.Object) -> str | None:
        """``None`` if the wall is parametrically editable, else a user-facing string naming
        the specific gap so the user can fix the precise blocker."""
        element = tool.Ifc.get_entity(obj)
        if not element:
            return "Object is not an IFC element."
        if not element.is_a("IfcWall"):
            return f"Object is an {element.is_a()}, not an IfcWall."
        if tool.Model.get_usage_type(element) != "LAYER2":
            return (
                "Wall has no IfcMaterialLayerSetUsage with LayerSetDirection AXIS2 (required for parametric editing)."
            )
        representation = ifcopenshell.util.representation.get_representation(element, "Model", "Body", "MODEL_VIEW")
        if not representation:
            return "Wall has no Model/Body/MODEL_VIEW representation to drive parametric dimensions."
        if not tool.Model.get_extrusion(representation):
            return (
                "Wall body is not an IfcExtrudedAreaSolid "
                "(e.g. a brep mesh or boolean result without a base extrusion)."
            )
        return None
