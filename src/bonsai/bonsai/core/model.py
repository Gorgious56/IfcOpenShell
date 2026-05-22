# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
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
# This file was modified with the assistance of an AI coding tool.

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Literal, Optional

if TYPE_CHECKING:
    import bpy
    from mathutils import Vector

    import bonsai.tool as tool
    from bonsai.bim.module.model.wall import DumbWallAligner, DumbWallJoiner

    AlignType = Literal["CENTER", "EXTERIOR", "INTERIOR"]
    OffsetType = Literal["CENTER", "EXTERIOR", "INTERIOR"]


def unjoin_walls(
    ifc: type[tool.Ifc],
    blender: type[tool.Blender],
    geometry: type[tool.Geometry],
    joiner: DumbWallJoiner,
    model: type[tool.Model],
) -> None:
    """Unjoin selected walls."""
    for obj in blender.get_selected_objects():
        if not (element := ifc.get_entity(obj)) or model.get_usage_type(element) != "LAYER2":
            continue
        geometry.clear_scale(obj)
        if ifc.is_moved(obj):
            geometry.run_edit_object_placement(obj=obj)
        joiner.unjoin(obj)


def extend_walls(
    ifc: type[tool.Ifc],
    blender: type[tool.Blender],
    geometry: type[tool.Geometry],
    joiner: DumbWallJoiner,
    model: type[tool.Model],
    target: Vector,
    connection: Optional[str] = None,
) -> None:
    """Extend selected walls to the target."""
    for obj in blender.get_selected_objects():
        if not (element := ifc.get_entity(obj)) or model.get_usage_type(element) != "LAYER2":
            continue
        geometry.clear_scale(obj)
        joiner.extend(obj, target, connection)


def join_walls_LV(
    ifc: type[tool.Ifc],
    blender: type[tool.Blender],
    geometry: type[tool.Geometry],
    joiner: DumbWallJoiner,
    model: type[tool.Model],
    join_type: Literal["L", "V"] = "L",
) -> None:
    selected_objs = [
        o for o in blender.get_selected_objects() if (e := ifc.get_entity(o)) and model.get_usage_type(e) == "LAYER2"
    ]
    if len(selected_objs) != 2:
        raise RequireTwoWallsError("Two vertically layered elements must be selected to connect their paths together")

    if active_obj := blender.get_active_object():
        another_selected_object = next(o for o in selected_objs if o != active_obj)
    else:
        active_obj, another_selected_object = selected_objs

    for obj in selected_objs:
        geometry.clear_scale(obj)

    joiner.connect(another_selected_object, active_obj)


def offset_walls(ifc: type[tool.Ifc], blender: type[tool.Blender], model: type[tool.Model], offset_type: OffsetType):
    objs = [
        obj
        for obj in blender.get_selected_objects()
        if (element := ifc.get_entity(obj)) and model.get_usage_type(element) == "LAYER2"
    ]
    for obj in objs:
        model.offset_wall(obj, offset_type)
    model.recalculate_walls(objs)


def align_walls(
    ifc: type[tool.Ifc],
    blender: type[tool.Blender],
    model: type[tool.Model],
    aligner: DumbWallAligner,
    align_type: AlignType,
):
    reference_obj = blender.get_active_object(is_selected=True)
    if not reference_obj or not (e := ifc.get_entity(reference_obj)) or not model.get_usage_type(e) == "LAYER2":
        reference_obj = None
    objs = [
        o
        for o in blender.get_selected_objects()
        if o != reference_obj and (e := ifc.get_entity(o)) and model.get_usage_type(e) == "LAYER2"
    ]
    if not reference_obj or not objs:
        raise RequireAtLeastTwoLayeredElements(
            "At least two vertically layered elements must be selected to match alignments."
        )
    aligner.set_reference_wall(reference_obj)
    for obj in objs:
        if align_type == "CENTER":
            aligner.align_centerline(obj)
        elif align_type == "EXTERIOR":
            aligner.align_first_layer(obj)
        elif align_type == "INTERIOR":
            aligner.align_last_layer(obj)


