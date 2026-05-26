# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2022 Dion Moult <dion@thinkmoult.com>
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

import json
from typing import Any

import bpy
import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.material
import ifcopenshell.api.root
import ifcopenshell.api.style
import ifcopenshell.api.type
import ifcopenshell.util.element
import ifcopenshell.util.representation
import ifcopenshell.util.shape_builder
import numpy as np
import pytest
from ifcopenshell.util.shape_builder import ShapeBuilder, V

import bonsai.core.tool
import bonsai.tool as tool
from bonsai.tool.model import Model as subject
from test.bim.bootstrap import NewFile


class TestImplementsTool(NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.Model)


class TestResolveActivePropsForEdit(NewFile):
    """Branch coverage for the active-object + is_editing + (optional) subtype
    guard helper. Operators that delegate their guard preamble here rely on
    each branch returning ``None`` cleanly so they can ``return {"CANCELLED"}``.

    The helper only touches ``context.active_object`` from the bpy surface; a
    ``Mock(spec=bpy.types.Context)`` is sufficient to drive each branch
    without instantiating real objects.
    """

    @staticmethod
    def _make_context(active_object):
        from unittest.mock import Mock

        context = Mock(spec=bpy.types.Context)
        context.active_object = active_object
        return context

    def test_returns_none_when_no_active_object(self):
        context = self._make_context(active_object=None)

        # props_getter must NOT be invoked when there's no active object,
        # so a raise here would fail the test loudly.
        def boom(_obj):
            raise AssertionError("props_getter must not be called without an active object")

        assert subject.resolve_active_props_for_edit(context, boom) is None

    def test_returns_none_when_props_not_editing(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        obj = Mock(spec=bpy.types.Object)
        context = self._make_context(active_object=obj)
        props = SimpleNamespace(is_editing=False)

        assert subject.resolve_active_props_for_edit(context, lambda _o: props) is None

    def test_returns_tuple_when_editing_and_no_subtype_constraint(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        obj = Mock(spec=bpy.types.Object)
        context = self._make_context(active_object=obj)
        props = SimpleNamespace(is_editing=True)

        result = subject.resolve_active_props_for_edit(context, lambda _o: props)
        assert result == (obj, props)

    def test_returns_none_when_subtype_does_not_match(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        obj = Mock(spec=bpy.types.Object)
        context = self._make_context(active_object=obj)
        props = SimpleNamespace(is_editing=True, kind="FOO")

        result = subject.resolve_active_props_for_edit(context, lambda _o: props, subtype=("kind", "BAR"))
        assert result is None

    def test_returns_tuple_when_subtype_matches(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        obj = Mock(spec=bpy.types.Object)
        context = self._make_context(active_object=obj)
        props = SimpleNamespace(is_editing=True, kind="BAR")

        result = subject.resolve_active_props_for_edit(context, lambda _o: props, subtype=("kind", "BAR"))
        assert result == (obj, props)

    def test_returns_none_when_subtype_attr_missing_on_props(self):
        """A typo'd ``subtype`` attr should fail closed (None), not silently
        succeed — otherwise a refactor that renames the props field would
        accept every input and pass the guard."""
        from types import SimpleNamespace
        from unittest.mock import Mock

        obj = Mock(spec=bpy.types.Object)
        context = self._make_context(active_object=obj)
        # is_editing True but the props lacks the requested ``kind`` attr.
        props = SimpleNamespace(is_editing=True)

        result = subject.resolve_active_props_for_edit(context, lambda _o: props, subtype=("kind", "BAR"))
        assert result is None


class TestGenerateOccurrenceName(NewFile):
    def test_generating_based_on_class(self):
        ifc = ifcopenshell.file()
        element_type = ifc.createIfcWallType(Name="Foobar")
        prefs = tool.Blender.get_addon_preferences()
        with tool.Blender.preserve_prop_value(prefs, "occurrence_name_style"):
            prefs.occurrence_name_style = "CLASS"
            assert subject.generate_occurrence_name(element_type, "IfcWall") == "Wall"

    def test_generating_based_on_type_name(self):
        ifc = ifcopenshell.file()
        element_type = ifc.createIfcWallType()
        prefs = tool.Blender.get_addon_preferences()
        with tool.Blender.preserve_prop_value(prefs, "occurrence_name_style"):
            prefs.occurrence_name_style = "TYPE"
            assert subject.generate_occurrence_name(element_type, "IfcWall") == "Unnamed"
            element_type.Name = "Foobar"
            assert subject.generate_occurrence_name(element_type, "IfcWall") == "Foobar"

    def test_generating_based_on_a_custom_function(self):
        ifc = ifcopenshell.file()
        element_type = ifc.createIfcWallType()
        prefs = tool.Blender.get_addon_preferences()
        with tool.Blender.preserve_prop_value(prefs, "occurrence_name_style"):
            prefs.occurrence_name_style = "CUSTOM"
            prefs.occurrence_name_function = '"Foobar"'
            assert subject.generate_occurrence_name(element_type, "IfcWall") == "Foobar"


class TestGetBooleans(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)

        context = ifc.createIfcGeometricRepresentationContext()
        element = ifc.createIfcWall()

        items = [ifc.createIfcExtrudedAreaSolid()]
        representation = ifc.createIfcShapeRepresentation(Items=items, ContextOfItems=context)
        ifcopenshell.api.geometry.assign_representation(ifc, product=element, representation=representation)

        builder = ifcopenshell.util.shape_builder.ShapeBuilder(ifc)
        cut1 = builder.half_space_solid(builder.plane())
        cut2 = builder.half_space_solid(builder.plane())
        bools = ifcopenshell.api.geometry.add_boolean(ifc, first_item=items[0], second_items=[cut1, cut2])

        assert set(subject.get_booleans(element, representation)) == set(bools)


class TestGetManualBooleans(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)

        context = ifc.createIfcGeometricRepresentationContext()
        element = ifc.createIfcWall()

        items = [ifc.createIfcExtrudedAreaSolid()]
        representation = ifc.createIfcShapeRepresentation(Items=items, ContextOfItems=context)
        ifcopenshell.api.geometry.assign_representation(ifc, product=element, representation=representation)

        builder = ifcopenshell.util.shape_builder.ShapeBuilder(ifc)
        cut1 = builder.half_space_solid(builder.plane())
        cut2 = builder.half_space_solid(builder.plane())
        bools = ifcopenshell.api.geometry.add_boolean(ifc, first_item=items[0], second_items=[cut1, cut2])

        assert set(subject.get_booleans(element, representation)) == set(bools)
        assert len(subject.get_manual_booleans(element, representation)) == 0

        bool1 = bools[0]

        subject.mark_manual_booleans(element, [bool1])
        assert set(subject.get_manual_booleans(element, representation)) == {bool1}


class TestMarkManualBooleans(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)

        element = ifc.createIfcWall()
        boolean = ifc.createIfcBooleanClippingResult()
        subject.mark_manual_booleans(element, [boolean])
        pset = ifcopenshell.util.element.get_pset(element, "BBIM_Boolean")
        assert pset
        value = json.loads(pset["Data"])
        assert set(value) == {boolean.id()}


class TestUnmarkManualBooleans(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)

        element = ifc.createIfcWall()
        boolean = ifc.createIfcBooleanClippingResult()
        boolean2 = ifc.createIfcBooleanClippingResult()
        subject.mark_manual_booleans(element, [boolean, boolean2])
        subject.unmark_manual_booleans(element, [boolean.id()])

        pset = ifcopenshell.util.element.get_pset(element, "BBIM_Boolean")
        assert pset
        value = json.loads(pset["Data"])
        assert set(value) == {boolean2.id()}


class TestStairCalculatedParams(NewFile):
    def compare_data(self, pset_data, expected_calculated_data):
        calculated_data = subject.get_active_stair_calculated_params(pset_data)
        for key, value in expected_calculated_data.items():
            assert tool.Cad.is_x(calculated_data[key], value)

    def test_run(self):
        bpy.ops.bim.create_project()
        bpy.ops.mesh.add_stair()
        pset_data_base = {
            "number_of_treads": 3,
            "height": 1.0,
            "tread_run": 0.3,
            "custom_first_last_tread_run": (None, None),
            "nosing_length": 0.0,
        }
        calculated_data_base = {
            "Number of Risers": 4,
            "Tread Rise": 0.25,
            "Length": 1.2,
        }
        self.compare_data(pset_data_base, calculated_data_base)

        # custom first and last treads run
        pset_data = pset_data_base.copy()
        calculated_data = calculated_data_base.copy()
        pset_data["custom_first_last_tread_run"] = (0.1, 0.4)
        pset_data["custom_tread_lock"] = False
        calculated_data["Length"] += -0.2 + 0.1
        self.compare_data(pset_data, calculated_data)

        # zero-width first tread
        pset_data = pset_data_base.copy()
        calculated_data = calculated_data_base.copy()
        pset_data["custom_first_last_tread_run"] = (0.0, None)
        pset_data["custom_tread_lock"] = False
        calculated_data["Length"] = 0.9  # Only 3 treads at 0.3 each
        self.compare_data(pset_data, calculated_data)

        # zero-width last tread
        pset_data = pset_data_base.copy()
        calculated_data = calculated_data_base.copy()
        pset_data["custom_first_last_tread_run"] = (None, 0.0)
        pset_data["custom_tread_lock"] = False
        calculated_data["Length"] = 0.9  # Only 3 treads at 0.3 each
        self.compare_data(pset_data, calculated_data)

        # both first and last treads zero-width
        pset_data = pset_data_base.copy()
        calculated_data = calculated_data_base.copy()
        pset_data["custom_first_last_tread_run"] = (0.0, 0.0)
        pset_data["custom_tread_lock"] = False
        calculated_data["Length"] = 0.6  # Only 2 middle treads at 0.3 each
        self.compare_data(pset_data, calculated_data)

        # overlap affects stair length only by first tread
        pset_data = pset_data_base.copy()
        calculated_data = calculated_data_base.copy()
        pset_data["nosing_length"] = 0.1
        calculated_data["Length"] += 0.1
        self.compare_data(pset_data, calculated_data)

        # tread gap
        pset_data = pset_data_base.copy()
        calculated_data = calculated_data_base.copy()
        pset_data["nosing_length"] = -0.1
        calculated_data["Length"] += 0.1 * pset_data["number_of_treads"]
        self.compare_data(pset_data, calculated_data)


class TestGenerateStair2DProfile(NewFile):
    def compare_data(self, generated_profile, expected_profile):
        verts_gen, edges_gen, faces_gen = generated_profile
        verts, edges, faces = expected_profile

        assert np.all(edges == np.array(edges_gen))
        assert faces == tuple(tuple(face) for face in faces_gen)
        for vert, vert_gen in zip(verts, verts_gen, strict=True):
            assert np.allclose(vert, V(vert_gen), atol=0.01)

    CONCRETE_STAIR_KWARGS: dict[str, Any] = {
        "base_slab_depth": 0.25,
        "has_top_nib": False,
        "height": 1.0,
        "number_of_treads": 3,
        "stair_type": "CONCRETE",
        "top_slab_depth": 0.25,
        "tread_depth": 0.25,
        "tread_run": 0.3,
        "width": 1.2,
    }

    def test_create_concrete_stair(self):
        kwargs = self.CONCRETE_STAIR_KWARGS.copy()
        verts_data = (
            V(0.0, 0, 0.0),
            V(0.0, 0, 0.25),
            V(0.3, 0, 0.25),
            V(0.3, 0, 0.5),
            V(0.6, 0, 0.5),
            V(0.6, 0, 0.75),
            V(0.9, 0, 0.75),
            V(0.9, 0, 1.0),
            V(1.2, 0, 1.0),
            V(1.2, 0, 0.67457),
            V(0.1, 0, -0.25),
            V(0.0, 0, -0.25),
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 4),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 8),
            (8, 9),
            (11, 0),
            (10, 11),
            (9, 10),
        )
        edges_data = [e[::-1] for e in edges_data]
        faces_data = ()
        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)

    def test_create_concrete_stair_nib(self):
        kwargs = self.CONCRETE_STAIR_KWARGS.copy()
        kwargs["has_top_nib"] = True
        verts_data = (
            V(0.0, 0, 0.0),
            V(0.0, 0, 0.25),
            V(0.3, 0, 0.25),
            V(0.3, 0, 0.5),
            V(0.6, 0, 0.5),
            V(0.6, 0, 0.75),
            V(0.9, 0, 0.75),
            V(0.9, 0, 1.0),
            V(1.2, 0, 1.0),
            V(1.2, 0, 0.75),
            V(1.3, 0, 0.75),
            V(0.1, 0, -0.25),
            V(0.0, 0, -0.25),
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 4),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 8),
            (8, 9),
            (9, 10),
            (12, 0),
            (11, 12),
            (10, 11),
        )
        edges_data = [e[::-1] for e in edges_data]

        faces_data = ()
        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)

    def test_create_concrete_stair_zero_width_first_tread(self):
        kwargs = self.CONCRETE_STAIR_KWARGS.copy()
        kwargs["custom_first_last_tread_run"] = (0.0, None)
        verts_data = (
            V(0.0, 0, 0.0),
            # First tread skipped - goes straight to second tread
            V(0.0, 0, 0.5),
            V(0.3, 0, 0.5),
            V(0.3, 0, 0.75),
            V(0.6, 0, 0.75),
            V(0.6, 0, 1.0),
            V(0.9, 0, 1.0),
            V(0.9, 0, 0.6745729),
            V(0.0, 0, -0.0754271),
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 4),
            (4, 5),
            (5, 6),
            (6, 7),
            (8, 0),
            (7, 8),
        )
        edges_data = [e[::-1] for e in edges_data]
        faces_data = ()
        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)

    def test_create_concrete_stair_zero_width_last_tread(self):
        kwargs = self.CONCRETE_STAIR_KWARGS.copy()
        kwargs["custom_first_last_tread_run"] = (None, 0.0)
        verts_data = (
            V(0.0, 0, 0.0),
            V(0.0, 0, 0.25),
            V(0.3, 0, 0.25),
            V(0.3, 0, 0.5),
            V(0.6, 0, 0.5),
            V(0.6, 0, 0.75),
            V(0.9, 0, 0.75),
            # Last tread skipped
            V(0.9, 0, 0.42457),
            V(0.1, 0, -0.25),
            V(0.0, 0, -0.25),
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 4),
            (4, 5),
            (5, 6),
            (6, 7),
            (9, 0),
            (8, 9),
            (7, 8),
        )
        edges_data = [e[::-1] for e in edges_data]
        faces_data = ()
        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)

    WOOD_STEEL_STAIR_KWARGS: dict[str, Any] = {
        "height": 1.0,
        "number_of_treads": 3,
        "stair_type": "WOOD/STEEL",
        "tread_depth": 0.25,
        "tread_run": 0.3,
        "width": 1.2,
    }

    def test_create_wood_steel_stair(self):
        kwargs = self.WOOD_STEEL_STAIR_KWARGS.copy()
        verts_data = (
            V(0.0, 0, 0.0),
            V(0.3, 0, 0.0),
            V(0.3, 0, 0.25),
            V(0.0, 0, 0.25),
            V(0.3, 0, 0.25),
            V(0.6, 0, 0.25),
            V(0.6, 0, 0.5),
            V(0.3, 0, 0.5),
            V(0.6, 0, 0.5),
            V(0.9, 0, 0.5),
            V(0.9, 0, 0.75),
            V(0.6, 0, 0.75),
            V(0.9, 0, 0.75),
            V(1.2, 0, 0.75),
            V(1.2, 0, 1.0),
            V(0.9, 0, 1.0),
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 0),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 4),
            (8, 9),
            (9, 10),
            (10, 11),
            (11, 8),
            (12, 13),
            (13, 14),
            (14, 15),
            (15, 12),
        )

        faces_data = ()

        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)

    def test_create_wood_steel_stair_zero_width_first_tread(self):
        kwargs = self.WOOD_STEEL_STAIR_KWARGS.copy()
        kwargs["custom_first_last_tread_run"] = (0.0, None)
        verts_data = (
            # First tread skipped - start at second tread
            V(0.0, 0, 0.25),
            V(0.3, 0, 0.25),
            V(0.3, 0, 0.5),
            V(0.0, 0, 0.5),
            V(0.3, 0, 0.5),
            V(0.6, 0, 0.5),
            V(0.6, 0, 0.75),
            V(0.3, 0, 0.75),
            V(0.6, 0, 0.75),
            V(0.9, 0, 0.75),
            V(0.9, 0, 1.0),
            V(0.6, 0, 1.0),
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 0),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 4),
            (8, 9),
            (9, 10),
            (10, 11),
            (11, 8),
        )

        faces_data = ()

        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)

    def test_create_wood_steel_stair_zero_width_last_tread(self):
        """Test wood/steel stair with zero-width last tread"""
        kwargs = self.WOOD_STEEL_STAIR_KWARGS.copy()
        kwargs["custom_first_last_tread_run"] = (None, 0.0)

        verts_data = (
            V(0.0, 0, 0.0),
            V(0.3, 0, 0.0),
            V(0.3, 0, 0.25),
            V(0.0, 0, 0.25),
            V(0.3, 0, 0.25),
            V(0.6, 0, 0.25),
            V(0.6, 0, 0.5),
            V(0.3, 0, 0.5),
            V(0.6, 0, 0.5),
            V(0.9, 0, 0.5),
            V(0.9, 0, 0.75),
            V(0.6, 0, 0.75),
            # Last tread skipped
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 0),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 4),
            (8, 9),
            (9, 10),
            (10, 11),
            (11, 8),
        )

        faces_data = ()

        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)

    GENERIC_STAIR_KWARGS: dict[str, Any] = {
        "height": 1.0,
        "number_of_treads": 3,
        "stair_type": "GENERIC",
        "tread_run": 0.3,
        "width": 1.2,
    }

    def test_create_generic_stair(self):
        kwargs = self.GENERIC_STAIR_KWARGS.copy()
        verts_data = (
            V(0.0, 0, 0.0),
            V(0.0, 0, 0.25),
            V(0.3, 0, 0.25),
            V(0.3, 0, 0.5),
            V(0.6, 0, 0.5),
            V(0.6, 0, 0.75),
            V(0.9, 0, 0.75),
            V(0.9, 0, 1.0),
            V(1.2, 0, 1.0),
            V(1.2, 0, 0.0),
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 4),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 8),
            (8, 9),
            (9, 0),
        )
        edges_data = [e[::-1] for e in edges_data]

        faces_data = ()
        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)

    def test_create_generic_stair_zero_width_treads(self):
        kwargs = self.GENERIC_STAIR_KWARGS.copy()
        kwargs["custom_first_last_tread_run"] = (0.0, 0.0)
        verts_data = (
            V(0.0, 0, 0.0),
            # First tread skipped
            V(0.0, 0, 0.5),
            V(0.3, 0, 0.5),
            V(0.3, 0, 0.75),
            V(0.6, 0, 0.75),
            # Last tread skipped
            V(0.6, 0, 0.0),
        )
        edges_data = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 4),
            (4, 5),
            (5, 0),
        )
        edges_data = [e[::-1] for e in edges_data]

        faces_data = ()
        expected_profile = (verts_data, edges_data, faces_data)
        generated_profile = subject.generate_stair_2d_profile(**kwargs)
        self.compare_data(generated_profile, expected_profile)


