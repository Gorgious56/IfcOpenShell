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

from math import pi

import bpy
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.system
import ifcopenshell.util.system
import ifcopenshell.util.unit
import numpy as np
from mathutils import Euler, Matrix, Vector

import bonsai.core.tool
import bonsai.tool as tool
from bonsai.tool.system import System as subject
from test.bim.bootstrap import NewFile


class TestImplementsTool(NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.System)


class TestAddPorts(NewFile):
    def setup_mep_segment(self):
        bpy.ops.bim.create_project()
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
        obj = bpy.data.objects["Cube"]
        obj.scale = (1, 1, 5)
        bpy.ops.bim.assign_class(ifc_class="IfcDuctSegment", predefined_type="RIGIDSEGMENT", userdefined_type="")
        element = tool.Ifc.get_entity(obj)
        obj.matrix_world = Euler((pi / 2, 0, pi / 2)).to_matrix().to_4x4() @ obj.matrix_world
        # move origin
        assert isinstance(obj.data, bpy.types.Mesh)
        for v in obj.data.vertices:
            v.co += Vector((0, 0, 2.5))
        return obj, element

    def check_ports_matrices(self, ports, expected_matrices):
        si_conversion = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        for port, expected_matrix in zip(ports, expected_matrices, strict=True):
            port_matrix = tool.Model.get_element_matrix(port)
            port_matrix.translation *= si_conversion
            assert np.allclose(
                port_matrix, expected_matrix, atol=1.0e-5
            ), f"Matrix does not match:\n{port_matrix}\n{expected_matrix}"

    def test_run(self):
        # default use
        obj, element = self.setup_mep_segment()
        ports = subject.add_ports(obj)
        assert len(subject.get_ports(element)) == len(ports)
        self.check_ports_matrices(ports, (obj.matrix_world, obj.matrix_world @ Matrix.Translation((0, 0, 5))))

        # skip end port
        obj, element = self.setup_mep_segment()
        ports = subject.add_ports(obj, add_end_port=False)
        self.check_ports_matrices(ports, (obj.matrix_world,))

        # skip start port
        obj, element = self.setup_mep_segment()
        ports = subject.add_ports(obj, add_start_port=False)
        self.check_ports_matrices(ports, (obj.matrix_world @ Matrix.Translation((0, 0, 5)),))

        # position end port
        obj, element = self.setup_mep_segment()
        ports = subject.add_ports(obj, end_port_pos=Vector((1, 2, 3)))
        translated_matrix = obj.matrix_world.copy()
        translated_matrix.translation = (1, 2, 3)
        self.check_ports_matrices(ports, (obj.matrix_world, translated_matrix))

        # offset end port
        obj, element = self.setup_mep_segment()
        ports = subject.add_ports(obj, offset_end_port=Vector((0, 0, 1)))
        translated_matrix = obj.matrix_world.copy()
        translated_matrix.translation = (5, 0, 1)
        self.check_ports_matrices(ports, (obj.matrix_world, translated_matrix))


class TestCreateEmptyAtCursorWithElementOrientation(NewFile):
    def test_run(self):
        assert bpy.context.scene
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        obj = bpy.data.objects.new("Object", None)
        element = ifc.createIfcWall()
        tool.Ifc.link(element, obj)
        obj = subject.create_empty_at_cursor_with_element_orientation(element)
        assert obj.matrix_world == bpy.context.scene.cursor.matrix


class TestCreatePortAtCursor(NewFile):
    def test_run(self):
        assert bpy.context.scene
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        system = ifcopenshell.api.system.add_system(ifc)
        element = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
        ifcopenshell.api.system.assign_system(ifc, products=[element], system=system)
        obj = tool.Ifc.link(element, bpy.data.objects.new("Object", None))
        port = subject.create_port_at_cursor(element)
        assert port.is_a("IfcDistributionPort")
        assert ifcopenshell.util.system.get_ports(element) == [port]


