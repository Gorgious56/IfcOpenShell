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

"""Smoke + walk-primitive tests for the wall-system-path decorator.

The decorator itself reuses the same two-tier cache pattern as
``MEPSystemPathDecorator`` (already pinned by ``test_mep_system_path_cache.py``);
these tests pin the walls-specific surface:

- ``tool.Wall.walk_connected_walls`` BFS over ``IfcRelConnectsPathElements``.
- ``WallSystemPathDecorator`` install / uninstall existence.
- The unified ``show_paths`` toggle on ``BIMModelProperties`` (drives both
  the wall and MEP path decorators in one user-facing switch).
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bpy
import ifcopenshell
import pytest

import bonsai.tool as tool
from bonsai.bim.module.model import decorator as decorator_module
from test.bim.bootstrap import NewFile

pytestmark = pytest.mark.model


@pytest.mark.model
def test_wall_system_path_decorator_class_present():
    """Pin the install / uninstall surface so a renaming refactor doesn't
    silently drop the wall-path overlay at addon load."""
    from bonsai.bim.module.model.decorator import WallSystemPathDecorator

    assert hasattr(WallSystemPathDecorator, "install")
    assert hasattr(WallSystemPathDecorator, "uninstall")


@pytest.mark.model
def test_show_paths_property_attached_to_model_props():
    """The unified ``show_paths`` toggle drives both MEP and wall path
    decorators. Pin its presence on BIMModelProperties so an accidental
    rename can't break the user-facing path-overlay switch."""
    model_props = tool.Model.get_model_props()
    assert hasattr(model_props, "show_paths")
    assert isinstance(model_props.show_paths, bool)


@pytest.mark.model
def test_walk_connected_walls_returns_empty_for_non_wall_start():
    """``walk_connected_walls`` must reject non-wall start elements without
    crashing. Mirrors ``walk_connected_mep_elements``'s gate against
    non-MEP starts."""
    import ifcopenshell

    ifc_file = ifcopenshell.file()
    # IfcSite is the canonical "not a wall" — also not a path element at all.
    site = ifc_file.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new())
    assert tool.Wall.walk_connected_walls(site) == []


@pytest.mark.model
class TestWalkConnectedWalls(NewFile):
    """End-to-end walk tests against a real demo-template project. The
    walking primitive is the building block of ``WallSystemPathDecorator``;
    it must return the connected walls in BFS order regardless of which
    side of the relation the start lives on."""

    def _make_perpendicular_pair_and_fillet(self):
        from test.bim.module.model.test_wall_fillet_gizmo import (
            _create_perpendicular_wall_pair,
        )

        elem_a, elem_b = _create_perpendicular_wall_pair()
        result = bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=1.0)
        assert "FINISHED" in result
        ifc_file = tool.Ifc.get()
        # After the fillet, the project contains wall A, the curved corner,
        # and wall B — the corner is connected to BOTH originals.
        walls = ifc_file.by_type("IfcWall")
        assert len(walls) == 3
        corner = next(w for w in walls if w not in (elem_a, elem_b))
        return elem_a, elem_b, corner

    def test_walking_from_either_original_reaches_all_three_walls(self):
        """The fillet flow creates two ``IfcRelConnectsPathElements``
        (A↔corner, corner↔B). Walking from A must reach corner AND B; same
        for walking from B — both directions of the relation must be
        traversed."""
        elem_a, elem_b, corner = self._make_perpendicular_pair_and_fillet()

        from_a = tool.Wall.walk_connected_walls(elem_a)
        assert {w.id() for w in from_a} == {elem_a.id(), corner.id(), elem_b.id()}
        assert from_a[0].id() == elem_a.id(), "start element must come first in BFS order"

        from_b = tool.Wall.walk_connected_walls(elem_b)
        assert {w.id() for w in from_b} == {elem_a.id(), elem_b.id(), corner.id()}
        assert from_b[0].id() == elem_b.id()

    def test_walking_from_corner_reaches_both_originals(self):
        """The corner sits in the middle of the connection graph. Walking
        from it must reach both originals in a single BFS pass — pins the
        guarantee that mixed in / out-edges traverse correctly."""
        elem_a, elem_b, corner = self._make_perpendicular_pair_and_fillet()

        from_corner = tool.Wall.walk_connected_walls(corner)
        assert {w.id() for w in from_corner} == {elem_a.id(), elem_b.id(), corner.id()}

    def test_walking_returns_just_start_for_isolated_wall(self):
        """An IfcWall with no ``IfcRelConnectsPathElements`` returns a
        single-element list. The pristine project's first wall is the
        natural fixture for this — no fillet, no connection."""
        from test.bim.module.model.test_wall_fillet_gizmo import (
            _create_perpendicular_wall_pair,
        )

        elem_a, _ = _create_perpendicular_wall_pair()
        # Pre-fillet, neither wall has IfcRelConnectsPathElements — walking
        # from one must yield only itself.
        result = tool.Wall.walk_connected_walls(elem_a)
        assert [w.id() for w in result] == [elem_a.id()]