class TestUsingArrays(NewFile):
    def setup_array(self, add_second_layer=False, sync_children=False):
        tool.Project.get_project_props().template_file = "0"
        bpy.ops.bim.create_project()

        bpy.ops.mesh.primitive_cube_add()
        obj = bpy.context.active_object
        assert obj
        rprops = tool.Root.get_root_props()
        rprops.ifc_product = "IfcElement"
        bpy.ops.bim.assign_class(ifc_class="IfcActuator", predefined_type="ELECTRICACTUATOR", userdefined_type="")

        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(obj)
        props.count = 4
        props.x = 4
        props.sync_children = sync_children
        bpy.ops.bim.edit_array(item=0)

        if add_second_layer:
            bpy.ops.bim.add_array()
            bpy.ops.bim.enable_editing_array_item(item=1)
            props = tool.Model.get_array_props(obj)
            props.count = 3
            props.y = 4
            props.sync_children = sync_children
            bpy.ops.bim.edit_array(item=1)

    def test_remove_array_last_to_first(self):
        self.setup_array(add_second_layer=True)
        bpy.ops.bim.remove_array(item=1)
        assert len(bpy.context.selected_objects) == 4
        bpy.ops.bim.remove_array(item=0)
        assert len(bpy.context.selected_objects) == 1

    def test_remove_array_first_to_last(self):
        self.setup_array(add_second_layer=True)
        bpy.ops.bim.remove_array(item=0)
        assert len(bpy.context.selected_objects) == 3
        bpy.ops.bim.remove_array(item=0)
        assert len(bpy.context.selected_objects) == 1

    def test_apply_array_1_layer(self):
        self.setup_array()
        bpy.ops.bim.apply_array()

        objs = bpy.context.selected_objects
        assert len(objs) == 4
        # check BBIM_Array psets are removed
        for obj in objs:
            element = tool.Ifc.get_entity(obj)
            pset = ifcopenshell.util.element.get_pset(element, "BBIM_Array")
            assert pset is None, (obj, pset)

    def test_apply_array_multiple_layers(self):
        self.setup_array(add_second_layer=True)
        bpy.ops.bim.apply_array()  # apply second layer
        bpy.ops.bim.apply_array()  # apply first layer

        objs = bpy.context.selected_objects
        assert len(objs) == 12

        # check BBIM_Array psets are removed
        for obj in objs:
            element = tool.Ifc.get_entity(obj)
            pset = ifcopenshell.util.element.get_pset(element, "BBIM_Array")
            assert pset is None, (obj, pset)

    def test_apply_array_with_sync_children(self):
        self.setup_array(sync_children=True)
        bpy.ops.bim.apply_array()

        objs = bpy.context.selected_objects
        assert len(objs) == 4
        # check BBIM_Array psets are removed
        for obj in objs:
            element = tool.Ifc.get_entity(obj)
            pset = ifcopenshell.util.element.get_pset(element, "BBIM_Array")
            assert pset is None, (obj, pset)

    def test_handle_array_on_copied_element_detaches_copy_only(self):
        """The detach branch (``array_data=None``) of the post-copy hook must
        remove the BBIM_Array pset from the COPY without touching the source.

        Exercises the contract that ``DumbWallJoiner.duplicate_wall`` relies on
        when splitting a wall that is part of an array: the split-off half is
        produced via ``bonsai.core.root.copy_class`` (which copies the pset
        verbatim) and then scrubbed via this hook. A regression here would
        cause the split-off wall to pose as an array child of the source."""
        import bonsai.core.root

        self.setup_array()
        parent_obj = bpy.context.active_object
        parent_element = tool.Ifc.get_entity(parent_obj)
        assert ifcopenshell.util.element.get_pset(parent_element, "BBIM_Array") is not None

        # Mimic the wall-split duplicate path: clone bpy obj, then copy_class
        # to create a new IFC entity that inherits the source's BBIM_Array pset.
        copy_obj = parent_obj.copy()
        copy_obj.data = parent_obj.data.copy()
        for collection in parent_obj.users_collection:
            collection.objects.link(copy_obj)
        bonsai.core.root.copy_class(tool.Ifc, tool.Collector, tool.Geometry, tool.Root, obj=copy_obj)
        copy_element = tool.Ifc.get_entity(copy_obj)
        assert copy_element is not None
        assert ifcopenshell.util.element.get_pset(copy_element, "BBIM_Array") is not None

        subject.handle_array_on_copied_element(copy_element, array_data=None)

        assert ifcopenshell.util.element.get_pset(copy_element, "BBIM_Array") is None
        # Source parent's pset must remain intact — its array keeps working.
        assert ifcopenshell.util.element.get_pset(parent_element, "BBIM_Array") is not None


