# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2023 @Andrej730
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

from dataclasses import dataclass, field
from math import cos, pi, radians, sin, tan
from typing import Literal, Optional

import numpy as np
from typing_extensions import assert_never

import ifcopenshell.util.unit
from ifcopenshell.util.shape_builder import (
    TOLERANCE,
    SequenceOfVectors,
    ShapeBuilder,
    V,
    np_angle,
    np_angle_signed,
    np_intersect_line_line,
    np_lerp,
    np_normal,
    np_normalized,
    np_to_3d,
)
from ifcopenshell.util.unit import mm_to_m as mm

TERMINAL_TYPE = Literal[
    "180",
    "TO_END_POST",
    "TO_WALL",
    "TO_FLOOR",
    "TO_END_POST_AND_FLOOR",
]

# Geometric design constants for the WALL_MOUNTED_HANDRAIL railing type (millimetres).
TERMINAL_RADIUS_MM = 150
HANDRAIL_FILLET_RADIUS_MM = 100
SUPPORT_ARC_RADIUS_MM = 10
SUPPORT_DISK_DEPTH_MM = 20

# Default parameter values for ``add_railing_representation`` (millimetres).
DEFAULT_SUPPORT_SPACING_MM = 1000
DEFAULT_RAILING_DIAMETER_MM = 50
DEFAULT_CLEAR_WIDTH_MM = 40
DEFAULT_HEIGHT_MM = 1000


@dataclass
class RailingSupport:
    """Pure-geometry description of a single wall-mount support.

    A support consists of:

    - A 3-point polyline (base at the handrail, mid-arc, floor end)
      swept into a cylinder of radius ``arc_radius``.
    - A short disk extrusion (wall-attachment plate) at the floor end.

    All values are in IFC project units.
    """

    arc_polyline: np.ndarray  # shape (3, 3)
    arc_radius: float
    disk_position: np.ndarray  # shape (3,) — equal to arc_polyline[-1]
    disk_radius: float
    disk_depth: float
    disk_z_rotation: float  # rotation around Z applied to the disk's "Y" extrude axis


@dataclass
class WallMountedHandrailGeometry:
    """Pure-geometry description of a wall-mounted handrail.

    Decoupled from any IFC entity creation. The shared data structure is
    consumed by :func:`add_railing_representation` (which wraps it as an
    ``IfcShapeRepresentation``) and by viewport-only previews in authoring
    add-ons that need to update mesh state without mutating the IFC file.

    All values are in IFC project units.
    """

    handrail_polyline: np.ndarray  # shape (N, 3)
    handrail_arc_point_indices: list[int]
    handrail_radius: float
    supports: list[RailingSupport] = field(default_factory=list)