class TestDeleteElementObjects(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        obj = bpy.data.objects.new("Object", None)
        element = ifc.createIfcWall()
        tool.Ifc.link(element, obj)
        subject.delete_element_objects([element])
        assert not bpy.data.objects.get("Object")


class TestDisableEditingSystem(NewFile):
    def test_run(self):
        props = tool.System.get_system_props()
        props.edited_system_id = 10
        subject.disable_editing_system()
        assert props.edited_system_id == 0


class TestDisableSystemEditingUI(NewFile):
    def test_run(self):
        subject.enable_system_editing_ui()
        subject.disable_system_editing_ui()
        props = tool.System.get_system_props()
        assert props.is_editing is False


class TestEnableSystemEditingUI(NewFile):
    def test_run(self):
        subject.enable_system_editing_ui()
        props = tool.System.get_system_props()
        assert props.is_editing is True


class TestExportSystemAttributes(NewFile):
    def test_run(self):
        TestImportSystemAttributes().test_importing_a_system()
        assert subject.export_system_attributes() == {
            "GlobalId": "GlobalId",
            "Name": "Name",
            "Description": "Description",
            "ObjectType": "ObjectType",
        }


class TestGetConnectedPort(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        port1 = ifcopenshell.api.system.add_port(ifc)
        port2 = ifcopenshell.api.system.add_port(ifc)
        ifcopenshell.api.system.connect_port(ifc, port1=port1, port2=port2)
        assert subject.get_connected_port(port1) == port2
        assert subject.get_connected_port(port2) == port1


class TestGetPorts(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        element = ifc.createIfcDuctSegment()
        port = ifc.createIfcDistributionPort()
        ifcopenshell.api.system.assign_port(ifc, element=element, port=port)
        assert subject.get_ports(element) == [port]


class TestImportSystemAttributes(NewFile):
    def test_importing_a_system(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        system = ifc.createIfcSystem()
        system.GlobalId = "GlobalId"
        system.Name = "Name"
        system.Description = "Description"
        system.ObjectType = "ObjectType"
        subject().import_system_attributes(system)
        props = tool.System.get_system_props()
        assert props.system_attributes["GlobalId"].string_value == "GlobalId"
        assert props.system_attributes["Name"].string_value == "Name"
        assert props.system_attributes["Description"].string_value == "Description"
        assert props.system_attributes["ObjectType"].string_value == "ObjectType"

    def test_importing_a_building_system(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        system = ifc.createIfcBuildingSystem()
        system.GlobalId = "GlobalId"
        system.Name = "Name"
        system.Description = "Description"
        system.ObjectType = "ObjectType"
        system.PredefinedType = "SHADING"
        system.LongName = "LongName"
        subject().import_system_attributes(system)
        props = tool.System.get_system_props()
        assert props.system_attributes["GlobalId"].string_value == "GlobalId"
        assert props.system_attributes["Name"].string_value == "Name"
        assert props.system_attributes["Description"].string_value == "Description"
        assert props.system_attributes["ObjectType"].string_value == "ObjectType"
        assert props.system_attributes["PredefinedType"].enum_value == "SHADING"
        assert props.system_attributes["LongName"].string_value == "LongName"

    def test_importing_a_distribution_system(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        system = ifc.createIfcDistributionSystem()
        system.GlobalId = "GlobalId"
        system.Name = "Name"
        system.Description = "Description"
        system.ObjectType = "ObjectType"
        system.PredefinedType = "ELECTRICAL"
        system.LongName = "LongName"
        subject().import_system_attributes(system)
        props = tool.System.get_system_props()
        assert props.system_attributes["GlobalId"].string_value == "GlobalId"
        assert props.system_attributes["Name"].string_value == "Name"
        assert props.system_attributes["Description"].string_value == "Description"
        assert props.system_attributes["ObjectType"].string_value == "ObjectType"
        assert props.system_attributes["PredefinedType"].enum_value == "ELECTRICAL"
        assert props.system_attributes["LongName"].string_value == "LongName"


class TestImportSystems(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        system = ifc.createIfcDistributionSystem()
        zone = ifc.createIfcZone()
        subject.import_systems()
        props = tool.System.get_system_props()
        assert len(props.systems) == 2
        assert props.systems[0].ifc_definition_id == system.id()
        assert props.systems[0].name == "Unnamed"
        assert props.systems[0].ifc_class == "IfcDistributionSystem"


class TestLoadPorts(NewFile):
    def test_run(self):
        bpy.ops.bim.create_project()
        ifc = tool.Ifc.get()

        element = ifc.create_entity("IfcChiller")
        obj = bpy.data.objects.new("Object", None)
        tool.Ifc.link(element, obj)

        port = ifc.create_entity("IfcDistributionPort")
        subject.load_ports(element, [port])
        obj = tool.Ifc.get_object(port)
        assert isinstance(obj, bpy.types.Object)
        assert obj.users_collection
        assert list(obj.location) == [0, 0, 0]


class TestRunGeometryEditObjectPlacement(NewFile):
    def test_nothing(self):
        pass


class TestRunRootAssignClass(NewFile):
    def test_nothing(self):
        pass


class TestSelectSystemProducts(NewFile):
    def test_run(self):
        assert bpy.context.scene
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        element = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcPump")
        system = ifcopenshell.api.system.add_system(ifc, ifc_class="IfcSystem")
        ifcopenshell.api.system.assign_system(ifc, products=[element], system=system)
        obj = bpy.data.objects.new("Object", None)
        bpy.context.scene.collection.objects.link(obj)
        tool.Ifc.link(element, obj)
        subject.select_system_products(system)
        assert obj in bpy.context.selected_objects


class TestSetActiveSystem(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        system = ifcopenshell.api.system.add_system(ifc, ifc_class="IfcSystem")
        subject.set_active_edited_system(system)
        props = tool.System.get_system_props()
        assert props.edited_system_id == system.id()


class TestFlowElementAndControls(NewFile):
    def test_run(self):
        ifc = ifcopenshell.file()
        flow_element = ifc.createIfcFlowSegment()
        flow_control = ifc.createIfcController()
        flow_control1 = ifc.createIfcController()

        assert len(subject.get_flow_element_controls(flow_element)) == 0
        assert subject.get_flow_control_flow_element(flow_control) == None

        ifcopenshell.api.system.assign_flow_control(
            ifc,
            related_flow_control=flow_control,
            relating_flow_element=flow_element,
        )
        ifcopenshell.api.system.assign_flow_control(
            ifc,
            related_flow_control=flow_control1,
            relating_flow_element=flow_element,
        )
        controls = subject.get_flow_element_controls(flow_element)
        assert set(controls) == set((flow_control, flow_control1))
        assert subject.get_flow_control_flow_element(flow_control) == flow_element


class TestGetPortRelatingElement(NewFile):
    def test_returns_parent_element_when_port_is_nested(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        element = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
        port = ifcopenshell.api.system.add_port(ifc, element=element)
        assert subject.get_port_relating_element(port) == element

    def test_returns_none_when_port_has_no_nests(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        # Free-standing port — created without an enclosing element.
        port = ifcopenshell.api.system.add_port(ifc)
        assert subject.get_port_relating_element(port) is None


class TestWalkConnectedMepElements(NewFile):
    def _connect(self, ifc, a, b):
        """Connect last port of element a to first port of element b."""
        ports_a = ifcopenshell.util.system.get_ports(a)
        ports_b = ifcopenshell.util.system.get_ports(b)
        ifcopenshell.api.system.connect_port(ifc, port1=ports_a[-1], port2=ports_b[0])

    def test_returns_empty_for_non_mep_start(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        wall = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcWall")
        assert subject.walk_connected_mep_elements(wall) == []

    def test_returns_just_start_when_no_neighbours(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        segment = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
        ifcopenshell.api.system.add_port(ifc, element=segment)
        ifcopenshell.api.system.add_port(ifc, element=segment)
        assert subject.walk_connected_mep_elements(segment) == [segment]

    def test_traverses_chain(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        segments = []
        for _ in range(3):
            seg = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
            ifcopenshell.api.system.add_port(ifc, element=seg)
            ifcopenshell.api.system.add_port(ifc, element=seg)
            segments.append(seg)
        self._connect(ifc, segments[0], segments[1])
        self._connect(ifc, segments[1], segments[2])
        # BFS order: start, then chain neighbours. Pinned because path-rendering
        # callers (MEP overlay decorator) depend on traversal order.
        result = subject.walk_connected_mep_elements(segments[0])
        assert result == segments

    def test_terminates_on_cycle(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        a = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
        b = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
        for element in (a, b):
            ifcopenshell.api.system.add_port(ifc, element=element)
            ifcopenshell.api.system.add_port(ifc, element=element)
        # Connect both pairs of ports → closed loop a ↔ b.
        ports_a = ifcopenshell.util.system.get_ports(a)
        ports_b = ifcopenshell.util.system.get_ports(b)
        ifcopenshell.api.system.connect_port(ifc, port1=ports_a[0], port2=ports_b[0])
        ifcopenshell.api.system.connect_port(ifc, port1=ports_a[1], port2=ports_b[1])
        result = subject.walk_connected_mep_elements(a)
        assert set(result) == {a, b}

    def test_filters_non_mep_neighbours(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        segment = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
        terminal = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcFlowTerminal")
        ifcopenshell.api.system.add_port(ifc, element=segment)
        ifcopenshell.api.system.add_port(ifc, element=terminal)
        self._connect(ifc, segment, terminal)
        # IfcFlowTerminal is neither IfcFlowSegment nor IfcFlowFitting, so
        # is_mep_element rejects it — the BFS walks through but does not
        # collect it.
        assert subject.walk_connected_mep_elements(segment) == [segment]


class TestGetPortWorldPosition(NewFile):
    def test_returns_origin_when_port_has_no_placement(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        port = ifc.createIfcDistributionPort()
        assert subject.get_port_world_position(port) == Vector((0.0, 0.0, 0.0))

    def test_falls_back_to_raw_ifc_world_when_parent_missing(self):
        ifc = ifcopenshell.file()
        tool.Ifc().set(ifc)
        # Free-standing port: no IfcRelNests → no parent_element → fallback
        # path returns the raw IFC-placement world position.
        port = ifcopenshell.api.system.add_port(ifc)
        ifcopenshell.api.geometry.edit_object_placement(
            ifc, product=port, matrix=Matrix.Translation((1.0, 2.0, 3.0)), is_si=False
        )
        position = subject.get_port_world_position(port)
        assert position == Vector((1.0, 2.0, 3.0))

    def test_uses_parent_blender_matrix_world_when_parent_object_present(self):
        bpy.ops.bim.create_project()
        ifc = tool.Ifc.get()
        segment = ifcopenshell.api.root.create_entity(ifc, ifc_class="IfcDuctSegment")
        port = ifcopenshell.api.system.add_port(ifc, element=segment)
        # Anchor port + segment at IFC origin, then translate the Blender
        # object — the world position should follow the Blender translation,
        # not the IFC placement.
        ifcopenshell.api.geometry.edit_object_placement(ifc, product=segment, matrix=Matrix.Identity(4), is_si=False)
        ifcopenshell.api.geometry.edit_object_placement(ifc, product=port, matrix=Matrix.Identity(4), is_si=False)
        obj = bpy.data.objects.new("Segment", None)
        tool.Ifc.link(segment, obj)
        obj.matrix_world = Matrix.Translation((10.0, 0.0, 0.0))
        position = subject.get_port_world_position(port)
        assert position == Vector((10.0, 0.0, 0.0))