class TestMirrorParentVoidFillingsToChildren(NewFile):
    """Array children of a filling inherit their parent's void+filling chain.

    The contract: when the array parent is a door / window / generic filling
    that voids a host element (wall, slab, …), each child element receives
    its own IfcOpeningElement cut into the same host, sharing the parent's
    opening representation via a MappedRepresentation. Without this, an
    arrayed door appears to pass through solid wall material — semantically
    invalid for any downstream IFC consumer (validators, clash, schedules).
    """

    def _setup_door_in_wall(self):
        bpy.ops.bim.create_project()
        bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
        wall_obj = bpy.context.active_object
        assert wall_obj
        rprops = tool.Root.get_root_props()
        rprops.ifc_product = "IfcElement"
        bpy.ops.bim.assign_class(ifc_class="IfcWall")

        bpy.ops.mesh.primitive_cube_add(size=0.4, location=(0, 0, 0.5))
        door_obj = bpy.context.active_object
        assert door_obj
        rprops.ifc_product = "IfcElement"
        bpy.ops.bim.assign_class(ifc_class="IfcDoor")

        # Wire FillsVoids manually using the same building blocks the
        # canonical generator does, minus its wall-axis snap (which expects a
        # parametric wall with a material layer set — this test uses a bare
        # mesh wall).
        import ifcopenshell.api.feature
        import ifcopenshell.api.root

        from bonsai.bim.module.model.opening import FilledOpeningGenerator

        door = tool.Ifc.get_entity(door_obj)
        wall = tool.Ifc.get_entity(wall_obj)
        ifc_file = tool.Ifc.get()

        opening = ifcopenshell.api.root.create_entity(
            ifc_file, ifc_class="IfcOpeningElement", predefined_type="OPENING", name="Opening"
        )
        ifcopenshell.api.geometry.edit_object_placement(
            ifc_file, product=opening, matrix=np.array(door_obj.matrix_world), is_si=True
        )
        representation = FilledOpeningGenerator().generate_opening_from_filling(
            door, door_obj, opening_thickness_si=0.5
        )
        mapped = ifcopenshell.api.geometry.map_representation(ifc_file, representation=representation)
        ifcopenshell.api.geometry.assign_representation(ifc_file, product=opening, representation=mapped)
        ifcopenshell.api.feature.add_feature(ifc_file, feature=opening, element=wall)
        ifcopenshell.api.feature.add_filling(ifc_file, opening=opening, element=door)
        return wall_obj, door_obj

    def _activate(self, obj):
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

    def test_no_op_when_parent_has_no_fills_voids(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        parent = ifc.createIfcWall()
        child = ifc.createIfcWall()

        subject.mirror_parent_void_fillings_to_children(parent, [child])

        assert not ifc.by_type("IfcOpeningElement")
        assert not ifc.by_type("IfcRelVoidsElement")
        assert not ifc.by_type("IfcRelFillsElement")

    def test_unshare_opening_representation_replaces_representation_with_deep_copy(self):
        """Directly exercising the helper: after the call, the filling's
        opening must have a Representation entity distinct from any other
        sibling's, so a subsequent body-replacement on the original cannot
        cascade through it."""
        wall_obj, door_obj = self._setup_door_in_wall()
        door = tool.Ifc.get_entity(door_obj)
        original_rep = door.FillsVoids[0].RelatingOpeningElement.Representation

        subject.unshare_opening_representation(door)

        detached_rep = door.FillsVoids[0].RelatingOpeningElement.Representation
        assert detached_rep is not None
        assert detached_rep != original_rep, (
            "Opening Representation should be a distinct entity after detach — "
            "got the original entity back."
        )

    def test_unshare_opening_representation_no_op_for_filling_without_fills_voids(self):
        """A filling without ``FillsVoids`` (e.g. orphaned window with no
        opening) is a defensible no-op — the helper must not crash and must
        not mutate any unrelated entity."""
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        filling = ifc.createIfcDoor()
        before = len(list(ifc))

        subject.unshare_opening_representation(filling)

        assert len(list(ifc)) == before

    def test_no_op_when_children_list_is_empty(self):
        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)
        door = tool.Ifc.get_entity(door_obj)
        before = len(wall.HasOpenings)

        subject.mirror_parent_void_fillings_to_children(door, [])

        assert len(wall.HasOpenings) == before

    def test_array_through_add_array_creates_openings_for_each_child(self):
        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)
        assert len(wall.HasOpenings) == 1

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)

        # parent + 2 new children → 3 openings, each linked to a distinct filling
        assert len(wall.HasOpenings) == 3
        filling_ids = set()
        for rel in wall.HasOpenings:
            opening = rel.RelatedOpeningElement
            assert opening.HasFillings, "Every child opening must reference its filling"
            filling_ids.add(opening.HasFillings[0].RelatedBuildingElement.GlobalId)
        assert len(filling_ids) == 3, "Each child must be the filling of its own opening"
        assert tool.Ifc.get_entity(door_obj).GlobalId in filling_ids

    def test_opt_out_via_per_child_opening_false_leaves_host_uncut(self):
        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)
        baseline_openings = len(wall.HasOpenings)

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        props.per_child_opening = False
        bpy.ops.bim.edit_array(item=0)

        # Only the parent's original opening remains; children are free-floating.
        assert len(wall.HasOpenings) == baseline_openings

    def test_count_reduction_removes_orphaned_child_openings(self):
        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 4
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)
        assert len(wall.HasOpenings) == 4

        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 2
        bpy.ops.bim.edit_array(item=0)

        # Removed children must take their openings with them — host stays symmetric.
        assert len(wall.HasOpenings) == 2

    def test_multi_layer_array_mirrors_all_children(self):
        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)

        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=1)
        props = tool.Model.get_array_props(door_obj)
        props.count = 2
        props.z = 1.0
        bpy.ops.bim.edit_array(item=1)

        # 3 (X) * 2 (Z) = 6 doors; each layer's mirror call must fire.
        assert len(wall.HasOpenings) == 6
        filling_ids = {
            rel.RelatedOpeningElement.HasFillings[0].RelatedBuildingElement.GlobalId for rel in wall.HasOpenings
        }
        assert len(filling_ids) == 6, "Each of the 6 array instances gets its own opening + filling"

    def test_apply_preserves_child_fillings(self):
        """Applying the array converts children to standalone elements but their
        wall-filling relationship must survive — that's the whole point of the
        opening lifecycle being driven by ``regenerate_array``'s child set, not
        by the BBIM_Array pset's existence."""
        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)
        door = tool.Ifc.get_entity(door_obj)

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)
        assert len(wall.HasOpenings) == 3

        # Snapshot child GUIDs before apply — afterwards the BBIM_Array pset
        # (and its children list) is gone, so we need to capture identity now.
        parent_pset_data = json.loads(ifcopenshell.util.element.get_pset(door, "BBIM_Array", "Data"))
        child_guids = parent_pset_data[0]["children"]
        assert len(child_guids) == 2
        children = [tool.Ifc.get().by_guid(g) for g in child_guids]

        self._activate(door_obj)
        bpy.ops.bim.apply_array()

        # Apply contract: children lose their BBIM_Array pset (become standalone).
        for child in children:
            assert ifcopenshell.util.element.get_pset(child, "BBIM_Array") is None

        # Mirror contract: each former child still cuts and fills its own opening
        # on the same host wall — the apply path must NOT regress this.
        assert len(wall.HasOpenings) == 3, "Wall openings must survive array apply"
        for child in children:
            assert child.FillsVoids, f"Child {child.GlobalId} lost its filling on apply"
            host = child.FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement
            assert host == wall

    def test_apply_detaches_child_opening_bodies_from_parent(self):
        """After the apply path runs, every former child opening's body
        representation must be a distinct entity from the parent's — so an
        edit driving ``get_inverse`` on the parent body no longer cascades
        via the shared ``IfcRepresentationMap`` into the former-children."""
        wall_obj, door_obj = self._setup_door_in_wall()
        door = tool.Ifc.get_entity(door_obj)

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)

        parent_opening = door.FillsVoids[0].RelatingOpeningElement
        parent_body = ifcopenshell.util.representation.resolve_representation(
            ifcopenshell.util.representation.get_representation(parent_opening, "Model", "Body", "MODEL_VIEW")
        )

        # Snapshot children before apply — afterwards the BBIM_Array pset
        # (and its children list) is gone.
        parent_pset_data = json.loads(ifcopenshell.util.element.get_pset(door, "BBIM_Array", "Data"))
        child_guids = parent_pset_data[0]["children"]
        children = [tool.Ifc.get().by_guid(g) for g in child_guids]

        # Pre-apply sanity: children share the parent body via mapped representation —
        # this is the bug-prone state the fix must dissolve.
        for child in children:
            child_opening = child.FillsVoids[0].RelatingOpeningElement
            child_body = ifcopenshell.util.representation.resolve_representation(
                ifcopenshell.util.representation.get_representation(child_opening, "Model", "Body", "MODEL_VIEW")
            )
            assert child_body == parent_body

        self._activate(door_obj)
        bpy.ops.bim.apply_array()

        # Post-apply: each child opening's body must be its own deep-copy.
        for child in children:
            child_opening = child.FillsVoids[0].RelatingOpeningElement
            child_body = ifcopenshell.util.representation.resolve_representation(
                ifcopenshell.util.representation.get_representation(child_opening, "Model", "Body", "MODEL_VIEW")
            )
            assert child_body != parent_body, (
                f"Child {child.GlobalId} opening body still shares the parent's entity "
                f"after apply — independent edits will cascade across siblings."
            )

    def test_void_limit_skipped_openings_surface_in_pending_recut_and_apply_button_recuts(self):
        """When an array's child openings push a host over ``void_limit``, the
        importer skips opening subtractions and the host renders solid. The
        load operator must surface the affected host on
        ``BIMProjectProperties.pending_opening_recut`` so the Project panel
        banner offers a one-click recut, and the apply operator must restore
        the cuts when invoked."""
        from pathlib import Path

        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)

        # Exceed the default void_limit so the wall lands in ``gross_elements`` on load.
        array_count = tool.Project.get_project_props().void_limit + 5
        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = array_count
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)
        assert len(wall.HasOpenings) == array_count

        wall_guid = wall.GlobalId
        in_session_vertex_count = len(wall_obj.data.vertices)

        ifc_path = Path("test/files/temp/test_void_limit_pending_recut.ifc").absolute()
        ifc_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.bim.save_project(filepath=str(ifc_path), should_save_as=True)

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        reloaded_wall = tool.Ifc.get().by_guid(wall_guid)
        reloaded_wall_obj = tool.Ifc.get_object(reloaded_wall)
        assert reloaded_wall_obj is not None
        reloaded_uncut_vertex_count = len(reloaded_wall_obj.data.vertices)

        # Pending list contains the wall.
        pending = tool.Project.get_project_props().pending_opening_recut
        assert len(pending) == 1, f"Expected 1 pending entry, got {len(pending)}"
        assert pending[0].ifc_definition_id == reloaded_wall.id()

        # Wall is solid (kernel skipped cuts).
        assert reloaded_uncut_vertex_count < in_session_vertex_count, (
            f"Wall should have been loaded uncut: reloaded vertex count {reloaded_uncut_vertex_count} "
            f"is not less than in-session cut count {in_session_vertex_count}."
        )

        # Apply operator restores the cuts and clears the list.
        bpy.ops.bim.apply_pending_opening_cuts()

        recut_wall_obj = tool.Ifc.get_object(reloaded_wall)
        assert len(recut_wall_obj.data.vertices) == in_session_vertex_count, (
            f"After apply: vertex count {len(recut_wall_obj.data.vertices)} does not match in-session {in_session_vertex_count}."
        )
        assert len(tool.Project.get_project_props().pending_opening_recut) == 0, "Pending list should be empty after apply."

    def test_void_limit_pending_recut_select_picks_affected_blender_objects(self):
        """The select operator must resolve every pending-recut entry to its
        Blender object and replace the active selection with that set, so the
        user can jump directly to the affected elements before deciding to
        Apply or Dismiss."""
        from pathlib import Path

        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)
        wall_guid = wall.GlobalId

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = tool.Project.get_project_props().void_limit + 5
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)

        ifc_path = Path("test/files/temp/test_void_limit_select.ifc").absolute()
        ifc_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.bim.save_project(filepath=str(ifc_path), should_save_as=True)

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        reloaded_wall = tool.Ifc.get().by_guid(wall_guid)
        reloaded_wall_obj = tool.Ifc.get_object(reloaded_wall)
        assert len(tool.Project.get_project_props().pending_opening_recut) == 1

        # Pre-select something else so we can verify the operator replaces the
        # selection rather than appending to it.
        bpy.ops.object.select_all(action="DESELECT")
        bpy.ops.bim.select_pending_opening_cuts()

        selected = list(bpy.context.selected_objects)
        assert selected == [reloaded_wall_obj]
        assert bpy.context.view_layer.objects.active is reloaded_wall_obj

    def test_void_limit_pending_recut_select_no_op_when_ifc_unloaded(self):
        """The select operator must report a clean ``CANCELLED`` when invoked
        with no loaded IFC, rather than crashing on ``None.by_id``."""
        result = bpy.ops.bim.select_pending_opening_cuts()
        assert result == {"CANCELLED"}

    def test_void_limit_pending_recut_dismiss_clears_list_without_mutating_geometry(self):
        """The dismiss button must clear the pending list without touching
        any IFC entity or Blender mesh — the user can opt to leave the host
        uncut on purpose (e.g. performance preference)."""
        from pathlib import Path

        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)
        wall_guid = wall.GlobalId

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = tool.Project.get_project_props().void_limit + 5
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)

        ifc_path = Path("test/files/temp/test_void_limit_dismiss.ifc").absolute()
        ifc_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.bim.save_project(filepath=str(ifc_path), should_save_as=True)

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        reloaded_wall = tool.Ifc.get().by_guid(wall_guid)
        reloaded_wall_obj = tool.Ifc.get_object(reloaded_wall)
        before_vertex_count = len(reloaded_wall_obj.data.vertices)
        assert len(tool.Project.get_project_props().pending_opening_recut) == 1

        bpy.ops.bim.dismiss_pending_opening_cuts()

        assert len(tool.Project.get_project_props().pending_opening_recut) == 0
        # Geometry unchanged — dismiss is a no-op for the host mesh.
        assert len(reloaded_wall_obj.data.vertices) == before_vertex_count

    def test_array_child_openings_apply_to_wall_after_full_load_project_roundtrip(self):
        """Full roundtrip: save the file to disk, ``bim.load_project`` it
        back in a fresh session, and verify the wall mesh still has the
        array-child openings cut into it. This is the user's exact
        reproduction — opening a saved .ifc in a brand-new blend file."""
        from pathlib import Path

        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)
        assert len(wall.HasOpenings) == 3

        wall_guid = wall.GlobalId
        in_session_vertex_count = len(wall_obj.data.vertices)

        ifc_path = Path("test/files/temp/test_array_roundtrip.ifc").absolute()
        ifc_path.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.bim.save_project(filepath=str(ifc_path), should_save_as=True)

        bpy.ops.bim.load_project(filepath=str(ifc_path))

        ifc_file = tool.Ifc.get()
        round_wall = ifc_file.by_guid(wall_guid)
        assert len(round_wall.HasOpenings) == 3, "Wall lost openings after load_project"

        round_wall_obj = tool.Ifc.get_object(round_wall)
        assert round_wall_obj is not None
        reloaded_vertex_count = len(round_wall_obj.data.vertices)
        # The in-session wall was cut by 3 openings — the reloaded wall should
        # have the same (cut) topology. A naked cube/box would have 8 verts.
        assert reloaded_vertex_count == in_session_vertex_count, (
            f"Wall mesh vertex count changed across save/load: in-session={in_session_vertex_count}, "
            f"reloaded={reloaded_vertex_count} — array-child openings may not have been applied."
        )

    def test_array_child_openings_apply_to_wall_on_reimport(self):
        """After an array creates per-child openings, the host wall's mesh
        has the expected cuts. When the wall is re-imported by the geometry
        kernel (the same path file-load uses), the cuts must still be present
        — otherwise the wall appears solid where the children's openings
        should subtract from it."""
        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)
        assert len(wall.HasOpenings) == 3

        in_session_vertex_count = len(wall_obj.data.vertices)

        # Force a fresh kernel re-import — equivalent to opening the .ifc in
        # a new Blender session, but in-process.
        wall_body = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
        assert wall_body is not None
        tool.Geometry.reimport_element_representations(wall_obj, wall_body, apply_openings=True)

        reimported_vertex_count = len(wall_obj.data.vertices)

        # If the kernel applied the child openings, the reimported mesh should
        # have the same (or near-same) vertex count as the in-session one. A
        # drop close to "uncut cube" geometry (8 verts for a primitive cube)
        # is the signature of the bug — openings stayed in the IFC but the
        # kernel skipped them, so the wall renders solid.
        assert reimported_vertex_count > 8, (
            f"Wall mesh has only {reimported_vertex_count} vertices after kernel reimport — "
            f"the child openings did not cut the wall (in-session had {in_session_vertex_count})."
        )

    def test_array_child_openings_survive_ifc_roundtrip(self):
        """Diagnostic: after creating array-child openings via mirror, the
        ``IfcOpeningElement`` + ``IfcRelVoidsElement`` + ``IfcRelFillsElement``
        chain for each child must survive a textual IFC serialise/deserialise
        round-trip without entities being dropped or relationships breaking."""
        import ifcopenshell

        wall_obj, door_obj = self._setup_door_in_wall()
        wall = tool.Ifc.get_entity(wall_obj)
        door = tool.Ifc.get_entity(door_obj)

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)
        assert len(wall.HasOpenings) == 3

        wall_guid = wall.GlobalId
        door_guid = door.GlobalId
        child_guids = json.loads(ifcopenshell.util.element.get_pset(door, "BBIM_Array", "Data"))[0]["children"]
        assert len(child_guids) == 2

        # Snapshot opening + filling entity counts so the round-trip can be
        # compared against the in-session state.
        before_openings = len(tool.Ifc.get().by_type("IfcOpeningElement"))
        before_voids = len(tool.Ifc.get().by_type("IfcRelVoidsElement"))
        before_fills = len(tool.Ifc.get().by_type("IfcRelFillsElement"))

        # Serialise to text and parse back into a fresh in-memory file —
        # mirrors what writing then re-opening the .ifc does at the entity
        # level (representation reduction, ownership history walk, etc.).
        roundtripped = ifcopenshell.file.from_string(tool.Ifc.get().to_string())

        assert len(roundtripped.by_type("IfcOpeningElement")) == before_openings
        assert len(roundtripped.by_type("IfcRelVoidsElement")) == before_voids
        assert len(roundtripped.by_type("IfcRelFillsElement")) == before_fills

        round_wall = roundtripped.by_guid(wall_guid)
        round_door = roundtripped.by_guid(door_guid)
        assert len(round_wall.HasOpenings) == 3
        assert round_door.FillsVoids, "Parent door lost its filling after roundtrip"

        for child_guid in child_guids:
            child = roundtripped.by_guid(child_guid)
            assert child.FillsVoids, f"Array child {child_guid} lost its filling after roundtrip"
            child_opening = child.FillsVoids[0].RelatingOpeningElement
            host = child_opening.VoidsElements[0].RelatingBuildingElement
            assert host == round_wall, f"Child {child_guid} opening no longer voids the wall after roundtrip"
            assert child_opening.Representation is not None, (
                f"Child {child_guid} opening lost its Representation after roundtrip — the kernel will not cut the wall."
            )

    def test_apply_isolates_independent_children_from_parent_body_replacement(self):
        """End-to-end contract: after apply, swapping the parent opening's body
        representation (the pattern parametric-edit flows exercise via
        ``ifc_file.get_inverse`` + ``replace_attribute``) must not rewrite
        the former children's opening bodies. This is the user-visible
        invariant — editing one independent former-sibling no longer
        reshapes the others."""
        wall_obj, door_obj = self._setup_door_in_wall()
        door = tool.Ifc.get_entity(door_obj)
        ifc_file = tool.Ifc.get()

        self._activate(door_obj)
        bpy.ops.bim.add_array()
        bpy.ops.bim.enable_editing_array_item(item=0)
        props = tool.Model.get_array_props(door_obj)
        props.count = 3
        props.x = 1.0
        bpy.ops.bim.edit_array(item=0)

        parent_pset_data = json.loads(ifcopenshell.util.element.get_pset(door, "BBIM_Array", "Data"))
        children = [tool.Ifc.get().by_guid(g) for g in parent_pset_data[0]["children"]]

        self._activate(door_obj)
        bpy.ops.bim.apply_array()

        # Capture each independent child's resolved body identity now.
        before = {
            child.GlobalId: ifcopenshell.util.representation.resolve_representation(
                ifcopenshell.util.representation.get_representation(
                    child.FillsVoids[0].RelatingOpeningElement, "Model", "Body", "MODEL_VIEW"
                )
            )
            for child in children
        }

        # Simulate the body-replacement pattern: take the parent opening's
        # resolved body and rewrite every inverse to point at a brand-new
        # representation entity. If sharing wasn't severed, the children's
        # bodies would be rewritten too.
        parent_opening = door.FillsVoids[0].RelatingOpeningElement
        old_parent_body = ifcopenshell.util.representation.resolve_representation(
            ifcopenshell.util.representation.get_representation(parent_opening, "Model", "Body", "MODEL_VIEW")
        )
        new_body = ifcopenshell.util.element.copy_deep(
            ifc_file, old_parent_body, exclude=["IfcGeometricRepresentationContext"]
        )
        for inverse in ifc_file.get_inverse(old_parent_body):
            ifcopenshell.util.element.replace_attribute(inverse, old_parent_body, new_body)

        for child in children:
            after_body = ifcopenshell.util.representation.resolve_representation(
                ifcopenshell.util.representation.get_representation(
                    child.FillsVoids[0].RelatingOpeningElement, "Model", "Body", "MODEL_VIEW"
                )
            )
            assert after_body == before[child.GlobalId], (
                f"Independent former child {child.GlobalId} opening body changed when the "
                f"parent's body was replaced — apply path failed to detach the mapped representation."
            )


