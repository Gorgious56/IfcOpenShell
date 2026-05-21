# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2023 Dion Moult <dion@thinkmoult.com>, @Andrej730
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

from mathutils import Vector

from bonsai.tool.cad import Cad as subject
from test.bim.bootstrap import NewFile

V = lambda *x: Vector([float(i) for i in x])


class TestAreEdgesCollinear(NewFile):
    def test_run(self):
        # fmt: off
        # Parallel edges but not collinear (different z-coordinates)
        assert not subject.are_edges_collinear(
            (V(-1,0,-1), V(1,0,-1)), 
            (V(-1,0,1), V(1,0,1))
        )
        
        # One edge is just a point and the other is a line segment.
        assert not subject.are_edges_collinear(
            (V(1,-1,0), V(1,-1,0)), 
            (V(-1,1,0), V(1,1,0))
        )
        
        # Both edges are collinear and overlap.
        assert subject.are_edges_collinear(
            (V(0,0,0), V(2,2,2)),
            (V(1,1,1), V(3,3,3))
        )

        # Both edges are collinear but don't overlap.
        assert subject.are_edges_collinear(
            (V(0,0,0), V(1,1,1)),
            (V(2,2,2), V(3,3,3))
        )
        
        # Edges are not parallel and not collinear.
        assert not subject.are_edges_collinear(
            (V(0,0,0), V(1,1,1)),
            (V(0,1,0), V(1,0,1))
        )
        # fmt: on


class TestClosestPoints(NewFile):
    def test_run(self):
        # non collinear
        edge1 = (V(0, 0, 0), V(1, 0, 0))
        edge2 = (V(2, 0, 1), V(2, 0, 2))
        assert subject.closest_points(edge1, edge2)[0] == (edge1[1], edge2[0])

        # check other points
        assert subject.closest_points(edge1, edge2)[1] == (edge1[0], edge2[1])

        # collinear
        edge1 = (V(0, 0, 0), V(1, 0, 0))
        edge2 = (V(3, 0, 0), V(2, 0, 0))
        assert subject.closest_points(edge1, edge2)[0] == (edge1[1], edge2[1])

        # parallel
        edge1 = (V(0, 0, 0), V(1, 0, 0))
        edge2 = (V(-5, 0, 0), V(-1, 0, 0))
        assert subject.closest_points(edge1, edge2)[0] == (edge1[0], edge2[1])

        # overlapping
        edge1 = (V(0, 0, 0), V(3, 0, 0))
        edge2 = (V(2, 0, 0), V(5, 0, 0))
        assert subject.closest_points(edge1, edge2)[0] == (edge1[1], edge2[0])

        # edge as a point
        edge1 = (V(0, 0, 0), V(0, 0, 0))
        edge2 = (V(1, 0, 1), V(2, 0, 2))
        assert subject.closest_points(edge1, edge2)[0] == (edge1[0], edge2[0])


class TestSweepDiskAlongPolyline(NewFile):
    """Pin the viewport-only sweep helper that backs the WALL_MOUNTED_HANDRAIL
    preview in :mod:`bonsai.bim.module.model.railing` (closes #7439).

    The helper must produce non-empty mesh geometry for any polyline of at
    least two points and silently no-op on degenerate input — the railing
    preview calls it from a per-frame update callback, so a raise would
    blank the viewport on every property edit.
    """

    def test_two_point_polyline_produces_one_capped_cylinder(self):
        import bmesh

        bm = bmesh.new()
        subject.sweep_disk_along_polyline(
            bm,
            [V(0, 0, 0), V(1, 0, 0)],
            radius=0.05,
            profile_segments=8,
        )
        # One 8-sided capped cylinder: 2 rings of 8 verts plus 2 cap centres = 18 verts.
        # Asserting >= 16 stays robust if Blender ever changes cap topology.
        assert len(bm.verts) >= 16
        assert len(bm.faces) > 0
        bm.free()

    def test_short_polyline_is_a_noop(self):
        """Single point produces no geometry — caller-friendly fallback."""
        import bmesh

        bm = bmesh.new()
        subject.sweep_disk_along_polyline(bm, [V(0, 0, 0)], radius=0.05)
        assert len(bm.verts) == 0
        bm.free()

    def test_zero_length_edge_is_skipped(self):
        """Coincident consecutive points produce no degenerate cylinder.

        Otherwise ``create_cone`` with ``depth=0`` would emit a zero-area
        bmesh face that confuses downstream normal recalculation.
        """
        import bmesh

        bm = bmesh.new()
        subject.sweep_disk_along_polyline(
            bm,
            [V(0, 0, 0), V(0, 0, 0), V(1, 0, 0)],  # first edge has length 0
            radius=0.05,
        )
        # Exactly one cylinder produced (from the second edge).
        # Same vertex count as the two-point case above.
        assert 16 <= len(bm.verts) <= 20
        bm.free()


class TestAddDiskExtrusion(NewFile):
    """Pin the support-disk helper. The railing's wall-attachment plates use
    this — one per support — and the parametric-edit preview re-runs it on
    every property change."""

    def test_produces_capped_cylinder(self):
        import bmesh

        bm = bmesh.new()
        subject.add_disk_extrusion(
            bm,
            position=V(0, 0, 0),
            radius=0.025,
            depth=0.02,
            axis_rotation_z=0.0,
            profile_segments=12,
        )
        # 12-sided cylinder with caps: 2 rings of 12 + 2 cap centres = 26.
        assert len(bm.verts) >= 24
        assert len(bm.faces) > 0
        bm.free()

    def test_zero_depth_disk_is_a_noop(self):
        """A zero-depth disk would be a degenerate plane — skip rather than emit."""
        import bmesh

        bm = bmesh.new()
        subject.add_disk_extrusion(bm, position=V(0, 0, 0), radius=0.025, depth=0.0, axis_rotation_z=0.0)
        assert len(bm.verts) == 0
        bm.free()