def compute_wall_mounted_handrail_geometry(
    *,
    railing_path: SequenceOfVectors,
    support_spacing: float,
    railing_diameter: float,
    clear_width: float,
    height: float,
    use_manual_supports: bool = False,
    terminal_type: TERMINAL_TYPE = "180",
    looped_path: bool = False,
    unit_scale: float = 1.0,
) -> WallMountedHandrailGeometry:
    """Compute pure geometric data for a wall-mounted handrail.

    The result can be wrapped into an ``IfcShapeRepresentation`` by
    :func:`add_railing_representation`, or converted directly to a Blender
    bmesh (or any other viewport mesh) for a live preview that does not
    mutate the IFC file.

    Geometric inputs (``railing_path``, ``support_spacing``,
    ``railing_diameter``, ``clear_width``, ``height``) are expected in IFC
    project units. ``unit_scale`` is used only to convert hard-coded
    millimetre constants (fillet radius, support rod radius, etc.) into
    project units.

    :param railing_path: Sequence of 3D points along the top of the
        handrail (not the centre). Must contain at least 2 points.
    :param support_spacing: Distance between automatic supports.
    :param railing_diameter: Handrail tube diameter.
    :param clear_width: Clear gap between the wall and the handrail tube.
    :param height: Total railing height (top of handrail to floor).
    :param use_manual_supports: If true, one support is placed on every
        non-collinear vertex of ``railing_path``; if false, supports are
        distributed automatically by ``support_spacing``.
    :param terminal_type: Style of the terminal end cap.
    :param looped_path: If true, the railing closes on its first point.
    :param unit_scale: Output of
        :func:`ifcopenshell.util.unit.calculate_unit_scale`. Defaults to
        1.0 (i.e. inputs are already in metres).
    """
    z_down = V(0, 0, -1)
    railing_radius = railing_diameter / 2
    # for calculations purposes we use height without railing radius
    height_below_handrail = height - railing_radius
    cap_type = terminal_type
    railing_coords: np.ndarray = np.subtract(railing_path, z_down * railing_radius)

    # mm-based stylistic constants converted to project units
    terminal_radius = mm(TERMINAL_RADIUS_MM) / unit_scale
    railing_fillet_radius = mm(HANDRAIL_FILLET_RADIUS_MM) / unit_scale
    support_length = clear_width + railing_radius
    support_arc_radius = mm(SUPPORT_ARC_RADIUS_MM) / unit_scale
    support_disk_radius = railing_radius
    support_disk_depth = mm(SUPPORT_DISK_DEPTH_MM) / unit_scale

    np_Z = 2
    np_XY = slice(2)
    np_YX = [1, 0]

    arc_points: list[np.ndarray] = []
    supports: list[RailingSupport] = []

    def collinear(d0: np.ndarray, d1: np.ndarray) -> bool:
        # Cross-product magnitude is linear near zero, so the test stays
        # numerically stable for near-parallel unit vectors. The natural
        # arccos(dot) formulation is not stable here: sub-ulp overshoot of
        # dot past 1.0 returns NaN, which would silently break the fillet
        # on straight subdivided edges. Anti-parallel vectors also collapse
        # |d0 × d1| to 0 — and that "no usable turn" outcome is what the
        # fillet caller wants, so we treat it as collinear too.
        return bool(np.linalg.norm(np.cross(d0, d1)) < TOLERANCE)

    def make_support(point: np.ndarray, railing_direction: np.ndarray) -> RailingSupport:
        """Build a pure-geometry support description from a point + railing direction."""
        ortho_dir = railing_direction[np_YX] * (1, -1)
        ortho_dir = np_normalized(np_to_3d(ortho_dir))
        arc_center = point + ortho_dir * support_length
        support_points = V(
            [
                point,
                arc_center - ortho_dir * support_length * cos(pi / 4) + z_down * support_length * sin(pi / 4),
                arc_center + z_down * support_length,
            ]
        )
        angle = np_angle_signed((0, 1), ortho_dir[np_XY])
        return RailingSupport(
            arc_polyline=support_points,
            arc_radius=support_arc_radius,
            disk_position=support_points[-1],
            disk_radius=support_disk_radius,
            disk_depth=support_disk_depth,
            disk_z_rotation=angle,
        )

    def get_fillet_points(v0: np.ndarray, v1: np.ndarray, v2: np.ndarray, radius: float) -> list[np.ndarray]:
        """get fillet points between edges v0v1 and v1v2"""
        dir1 = np_normalized(v0 - v1)
        dir2 = np_normalized(v2 - v1)
        edge_angle = np_angle(dir1, dir2)
        slide_distance = radius / tan(edge_angle / 2)

        fillet_v1co = v1 + (dir1 * slide_distance)
        fillet_v2co = v1 + (dir2 * slide_distance)

        normal = np_normal([v0, v1, v2])
        center = np_intersect_line_line(
            fillet_v1co,
            fillet_v1co + np.cross(normal, dir1),
            fillet_v2co,
            fillet_v2co + np.cross(normal, dir2),
        )[0]

        dir_ = np_normalized(np_lerp(fillet_v1co, fillet_v2co, 0.5) - center)
        midpointco = center + dir_ * radius
        return [fillet_v1co, midpointco, fillet_v2co]

    def _safe_get_fillet_points(
        v0: np.ndarray, v1: np.ndarray, v2: np.ndarray, radius: float
    ) -> Optional[list[np.ndarray]]:
        """Call ``get_fillet_points`` and return ``None`` if the result is
        numerically unusable.

        ``get_fillet_points`` divides by ``tan(edge_angle / 2)``, takes the
        normal of three points, and intersects two lines — each step can
        produce ``ZeroDivisionError`` (anti-parallel directions →
        ``edge_angle = 0``) or NaN (collinear vertices → zero-norm normal,
        zero-length edges → NaN direction). The caller decides what to do
        with the missing arc; this wrapper only signals "can't compute".
        """
        try:
            fillet_points = get_fillet_points(v0, v1, v2, radius)
        except (ZeroDivisionError, FloatingPointError):
            return None
        for fp in fillet_points:
            if np.any(np.isnan(fp)) or np.any(np.isinf(fp)):
                return None
        return fillet_points

    def add_arcs_on_turning_points(base_points: np.ndarray) -> np.ndarray:
        """add 3 point fillet arcs on turning points of the railing path"""
        if len(base_points) < 3:
            return base_points

        # looking for turning points by checking non-collinear edges
        output_points: list[np.ndarray] = list(base_points[:1])
        prev_dir = np_normalized(base_points[1] - base_points[0])
        i = 1
        while i < len(base_points) - 1:
            cur_dir = np_normalized(base_points[i + 1] - base_points[i])

            # Treat NaN cur_dir (zero-length edge → np_normalized of zero) as
            # collinear: a coincident path vertex carries no turn information,
            # so the safest fallback is "stay on the previous direction".
            cur_dir_is_nan = bool(np.any(np.isnan(cur_dir)))

            if cur_dir_is_nan or collinear(cur_dir, prev_dir):
                output_points.append(base_points[i])
            else:
                fillet_points = _safe_get_fillet_points(
                    base_points[i - 1], base_points[i], base_points[i + 1], railing_fillet_radius
                )
                if fillet_points is None:
                    # Numerically degenerate turn (anti-parallel directions,
                    # nearly-collinear triangle, etc.). Falling back to a
                    # sharp turn keeps the rest of the polyline real-valued
                    # instead of poisoning it with NaN.
                    output_points.append(base_points[i])
                else:
                    output_points.extend(fillet_points)
                    arc_points.append(fillet_points[1])

            # Only advance prev_dir when cur_dir is well-defined — keeping a
            # NaN prev_dir would cascade through every subsequent collinearity
            # check.
            if not cur_dir_is_nan:
                prev_dir = cur_dir
            i = i + 1

        if looped_path:
            output_points[0] = output_points[-1]
        else:
            output_points.append(base_points[-1])
        return V(output_points)

    def collect_supports(coords: np.ndarray, manual_supports: bool) -> None:
        """Populate ``supports`` based on the railing coordinates."""
        # simplified_coords is a list of points that form non-collinear edges
        simplified_coords: list[np.ndarray] = [coords[0]]
        prev_dir = np_normalized(coords[1] - coords[0])

        # iterating over each edge of the railing path
        for i in range(1, len(coords) - 1):
            cur_dir = np_normalized(coords[i + 1] - coords[i])

            if not collinear(cur_dir, prev_dir):
                simplified_coords.append(coords[i])
                prev_dir = cur_dir

            # for manual supports each vertex on the railing path edge
            # will be a point for a support
            elif manual_supports:
                supports.append(make_support(point=coords[i], railing_direction=cur_dir))

        simplified_coords.append(coords[-1])

        if manual_supports:
            return

        # create automatic supports based on the support spacing
        for i in range(len(simplified_coords) - 1):
            v0, v1 = simplified_coords[i : i + 2]
            edge = v1 - v0
            length: float = np.linalg.norm(edge)
            edge_dir = np_normalized(edge)
            n_supports, support_offset = divmod(length, support_spacing)
            n_supports = int(n_supports) + 1
            support_offset /= 2

            start_position = v0 + support_offset * edge_dir
            for support_i in range(n_supports):
                support_position = start_position + support_i * support_spacing * edge_dir
                supports.append(make_support(point=support_position, railing_direction=edge))

    def add_cap(
        railing_coords: np.ndarray, arc_points_list: list[np.ndarray], start: bool = False
    ) -> tuple[np.ndarray, list[np.ndarray]]:
        """add handrail terminal cap"""
        railing_coords_for_cap = railing_coords[::-1] if start else railing_coords
        arc_points_list = arc_points_list[::-1] if start else arc_points_list

        start_point: np.ndarray = railing_coords_for_cap[-1]
        cap_dir = railing_coords_for_cap[-1] - railing_coords_for_cap[-2]
        cap_dir = np_normalized(cap_dir)
        ortho_dir = np_to_3d(cap_dir[np_YX] * (1, -1))
        ortho_dir = np_normalized(ortho_dir)
        local_z_down = np.cross(cap_dir, ortho_dir)
        if start:
            ortho_dir = -ortho_dir

        arc_middle_point_cos = sin(radians(45))

        if cap_type in ("180", "TO_END_POST"):
            arc_point = start_point + cap_dir * terminal_radius + terminal_radius * local_z_down
            arc_points_list.append(arc_point)
            cap_coords = [arc_point, start_point + terminal_radius * 2 * local_z_down]

            if cap_type == "TO_END_POST":
                end_point = railing_coords_for_cap[-2].copy()
                end_point[np_Z] -= terminal_radius * 2
                cap_coords.append(end_point)

        elif cap_type == "TO_WALL":
            arc_point = (
                start_point
                + cap_dir * clear_width * arc_middle_point_cos
                + ortho_dir * clear_width * (1 - arc_middle_point_cos)
            )
            arc_points_list.append(arc_point)
            cap_coords = [arc_point, start_point + ortho_dir * clear_width + cap_dir * clear_width]

        elif cap_type == "TO_FLOOR":
            arc_point = (
                start_point
                + cap_dir * terminal_radius * arc_middle_point_cos
                + z_down * terminal_radius * (1 - arc_middle_point_cos)
            )
            arc_points_list.append(arc_point)
            arc_end = start_point + cap_dir * terminal_radius + terminal_radius * z_down
            cap_coords = [
                arc_point,
                arc_end,
                arc_end + z_down * (height_below_handrail - terminal_radius),
            ]

        elif cap_type == "TO_END_POST_AND_FLOOR":
            first_arc_end = start_point + cap_dir * terminal_radius + terminal_radius * local_z_down
            first_arc_coords = get_fillet_points(
                start_point, start_point + cap_dir * terminal_radius, first_arc_end, terminal_radius
            )
            arc_points_list.append(first_arc_coords[1])

            end_point = railing_coords_for_cap[-2].copy()
            end_point[np_Z] -= height_below_handrail
            second_arc_coords = get_fillet_points(
                first_arc_end, first_arc_end + local_z_down * terminal_radius, end_point, terminal_radius
            )
            arc_points_list.append(second_arc_coords[1])
            cap_coords = [start_point] + first_arc_coords + second_arc_coords + [end_point]
        else:
            assert_never(cap_type)

        railing_coords = np.vstack((railing_coords_for_cap, cap_coords))

        if start:
            railing_coords = railing_coords[::-1]
            arc_points_list = arc_points_list[::-1]
        return railing_coords, arc_points_list

    def get_arc_indices(points: np.ndarray, arc_pts: list[np.ndarray]) -> list[int]:
        points_ = points.copy()
        arc_indices = []
        i_base = 0
        for arc_point in arc_pts:
            for i, point in enumerate(points_):
                if np.allclose(arc_point, point):
                    current_index = i + i_base
                    arc_indices.append(current_index)
                    i_base = current_index + 1
                    break
            else:
                raise Exception(
                    f"Arc point '{arc_point}' is not present in points:\n{points_}\nFull points data:\n{points}"
                )
            points_ = points_[i + 1 :]
        return arc_indices

    # need to add first two points to the path
    # to create the turning arcs and supports on the last segment of the loop
    if looped_path:
        railing_coords = np.vstack((railing_coords, railing_coords[:2]))

    collect_supports(railing_coords, manual_supports=use_manual_supports)
    railing_coords = add_arcs_on_turning_points(railing_coords)

    if not looped_path and cap_type != "NONE":
        railing_coords, arc_points = add_cap(railing_coords, arc_points, start=True)
        railing_coords, arc_points = add_cap(railing_coords, arc_points, start=False)

    return WallMountedHandrailGeometry(
        handrail_polyline=railing_coords,
        handrail_arc_point_indices=get_arc_indices(railing_coords, arc_points),
        handrail_radius=railing_radius,
        supports=supports,
    )