class TestApplyIfcMaterialChanges(NewFile):
    def get_used_styles(self, obj: bpy.types.Object) -> set[ifcopenshell.entity_instance]:
        ifc_file = tool.Ifc.get()
        return {
            ifc_file.by_id(tool.Blender.get_ifc_definition_id(s.material)) for s in obj.material_slots if s.material
        }

    def get_mesh(self, obj: bpy.types.Object) -> bpy.types.Mesh:
        mesh = obj.data
        assert isinstance(mesh, bpy.types.Mesh)
        return mesh

    def setup_test(self, and_elements: bool = True) -> None:
        props = tool.Project.get_project_props()
        props.template_file = "0"
        bpy.context.scene.unit_settings.length_unit = "MILLIMETERS"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()

        # Setup materials and styles.
        context = ifcopenshell.util.representation.get_context(ifc_file, "Model", "Body", "MODEL_VIEW")
        assert context  # Type checker.

        red_material = ifcopenshell.api.material.add_material(ifc_file, "Red Material")
        bpy.ops.bim.load_styles(style_type="IfcSurfaceStyle")
        bpy.ops.bim.enable_adding_presentation_style()
        sprops = tool.Style.get_style_props()
        sprops.style_name = "Red"
        bpy.ops.bim.add_presentation_style()
        red_style = next(i for i in ifc_file.by_type("IfcSurfaceStyle") if i.Name == "Red")
        ifcopenshell.api.style.assign_material_style(ifc_file, red_material, red_style, context)

        blue_material = ifcopenshell.api.material.add_material(ifc_file, "Blue Material")
        bpy.ops.bim.enable_adding_presentation_style()
        sprops.style_name = "Blue"
        bpy.ops.bim.add_presentation_style()
        blue_style = next(i for i in ifc_file.by_type("IfcSurfaceStyle") if i.Name == "Blue")
        ifcopenshell.api.style.assign_material_style(ifc_file, blue_material, blue_style, context)

        bpy.ops.bim.enable_adding_presentation_style()
        sprops.style_name = "Green"
        bpy.ops.bim.add_presentation_style()

        if and_elements:
            self.setup_elements()

    def setup_elements(self) -> None:
        ifc_file = tool.Ifc.get()
        blue_material = next(i for i in ifc_file.by_type("IfcMaterial") if i.Name == "Blue Material")
        blue_style = tool.Material.get_style(blue_material)

        # Element type.
        bpy.ops.mesh.primitive_cube_add(size=10, location=(0, 0, 4))
        element_type_obj = bpy.data.objects["Cube"]
        bpy.ops.bim.assign_class(ifc_class="IfcActuatorType", predefined_type="ELECTRICACTUATOR", userdefined_type="")
        element_type = tool.Ifc.get_entity(element_type_obj)

        # Setup occurrences.
        relating_type_id = element_type.id()
        bpy.ops.bim.add_occurrence(relating_type_id=relating_type_id)
        simple = bpy.context.active_object
        simple.name = "Simple"

        # Occurrence with an opening.
        bpy.ops.bim.add_occurrence(relating_type_id=relating_type_id)
        with_opening = bpy.context.active_object
        with_opening.name = "With Opening"
        props = tool.Root.get_root_props()
        props.representation_obj = with_opening
        bpy.ops.bim.add_element(ifc_product="IfcFeatureElement", ifc_class="IfcOpeningElement")

        # Occurrence with a material override.
        bpy.ops.bim.add_occurrence(relating_type_id=relating_type_id)
        with_material = bpy.context.active_object
        with_material.name = "With Material"
        tool.Blender.set_objects_selection(bpy.context, active_object=with_material, selected_objects=[with_material])

        ifcopenshell.api.material.assign_material(
            ifc_file, products=[tool.Ifc.get_entity(with_material)], material=blue_material
        )
        tool.Material.ensure_material_assigned([tool.Ifc.get_entity(with_material)], material=blue_material)

        assert self.get_used_styles(element_type_obj) == set()
        for element in ifc_file.by_type("IfcActuator"):
            obj = tool.Ifc.get_object(element)
            expected = {blue_style} if obj.name == "With Material" else set()
            assert self.get_used_styles(obj) == expected

    def test_element_type_and_occurrences(self):
        self.setup_test()
        ifc_file = tool.Ifc.get()
        element_type = next(ifc_file.by_type("IfcActuatorType").__iter__())
        red_material = next(i for i in ifc_file.by_type("IfcMaterial") if i.Name == "Red Material")
        red_style = tool.Material.get_style(red_material)
        blue_style = next(i for i in ifc_file.by_type("IfcSurfaceStyle") if i.Name == "Blue")

        ifcopenshell.api.material.assign_material(ifc_file, material=red_material, products=[element_type])
        tool.Material.ensure_material_assigned([element_type], material=red_material)
        assert self.get_used_styles(tool.Ifc.get_object(element_type)) == {red_style}
        for element in ifc_file.by_type("IfcActuator"):
            obj = tool.Ifc.get_object(element)
            expected = {blue_style} if obj.name == "With Material" else {red_style}
            assert self.get_used_styles(obj) == expected

        ifcopenshell.api.material.unassign_material(ifc_file, products=[element_type])
        tool.Material.ensure_material_unassigned([element_type])
        assert self.get_used_styles(tool.Ifc.get_object(element_type)) == set()
        for element in ifc_file.by_type("IfcActuator"):
            obj = tool.Ifc.get_object(element)
            expected = {blue_style} if obj.name == "With Material" else set()
            assert self.get_used_styles(obj) == expected

    def test_dont_override_exisiting_styles(self):
        self.setup_test()
        ifc_file = tool.Ifc.get()
        element_type = next(ifc_file.by_type("IfcActuatorType").__iter__())
        red_material = next(i for i in ifc_file.by_type("IfcMaterial") if i.Name == "Red Material")
        green_style = next(i for i in ifc_file.by_type("IfcSurfaceStyle") if i.Name == "Green")

        # Occurrence with a style.
        element_type_obj = tool.Ifc.get_object(element_type)
        with bpy.context.temp_override(selected_objects=[element_type_obj]):
            bpy.ops.bim.assign_style_to_selected(style_id=green_style.id())

        ifcopenshell.api.material.assign_material(ifc_file, material=red_material, products=[element_type])
        tool.Material.ensure_material_assigned([element_type], material=red_material)
        assert self.get_used_styles(tool.Ifc.get_object(element_type)) == {green_style}
        for element in ifc_file.by_type("IfcActuator"):
            obj = tool.Ifc.get_object(element)
            assert self.get_used_styles(obj) == {green_style}

        ifcopenshell.api.material.unassign_material(ifc_file, products=[element_type])
        tool.Material.ensure_material_unassigned([element_type])
        assert self.get_used_styles(tool.Ifc.get_object(element_type)) == {green_style}
        for element in ifc_file.by_type("IfcActuator"):
            obj = tool.Ifc.get_object(element)
            assert self.get_used_styles(obj) == {green_style}

    def test_assign_material_to_representation_that_has_2_items_and_1_item_has_a_style(self):
        self.setup_test(and_elements=False)
        ifc_file = tool.Ifc.get()
        red_material = next(i for i in ifc_file.by_type("IfcMaterial") if i.Name == "Red Material")
        red_style = tool.Material.get_style(red_material)
        green_style = next(i for i in ifc_file.by_type("IfcSurfaceStyle") if i.Name == "Green")

        bpy.ops.mesh.primitive_cube_add(size=10, location=(0, 0, 4))
        obj = bpy.data.objects["Cube"]
        bpy.ops.bim.assign_class(ifc_class="IfcActuator", predefined_type="ELECTRICACTUATOR", userdefined_type="")
        element = tool.Ifc.get_entity(obj)
        builder = ShapeBuilder(ifc_file)

        # Change representation that consists of 2 rep items:
        # 1 with style and other without.
        rep = tool.Geometry.get_active_representation(obj)
        assert rep
        cube = rep.Items[0]
        cube2 = builder.deep_copy(cube)
        rep.Items = [cube, cube2]
        tool.Style.assign_style_to_representation_item(cube, green_style)
        tool.Geometry._reload_representation(obj)

        def get_material_indices(mesh: bpy.types.Mesh) -> np.ndarray:
            buffer = np.empty(len(mesh.polygons), dtype="I")
            mesh.polygons.foreach_get("material_index", buffer)
            return buffer

        mesh = self.get_mesh(obj)
        assert len(mesh.materials) == 2
        assert set(mesh.materials) == {bpy.data.materials["Green"], None}

        ifcopenshell.api.material.assign_material(ifc_file, products=[element], material=red_material)
        tool.Material.ensure_material_assigned([element], material=red_material)
        assert self.get_used_styles(obj) == {green_style, red_style}
        ifcopenshell.api.material.unassign_material(ifc_file, products=[element])
        tool.Material.ensure_material_unassigned([element])
        mesh = self.get_mesh(obj)
        assert len(mesh.materials) == 2
        assert set(mesh.materials) == {bpy.data.materials["Green"], None}

        # Test that if style is the same it would just reuse it.
        tool.Style.assign_style_to_representation_item(cube, red_style)
        tool.Geometry._reload_representation(obj)
        mesh = self.get_mesh(obj)
        assert len(mesh.materials) == 2
        assert set(mesh.materials) == {bpy.data.materials["Red"], None}

        ifcopenshell.api.material.assign_material(ifc_file, products=[element], material=red_material)
        tool.Material.ensure_material_assigned([element], material=red_material)
        mesh = self.get_mesh(obj)
        assert mesh.materials[:] == [bpy.data.materials["Red"]]
        # All polygons are just reassigned to the existing material.
        assert set(get_material_indices(mesh)) == {mesh.materials.find("Red")}

        ifcopenshell.api.material.unassign_material(ifc_file, products=[element])
        tool.Material.ensure_material_unassigned([element])
        mesh = self.get_mesh(obj)
        assert len(mesh.materials) == 2
        assert set(mesh.materials) == {bpy.data.materials["Red"], None}
        assert set(get_material_indices(mesh)) == {0, 1}

    def test_assign_unassign_overriding_occurrence_material(self):
        self.setup_test(and_elements=True)
        ifc_file = tool.Ifc.get()
        element_type = next(ifc_file.by_type("IfcActuatorType").__iter__())
        red_material = next(i for i in ifc_file.by_type("IfcMaterial") if i.Name == "Red Material")
        no_style_material = ifcopenshell.api.material.add_material(ifc_file, "No Style")
        obj = bpy.data.objects["Simple"]
        element = tool.Ifc.get_entity(obj)

        ifcopenshell.api.material.assign_material(ifc_file, material=red_material, products=[element_type])
        tool.Material.ensure_material_assigned([element_type], material=red_material)

        # Override type material.
        ifcopenshell.api.material.assign_material(ifc_file, material=no_style_material, products=[element])
        tool.Material.ensure_material_assigned([element], material=no_style_material)
        assert self.get_mesh(obj).materials[:] == []

        ifcopenshell.api.material.unassign_material(ifc_file, products=[element])
        tool.Material.ensure_material_unassigned([element])
        assert self.get_mesh(obj).materials[:] == [bpy.data.materials["Red"]]