def align_objects(
    blender: type[tool.Blender], model: type[tool.Model], align_type: Literal["CENTER", "POSITIVE", "NEGATIVE"]
):
    reference_obj = blender.get_active_object(is_selected=True)
    objs = [o for o in blender.get_selected_objects() if o != reference_obj]
    if not reference_obj or not objs:
        raise RequireAtLeastTwoElements("At least two objects must be selected to match alignments.")
    model.align_objects(reference_obj, objs, align_type)


def extend_wall_to_slab(
    ifc: type[tool.Ifc],
    geometry: type[tool.Geometry],
    model: type[tool.Model],
    slab_obj: bpy.types.Object,
    wall_objs: list[bpy.types.Object],
) -> None:
    if not (clip := model.get_slab_clipping_bmesh(slab_obj)):
        return  # Nothing to clip?
    slab = ifc.get_entity(slab_obj)
    for obj in wall_objs:
        if ifc.is_moved(obj):
            geometry.run_edit_object_placement(obj=obj)
        wall = ifc.get_entity(obj)
        model.clip_wall_to_slab(wall, clip)
        model.connect_wall_to_slab(wall, slab)
    model.reload_body_representation(wall_objs)


class RequireTwoWallsError(Exception):
    pass


class RequireAtLeastTwoLayeredElements(Exception):
    pass


class RequireAtLeastTwoElements(Exception):
    pass


class RequireLayeredElement(Exception):
    pass


# --- Wall geometry math (pure) ------------------------------------------------
# Tuple in / tuple out so these helpers run under ``pytest test/core/`` without
# ``bpy`` or ``mathutils``. Callers convert ``mathutils.Vector`` at the boundary.


def baseline_from_offset(offset: float, thickness: float, tolerance: float = 0.001) -> str:
    """Classify a numeric layer offset as EXTERIOR / CENTER / INTERIOR.

    Mirrors the math in ``tool.Model.offset_wall`` for both POSITIVE and NEGATIVE
    direction_sense walls. Returns the closest canonical baseline; falls back to
    ``"CENTER"`` when nothing is within ``tolerance``."""
    candidates = (
        ("EXTERIOR", 0.0),
        ("CENTER", -thickness / 2),
        ("INTERIOR", -thickness),
        ("EXTERIOR", thickness),
        ("CENTER", thickness / 2),
        ("INTERIOR", 0.0),
    )
    best = min(candidates, key=lambda c: abs(offset - c[1]))
    return best[0] if abs(offset - best[1]) < tolerance else "CENTER"


def project_axis_intersection(
    seg_a: tuple[tuple[float, float, float], tuple[float, float, float]],
    seg_b: tuple[tuple[float, float, float], tuple[float, float, float]],
    parallel_threshold: float,
) -> Optional[tuple[float, float, float]]:
    """Compute the 2D (X,Y plane) intersection of two world-space axis segments.

    Each segment is a pair of 3-tuples. Returns the intersection as a 3-tuple
    (Z is the average of the four input Zs, for visual placement) or ``None`` if
    the segments are parallel within ``parallel_threshold`` (a dot-product magnitude
    threshold — e.g. ``cos(2°) ≈ 0.9994`` treats walls within 2° of parallel as parallel)."""
    p1, p2 = seg_a
    p3, p4 = seg_b
    d1x, d1y = p2[0] - p1[0], p2[1] - p1[1]
    d2x, d2y = p4[0] - p3[0], p4[1] - p3[1]
    d1_len = (d1x * d1x + d1y * d1y) ** 0.5
    d2_len = (d2x * d2x + d2y * d2y) ** 0.5
    if d1_len < 1e-9 or d2_len < 1e-9:
        return None
    dot = (d1x * d2x + d1y * d2y) / (d1_len * d2_len)
    if abs(dot) >= parallel_threshold:
        return None
    denom = d1x * d2y - d1y * d2x
    if abs(denom) < 1e-9:
        return None
    t = ((p3[0] - p1[0]) * d2y - (p3[1] - p1[1]) * d2x) / denom
    ix = p1[0] + t * d1x
    iy = p1[1] + t * d1y
    iz = (p1[2] + p2[2] + p3[2] + p4[2]) / 4
    return (ix, iy, iz)


