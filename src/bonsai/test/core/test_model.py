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

"""Tests for pure-Python math helpers in bonsai.core.model used by the wall gizmo system.

These run in the core lane (``pytest test/core/``) — no Blender, no IFC file."""

import math

import pytest

import bonsai.core.model as subject


class TestBaselineFromOffset:
    THICKNESS = 0.2

    def test_positive_direction_exterior(self):
        assert subject.baseline_from_offset(0.0, self.THICKNESS) == "EXTERIOR"

    def test_positive_direction_center(self):
        assert subject.baseline_from_offset(-self.THICKNESS / 2, self.THICKNESS) == "CENTER"

    def test_positive_direction_interior(self):
        assert subject.baseline_from_offset(-self.THICKNESS, self.THICKNESS) == "INTERIOR"

    def test_negative_direction_exterior(self):
        assert subject.baseline_from_offset(self.THICKNESS, self.THICKNESS) == "EXTERIOR"

    def test_negative_direction_center(self):
        assert subject.baseline_from_offset(self.THICKNESS / 2, self.THICKNESS) == "CENTER"

    def test_negative_direction_interior(self):
        assert subject.baseline_from_offset(0.0, self.THICKNESS) == "EXTERIOR"

    def test_within_tolerance_still_matches(self):
        # A 0.5mm jitter on a 200mm wall should still classify cleanly.
        assert subject.baseline_from_offset(-self.THICKNESS / 2 + 0.0005, self.THICKNESS) == "CENTER"

    def test_outside_tolerance_falls_back_to_center(self):
        # 50mm offset on a 200mm wall — not a canonical position.
        assert subject.baseline_from_offset(0.05, self.THICKNESS) == "CENTER"


class TestProjectAxisIntersection:
    PARALLEL_THRESHOLD = 0.9994  # cos(2°)

    def test_perpendicular_walls_meet_at_corner(self):
        # Wall A along +X from origin; wall B along +Y from (5, 0, 0).
        # Axes meet exactly at (5, 0).
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (5.0, 3.0, 0.0))
        result = subject.project_axis_intersection(seg_a, seg_b, self.PARALLEL_THRESHOLD)
        assert result is not None
        assert result[0] == pytest.approx(5.0)
        assert result[1] == pytest.approx(0.0)

    def test_offset_walls_intersect_at_extrapolated_point(self):
        # Wall A: y=0 from x=1 to x=6.
        # Wall B: x=0 from y=1 to y=4.
        # Infinite-line intersection at (0, 0).
        seg_a = ((1.0, 0.0, 0.0), (6.0, 0.0, 0.0))
        seg_b = ((0.0, 1.0, 0.0), (0.0, 4.0, 0.0))
        result = subject.project_axis_intersection(seg_a, seg_b, self.PARALLEL_THRESHOLD)
        assert result is not None
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(0.0)

    def test_parallel_walls_return_none(self):
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((0.0, 1.0, 0.0), (5.0, 1.0, 0.0))
        assert subject.project_axis_intersection(seg_a, seg_b, self.PARALLEL_THRESHOLD) is None

    def test_anti_parallel_walls_return_none(self):
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 1.0, 0.0), (0.0, 1.0, 0.0))  # opposite direction
        assert subject.project_axis_intersection(seg_a, seg_b, self.PARALLEL_THRESHOLD) is None

    def test_nearly_parallel_walls_return_none(self):
        # 1° off parallel — within the ~2° dead-band.
        angle = math.radians(1)
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((0.0, 1.0, 0.0), (5.0 * math.cos(angle), 1.0 + 5.0 * math.sin(angle), 0.0))
        assert subject.project_axis_intersection(seg_a, seg_b, self.PARALLEL_THRESHOLD) is None

    def test_zero_length_segment_returns_none(self):
        seg_a = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        seg_b = ((0.0, 0.0, 0.0), (1.0, 1.0, 0.0))
        assert subject.project_axis_intersection(seg_a, seg_b, self.PARALLEL_THRESHOLD) is None

    def test_intersection_z_is_average_of_endpoint_zs(self):
        # Walls at different elevations; the icon-placement Z should be the average.
        seg_a = ((0.0, 0.0, 1.0), (5.0, 0.0, 1.0))  # at z=1
        seg_b = ((5.0, 0.0, 3.0), (5.0, 3.0, 3.0))  # at z=3
        result = subject.project_axis_intersection(seg_a, seg_b, self.PARALLEL_THRESHOLD)
        assert result is not None
        assert result[2] == pytest.approx(2.0)