class TestOffsetWall(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)

        wall_type = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWallType", name="WAL01")
        material_set = ifcopenshell.api.material.add_material_set(ifc, set_type="IfcMaterialLayerSet")
        material = ifcopenshell.api.material.add_material(ifc, name="PB01", category="gypsum")
        layer = ifcopenshell.api.material.add_layer(ifc, layer_set=material_set, material=material)
        ifcopenshell.api.material.edit_layer(ifc, layer=layer, attributes={"LayerThickness": 100})
        ifcopenshell.api.material.assign_material(ifc, products=[wall_type], material=material_set)

        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        ifcopenshell.api.type.assign_type(ifc, related_objects=[wall], relating_type=wall_type)
        rel = ifcopenshell.api.material.assign_material(ifc, products=[wall], type="IfcMaterialLayerSetUsage")
        usage = rel.RelatingMaterial
        obj = bpy.data.objects.new("Wall", None)
        tool.Ifc.link(wall, obj)

        usage.DirectionSense = "POSITIVE"
        subject.offset_wall(obj, "CENTER")
        assert usage.OffsetFromReferenceLine == -50
        usage.DirectionSense = "NEGATIVE"
        subject.offset_wall(obj, "CENTER")
        assert usage.OffsetFromReferenceLine == 50

        usage.DirectionSense = "POSITIVE"
        subject.offset_wall(obj, "INTERIOR")
        assert usage.OffsetFromReferenceLine == -100
        usage.DirectionSense = "NEGATIVE"
        subject.offset_wall(obj, "INTERIOR")
        assert usage.OffsetFromReferenceLine == 0

        usage.DirectionSense = "POSITIVE"
        subject.offset_wall(obj, "EXTERIOR")
        assert usage.OffsetFromReferenceLine == 0
        usage.DirectionSense = "NEGATIVE"
        subject.offset_wall(obj, "EXTERIOR")
        assert usage.OffsetFromReferenceLine == 100


