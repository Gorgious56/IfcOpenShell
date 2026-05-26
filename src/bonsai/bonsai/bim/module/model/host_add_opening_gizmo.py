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

"""Generic single-click "Add Opening" gizmo for hosts (walls, slabs, roofs).

One GizmoGroup serves every IFC host type that exposes ``HasOpenings``:
parametric LAYER2 walls, any ``IfcSlab``, and any ``IfcRoof``. The poll
guards host-host pairings so this gizmo never overlaps with the existing
wall-join / extend-vertically gizmos. The positioner dispatches on element
type — walls use axis-projection + camera-facing-Y math (which requires the
parametric layer-set); slabs and roofs use a world-Z face bias driven by
the void object's elevation against the host's bounding box."""

import bpy
from mathutils import Vector

import bonsai.tool as tool
from bonsai.bim.module.drawing import gizmos as gizmo
from bonsai.bim.module.model.wall import (
    WallGeomCachedBillboardingMixin,
    get_wall_geom_cached,
    wall_camera_facing_icon_y,
)


def is_supported_host(element) -> bool:
    """Total predicate (None → False). Walls need parametric LAYER2 (the axis polyline +
    layer-set offsets drive the icon); slabs and roofs only need the bound box so any
    IfcSlab / IfcRoof qualifies regardless of parametric modifier state."""
    if element is None:
        return False
    return tool.Parametric.is_wall(element) or element.is_a("IfcSlab") or element.is_a("IfcRoof")


def _world_aabb_z(obj: bpy.types.Object) -> tuple[float, float]:
    """World-space ``(min_z, max_z)`` of the object's bound box."""
    mw = obj.matrix_world
    corners = [mw @ Vector(c) for c in obj.bound_box]
    zs = [c.z for c in corners]
    return min(zs), max(zs)


class GizmoHostAddOpening(bpy.types.GizmoGroup, WallGeomCachedBillboardingMixin):
    """Activates when a host element (wall / slab / roof) is the active object
    and exactly one other selected object is *not* itself a host.

    Renders a single ``VIEW3D_GT_add_opening`` icon at the void object's
    projected location on the host. A click dispatches ``bim.add_opening``,
    which handles any element exposing the ``HasOpenings`` inverse.

    Per-frame positioning keeps the icon facing the camera as the viewport
    orbits."""

    bl_idname = "OBJECT_GGT_bim_host_add_opening"
    bl_label = "Host Add Opening Gizmo"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"3D", "PERSISTENT"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        if not tool.Blender.are_viewport_gizmos_enabled():
            return False
        selected = tool.Blender.get_selected_objects()
        if len(selected) != 2:
            return False
        active = context.active_object
        if active is None or active not in selected:
            return False
        element = tool.Ifc.get_entity(active)
        if not element or not is_supported_host(element):
            return False
        # The operator itself filters on HasOpenings, but checking here keeps
        # the icon from appearing on host classes that can't accept openings
        # in the active IFC schema.
        if not hasattr(element, "HasOpenings"):
            return False
        other = next(o for o in selected if o is not active)
        # Host + host pairings are claimed by host-specific gizmos (wall-join,
        # extend-vertical, …) — suppress here so the add-opening icon never
        # stacks on top of them.
        if is_supported_host(tool.Ifc.get_entity(other)):
            return False
        return True

    def setup(self, context: bpy.types.Context) -> None:
        colors = self._icon_colors()
        self.add_opening_icon = self.setup_icon_gizmo(
            "VIEW3D_GT_add_opening", colors.default, colors.highlight, "bim.add_opening"
        )

    def position_gizmos(self, context: bpy.types.Context) -> None:
        host_obj = context.active_object
        if not host_obj:
            return
        selected = tool.Blender.get_selected_objects()
        other = next((o for o in selected if o is not host_obj), None)
        if not other:
            return
        element = tool.Ifc.get_entity(host_obj)
        if not element:
            return

        if tool.Parametric.is_wall(element):
            world_pos = wall_anchor(context, self, host_obj, other)
        else:
            world_pos = layer3_anchor(host_obj, other)
        if world_pos is None:
            return
        self.add_opening_icon.matrix_basis = gizmo.billboarded_at(world_pos, gizmo.get_billboard_rotation(context))


def wall_anchor(
    context: bpy.types.Context, group: bpy.types.GizmoGroup, wall_obj: bpy.types.Object, other: bpy.types.Object
) -> Vector | None:
    """World-space anchor for the add-opening icon on a wall host: void origin
    projected onto the wall reference-line X (clamped to wall extents), lifted to
    the camera-facing wall-local Y."""
    geom = get_wall_geom_cached(group, wall_obj)
    if not geom:
        return None
    mw = wall_obj.matrix_world
    wall_local = mw.inverted() @ other.matrix_world.translation
    local_x = max(geom["anchor_x"], min(wall_local.x, geom["anchor_x"] + geom["length"]))
    icon_y = wall_camera_facing_icon_y(context, mw, geom)
    base_world = mw @ Vector((local_x, icon_y, 0.0))
    top_world = mw @ Vector((local_x, icon_y, geom["height"] + gizmo.BaseParametricGizmoGroup.ICON_Z_OFFSET))
    return gizmo.BaseParametricGizmoGroup.pick_visible_anchor(context, base_world, top_world)


def layer3_anchor(host_obj: bpy.types.Object, other: bpy.types.Object) -> Vector:
    """World-space anchor for the add-opening icon on a LAYER3 host (slab / roof):
    void's world XY, lifted to the AABB face nearer the void. AABB-driven so it works
    for both parametric slabs and mesh-bodied roofs; may drift a few cm on sloped
    hosts (click-target hint only — the operator places the actual opening)."""
    min_z, max_z = _world_aabb_z(host_obj)
    other_z = other.matrix_world.translation.z
    face_z = max_z if other_z >= (min_z + max_z) * 0.5 else min_z
    offset = (
        gizmo.BaseParametricGizmoGroup.ICON_Z_OFFSET
        if face_z == max_z
        else -gizmo.BaseParametricGizmoGroup.ICON_Z_OFFSET
    )
    anchor_xy = other.matrix_world.translation.xy
    return Vector((anchor_xy.x, anchor_xy.y, face_z + offset))
