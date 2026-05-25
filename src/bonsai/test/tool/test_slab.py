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
import ifcopenshell
import pytest

import bonsai.core.tool
import bonsai.tool as tool
from bonsai.tool.slab import Slab as subject
from test.bim.bootstrap import NewFile

pytestmark = pytest.mark.model


class TestImplementsTool(NewFile):
    def test_run(self):
        assert isinstance(subject(), bonsai.core.tool.Slab)


class TestIsSlab(NewFile):
    """Predicate totality + correctness for ``tool.Blender.Modifier.is_slab``.

    The gizmo's ``poll()`` runs this on every redraw, so the predicate must
    never raise and must reject non-LAYER3 slabs cleanly."""

    def test_returns_true_for_layer3_slab(self):
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        slab_type = ifc_file.by_type("IfcSlabType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=slab_type.id())
        slab = ifc_file.by_type("IfcSlab")[0]
        assert tool.Blender.Modifier.is_slab(slab) is True

    def test_returns_false_for_wall(self):
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        wall_type = ifc_file.by_type("IfcWallType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
        wall = ifc_file.by_type("IfcWall")[0]
        assert tool.Blender.Modifier.is_slab(wall) is False

    def test_returns_false_for_slab_without_layer3_usage(self):
        # Bare IfcSlab with no IfcMaterialLayerSetUsage — should not qualify
        # as a parametric host for the gizmo.
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        slab = ifc.createIfcSlab()
        assert tool.Blender.Modifier.is_slab(slab) is False

    def test_returns_false_for_non_slab_ifc_class(self):
        ifc = ifcopenshell.file()
        tool.Ifc.set(ifc)
        # IfcDiscreteAccessory has no Bonsai modifier semantics at all —
        # exercising it pins that the predicate isn't accidentally permissive.
        accessory = ifc.createIfcDiscreteAccessory()
        assert tool.Blender.Modifier.is_slab(accessory) is False


class TestReadGeometry(NewFile):
    """``Slab.read_geometry`` returns the dict the gizmo positioner consumes,
    or ``None`` when the slab is not parametric."""

    def test_returns_depth_and_x_angle_for_layer3_slab(self):
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        slab_type = ifc_file.by_type("IfcSlabType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=slab_type.id())
        slab = ifc_file.by_type("IfcSlab")[0]
        obj = tool.Ifc.get_object(slab)
        assert isinstance(obj, bpy.types.Object)

        geom = subject.read_geometry(obj)
        assert geom is not None
        assert geom["depth"] > 0.0
        assert geom["x_angle"] == pytest.approx(0.0)

    def test_returns_none_for_non_ifc_object(self):
        # Plain mesh with no IFC link must not raise — gizmo poll routinely
        # calls this on the non-host object in the selection.
        obj = bpy.data.objects.new("PlainMesh", bpy.data.meshes.new("Mesh"))
        assert subject.read_geometry(obj) is None

    def test_returns_none_for_wall_object(self):
        # A wall is parametric, but not for the slab reader.
        tool.Project.get_project_props().template_file = "IFC4 Demo Template.ifc"
        bpy.ops.bim.create_project()
        ifc_file = tool.Ifc.get()
        wall_type = ifc_file.by_type("IfcWallType")[0]
        bpy.ops.bim.add_occurrence(relating_type_id=wall_type.id())
        wall = ifc_file.by_type("IfcWall")[0]
        wall_obj = tool.Ifc.get_object(wall)
        assert isinstance(wall_obj, bpy.types.Object)
        assert subject.read_geometry(wall_obj) is None
