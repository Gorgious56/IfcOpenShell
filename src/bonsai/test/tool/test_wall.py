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

import bpy
import pytest

import bonsai.core.tool
import bonsai.tool as tool
from bonsai.tool.wall import Wall as subject
from test.bim.bootstrap import NewFile

pytestmark = pytest.mark.model


class TestImplementsTool(NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.Wall)


class TestReadGeometry(NewFile):
    """``Wall.read_geometry`` returns the WallGeometry dict consumed by gizmo
    positioning and draft initialisation, or ``None`` when the wall is not
    LAYER2-extruded."""

    def test_returns_geometry_dict_for_layer2_wall(self):
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        wall_type = ifc_file.by_type("IfcWallType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
        wall = ifc_file.by_type("IfcWall")[0]
        obj = tool.Ifc.get_object(wall)
        assert isinstance(obj, bpy.types.Object)

        geom = subject.read_geometry(obj)
        assert geom is not None
        assert geom["length"] > 0.0
        assert geom["height"] > 0.0
        assert geom["thickness"] > 0.0
        assert geom["x_angle"] == pytest.approx(0.0)
        assert isinstance(geom["anchor_x"], float)
        assert isinstance(geom["offset"], float)

    def test_returns_none_for_non_ifc_object(self):
        # Plain mesh with no IFC link must not raise — gizmo poll routinely
        # calls this on the non-host object in the selection.
        obj = bpy.data.objects.new("PlainMesh", bpy.data.meshes.new("Mesh"))
        assert subject.read_geometry(obj) is None

    def test_returns_none_for_slab_object(self):
        # A slab is parametric, but not for the wall reader.
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        slab_type = ifc_file.by_type("IfcSlabType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=slab_type.id())
        slab = ifc_file.by_type("IfcSlab")[0]
        slab_obj = tool.Ifc.get_object(slab)
        assert isinstance(slab_obj, bpy.types.Object)
        assert subject.read_geometry(slab_obj) is None


class TestValidateForParametricEdit(NewFile):
    """``Wall.validate_for_parametric_edit`` returns ``None`` for an editable
    wall, otherwise a user-facing string naming the specific gap."""

    def test_returns_none_for_layer2_wall(self):
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        wall_type = ifc_file.by_type("IfcWallType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
        wall = ifc_file.by_type("IfcWall")[0]
        obj = tool.Ifc.get_object(wall)
        assert subject.validate_for_parametric_edit(obj) is None

    def test_returns_message_for_non_ifc_object(self):
        obj = bpy.data.objects.new("PlainMesh", bpy.data.meshes.new("Mesh"))
        msg = subject.validate_for_parametric_edit(obj)
        assert isinstance(msg, str)
        assert msg

    def test_returns_message_for_slab_object(self):
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        slab_type = ifc_file.by_type("IfcSlabType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=slab_type.id())
        slab = ifc_file.by_type("IfcSlab")[0]
        slab_obj = tool.Ifc.get_object(slab)
        msg = subject.validate_for_parametric_edit(slab_obj)
        assert isinstance(msg, str)
        assert "wall" in msg.lower()

    def test_returns_message_for_wall_without_body_representation(self):
        # A wall with its Model/Body/MODEL_VIEW representation detached hits
        # the ``no representation`` branch — realistic for imported IFC files
        # where the body was authored in a context Bonsai doesn't expect.
        import ifcopenshell.api.geometry
        import ifcopenshell.util.representation

        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        wall_type = ifc_file.by_type("IfcWallType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
        wall = ifc_file.by_type("IfcWall")[0]
        obj = tool.Ifc.get_object(wall)

        body = ifcopenshell.util.representation.get_representation(wall, "Model", "Body", "MODEL_VIEW")
        assert body is not None  # sanity: add_occurrence produced a body
        ifcopenshell.api.geometry.unassign_representation(ifc_file, product=wall, representation=body)

        msg = subject.validate_for_parametric_edit(obj)
        assert isinstance(msg, str)
        assert "representation" in msg.lower()