class TestGetExistingXAngle(NewFile):
    """``get_existing_x_angle(extrusion)`` returns the signed slope (radians)
    of an IfcExtrudedAreaSolid's ExtrudedDirection, applying a ``+ pi``
    correction when the direction points into the negative-z half-space.

    The correction is the difference between this canonical helper and a
    hand-rolled ``Vector((0, 1)).angle_signed(Vector((y, z)))`` closure;
    omitting it drifts ``props.x_angle`` on inverted-extrusion walls/slabs."""

    def test_returns_zero_for_vertical_extrusion(self):
        ifc = ifcopenshell.file()
        direction = ifc.createIfcDirection((0.0, 0.0, 1.0))
        extrusion = ifc.createIfcExtrudedAreaSolid(ExtrudedDirection=direction, Depth=1.0)
        assert subject.get_existing_x_angle(extrusion) == pytest.approx(0.0)

    def test_returns_signed_slope_for_slanted_extrusion(self):
        # Direction (0, sin(slope), cos(slope)): the (y, z) vector is to the
        # right of (0, 1); ``mathutils.Vector.angle_signed`` returns positive
        # when ``other`` lies on the +y side of ``self``, hence +slope.
        from math import cos, radians, sin

        slope = radians(30)
        ifc = ifcopenshell.file()
        direction = ifc.createIfcDirection((0.0, sin(slope), cos(slope)))
        extrusion = ifc.createIfcExtrudedAreaSolid(ExtrudedDirection=direction, Depth=1.0)
        assert subject.get_existing_x_angle(extrusion) == pytest.approx(slope)

    def test_applies_pi_correction_for_inverted_extrusion(self):
        # Direction (0, sin(slope), -cos(slope)): the (y, z) vector is in the
        # lower-right quadrant relative to (0, 1) → angle_signed = π - slope.
        # z ≤ 0 triggers the +π correction → result = 2π - slope. Pins both
        # the raw mathutils sign convention AND the +π shift.
        from math import cos, pi, radians, sin

        slope = radians(30)
        ifc = ifcopenshell.file()
        direction = ifc.createIfcDirection((0.0, sin(slope), -cos(slope)))
        extrusion = ifc.createIfcExtrudedAreaSolid(ExtrudedDirection=direction, Depth=1.0)
        assert subject.get_existing_x_angle(extrusion) == pytest.approx(2 * pi - slope)

    def test_ignores_x_component_in_extrusion_direction(self):
        # The helper operates in the y-z plane only — the x component of
        # ``DirectionRatios`` is dropped silently. Any change that adds
        # 3D-slant support must update this test.
        from math import cos, radians, sin

        slope = radians(30)
        ifc = ifcopenshell.file()
        direction = ifc.createIfcDirection((0.5, sin(slope), cos(slope)))
        extrusion = ifc.createIfcExtrudedAreaSolid(ExtrudedDirection=direction, Depth=1.0)
        assert subject.get_existing_x_angle(extrusion) == pytest.approx(slope)

    def test_treats_horizontal_extrusion_as_inverted(self):
        # Boundary: z == 0 (a purely horizontal extrusion) hits the
        # ``else`` branch via ``if z > 0``. angle_signed((0,1), (1,0)) is
        # +π/2; the +π correction shifts to +3π/2.
        from math import pi

        ifc = ifcopenshell.file()
        direction = ifc.createIfcDirection((0.0, 1.0, 0.0))
        extrusion = ifc.createIfcExtrudedAreaSolid(ExtrudedDirection=direction, Depth=1.0)
        assert subject.get_existing_x_angle(extrusion) == pytest.approx(3 * pi / 2)