def opening_is_past_cut(min_t: float, cut_percentage: float) -> bool:
    """True when the opening's near edge sits past the cut on the t axis —
    the lower-t wall (element1) must drop the opening; the high-t side keeps it.

    Strict inequality is load-bearing: a boundary-only touch
    (``min_t == cut_percentage``) keeps the opening on element1. A degenerate
    extent sitting exactly on the cut must NOT be removed from both walls —
    that would leave the user with two walls and no hole anywhere. NaN inputs
    compare False and so leave the opening on both walls — the safe default
    when the upstream extent helper cannot resolve a true bounding range."""
    return min_t > cut_percentage


def opening_is_before_cut(max_t: float, cut_percentage: float) -> bool:
    """Mirror of ``opening_is_past_cut`` for the high-t side — the wall on
    the higher-t side (element2) drops the opening when its far edge sits
    before the cut. Strict inequality carries the same boundary invariant;
    NaN inputs leave the opening on both walls."""
    return max_t < cut_percentage


def opening_straddles_cut(min_t: float, max_t: float, cut_percentage: float) -> bool:
    """True when the opening's extent crosses the cut on the t axis — both
    walls' bodies need cutting, so the neighbour wall gets a pure-void copy.
    Strict inequalities: a boundary touch is not a straddle (handled by the
    two single-sided predicates above). NaN inputs return False."""
    return min_t < cut_percentage < max_t


WallJoinState = Literal["joined", "collinear", "intersect", "none"]


def classify_wall_join_state(
    seg_a: tuple[tuple[float, float, float], tuple[float, float, float]],
    seg_b: tuple[tuple[float, float, float], tuple[float, float, float]],
    are_joined: bool,
    parallel_threshold: float,
    collinear_tolerance: float,
) -> tuple[WallJoinState, Optional[tuple[float, float, float]]]:
    """Classify the geometric state of a wall pair as one of four mutually
    exclusive outcomes. Centralising the decision in one function keeps
    independent callers in lockstep — adding a state or re-ordering priority
    cannot be forgotten in one branch.

    Returns ``(state, intersection)``. The intersection point is non-None
    only for the ``"intersect"`` branch; callers that need it can read it
    here without recomputing the axis intersection.

    Branches, in priority order:

    - ``("joined", None)`` — caller-supplied flag asserting an
      ``IfcRelConnectsPathElements`` exists between the two walls. The IFC
      inverse-graph query is bim-layer code; this function stays pure.
    - ``("collinear", None)`` — the two axes are parallel within
      ``parallel_threshold`` AND lie on the same infinite line within
      ``collinear_tolerance``.
    - ``("intersect", (x, y, z))`` — the two axes meet at a non-parallel angle
      and the projected intersection is the second element.
    - ``("none", None)`` — the axes are parallel but not collinear (no
      meaningful intersection to anchor a join on)."""
    if are_joined:
        return "joined", None
    if are_axes_collinear(seg_a, seg_b, parallel_threshold, collinear_tolerance):
        return "collinear", None
    intersection = project_axis_intersection(seg_a, seg_b, parallel_threshold)
    if intersection is None:
        return "none", None
    return "intersect", intersection


def wall_join_preview_lines(
    seg_a: tuple[tuple[float, float, float], tuple[float, float, float]],
    seg_b: tuple[tuple[float, float, float], tuple[float, float, float]],
    intersection: tuple[float, float, float],
) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """Two line segments showing how each wall axis would extend to reach a
    precomputed XY intersection.

    Each segment goes from the input axis endpoint nearest the intersection
    to the intersection itself, held at the originating axis's own Z so the
    segment stays horizontal at that wall's floor level — even when the two
    walls sit at different elevations.

    Returned in input order ``[floor_a, floor_b]`` so callers can map line
    index back to the two input segments. The caller supplies the
    intersection (rather than this function recomputing it) so the math can
    be shared with whichever upstream step also needed it."""
    ix, iy, _ = intersection

    def _nearest(seg: tuple[tuple[float, float, float], tuple[float, float, float]]) -> tuple[float, float, float]:
        return min(seg, key=lambda p: (p[0] - ix) ** 2 + (p[1] - iy) ** 2)

    near_a = _nearest(seg_a)
    near_b = _nearest(seg_b)
    return [
        (near_a, (ix, iy, near_a[2])),
        (near_b, (ix, iy, near_b[2])),
    ]