@pytest.mark.model
class TestHasAxisRepresentation:
    """Pin the predicate ``tool.Geometry.has_axis_representation`` against
    raw IFC entities. Anything that draws a schematic 1D path overlay must
    consult this predicate before deriving coordinates — elements without an
    Axis representation cannot be projected to an unambiguous line, and
    falling back to mesh-derived geometry produces misleading overlays."""

    def test_element_without_representation_is_rejected(self):
        ifc_file = ifcopenshell.file()
        element = ifc_file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
        assert tool.Geometry.has_axis_representation(element) is False

    def test_element_with_body_only_is_rejected(self):
        ifc_file = ifcopenshell.file()
        element = ifc_file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
        body = ifc_file.create_entity(
            "IfcShapeRepresentation",
            RepresentationIdentifier="Body",
            RepresentationType="Brep",
            Items=[],
        )
        element.Representation = ifc_file.create_entity("IfcProductDefinitionShape", Representations=[body])
        assert tool.Geometry.has_axis_representation(element) is False

    def test_element_with_axis_is_accepted(self):
        ifc_file = ifcopenshell.file()
        element = ifc_file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
        axis = ifc_file.create_entity(
            "IfcShapeRepresentation",
            RepresentationIdentifier="Axis",
            RepresentationType="Curve2D",
            Items=[],
        )
        element.Representation = ifc_file.create_entity("IfcProductDefinitionShape", Representations=[axis])
        assert tool.Geometry.has_axis_representation(element) is True

    def test_element_with_body_and_axis_is_accepted(self):
        ifc_file = ifcopenshell.file()
        element = ifc_file.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new())
        axis = ifc_file.create_entity(
            "IfcShapeRepresentation",
            RepresentationIdentifier="Axis",
            RepresentationType="Curve2D",
            Items=[],
        )
        body = ifc_file.create_entity(
            "IfcShapeRepresentation",
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[],
        )
        element.Representation = ifc_file.create_entity("IfcProductDefinitionShape", Representations=[axis, body])
        assert tool.Geometry.has_axis_representation(element) is True


@pytest.mark.model
def test_wall_seed_skips_wall_without_axis_representation(monkeypatch):
    """A selected IfcWall that lacks an IFC Axis representation (custom
    BREP-only body) must not seed the overlay. The decorator can only
    project walls with a real reference axis to a 1D path; falling back to
    the synthetic 1m line from ``get_reference_line``'s last-resort path
    would draw a misleading segment at the object origin."""
    from bonsai.bim import decorator_cache
    from bonsai.bim.module.model.decorator import WallSystemPathDecorator

    decorator_cache.reset_for_test()
    decorator = WallSystemPathDecorator()

    element = Mock()
    element.GlobalId = "guid-brep-only"
    element.is_a = Mock(return_value=True)
    obj = Mock()

    build = Mock(return_value=([], []))
    monkeypatch.setattr(decorator, "_build_geometry", build)

    walk = Mock(return_value=[element])

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch.object(
                tool.Model,
                "get_model_props",
                return_value=SimpleNamespace(show_paths=True),
            )
        )
        stack.enter_context(patch.object(tool.Ifc, "get", return_value=Mock(name="ifc_file")))
        stack.enter_context(patch.object(tool.Ifc, "get_entity", return_value=element))
        stack.enter_context(patch.object(tool.Geometry, "has_axis_representation", return_value=False))
        stack.enter_context(patch.object(tool.Wall, "walk_connected_walls", walk))
        stack.enter_context(
            patch.object(
                tool.Blender,
                "get_addon_preferences",
                return_value=SimpleNamespace(decorator_color_selected=(1.0, 0.5, 0.0, 1.0)),
            )
        )
        stack.enter_context(patch.object(decorator_module, "_stroke_lines_alpha", return_value=None))
        ctx = SimpleNamespace(selected_objects=[obj])
        decorator.draw(ctx)

    assert walk.call_count == 0, "axis-less seed must short-circuit before walk"
    assert build.call_count == 0, "axis-less seed must short-circuit before geometry build"