class TestWallJoinPreviewLines:
    """Each preview line connects the wall's nearer axis endpoint to the
    caller-supplied XY intersection, held at that wall's own axis Z. The
    caller passes the precomputed intersection (rather than the function
    recomputing it) so the same math can be shared with whichever upstream
    step also needed it. The parallel-axis case is the caller's
    responsibility — invalid inputs (no real intersection) yield garbage,
    so callers must gate the call on a real intersection existing first.

    Returns two lines in input order (``[floor_a, floor_b]``) so callers can
    map a line index back to the originating segment."""

    def test_perpendicular_walls_lines_meet_at_corner(self):
        # Wall A endpoint (5,0) is the nearest to the intersection (5,0); wall B's
        # nearest endpoint is also (5,0). Both lines collapse to a point but are
        # still well-defined and stay in selection order.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (5.0, 3.0, 0.0))
        result = subject.wall_join_preview_lines(seg_a, seg_b, intersection=(5.0, 0.0, 0.0))
        assert len(result) == 2
        (sa, ea), (sb, eb) = result
        assert sa == pytest.approx((5.0, 0.0, 0.0))
        assert ea == pytest.approx((5.0, 0.0, 0.0))
        assert sb == pytest.approx((5.0, 0.0, 0.0))
        assert eb == pytest.approx((5.0, 0.0, 0.0))

    def test_far_apart_walls_draw_long_preview_lines(self):
        # Two 1m walls whose axes meet ~50m away — the "bridge distant walls"
        # case. Each line spans from the wall's nearest endpoint to the
        # (50, 0) corner.
        seg_a = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        seg_b = ((50.0, 50.0, 0.0), (50.0, 51.0, 0.0))
        result = subject.wall_join_preview_lines(seg_a, seg_b, intersection=(50.0, 0.0, 0.0))
        assert len(result) == 2
        (sa, ea), (sb, eb) = result
        # Wall A's endpoint at x=1 is closer to (50, 0) than x=0.
        assert sa == pytest.approx((1.0, 0.0, 0.0))
        assert ea == pytest.approx((50.0, 0.0, 0.0))
        # Wall B's endpoint at y=50 is closer to (50, 0) than y=51.
        assert sb == pytest.approx((50.0, 50.0, 0.0))
        assert eb == pytest.approx((50.0, 0.0, 0.0))

    def test_walls_at_different_elevations_lines_stay_at_own_z(self):
        # Wall A on the floor (Z=0), wall B on a slab (Z=3). Each line stays
        # horizontal at its own wall's Z; the upper-wall line does NOT descend
        # to the lower wall's floor. Pins the "per-wall-axis Z" semantic — the
        # Z component of the supplied intersection tuple is ignored in favour
        # of each wall's own axis Z.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))  # floor at Z=0
        seg_b = ((5.0, 0.0, 3.0), (5.0, 3.0, 3.0))  # floor at Z=3
        result = subject.wall_join_preview_lines(seg_a, seg_b, intersection=(5.0, 0.0, 1.5))
        (sa, ea), (sb, eb) = result
        assert ea[2] == pytest.approx(0.0)
        assert eb[2] == pytest.approx(3.0)


