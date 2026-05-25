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

import bpy
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import numpy as np
from mathutils import Matrix

import bonsai.core.tool
import bonsai.tool as tool
from bonsai.tool.spatial import Spatial as subject
from test.bim.bootstrap import NewFile


class TestImplementsTool(NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.Spatial)


class TestCanContain(NewFile):
    def test_a_spatial_structure_element_can_contain_an_element(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        structure = ifc.createIfcSite()
        structure_obj = bpy.data.objects.new("Object", None)
        tool.Ifc.link(structure, structure_obj)
        element = ifc.createIfcWall()
        assert subject.can_contain(structure, element) is True

    def test_a_spatial_structure_element_can_contain_an_element_ifc2x3(self):
        ifc = ifcopenshell.file(schema="IFC2X3")
        tool.Ifc.set(ifc)
        structure = ifc.createIfcSite()
        structure_obj = bpy.data.objects.new("Object", None)
        tool.Ifc.link(structure, structure_obj)
        element = ifc.createIfcWall()
        assert subject.can_contain(structure, element) is True

    def test_a_spatial_zone_element_cannot_contain_an_element(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        structure = ifc.createIfcSpatialZone()
        structure_obj = bpy.data.objects.new("Object", None)
        tool.Ifc.link(structure, structure_obj)
        element = ifc.createIfcWall()
        assert subject.can_contain(structure, element) is False

    def test_a_non_spatial_element_cannot_contain_anything(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        structure = ifc.createIfcWall()
        structure_obj = bpy.data.objects.new("Object", None)
        tool.Ifc.link(structure, structure_obj)
        element = ifc.createIfcWall()
        assert subject.can_contain(structure, element) is False

    def test_a_non_element_cannot_be_contained(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        structure = ifc.createIfcSite()
        structure_obj = bpy.data.objects.new("Object", None)
        tool.Ifc.link(structure, structure_obj)
        element = ifc.createIfcTask()
        assert subject.can_contain(structure, element) is False

    def test_other_non_elements_that_have_a_contained_in_structure_attribute_can_be_contained(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        structure = ifc.createIfcSite()
        structure_obj = bpy.data.objects.new("Object", None)
        tool.Ifc.link(structure, structure_obj)
        element = ifc.createIfcGrid()
        assert subject.can_contain(structure, element) is True


class TestCanReference(NewFile):
    def test_an_element_can_reference_a_spatial_element(self):
        ifc = ifcopenshell.file()
        assert subject.can_reference(ifc.createIfcSite(), ifc.createIfcWall()) is True

    def test_an_element_can_reference_a_spatial_element_ifc2x3(self):
        ifc = ifcopenshell.file(schema="IFC2X3")
        tool.Ifc.set(ifc)
        assert subject.can_reference(ifc.createIfcSite(), ifc.createIfcWall()) is True

    def test_a_non_spatial_element_cannot_reference_anything(self):
        ifc = ifcopenshell.file()
        assert subject.can_reference(ifc.createIfcWall(), ifc.createIfcWall()) is False

    def test_a_non_element_cannot_reference_anything(self):
        ifc = ifcopenshell.file()
        assert subject.can_reference(ifc.createIfcSite(), ifc.createIfcTask()) is False


class TestDisableEditing(NewFile):
    def test_run(self):
        obj = bpy.data.objects.new("Object", None)
        subject.enable_editing(obj)
        subject.disable_editing(obj)
        props = tool.Spatial.get_object_spatial_props(obj)
        assert props.is_editing is False


class TestDuplicateObjectAndData(NewFile):
    def test_run(self):
        obj = bpy.data.objects.new("Object", bpy.data.meshes.new("Mesh"))
        new_obj = subject.duplicate_object_and_data(obj)
        assert new_obj != obj
        assert new_obj.data != obj.data
        obj = bpy.data.objects.new("Object", None)
        new_obj = subject.duplicate_object_and_data(obj)
        assert new_obj != obj
        assert new_obj.data is None


class TestEnableEditing(NewFile):
    def test_run(self):
        obj = bpy.data.objects.new("Object", None)
        subject.enable_editing(obj)
        props = tool.Spatial.get_object_spatial_props(obj)
        assert props.is_editing is True


class TestGetContainer(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        site = ifc.createIfcSite()
        wall = ifc.createIfcWall()
        ifcopenshell.api.spatial.assign_container(ifc, products=[wall], relating_structure=site)
        assert subject.get_container(wall) == site


class TestGetDecomposedElements(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        site = ifc.createIfcSite()
        wall = ifc.createIfcWall()
        ifcopenshell.api.spatial.assign_container(ifc, products=[wall], relating_structure=site)
        assert subject.get_decomposed_elements(site) == {wall}


class TestGetHostElement(NewFile):
    """``get_host_element`` is the type-agnostic chain-walk. Callers that
    don't care what type hosts the filling (decomposition-graph builders,
    BCF exporters, etc.) reach for this; the wall-only narrower shape lives
    in `get_host_wall`."""

    def test_door_in_wall_returns_wall(self):
        ifc = ifcopenshell.file()
        wall = ifc.createIfcWall()
        opening = ifc.createIfcOpeningElement()
        door = ifc.createIfcDoor()
        ifcopenshell.api.feature.add_feature(ifc, feature=opening, element=wall)
        ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=door)
        assert subject.get_host_element(door) == wall

    def test_door_in_slab_returns_slab(self):
        # Skylight-shaped case: the host is real but isn't a wall. The
        # general helper returns it; ``get_host_wall`` filters it out.
        ifc = ifcopenshell.file()
        slab = ifc.createIfcSlab()
        opening = ifc.createIfcOpeningElement()
        door = ifc.createIfcDoor()
        ifcopenshell.api.feature.add_feature(ifc, feature=opening, element=slab)
        ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=door)
        assert subject.get_host_element(door) == slab

    def test_filling_with_no_opening_returns_none(self):
        ifc = ifcopenshell.file()
        door = ifc.createIfcDoor()
        assert subject.get_host_element(door) is None

    def test_opening_with_no_void_returns_none(self):
        ifc = ifcopenshell.file()
        opening = ifc.createIfcOpeningElement()
        door = ifc.createIfcDoor()
        ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=door)
        assert subject.get_host_element(door) is None

    def test_non_filling_entity_returns_none(self):
        # An entity without a ``FillsVoids`` inverse (e.g. a wall) must not
        # raise — callers like the decomposition snapshot iterate every
        # entity in the scene, so the helper has to handle that cleanly.
        ifc = ifcopenshell.file()
        wall = ifc.createIfcWall()
        assert subject.get_host_element(wall) is None


class TestGetHostWall(NewFile):
    """``get_host_wall`` is the chain-walk callers reach for when a filling's
    wall-offset gizmo needs the host wall's length/height — the four guards
    here exist because the chain is sparse: a hosted door, an orphaned door,
    a half-built opening, and a door voiding a non-wall element all need
    distinct handling, and an exception at any link would bubble up to the
    gizmo's per-frame draw."""

    def test_door_in_wall_returns_wall(self):
        ifc = ifcopenshell.file()
        wall = ifc.createIfcWall()
        opening = ifc.createIfcOpeningElement()
        door = ifc.createIfcDoor()
        ifcopenshell.api.feature.add_feature(ifc, feature=opening, element=wall)
        ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=door)
        assert subject.get_host_wall(door) == wall

    def test_window_in_wall_returns_wall(self):
        ifc = ifcopenshell.file()
        wall = ifc.createIfcWall()
        opening = ifc.createIfcOpeningElement()
        window = ifc.createIfcWindow()
        ifcopenshell.api.feature.add_feature(ifc, feature=opening, element=wall)
        ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=window)
        assert subject.get_host_wall(window) == wall

    def test_filling_with_no_opening_returns_none(self):
        # Standalone door — never inserted into anything.
        ifc = ifcopenshell.file()
        door = ifc.createIfcDoor()
        assert subject.get_host_wall(door) is None

    def test_opening_with_no_void_returns_none(self):
        # Orphaned opening: door was filled into an opening that lost its host.
        ifc = ifcopenshell.file()
        opening = ifc.createIfcOpeningElement()
        door = ifc.createIfcDoor()
        ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=door)
        assert subject.get_host_wall(door) is None

    def test_host_is_slab_returns_none(self):
        # Door voiding a slab (a skylight, conceptually) — host exists but is
        # not an ``IfcWall``; the wall-offset gizmo callers must hide cleanly.
        ifc = ifcopenshell.file()
        slab = ifc.createIfcSlab()
        opening = ifc.createIfcOpeningElement()
        door = ifc.createIfcDoor()
        ifcopenshell.api.feature.add_feature(ifc, feature=opening, element=slab)
        ifcopenshell.api.feature.add_filling(ifc, opening=opening, element=door)
        assert subject.get_host_wall(door) is None


class TestGetObjectMatrix(NewFile):
    def test_run(self):
        obj = bpy.data.objects.new("Object", None)
        assert subject.get_object_matrix(obj) == obj.matrix_world


class TestGetRelativeObjectMatrix(NewFile):
    def test_run(self):
        obj = bpy.data.objects.new("Object", None)
        relative_obj = bpy.data.objects.new("Object", None)
        relative_obj.matrix_world[0][3] = 1
        assert subject.get_relative_object_matrix(obj, relative_obj)[0][3] == -1


class TestRunRootCopyClass(NewFile):
    def test_nothing(self):
        pass


class TestRunSpatialAssignContainer(NewFile):
    def test_nothing(self):
        pass


class TestSelectObject(NewFile):
    def test_run(self):
        obj = bpy.data.objects.new("Object", None)
        bpy.context.scene.collection.objects.link(obj)
        subject.select_object(obj)
        assert obj in bpy.context.selected_objects


class TestSetActiveObject(NewFile):
    def test_run(self):
        obj = bpy.data.objects.new("Object", None)
        bpy.context.scene.collection.objects.link(obj)
        subject.set_active_object(obj)
        assert bpy.context.view_layer.objects.active == obj
        assert obj in bpy.context.selected_objects


class TestSetRelativeObjectMatrix(NewFile):
    def test_run(self):
        obj = bpy.data.objects.new("Object", None)
        relative_obj = bpy.data.objects.new("Object", None)
        relative_obj.matrix_world[0][3] = 1
        matrix = Matrix()
        matrix[0][3] = 1
        subject.set_relative_object_matrix(obj, relative_obj, matrix)
        assert obj.matrix_world[0][3] == 2


class TestSelectProducts(NewFile):
    def test_select_products(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        product = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        obj = bpy.data.objects.new("Object", None)
        bpy.context.scene.collection.objects.link(obj)
        tool.Ifc.link(product, obj)
        subject.select_products([product])
        assert obj in bpy.context.selected_objects


class TestGenerateSpace(NewFile):
    def test_generate_space_at_cursor(self):
        bpy.ops.bim.create_project()
        ifc = tool.Ifc.get()
        scene = bpy.context.scene
        product = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        bpy.ops.mesh.primitive_cube_add(size=10, location=(0, 0, 4))
        obj = bpy.data.objects["Cube"]
        scene.collection.objects.link(obj)
        tool.Ifc.link(product, obj)
        scene.cursor.location = (0, 0, 0)

        bpy.ops.bim.generate_space()
        space = bpy.data.objects["IfcSpace/Space"]
        mesh = space.data
        assert isinstance(mesh, bpy.types.Mesh)
        assert len(mesh.vertices) == 8
        TEST_VERTS = sorted(
            (
                ((5.0, 5.0, 10.0)),
                ((-5.0, 5.0, 10.0)),
                ((-5.0, -5.0, 10.0)),
                ((5.0, -5.0, 10.0)),
                ((-5.0, 5.0, 0.0)),
                ((-5.0, -5.0, 0.0)),
                ((5.0, 5.0, 0.0)),
                ((5.0, -5.0, 0.0)),
            )
        )
        assert np.allclose(TEST_VERTS, sorted([tuple(v.co) for v in mesh.vertices]))
