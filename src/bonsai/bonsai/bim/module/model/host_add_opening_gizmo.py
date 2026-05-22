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
LAYER2 walls, LAYER3 slabs, and BBIM_Roof-tagged roofs. The poll guards
host-host pairings so this gizmo never overlaps with the existing wall-join /
extend-vertically gizmos. The positioner dispatches on element type — walls
keep the existing axis-projection + camera-facing-Y math; LAYER3 hosts use a
world-Z face bias driven by the void object's elevation."""

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
    """Element types this gizmo can dock onto. Total predicate — accepts
    ``None`` (returns ``False``) so the poll's ``other_element`` check stays a
    single boolean expression. Kept as a module-level helper so ``poll()`` and
    tests can exercise the dispatch decision independently."""
    if element is None:
        return False
    return (
        tool.Blender.Modifier.is_wall(element)
        or tool.Blender.Modifier.is_slab(element)
        or tool.Blender.Modifier.is_roof(element)
    )


def _world_aabb_z(obj: bpy.types.Object) -> tuple[float, float]:
    """World-space (min_z, max_z) of an object's bounding box. Used to choose
    between the top and bottom face of a LAYER3 host without needing to know
    the IFC extrusion direction convention."""
    mw = obj.matrix_world
    corners = [mw @ Vector(c) for c in obj.bound_box]
    zs = [c.z for c in corners]
    return min(zs), max(zs)


class GizmoHostAddOpening(bpy.types.GizmoGroup, WallGeomCachedBillboardingMixin):
    """Activates when a host element (wall / slab / roof) is the active object
    and exactly one other selected object is *not* itself a host.

    Renders a single ``VIEW3D_GT_add_opening`` icon at the void object's
    projected location on the host. A click dispatches ``bim.add_opening``,
    which the operator and ``FilledOpeningGenerator`` already handle for any
    element with an ``HasOpenings`` inverse — no operator-side change needed.

    Per-frame positioning (``BillboardingGizmoGroupMixin``) keeps the icon
    facing the camera as the viewport orbits."""

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
        # Host + host pairings belong to the wall-join / extend-vertical / future
        # slab-edit gizmos — block them here so icons never stack.
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

        if tool.Blender.Modifier.is_wall(element):
            world_pos = wall_anchor(context, self, host_obj, other)
        else:
            world_pos = layer3_anchor(host_obj, other)
        if world_pos is None:
            return
        self.add_opening_icon.matrix_basis = gizmo.billboarded_at(world_pos, gizmo.get_billboard_rotation(context))


def wall_anchor(
    context: bpy.types.Context, group: bpy.types.GizmoGroup, wall_obj: bpy.types.Object, other: bpy.types.Object
) -> Vector | None:
    """Wall branch — preserves the prior ``GizmoWallAddOpening`` math: project
    the void onto the wall's reference-line X, clamp to the extents, and pick
    base-vs-top by camera visibility. Kept module-level so tests can drive it
    without instantiating a real ``GizmoGroup``."""
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
    """LAYER3 host branch (slabs, roofs) — anchor at the void's world XY,
    offset to the camera-facing face along world Z.

    Uses the host's world-AABB rather than reading the IFC extrusion direction:
    this works for parametric LAYER3 slabs and for mesh-bodied roofs alike,
    without diverging Phase-1 readers for each host class. For sloped slabs the
    icon may sit a few centimetres off the true face, which is acceptable for
    a click-target hint."""
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