def resolve_extend_walls_target(
    target_obj: Any,
    objs: list[Any],
    reverse: bool,
) -> tuple[Any, list[Any]]:
    """Pick which object is the extend-target and which are extended.

    Default direction: ``objs`` are extended to meet ``target_obj``.
    Reversed direction (``reverse=True``) swaps the pair — equivalent to
    having passed them in the opposite order. The swap is well-defined only
    for the 1+1 case (one target + one other); for ``n>1`` it would be
    ambiguous, so the default direction is preserved instead."""
    if reverse and target_obj is not None and len(objs) == 1:
        return objs[0], [target_obj]
    return target_obj, objs


def displacement_from_x_angle(height: float, x_angle: float) -> float:
    """Top-edge horizontal displacement for a wall of given vertical ``height`` and
    slope ``x_angle`` (radians). Drives the slope dimension gizmo's display value.

    Inverse of :func:`x_angle_from_displacement`."""
    return height * math.tan(x_angle)


def x_angle_from_displacement(height: float, displacement: float) -> float:
    """Recover slope ``x_angle`` (radians) from a top-edge horizontal displacement.

    ``height`` is clamped to ``max(height, 1e-6)`` so vertical walls of effectively
    zero height map cleanly to ``±π/2`` via ``atan2`` rather than dividing by zero.

    Inverse of :func:`displacement_from_x_angle`."""
    return math.atan2(displacement, max(height, 1e-6))


def vertical_height_from_extrusion_depth(extrusion_depth: float, x_angle: float) -> float:
    """Vertical height of a wall given its slanted extrusion depth and slope.

    ``IfcExtrudedAreaSolid.Depth`` measures along the (possibly slanted) extrusion
    direction. The vertical height the user thinks of is ``depth * cos(x_angle)``.
    Unit-agnostic: the result is in the same units as ``extrusion_depth``."""
    return extrusion_depth * abs(math.cos(x_angle))


def extrusion_depth_from_vertical_height(vertical_height: float, x_angle: float) -> float:
    """Slanted extrusion depth for a wall of given vertical height and slope.

    The extrusion runs along a direction tilted by ``x_angle`` from vertical,
    so the slanted depth is ``vertical_height / cos(x_angle)``. ``cos(x_angle)``
    is clamped to ``1e-6`` to keep the result finite as ``x_angle`` approaches
    ``±π/2`` (a wall extruded fully horizontally has no meaningful vertical
    height to convert from).

    Unit-agnostic: the result is in the same units as ``vertical_height``."""
    return vertical_height / max(abs(math.cos(x_angle)), 1e-6)


def length_and_height_from_extrusion(
    extrusion_depth: float,
    x_angle: float,
    reference_line_x_extent: float,
    unit_scale: float,
) -> tuple[float, float]:
    """SI length and vertical height of a LAYER2 wall from its IFC primitives.

    Caller has already pulled the four primitives off the wall's Body
    ``IfcExtrudedAreaSolid``: the slanted ``Depth``, the extrusion ``x_angle``,
    the X-extent of the wall's reference-line polyline, and the file's unit
    scale. Length is the reference-line extent scaled to SI; height is the
    *vertical* projection of the slanted depth (``depth * cos(x_angle)``),
    not the slanted depth itself."""
    length = reference_line_x_extent * unit_scale
    height = vertical_height_from_extrusion_depth(extrusion_depth * unit_scale, x_angle)
    return length, height