class TestClassifyWallJoinState:
    """Pin the four branches of the wall-pair state classifier. The classifier
    is the single source of truth for what state a wall pair is in, called
    from multiple independent consumers; a regression in one branch would
    silently desync them — these tests are the contract that keeps them
    aligned."""

    PARALLEL_THRESHOLD = 0.9994
    COLLINEAR_TOLERANCE = 0.05

    def test_joined_wins_over_geometric_state(self):
        # Even when the geometry looks like a clean intersection, the IFC-graph
        # join flag takes priority. No intersection is returned for
        # non-``intersect`` states; that's the contract.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (5.0, 3.0, 0.0))
        state, intersection = subject.classify_wall_join_state(
            seg_a,
            seg_b,
            are_joined=True,
            parallel_threshold=self.PARALLEL_THRESHOLD,
            collinear_tolerance=self.COLLINEAR_TOLERANCE,
        )
        assert state == "joined"
        assert intersection is None

    def test_collinear_when_axes_share_infinite_line(self):
        # Two segments on y=0 with a gap between them — same axis line.
        seg_a = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0))
        seg_b = ((3.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        state, intersection = subject.classify_wall_join_state(
            seg_a,
            seg_b,
            are_joined=False,
            parallel_threshold=self.PARALLEL_THRESHOLD,
            collinear_tolerance=self.COLLINEAR_TOLERANCE,
        )
        assert state == "collinear"
        assert intersection is None

    def test_intersect_returns_state_and_intersection_xy(self):
        # Two perpendicular axes — the canonical "Join + Extend" case. The
        # classifier returns the intersection so the caller doesn't have to
        # re-run project_axis_intersection. Pinning this is what closes the
        # double-compute hazard the API restructure was meant to eliminate.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((10.0, 0.0, 0.0), (10.0, 5.0, 0.0))
        state, intersection = subject.classify_wall_join_state(
            seg_a,
            seg_b,
            are_joined=False,
            parallel_threshold=self.PARALLEL_THRESHOLD,
            collinear_tolerance=self.COLLINEAR_TOLERANCE,
        )
        assert state == "intersect"
        assert intersection is not None
        assert intersection[0] == pytest.approx(10.0)
        assert intersection[1] == pytest.approx(0.0)

    def test_none_for_parallel_but_not_collinear(self):
        # Parallel offset walls — no meaningful intersection, no shared line.
        # Consumers gate visibility off the ``"none"`` return.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((0.0, 1.0, 0.0), (5.0, 1.0, 0.0))
        state, intersection = subject.classify_wall_join_state(
            seg_a,
            seg_b,
            are_joined=False,
            parallel_threshold=self.PARALLEL_THRESHOLD,
            collinear_tolerance=self.COLLINEAR_TOLERANCE,
        )
        assert state == "none"
        assert intersection is None


class TestResolveExtendWallsTarget:
    """Pin the target/other swap with the reverse flag. Default direction
    extends ``objs`` to meet ``target_obj``; reversed direction swaps the
    roles. Only the 1+1 case has a well-defined inverse — for ``n>1`` the
    swap would be ambiguous and the default direction is preserved instead."""

    def test_default_direction_passes_through_unchanged(self):
        target = object()
        other = object()
        assert subject.resolve_extend_walls_target(target, [other], reverse=False) == (target, [other])

    def test_reverse_swaps_in_one_plus_one_case(self):
        target = object()
        other = object()
        assert subject.resolve_extend_walls_target(target, [other], reverse=True) == (other, [target])

    def test_reverse_is_noop_when_target_is_none(self):
        # Operator early-errors on missing target anyway; the helper just
        # passes the bogus state through so the caller can report it.
        other = object()
        assert subject.resolve_extend_walls_target(None, [other], reverse=True) == (None, [other])

    def test_reverse_is_noop_when_multiple_others(self):
        # Shift+click on a multi-select has no single well-defined inverse —
        # keep the default direction so a Shift modifier on a many-walls
        # selection doesn't silently shuffle which wall is the target.
        target = object()
        others = [object(), object()]
        assert subject.resolve_extend_walls_target(target, others, reverse=True) == (target, others)

    def test_reverse_is_noop_when_no_others(self):
        target = object()
        assert subject.resolve_extend_walls_target(target, [], reverse=True) == (target, [])


class TestSlopeRoundTrip:
    def test_zero_angle_zero_displacement(self):
        assert subject.displacement_from_x_angle(3.0, 0.0) == pytest.approx(0.0)
        assert subject.x_angle_from_displacement(3.0, 0.0) == pytest.approx(0.0)

    def test_positive_angle_positive_displacement(self):
        # 30° slope on a 3m wall → top moves ~1.732m in +Y.
        displacement = subject.displacement_from_x_angle(3.0, math.radians(30))
        assert displacement == pytest.approx(3.0 * math.tan(math.radians(30)))

    def test_negative_angle_negative_displacement(self):
        displacement = subject.displacement_from_x_angle(3.0, math.radians(-15))
        assert displacement < 0

    def test_round_trip_preserves_angle(self):
        # Drag-to-angle-to-drag preserves the original.
        original_angle = math.radians(20)
        displacement = subject.displacement_from_x_angle(3.0, original_angle)
        recovered = subject.x_angle_from_displacement(3.0, displacement)
        assert recovered == pytest.approx(original_angle, abs=1e-9)

    def test_round_trip_handles_zero_height(self):
        # Walls of effectively zero height should not divide-by-zero.
        recovered = subject.x_angle_from_displacement(0.0, 1.0)
        assert recovered == pytest.approx(math.pi / 2, abs=1e-3)


class TestAreAxesCollinear:
    PARALLEL_THRESHOLD = 0.9994
    LINE_TOLERANCE = 0.05

    def test_end_to_end_walls_along_x_are_collinear(self):
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (10.0, 0.0, 0.0))
        assert subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)

    def test_separated_collinear_walls_with_gap(self):
        # Walls with a 1m gap between them — still on the same line.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((6.0, 0.0, 0.0), (10.0, 0.0, 0.0))
        assert subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)

    def test_perpendicular_walls_are_not_collinear(self):
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((0.0, 0.0, 0.0), (0.0, 5.0, 0.0))
        assert not subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)

    def test_parallel_walls_offset_perpendicular_are_not_collinear(self):
        # Two parallel walls 1m apart — same direction but not the same line.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((0.0, 1.0, 0.0), (5.0, 1.0, 0.0))
        assert not subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)

    def test_anti_parallel_collinear_walls(self):
        # Reversed direction on the same line still counts as collinear.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((10.0, 0.0, 0.0), (6.0, 0.0, 0.0))
        assert subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)

    def test_z_is_ignored_for_plan_collinearity(self):
        # Walls on different floors are still considered collinear in plan.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 3.0), (10.0, 0.0, 3.0))
        assert subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)

    def test_zero_length_segment_is_not_collinear(self):
        seg_a = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        seg_b = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        assert not subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)

    def test_slightly_off_line_within_tolerance(self):
        # 2cm perpendicular offset — still within the 5cm tolerance.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.02, 0.0), (10.0, 0.02, 0.0))
        assert subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)

    def test_too_far_off_line_fails_tolerance(self):
        # 10cm perpendicular offset — outside the 5cm tolerance.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.10, 0.0), (10.0, 0.10, 0.0))
        assert not subject.are_axes_collinear(seg_a, seg_b, self.PARALLEL_THRESHOLD, self.LINE_TOLERANCE)