def add_railing_representation(
    file: ifcopenshell.file,
    *,  # keywords only as this API implementation is probably not final
    # IfcGeometricRepresentationContext
    context: ifcopenshell.entity_instance,
    railing_type: Literal["WALL_MOUNTED_HANDRAIL"] = "WALL_MOUNTED_HANDRAIL",
    railing_path: SequenceOfVectors,
    use_manual_supports: bool = False,
    support_spacing: Optional[float] = None,
    railing_diameter: Optional[float] = None,
    clear_width: Optional[float] = None,
    terminal_type: TERMINAL_TYPE = "180",
    height: Optional[float] = None,
    looped_path: bool = False,
    unit_scale: Optional[float] = None,
) -> ifcopenshell.entity_instance:
    """
    Units are expected to be in IFC project units.

    :param context: IfcGeometricRepresentationContext for the representation.
    :param railing_type: Type of the railing. Defaults to "WALL_MOUNTED_HANDRAIL".
    :param railing_path: A list of points coordinates for the railing path,
        coordinates are expected to be at the top of the railing, not at the center.
        If not provided, default path [(0, 0, 1), (1, 0, 1), (2, 0, 1)] (in meters) will be used
    :param use_manual_supports: If enabled, supports are added on every vertex on the edges of the railing path.
        If disabled, supports are added automatically based on the support spacing. Default to False.
    :param support_spacing: Distance between supports if automatic supports are used. Defaults to 1m.
    :param railing_diameter: Railing diameter. Defaults to 50mm.
    :param clear_width: Clear width between the railing and the wall. Defaults to 40mm.
    :param terminal_type: type of the cap. Defaults to "180".
    :param height: defaults to 1m
    :param looped_path: Whether to end the railing on the first point of `railing_path`. Defaults to False.
    :param unit_scale: The unit scale as calculated by
        ifcopenshell.util.unit.calculate_unit_scale. If not provided, it
        will be automatically calculated for you.
    :return: IfcShapeRepresentation for a railing.
    """
    if railing_type != "WALL_MOUNTED_HANDRAIL":
        raise Exception('Only "WALL_MOUNTED_HANDRAIL" railing_type is supported at the moment.')

    if unit_scale is None:
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(file)

    if railing_path is None:
        railing_path = V([(0, 0, 1), (1, 0, 1), (2, 0, 1)]) / unit_scale
    if support_spacing is None:
        support_spacing = mm(DEFAULT_SUPPORT_SPACING_MM) / unit_scale
    if railing_diameter is None:
        railing_diameter = mm(DEFAULT_RAILING_DIAMETER_MM) / unit_scale
    if clear_width is None:
        clear_width = mm(DEFAULT_CLEAR_WIDTH_MM) / unit_scale
    if height is None:
        height = mm(DEFAULT_HEIGHT_MM) / unit_scale

    geometry = compute_wall_mounted_handrail_geometry(
        railing_path=railing_path,
        use_manual_supports=use_manual_supports,
        support_spacing=support_spacing,
        railing_diameter=railing_diameter,
        clear_width=clear_width,
        terminal_type=terminal_type,
        height=height,
        looped_path=looped_path,
        unit_scale=unit_scale,
    )

    builder = ShapeBuilder(file)
    items_3d: list[ifcopenshell.entity_instance] = []

    for support in geometry.supports:
        support_polyline = builder.polyline(support.arc_polyline, closed=False, arc_points=(1,))
        items_3d.append(builder.create_swept_disk_solid(support_polyline, support.arc_radius))

        disk_circle = builder.circle(radius=support.disk_radius)
        y_extrusion_kwargs = builder.rotate_extrusion_kwargs_by_z(builder.extrude_kwargs("Y"), support.disk_z_rotation)
        items_3d.append(
            builder.extrude(
                disk_circle,
                support.disk_depth,
                position=support.disk_position,
                **y_extrusion_kwargs,
            )
        )

    railing_path_entity = builder.polyline(
        geometry.handrail_polyline,
        closed=False,
        arc_points=geometry.handrail_arc_point_indices,
    )
    items_3d.append(builder.create_swept_disk_solid(railing_path_entity, geometry.handrail_radius))

    return builder.get_representation(context, items=items_3d)
