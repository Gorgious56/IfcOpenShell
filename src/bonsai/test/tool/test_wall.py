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


def _create_fillet_corner_setup():
    """Build an IFC4 project with two perpendicular walls and run the fillet
    operator, returning ``(elem_a, elem_b, corner_elem)``."""
    from mathutils import Euler, Matrix, Vector

    import bonsai.core.geometry
    from bonsai.bim.module.model.wall import DumbWallJoiner

    tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
    bpy.ops.bim.create_project()
    ifc_file = tool.Ifc.get()
    wall_type = ifc_file.by_type("IfcWallType")[0]

    bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
    wall_a_obj = bpy.context.active_object
    DumbWallJoiner().set_length(wall_a_obj, 5.0)

    bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
    wall_b_obj = bpy.context.active_object
    wall_b_obj.matrix_world = (
        Matrix.Translation(Vector((5.0, 0.0, 0.0))) @ Euler((0, 0, 1.5707963267948966)).to_matrix().to_4x4()
    )
    bonsai.core.geometry.edit_object_placement(
        tool.Ifc, tool.Geometry, tool.Surveyor, obj=wall_b_obj, apply_scale=False
    )
    DumbWallJoiner().set_length(wall_b_obj, 5.0)

    elem_a = tool.Ifc.get_entity(wall_a_obj)
    elem_b = tool.Ifc.get_entity(wall_b_obj)
    bpy.ops.bim.create_wall_fillet(wall_a_id=elem_a.id(), wall_b_id=elem_b.id(), radius=1.0)

    corner = next(w for w in ifc_file.by_type("IfcWall") if w not in (elem_a, elem_b))
    return elem_a, elem_b, corner


class TestIsPathConnectableWall(NewFile):
    """``tool.Parametric.is_path_connectable_wall`` accepts both LAYER2 walls
    and fillet-corner walls — the looser gate used by unjoin / join gizmo
    polls so a fillet corner's path connections still drive gizmo placement."""

    def test_accepts_layer2_wall(self):
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        wall_type = ifc_file.by_type("IfcWallType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
        wall = ifc_file.by_type("IfcWall")[0]
        assert tool.Parametric.is_path_connectable_wall(wall) is True

    def test_accepts_fillet_corner_wall(self):
        _, _, corner = _create_fillet_corner_setup()
        assert tool.Parametric.is_path_connectable_wall(corner) is True

    def test_rejects_non_wall_element(self):
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        slab_type = ifc_file.by_type("IfcSlabType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=slab_type.id())
        slab = ifc_file.by_type("IfcSlab")[0]
        assert tool.Parametric.is_path_connectable_wall(slab) is False

    def test_rejects_none(self):
        assert tool.Parametric.is_path_connectable_wall(None) is False


class TestReadGeometryForFilletCorner(NewFile):
    """``Wall.read_geometry`` must return a usable WallGeometry dict for a
    fillet-corner wall so its gizmo group's ``position_gizmos`` can anchor the
    pen + unjoin icons on the chord axis."""

    def test_returns_dict_for_fillet_corner_wall(self):
        _, _, corner = _create_fillet_corner_setup()
        corner_obj = tool.Ifc.get_object(corner)
        assert isinstance(corner_obj, bpy.types.Object)

        geom = subject.read_geometry(corner_obj)
        assert geom is not None
        assert geom["length"] > 0.0
        assert geom["height"] > 0.0
        assert geom["x_angle"] == pytest.approx(0.0)