class TestClosestEndpointMidpoint:
    def test_end_to_end_walls_midpoint_is_the_shared_corner(self):
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (10.0, 0.0, 0.0))
        result = subject.closest_endpoint_midpoint(seg_a, seg_b)
        assert result == (pytest.approx(5.0), pytest.approx(0.0), pytest.approx(0.0))

    def test_walls_with_gap_midpoint_is_in_the_gap(self):
        # Wall A ends at x=5; wall B starts at x=7. Boundary midpoint is at x=6.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((7.0, 0.0, 0.0), (12.0, 0.0, 0.0))
        result = subject.closest_endpoint_midpoint(seg_a, seg_b)
        assert result == (pytest.approx(6.0), pytest.approx(0.0), pytest.approx(0.0))

    def test_perpendicular_walls_midpoint_is_between_nearest_endpoints(self):
        # Wall A's +X endpoint (5,0,0) and wall B's origin (5,0,0) → midpoint at (5,0,0).
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (5.0, 3.0, 0.0))
        result = subject.closest_endpoint_midpoint(seg_a, seg_b)
        assert result == (pytest.approx(5.0), pytest.approx(0.0), pytest.approx(0.0))

    def test_z_averaged_when_walls_at_different_elevations(self):
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 3.0), (10.0, 0.0, 3.0))
        result = subject.closest_endpoint_midpoint(seg_a, seg_b)
        # Closest pair: (5,0,0) and (5,0,3); midpoint Z = 1.5.
        assert result[2] == pytest.approx(1.5)


class TestVerticalHeightFromExtrusionDepth:
    def test_vertical_wall_returns_depth_unchanged(self):
        assert subject.vertical_height_from_extrusion_depth(3.0, 0.0) == pytest.approx(3.0)

    def test_30_degree_slope(self):
        # cos(30°) ≈ 0.866 → vertical height of a 3m slanted extrusion ≈ 2.598m.
        result = subject.vertical_height_from_extrusion_depth(3.0, math.radians(30))
        assert result == pytest.approx(3.0 * math.cos(math.radians(30)))

    def test_negative_angle_yields_same_magnitude(self):
        positive = subject.vertical_height_from_extrusion_depth(3.0, math.radians(30))
        negative = subject.vertical_height_from_extrusion_depth(3.0, math.radians(-30))
        assert positive == pytest.approx(negative)


