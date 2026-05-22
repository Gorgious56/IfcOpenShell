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

"""Four wall-offset dimension gizmos (left / right / top / bottom) shared by door and
window edit gizmo groups — both fillings sit in a LAYER2 wall and the offset math is
identical."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from mathutils import Vector

import bonsai.tool as tool
from bonsai.bim.module.drawing.gizmos import DimensionGizmoConfig

if TYPE_CHECKING:
    import bpy
    import ifcopenshell

    FillingProps = "BIMDoorProperties | BIMWindowProperties"


class _HostWallGeom(NamedTuple):
    """Cached IFC-derived geometry of a filling's host wall (SI metres / radians,
    wall-local frame). ``x_angle`` is non-zero for slanted extrusions."""

    host_wall: ifcopenshell.entity_instance
    wall_obj: bpy.types.Object
    length: float
    height: float
    x_angle: float
    axis_min_x: float
    axis_max_x: float


# Avoids repeating the host-wall chain walk and LAYER2 geometry read per gizmo per frame.
# Cleared on load to avoid name-collision shadowing from a previous file.
_GEOM_CACHE = tool.Parametric.GenerationKeyedCache()


def clear_caches() -> None:
    _GEOM_CACHE.clear()


def _host_wall_geom(filling_obj: bpy.types.Object) -> _HostWallGeom | None:
    """Resolve and cache the filling's host-wall geometry.

    Returns ``None`` if any link breaks: filling not in IFC, no host opening,
    no host wall, host not an ``IfcWall``, host not a LAYER2 extruded wall,
    or host not present in the Blender scene."""
    return _GEOM_CACHE.get_or_compute(filling_obj.name, lambda: _compute_host_wall_geom(filling_obj))


def _compute_host_wall_geom(filling_obj: bpy.types.Object) -> _HostWallGeom | None:
    element = tool.Ifc.get_entity(filling_obj)
    if not element:
        return None
    host_wall = tool.Spatial.get_host_wall(element)
    if not host_wall:
        return None
    wall_obj = tool.Ifc.get_object(host_wall)
    length_height = tool.Wall.get_length_and_height(host_wall)
    axis_extent = tool.Wall.get_axis_local_extent(host_wall)
    x_angle = tool.Wall.get_x_angle(host_wall)
    if not (wall_obj and length_height and axis_extent and x_angle is not None):
        return None
    length, height = length_height
    axis_min_x, axis_max_x = axis_extent
    return _HostWallGeom(
        host_wall=host_wall,
        wall_obj=wall_obj,
        length=length,
        height=height,
        x_angle=x_angle,
        axis_min_x=axis_min_x,
        axis_max_x=axis_max_x,
    )


def _filling_signed_x_extent(props: FillingProps, host_wall_obj: bpy.types.Object) -> tuple[float, float]:
    """``(filling_origin_x, filling_signed_width)`` in wall-local frame.

    ``filling_signed_width`` is ``±props.overall_width`` depending on whether the
    filling's local +X aligns with or opposes the wall's local +X (the
    add-opening flow may rotate a filling 180° around Z when it lands on the
    wall's opposite face). Callers compose leftmost/rightmost edges from
    these two numbers so the offsets behave correctly for both orientations."""
    filling_obj = props.id_data
    filling_in_wall = host_wall_obj.matrix_world.inverted() @ filling_obj.matrix_world
    filling_origin_x = filling_in_wall.translation.x
    x_axis_in_wall_x = filling_in_wall.col[0].x
    sign = 1.0 if x_axis_in_wall_x >= 0.0 else -1.0
    return filling_origin_x, sign * props.overall_width


def has_host_wall(props: FillingProps) -> bool:
    """Visibility predicate for all four wall-offset gizmos.

    True when the filling resolves to a LAYER2 host wall present in the
    scene. The slope of a slanted wall lives in the IFC extrusion direction
    and in the wall mesh vertices — ``wall.matrix_world`` stays upright —
    so wall-local Z still equals world vertical Z and the offset arithmetic
    round-trips on slanted walls. ``geom.height`` is already the vertical
    projection of the slanted extrusion."""
    return _host_wall_geom(props.id_data) is not None


def get_wall_offset_left(props: FillingProps) -> float:
    """Distance from wall's start edge to the filling's leftmost edge, SI metres."""
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return 0.0
    filling_origin_x, signed_width = _filling_signed_x_extent(props, geom.wall_obj)
    return filling_origin_x + min(0.0, signed_width) - geom.axis_min_x


def get_wall_offset_right(props: FillingProps) -> float:
    """Distance from the filling's rightmost edge to wall's end edge, SI metres."""
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return 0.0
    filling_origin_x, signed_width = _filling_signed_x_extent(props, geom.wall_obj)
    return geom.axis_max_x - (filling_origin_x + max(0.0, signed_width))


def get_wall_offset_bottom(props: FillingProps) -> float:
    """Distance from wall's base to the filling's sill (bottom edge), SI metres."""
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return 0.0
    filling_in_wall = geom.wall_obj.matrix_world.inverted() @ props.id_data.matrix_world
    return filling_in_wall.translation.z


def get_wall_offset_top(props: FillingProps) -> float:
    """Distance from the filling's top edge to wall's top, SI metres."""
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return 0.0
    return geom.height - get_wall_offset_bottom(props) - props.overall_height


def _translate_along_wall_axis(
    props: FillingProps, host_wall_obj: bpy.types.Object, delta: float, axis_index: int
) -> None:
    """Shift ``props.id_data`` by ``delta`` SI metres along the wall's local
    X (``axis_index=0``) or Z (``axis_index=2``). Applies the translation in
    world space so a rotated wall's offset still tracks the wall's local
    axes — the gizmo drag operates in the filling's *intent* frame, not the
    Blender world frame."""
    if delta == 0.0:
        return
    direction_world = host_wall_obj.matrix_world.to_3x3().col[axis_index].normalized()
    props.id_data.matrix_world.translation = props.id_data.matrix_world.translation + direction_world * delta


def set_wall_offset_left(props: FillingProps, value: float) -> None:
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return
    delta = max(0.0, value) - get_wall_offset_left(props)
    _translate_along_wall_axis(props, geom.wall_obj, delta, axis_index=0)


def set_wall_offset_right(props: FillingProps, value: float) -> None:
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return
    # Right-offset increase pulls the filling toward the wall's start — opposite sign of the left offset.
    delta = get_wall_offset_right(props) - max(0.0, value)
    _translate_along_wall_axis(props, geom.wall_obj, delta, axis_index=0)


def set_wall_offset_bottom(props: FillingProps, value: float) -> None:
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return
    delta = max(0.0, value) - get_wall_offset_bottom(props)
    _translate_along_wall_axis(props, geom.wall_obj, delta, axis_index=2)


def set_wall_offset_top(props: FillingProps, value: float) -> None:
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return
    delta = get_wall_offset_top(props) - max(0.0, value)
    _translate_along_wall_axis(props, geom.wall_obj, delta, axis_index=2)


# -----------------------------------------------------------------------------
# Gizmo placement
# -----------------------------------------------------------------------------
# All four arrows anchor at the **wall** edge and point **toward the filling** —
# the visual is "this is the gap between wall edge and filling edge". The arrow
# tip lands on the filling, the value reads as the gap magnitude, and dragging
# the tip "outward" stretches the gap (which moves the filling away from that
# wall edge).
#
# Left/right need a sign flip via :data:`DimensionGizmoConfig.compute_value`
# when the filling is 180°-rotated around Z relative to the wall — the filling's
# local +X then points the opposite world direction, so the dim arrow would
# render reversed without the flip. The gizmo system reverses the dim render
# 180° around Z whenever ``compute_value`` is negative; we lean on that to
# get the right visual direction in both orientations. Apply paths take
# ``abs(v)`` so the user-facing offset stays positive regardless of sign
# convention.
#
# Top/bottom don't need this — a 180° rotation around Z does not flip the Z
# axis, so the filling's local Z always agrees with the wall's local Z.


def _filling_x_sign(props: FillingProps) -> float:
    """+1 if the filling's local +X aligns with the wall's local +X, else -1."""
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return 1.0
    filling_in_wall = geom.wall_obj.matrix_world.inverted() @ props.id_data.matrix_world
    return 1.0 if filling_in_wall.col[0].x >= 0.0 else -1.0


def _wall_edge_in_filling_local(props: FillingProps, wall_local_x: float) -> Vector:
    """A wall-edge anchor (left edge at ``axis_min_x``, right edge at
    ``axis_max_x``) expressed in filling-local space, with Y zeroed and Z set
    to the filling's vertical mid-height for visual balance."""
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return Vector((0.0, 0.0, props.overall_height / 2))
    wall_edge_world = geom.wall_obj.matrix_world @ Vector((wall_local_x, 0.0, 0.0))
    pos = props.id_data.matrix_world.inverted() @ wall_edge_world
    return Vector((pos.x, 0.0, props.overall_height / 2))


def left_offset_position(props: FillingProps) -> Vector:
    """Wall-start edge in filling-local frame, at filling's vertical mid-height.

    Uses the IFC axis-line endpoint (via the cached ``axis_min_x``) rather
    than ``wall_obj.bound_box`` — for walls whose Blender mesh bounds drift
    from the IFC axis (trimmed walls, walls with end openings, edited axis
    representations), bound-box would anchor the arrow at the mesh edge
    while ``get_wall_offset_left`` measures from the IFC axis end. IFC is
    the authoritative source for parametric-wall geometry."""
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return Vector((0.0, 0.0, props.overall_height / 2))
    return _wall_edge_in_filling_local(props, geom.axis_min_x)


def right_offset_position(props: FillingProps) -> Vector:
    """Wall-end edge in filling-local frame, at filling's vertical mid-height.

    Same IFC-axis source as :func:`left_offset_position` — keeps the gizmo
    anchor and the dim value consistent."""
    geom = _host_wall_geom(props.id_data)
    if not geom:
        return Vector((0.0, 0.0, props.overall_height / 2))
    return _wall_edge_in_filling_local(props, geom.axis_max_x)


def bottom_offset_position(props: FillingProps) -> Vector:
    """Wall-base in filling-local Z = ``-bottom_offset`` below the filling origin."""
    return Vector((props.overall_width / 2, 0.0, -get_wall_offset_bottom(props)))


def top_offset_position(props: FillingProps) -> Vector:
    """Wall-top in filling-local Z = ``overall_height + top_offset`` above the filling origin."""
    return Vector((props.overall_width / 2, 0.0, props.overall_height + get_wall_offset_top(props)))


def get_wall_offset_left_signed(props: FillingProps) -> float:
    return _filling_x_sign(props) * get_wall_offset_left(props)


def get_wall_offset_right_signed(props: FillingProps) -> float:
    return _filling_x_sign(props) * get_wall_offset_right(props)


# Large negative clamp on left/right offsets so the signed compute_value (which drives the
# negative-value render flip for 180°-rotated fillings) isn't truncated to 0 on the first
# drag frame; the apply lambdas re-clamp via ``abs(v)``.
_SIGNED_OFFSET_MIN = -1e6

# attr_name doubles as the GizmoPreferences{Door,Window} BoolProperty name — keep in sync
# with the registrations in bim/ui.py.
WALL_OFFSET_GIZMO_CONFIGS: list[DimensionGizmoConfig] = [
    DimensionGizmoConfig(
        attr_name="host_wall_offset_left",
        axis=(1, 0, 0),
        min_value=_SIGNED_OFFSET_MIN,
        visibility_condition=lambda p: has_host_wall(p),
        compute_value=lambda p: get_wall_offset_left_signed(p),
        apply_value=lambda p, v: set_wall_offset_left(p, abs(v)),
        matrix_position=lambda p: left_offset_position(p),
    ),
    DimensionGizmoConfig(
        attr_name="host_wall_offset_right",
        axis=(-1, 0, 0),
        min_value=_SIGNED_OFFSET_MIN,
        visibility_condition=lambda p: has_host_wall(p),
        compute_value=lambda p: get_wall_offset_right_signed(p),
        apply_value=lambda p, v: set_wall_offset_right(p, abs(v)),
        matrix_position=lambda p: right_offset_position(p),
    ),
    DimensionGizmoConfig(
        attr_name="host_wall_offset_bottom",
        axis=(0, 0, 1),
        visibility_condition=lambda p: has_host_wall(p),
        compute_value=lambda p: get_wall_offset_bottom(p),
        apply_value=lambda p, v: set_wall_offset_bottom(p, v),
        matrix_position=lambda p: bottom_offset_position(p),
    ),
    DimensionGizmoConfig(
        attr_name="host_wall_offset_top",
        axis=(0, 0, -1),
        visibility_condition=lambda p: has_host_wall(p),
        compute_value=lambda p: get_wall_offset_top(p),
        apply_value=lambda p, v: set_wall_offset_top(p, v),
        matrix_position=lambda p: top_offset_position(p),
    ),
]