def are_axes_collinear(
    seg_a: tuple[tuple[float, float, float], tuple[float, float, float]],
    seg_b: tuple[tuple[float, float, float], tuple[float, float, float]],
    parallel_threshold: float = 0.9994,
    line_tolerance: float = 0.05,
) -> bool:
    """True if both axis segments lie on the same infinite line in plan.

    Two conditions: directions must be (anti-)parallel within ``parallel_threshold``
    (``cos(2°) ≈ 0.9994``), AND any endpoint of B must lie on A's infinite line
    within ``line_tolerance``. Plan-only (Z ignored) — two parallel walls at
    different elevations are still considered collinear because the merge operator
    handles Z resolution itself.

    Used by the wall-join gizmo's state machine: collinear pair → Merge icon at the
    boundary, perpendicular pair → Join icon at the intersection."""
    d1x, d1y = seg_a[1][0] - seg_a[0][0], seg_a[1][1] - seg_a[0][1]
    d2x, d2y = seg_b[1][0] - seg_b[0][0], seg_b[1][1] - seg_b[0][1]
    d1_len = (d1x * d1x + d1y * d1y) ** 0.5
    d2_len = (d2x * d2x + d2y * d2y) ** 0.5
    if d1_len < 1e-9 or d2_len < 1e-9:
        return False
    if abs((d1x * d2x + d1y * d2y) / (d1_len * d2_len)) < parallel_threshold:
        return False
    # Project seg_b[0] onto the infinite line through seg_a; the perpendicular
    # distance to the original point tells us how far off the line B sits.
    nx, ny = d1x / d1_len, d1y / d1_len
    dx, dy = seg_b[0][0] - seg_a[0][0], seg_b[0][1] - seg_a[0][1]
    t = dx * nx + dy * ny
    proj_x = seg_a[0][0] + nx * t
    proj_y = seg_a[0][1] + ny * t
    perp_x = seg_b[0][0] - proj_x
    perp_y = seg_b[0][1] - proj_y
    return (perp_x * perp_x + perp_y * perp_y) ** 0.5 < line_tolerance


def closest_endpoint_midpoint(
    seg_a: tuple[tuple[float, float, float], tuple[float, float, float]],
    seg_b: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> tuple[float, float, float]:
    """Midpoint of the closest pair of endpoints between two segments.

    For walls that meet end-to-end this is the shared corner; for walls with a
    small gap it's the midpoint of the gap. Either way it's the user-meaningful
    "boundary" where a merge would graft the two segments together."""
    endpoints_a = (seg_a[0], seg_a[1])
    endpoints_b = (seg_b[0], seg_b[1])

    def _distance_sq(p: tuple[float, float, float], q: tuple[float, float, float]) -> float:
        return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2

    closest_pair = min(((a, b) for a in endpoints_a for b in endpoints_b), key=lambda pair: _distance_sq(*pair))
    a, b = closest_pair
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)


def compute_path_connection_location(
    seg_self: tuple[tuple[float, float, float], tuple[float, float, float]],
    self_conn_type: str,
    seg_other: tuple[tuple[float, float, float], tuple[float, float, float]],
    other_conn_type: str,
    parallel_threshold: float = 0.9994,
) -> tuple[float, float, float]:
    """World-space location of a single ``IfcRelConnectsPathElements`` between two
    wall axes, given each wall's connection type (``ATSTART`` | ``ATEND`` | ``ATPATH``
    | ``NOTDEFINED``).

    The physical join sits at whichever wall has an end-type connection: an end-joined
    wall ends AT the join, while an ATPATH wall passes THROUGH it. Priority order:

    1. ``self`` is ATSTART/ATEND → that endpoint of ``self``.
    2. Else ``other`` is ATSTART/ATEND → that endpoint of ``other``.
    3. Else (both ATPATH or NOTDEFINED — cross junction or under-specified):
       fall back to the 2D axis intersection. If the axes are parallel,
       degenerate to :func:`closest_endpoint_midpoint` so the caller still gets
       a usable point on screen rather than ``None``.

    Pure tuple-in/tuple-out — runs in the core test lane without ``mathutils``."""
    if self_conn_type == "ATSTART":
        return seg_self[0]
    if self_conn_type == "ATEND":
        return seg_self[1]
    if other_conn_type == "ATSTART":
        return seg_other[0]
    if other_conn_type == "ATEND":
        return seg_other[1]
    intersection = project_axis_intersection(seg_self, seg_other, parallel_threshold)
    if intersection is not None:
        return intersection
    return closest_endpoint_midpoint(seg_self, seg_other)