class TestExtrusionDepthFromVerticalHeight:
    """Inverse of the vertical-height helper. Callers placing markers in
    wall-local space need the slanted extrusion depth, not the vertical
    height — feeding the vertical value as a local Z lands below the
    slanted top edge on sloped walls."""

    def test_vertical_wall_returns_height_unchanged(self):
        assert subject.extrusion_depth_from_vertical_height(3.0, 0.0) == pytest.approx(3.0)

    def test_30_degree_slope(self):
        # cos(30°) ≈ 0.866 → slanted depth of a 3m vertical wall ≈ 3 / 0.866 ≈ 3.464m.
        result = subject.extrusion_depth_from_vertical_height(3.0, math.radians(30))
        assert result == pytest.approx(3.0 / math.cos(math.radians(30)))

    def test_negative_angle_yields_same_magnitude(self):
        positive = subject.extrusion_depth_from_vertical_height(3.0, math.radians(30))
        negative = subject.extrusion_depth_from_vertical_height(3.0, math.radians(-30))
        assert positive == pytest.approx(negative)

    @pytest.mark.parametrize("angle_deg", [0, 15, 30, 45, 60, -15, -30, -45, -60])
    def test_roundtrip_with_vertical_height_from_extrusion_depth(self, angle_deg):
        # Round-trip vertical_height → extrusion_depth → vertical_height should
        # return the input across the slope range Bonsai supports
        # (soft_min/max ±π/3 per prop.py; covers typical authoring slopes).
        vertical = 3.0
        angle = math.radians(angle_deg)
        depth = subject.extrusion_depth_from_vertical_height(vertical, angle)
        roundtrip = subject.vertical_height_from_extrusion_depth(depth, angle)
        assert roundtrip == pytest.approx(vertical)

    def test_horizontal_extrusion_does_not_blow_up(self):
        # At ±π/2 cos is zero; helper clamps to avoid division-by-zero so
        # callers never see inf / nan even if a wall is momentarily edited
        # toward the degenerate slope limit during a slider drag.
        result = subject.extrusion_depth_from_vertical_height(3.0, math.pi / 2)
        assert math.isfinite(result)


class TestLengthAndHeightFromExtrusion:
    """Composition of the unit-scale and slanted-depth steps. The composition
    exists so callers can pass any LAYER2 wall's four primitives (slanted
    depth, x_angle, reference-line X extent, file unit scale) and get SI
    length + vertical height back in one step, without re-deriving the
    unit conversions or slope correction at each call site."""

    def test_vertical_meter_wall_returns_extent_and_depth_unchanged(self):
        length, height = subject.length_and_height_from_extrusion(
            extrusion_depth=3.0, x_angle=0.0, reference_line_x_extent=5.0, unit_scale=1.0
        )
        assert length == pytest.approx(5.0)
        assert height == pytest.approx(3.0)

    def test_unit_scale_converts_millimeter_inputs_to_si(self):
        # A wall stored in millimetres reports its Body Depth and reference line
        # in IFC units; the helper rescales both to SI in one step so the gizmo
        # never sees mixed units.
        length, height = subject.length_and_height_from_extrusion(
            extrusion_depth=3000.0, x_angle=0.0, reference_line_x_extent=5000.0, unit_scale=0.001
        )
        assert length == pytest.approx(5.0)
        assert height == pytest.approx(3.0)

    def test_slanted_wall_height_is_vertical_not_slanted(self):
        # Sloped extrusion: the wall's vertical height is depth*cos(angle), not
        # the slanted depth itself. Pinned at the composition level so a
        # regression here can't be masked by the lower-level helper still
        # passing on its own.
        angle = math.radians(30)
        length, height = subject.length_and_height_from_extrusion(
            extrusion_depth=3.0, x_angle=angle, reference_line_x_extent=5.0, unit_scale=1.0
        )
        assert length == pytest.approx(5.0)
        assert height == pytest.approx(3.0 * math.cos(angle))

    def test_negative_reference_extent_preserved(self):
        # A reverse-direction wall (p2.x < p1.x) yields a negative extent; the
        # helper does not abs() it so callers can detect orientation.
        length, _ = subject.length_and_height_from_extrusion(
            extrusion_depth=3.0, x_angle=0.0, reference_line_x_extent=-5.0, unit_scale=1.0
        )
        assert length == pytest.approx(-5.0)


class TestComputePathConnectionLocation:
    """Single-wall unjoin gizmo placement. For each ``IfcRelConnectsPathElements``
    between two walls, the visible join point is whichever wall has an end-type
    connection (``ATSTART``/``ATEND``) — that wall ends AT the join, while the
    other wall passes THROUGH it (``ATPATH``) or also ends there. Tests pin the
    priority order plus the cross-junction fallback for ATPATH/ATPATH."""

    def _seg_self(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))

    def _seg_other_perpendicular(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        # Other wall starts at (2.5, 0, 0) — middle of self's path — and goes north.
        # Used for T-junction cases.
        return ((2.5, 0.0, 0.0), (2.5, 3.0, 0.0))

    def test_self_atstart_returns_self_start(self):
        seg_self = self._seg_self()
        seg_other = self._seg_other_perpendicular()
        result = subject.compute_path_connection_location(seg_self, "ATSTART", seg_other, "ATEND")
        assert result == (pytest.approx(0.0), pytest.approx(0.0), pytest.approx(0.0))

    def test_self_atend_returns_self_end(self):
        seg_self = self._seg_self()
        seg_other = self._seg_other_perpendicular()
        result = subject.compute_path_connection_location(seg_self, "ATEND", seg_other, "ATSTART")
        assert result == (pytest.approx(5.0), pytest.approx(0.0), pytest.approx(0.0))

    def test_self_atstart_takes_priority_over_other_atend(self):
        # If both walls claim an end-connection (geometrically rare but legal in
        # IFC), self wins so the placement stays anchored to the selected wall.
        seg_self = self._seg_self()
        seg_other = ((0.0, 0.0, 0.0), (0.0, 3.0, 0.0))
        result = subject.compute_path_connection_location(seg_self, "ATSTART", seg_other, "ATEND")
        # self ATSTART is (0,0,0); other ATEND is (0,3,0). Priority picks self.
        assert result == (pytest.approx(0.0), pytest.approx(0.0), pytest.approx(0.0))

    def test_self_atpath_other_atstart_returns_other_start(self):
        # T-junction: self is the through-wall, other ends at self's middle.
        seg_self = self._seg_self()
        seg_other = self._seg_other_perpendicular()
        result = subject.compute_path_connection_location(seg_self, "ATPATH", seg_other, "ATSTART")
        # other ATSTART is (2.5, 0, 0) — the T point on self's path.
        assert result == (pytest.approx(2.5), pytest.approx(0.0), pytest.approx(0.0))

    def test_self_atpath_other_atend_returns_other_end(self):
        seg_self = self._seg_self()
        # Other wall ends at (2.5, 0, 0) from the north.
        seg_other = ((2.5, 3.0, 0.0), (2.5, 0.0, 0.0))
        result = subject.compute_path_connection_location(seg_self, "ATPATH", seg_other, "ATEND")
        assert result == (pytest.approx(2.5), pytest.approx(0.0), pytest.approx(0.0))

    def test_both_atpath_falls_back_to_intersection(self):
        # Cross junction (+): both walls pass through each other's middle.
        seg_self = self._seg_self()
        seg_other = ((2.5, -2.0, 0.0), (2.5, 2.0, 0.0))
        result = subject.compute_path_connection_location(seg_self, "ATPATH", seg_other, "ATPATH")
        assert result[0] == pytest.approx(2.5)
        assert result[1] == pytest.approx(0.0)

    def test_both_atpath_parallel_falls_back_to_midpoint(self):
        # Parallel-but-ATPATH/ATPATH shouldn't crash; degenerate fallback to
        # closest_endpoint_midpoint so the gizmo still gets a placeable point.
        seg_self = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_other = ((6.0, 0.0, 0.0), (11.0, 0.0, 0.0))
        result = subject.compute_path_connection_location(seg_self, "ATPATH", seg_other, "ATPATH")
        # closest endpoints are (5,0,0) and (6,0,0) → midpoint at (5.5, 0, 0).
        assert result == (pytest.approx(5.5), pytest.approx(0.0), pytest.approx(0.0))

    def test_notdefined_on_both_falls_back_to_intersection(self):
        seg_self = self._seg_self()
        seg_other = ((2.5, -2.0, 0.0), (2.5, 2.0, 0.0))
        result = subject.compute_path_connection_location(seg_self, "NOTDEFINED", seg_other, "NOTDEFINED")
        assert result[0] == pytest.approx(2.5)
        assert result[1] == pytest.approx(0.0)


class TestOpeningSplitPredicates:
    """Branch behaviour of the three wall-split inequality predicates that
    ``DumbWallJoiner.split`` uses to decide which side(s) of a cut keep each
    opening. The strict ``>`` / ``<`` choices are the load-bearing invariant —
    a regression to ``>=`` / ``<=`` here would silently drop an opening from
    both walls when its extent collapses onto the cut."""

    def test_straddling_opening_is_kept_on_both_sides(self):
        # An opening with extent [0.3, 0.7] and cut at 0.6 overlaps both
        # element1 and element2 — neither side may drop it.
        assert subject.opening_is_past_cut(0.3, 0.6) is False, "straddling opening must remain on element1"
        assert subject.opening_is_before_cut(0.7, 0.6) is False, "straddling opening must remain on element2"

    def test_opening_entirely_past_cut_is_removed_from_element1_only(self):
        # Extent [0.7, 0.9], cut 0.5 → opening sits wholly on element2's side.
        assert subject.opening_is_past_cut(0.7, 0.5) is True  # removed from element1
        assert subject.opening_is_before_cut(0.9, 0.5) is False  # kept on element2

    def test_opening_entirely_before_cut_is_removed_from_element2_only(self):
        # Mirror: extent [0.1, 0.3], cut 0.5 → opening sits wholly on element1's side.
        assert subject.opening_is_past_cut(0.1, 0.5) is False  # kept on element1
        assert subject.opening_is_before_cut(0.3, 0.5) is True  # removed from element2

    def test_opening_touching_cut_at_boundary_stays_on_both_walls(self):
        # Boundary touch: ``max_t == cut_percentage``. Strict inequality keeps
        # the opening on both walls — the safer default. A regression to
        # non-strict ``<=`` would remove it from element2.
        assert subject.opening_is_past_cut(0.2, 0.5) is False  # kept on element1
        assert subject.opening_is_before_cut(0.5, 0.5) is False  # kept on element2 (boundary == cut)

    def test_degenerate_range_at_cut_keeps_opening_on_both_walls(self):
        # Degenerate extent (t, t) at the cut, e.g. when the upstream extent
        # helper fell back to the placement origin. Non-strict comparisons
        # would match both removal conditions and both walls would drop the
        # opening; strict comparisons keep it on both.
        assert subject.opening_is_past_cut(0.5, 0.5) is False
        assert subject.opening_is_before_cut(0.5, 0.5) is False

    def test_filled_opening_void_straddle_keeps_void_on_neighbour(self):
        # Filling on element1 (filling_position < cut_percentage) while the
        # void straddles the cut → neighbour wall (element2) needs a void copy
        # via ``_add_void_copy``.
        assert subject.opening_straddles_cut(0.3, 0.7, 0.5) is True
        assert 0.4 <= 0.5  # filling_position <= cut_percentage — production takes the else branch

    def test_filled_opening_void_straddle_with_filling_on_far_side(self):
        # Symmetric case: filling moves to element2 with the original void;
        # element1 then needs a pure-void copy back.
        assert subject.opening_straddles_cut(0.3, 0.7, 0.5) is True
        assert 0.6 > 0.5  # filling_position > cut_percentage — production adds void copy to element1


class TestOpeningPredicateNaNHandling:
    """NaN / inf propagation. The upstream extent helper can return NaN when
    the wall axis is degenerate (zero length) or when ``ifcopenshell.geom``
    fails on a representation it can't process. The predicates must degrade
    safely: leave the opening on both walls rather than silently drop it."""

    def test_opening_is_past_cut_returns_false_on_nan(self):
        # NaN compares false in any direction — opening stays on element1.
        assert subject.opening_is_past_cut(math.nan, 0.5) is False
        assert subject.opening_is_past_cut(0.5, math.nan) is False

    def test_opening_is_before_cut_returns_false_on_nan(self):
        # Same safe default on the high-t side.
        assert subject.opening_is_before_cut(math.nan, 0.5) is False
        assert subject.opening_is_before_cut(0.5, math.nan) is False

    def test_opening_straddles_cut_returns_false_on_nan(self):
        # A NaN bound cannot straddle anything; the chained comparison short-
        # circuits to False on the first NaN comparison.
        assert subject.opening_straddles_cut(math.nan, 0.7, 0.5) is False
        assert subject.opening_straddles_cut(0.3, math.nan, 0.5) is False
        assert subject.opening_straddles_cut(0.3, 0.7, math.nan) is False

    def test_predicates_handle_infinity_as_well_defined_comparisons(self):
        # Sanity check: +inf min_t IS past any finite cut; -inf max_t IS
        # before any finite cut. This isn't a NaN safety property — it's
        # documenting the well-defined IEEE semantics for completeness so a
        # future change that wraps the predicates can't "fix" inf handling
        # by accident.
        assert subject.opening_is_past_cut(math.inf, 0.5) is True
        assert subject.opening_is_before_cut(-math.inf, 0.5) is True


class TestComputeFilletPolylines:
    """The fillet preview helper for two axis segments meeting at a corner.

    All segments lie on z=0 unless stated; the helper supports general 3D but
    the wall-corner use case is planar."""

    def _perpendicular_pair(self):
        # Wall A along +X ending at (5, 0); wall B along +Y starting at (5, 0).
        # Axes meet at (5, 0); both legs are 5m long.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (5.0, 5.0, 0.0))
        return seg_a, seg_b

    def test_perpendicular_walls_return_quarter_arc(self):
        seg_a, seg_b = self._perpendicular_pair()
        r = subject.compute_fillet_polylines(seg_a, seg_b, radius=1.0, arc_resolution=8)
        assert r["valid"] is True
        assert r["reason"] is None
        assert r["sweep_angle"] == pytest.approx(math.pi / 2)
        assert r["tangent_offset"] == pytest.approx(1.0)
        assert r["arc_radius"] == pytest.approx(1.0)
        assert len(r["arc"]) == 9  # arc_resolution + 1

    def test_acute_corner_returns_larger_tangent_offset(self):
        # 45° corner: wall A along +X, wall B going up-and-to-the-left at 135°.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (5.0 - 5.0 * math.cos(math.radians(45)), 5.0 * math.sin(math.radians(45)), 0.0))
        r = subject.compute_fillet_polylines(seg_a, seg_b, radius=1.0)
        assert r["valid"] is True
        # angle between legs = 45° → sweep = 135° → tangent_offset = tan(67.5°) ≈ 2.414
        assert r["sweep_angle"] == pytest.approx(math.radians(135))
        assert r["tangent_offset"] == pytest.approx(math.tan(math.radians(67.5)))

    def test_parallel_walls_return_invalid_with_parallel_reason(self):
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((0.0, 1.0, 0.0), (5.0, 1.0, 0.0))
        r = subject.compute_fillet_polylines(seg_a, seg_b, radius=0.5)
        assert r["valid"] is False
        assert r["reason"] == "parallel"
        assert r["invalid_axes"] is not None
        assert len(r["invalid_axes"]) == 2

    def test_collinear_walls_return_invalid_near_collinear(self):
        # End-to-end along +X: axes meet but sweep_angle ≈ 0.
        seg_a = ((0.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        seg_b = ((5.0, 0.0, 0.0), (10.0, 0.0, 0.0))
        r = subject.compute_fillet_polylines(seg_a, seg_b, radius=0.5)
        # Anti-parallel by direction (one approaches the corner from the
        # west, the other leaves it to the east) — sweep_angle near zero.
        assert r["valid"] is False
        assert r["reason"] in {"near_collinear", "parallel"}

    def test_radius_overshoot_returns_invalid_radius_with_arc_populated(self):
        # 90° corner, but the radius is so large the tangent point lies past
        # the far end of each leg. Decorator still needs arc + tangents to
        # render the overshoot in red.
        seg_a, seg_b = self._perpendicular_pair()  # legs are 5m
        r = subject.compute_fillet_polylines(seg_a, seg_b, radius=10.0, arc_resolution=4)
        assert r["valid"] is False
        assert r["reason"] == "invalid_radius"
        assert r["invalid_radius"] is True
        assert r["tangent_a"] is not None
        assert r["tangent_b"] is not None
        assert len(r["arc"]) == 5

    def test_join_side_matches_axis_orientation(self):
        # Wall A points away from the corner: seg_a[0] = corner, seg_a[1] = far.
        # → join side is ATSTART (corner is at seg_a[0]).
        # Wall B points toward the corner: seg_b[0] = far, seg_b[1] = corner.
        # → join side is ATEND.
        seg_a = ((5.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        seg_b = ((5.0, 5.0, 0.0), (5.0, 0.0, 0.0))
        r = subject.compute_fillet_polylines(seg_a, seg_b, radius=1.0)
        assert r["valid"] is True
        assert r["wall_a_join_side"] == "ATSTART"
        assert r["wall_b_join_side"] == "ATEND"

    def test_arc_endpoints_match_tangent_points(self):
        seg_a, seg_b = self._perpendicular_pair()
        r = subject.compute_fillet_polylines(seg_a, seg_b, radius=1.0, arc_resolution=16)
        assert r["valid"] is True
        first = r["arc"][0]
        last = r["arc"][-1]
        tangent_a = r["tangent_a"]
        tangent_b = r["tangent_b"]
        for coord_arc, coord_tan in zip(first, tangent_a):
            assert coord_arc == pytest.approx(coord_tan, abs=1e-9)
        for coord_arc, coord_tan in zip(last, tangent_b):
            assert coord_arc == pytest.approx(coord_tan, abs=1e-9)

    def test_arc_lies_in_horizontal_plane_for_floorplan_walls(self):
        seg_a, seg_b = self._perpendicular_pair()
        r = subject.compute_fillet_polylines(seg_a, seg_b, radius=1.0, arc_resolution=32)
        assert r["valid"] is True
        for point in r["arc"]:
            assert point[2] == pytest.approx(0.0, abs=1e-9)
        # All arc points sit at distance ``radius`` from arc_center.
        cx, cy, cz = r["arc_center"]
        for x, y, z in r["arc"]:
            distance = ((x - cx) ** 2 + (y - cy) ** 2 + (z - cz) ** 2) ** 0.5
            assert distance == pytest.approx(1.0, abs=1e-9)
